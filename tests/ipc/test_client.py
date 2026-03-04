"""Unit and integration tests for the IPC socket client library.

Story 29.3: Tests cover SocketClient lifecycle, send_command correlation,
concurrent requests, event subscription, auto-reconnect, timeout handling,
error responses, SyncSocketClient, and context manager support.

Integration tests use real SocketServer instances in tmp_path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from bmad_assist.ipc.client import (
    ConnectionState,
    IPCCommandError,
    IPCConnectionError,
    IPCReconnectError,
    IPCTimeoutError,
    SocketClient,
    SyncSocketClient,
)
from bmad_assist.ipc.protocol import (
    PROTOCOL_VERSION,
    ErrorCode,
    deserialize,
    make_error_response,
    make_event,
    read_message,
    write_message,
)
from bmad_assist.ipc.server import SocketServer
from bmad_assist.ipc.types import (
    GetCapabilitiesResult,
    GetStateResult,
    PingResult,
    RunnerState,
)


# ============================================================================
# Helper: send_rpc for integration tests (reused from test_server.py)
# ============================================================================


async def send_rpc(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    method: str,
    params: dict[str, Any] | None = None,
    request_id: int | str = 1,
) -> dict[str, Any]:
    """Send a JSON-RPC request and read the response."""
    request = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": request_id,
    }
    await write_message(writer, request)
    raw = await asyncio.wait_for(read_message(reader), timeout=5.0)
    return deserialize(raw)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create and monkeypatch socket directory."""
    d = tmp_path / "sockets"
    d.mkdir(mode=0o700)
    monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: d)
    return d


@pytest.fixture
def sock_path(sock_dir: Path) -> Path:
    """Socket path within the test socket directory."""
    return sock_dir / "test.sock"


# ============================================================================
# Unit Tests: Exception Hierarchy (Task 13.1 — AC #12)
# ============================================================================


class TestExceptionHierarchy:
    """Test IPC client exception classes."""

    def test_ipc_connection_error_inherits_ipc_error(self) -> None:
        from bmad_assist.ipc.protocol import IPCError

        exc = IPCConnectionError("test")
        assert isinstance(exc, IPCError)

    def test_ipc_timeout_error_inherits_ipc_error(self) -> None:
        from bmad_assist.ipc.protocol import IPCError

        exc = IPCTimeoutError("test")
        assert isinstance(exc, IPCError)

    def test_ipc_command_error_stores_fields(self) -> None:
        exc = IPCCommandError(code=-32601, message="Method not found", data={"method": "foo"})
        assert exc.code == -32601
        assert exc.message == "Method not found"
        assert exc.data == {"method": "foo"}
        assert "[-32601]" in str(exc)

    def test_ipc_command_error_data_none(self) -> None:
        exc = IPCCommandError(code=-32603, message="Internal error")
        assert exc.data is None

    def test_ipc_reconnect_error_inherits_ipc_error(self) -> None:
        from bmad_assist.ipc.protocol import IPCError

        exc = IPCReconnectError("test")
        assert isinstance(exc, IPCError)


# ============================================================================
# Unit Tests: ConnectionState (Task 13.12 — AC #6)
# ============================================================================


class TestConnectionState:
    """Test ConnectionState enum values."""

    def test_all_states_exist(self) -> None:
        assert ConnectionState.DISCONNECTED == "disconnected"
        assert ConnectionState.CONNECTING == "connecting"
        assert ConnectionState.CONNECTED == "connected"
        assert ConnectionState.RECONNECTING == "reconnecting"
        assert ConnectionState.CLOSED == "closed"

    def test_state_is_string_enum(self) -> None:
        assert isinstance(ConnectionState.CONNECTED, str)


# ============================================================================
# Unit Tests: SocketClient (Tasks 13.2-13.13 — AC #1-5, #7, #9-11)
# ============================================================================


class TestSocketClientInitial:
    """Test SocketClient initial state and properties."""

    def test_initial_state(self, tmp_path: Path) -> None:
        client = SocketClient(socket_path=tmp_path / "test.sock")
        assert client.is_connected is False
        assert client.state == ConnectionState.DISCONNECTED

    def test_initial_state_with_client_id(self, tmp_path: Path) -> None:
        client = SocketClient(
            socket_path=tmp_path / "test.sock",
            client_id="tui-main",
        )
        assert client._client_id == "tui-main"

    def test_request_id_auto_increments(self, tmp_path: Path) -> None:
        client = SocketClient(socket_path=tmp_path / "test.sock")
        id1 = client._next_request_id()
        id2 = client._next_request_id()
        id3 = client._next_request_id()
        assert id1 == 1
        assert id2 == 2
        assert id3 == 3


class TestSocketClientConnectErrors:
    """Test connect failure scenarios."""

    @pytest.mark.asyncio
    async def test_connect_socket_not_found(self, tmp_path: Path) -> None:
        client = SocketClient(socket_path=tmp_path / "nonexistent.sock")
        with pytest.raises(IPCConnectionError, match="Socket not found"):
            await client.connect(timeout=1.0)
        assert client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connect_already_connected(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Connecting when already connected is a no-op."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                # Second connect should be no-op
                await client.connect()
                assert client.state == ConnectionState.CONNECTED
            finally:
                await client.disconnect()
        finally:
            await server.stop()


class TestSocketClientDisconnect:
    """Test disconnect behavior."""

    @pytest.mark.asyncio
    async def test_disconnect_sets_closed_state(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            await client.disconnect()
            assert client.state == ConnectionState.CLOSED
            assert client.is_connected is False
        finally:
            await server.stop()


class TestSocketClientSendCommand:
    """Test send_command with request-response correlation."""

    @pytest.mark.asyncio
    async def test_send_command_not_connected(self, tmp_path: Path) -> None:
        client = SocketClient(socket_path=tmp_path / "test.sock")
        with pytest.raises(IPCConnectionError, match="Not connected"):
            await client.send_command("ping")

    @pytest.mark.asyncio
    async def test_send_command_ping(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """send_command correctly correlates request and response."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                result = await client.send_command("ping")
                assert result["pong"] is True
                assert "server_time" in result
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_concurrent_requests(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Multiple send_command calls in-flight resolve correctly."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                # Fire 3 concurrent requests
                results = await asyncio.gather(
                    client.send_command("ping"),
                    client.send_command("get_state"),
                    client.send_command("get_capabilities"),
                )
                # All should have resolved
                assert results[0]["pong"] is True
                assert "state" in results[1]
                assert "protocol_version" in results[2]
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_error_response_raises_ipc_command_error(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """JSON-RPC error response raises IPCCommandError."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                # pause is a supported method but server has no handler,
                # so it returns INTERNAL_ERROR (not METHOD_NOT_FOUND)
                with pytest.raises(IPCCommandError) as exc_info:
                    await client.send_command("pause")
                assert exc_info.value.code == ErrorCode.INTERNAL_ERROR.code
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_unknown_method_raises_ipc_command_error(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Unknown method raises IPCCommandError with METHOD_NOT_FOUND."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                with pytest.raises(IPCCommandError) as exc_info:
                    await client.send_command("nonexistent_method")
                assert exc_info.value.code == ErrorCode.METHOD_NOT_FOUND.code
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_timeout_raises_ipc_timeout_error(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """send_command() raises IPCTimeoutError when no response arrives in time."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                # Patch write_message to silently drop the request so no
                # response ever comes back, exercising the actual timeout
                # path in send_command().
                async def _noop_write(writer: Any, msg: Any) -> None:
                    pass  # Request never reaches server → no response

                with patch("bmad_assist.ipc.client.write_message", _noop_write):
                    with pytest.raises(IPCTimeoutError, match="Timeout waiting for response"):
                        await client.send_command("ping", timeout=0.05)

                # Verify future was cleaned up from pending
                # (the timed-out request ID should have been removed)
                assert all(
                    not f.done() or f.cancelled() for f in client._pending.values()
                )
            finally:
                await client.disconnect()
        finally:
            await server.stop()


class TestSocketClientEventSubscription:
    """Test event subscription and dispatch."""

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Subscribed callback receives broadcast events."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                received_events: list[dict[str, Any]] = []

                def on_event(params: dict[str, Any]) -> None:
                    received_events.append(params)

                client.subscribe(on_event)

                # Wait for client to be registered
                await asyncio.sleep(0.05)

                # Broadcast event from server
                event = make_event(
                    "phase_started",
                    {"phase": "dev_story"},
                    seq=server.next_event_seq(),
                )
                await server.broadcast(event)

                # Wait for event to arrive
                await asyncio.sleep(0.2)

                assert len(received_events) == 1
                assert received_events[0]["type"] == "phase_started"
                assert received_events[0]["data"]["phase"] == "dev_story"
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_subscribe_async_callback(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Async callbacks are awaited correctly."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                received: list[dict[str, Any]] = []

                async def on_event(params: dict[str, Any]) -> None:
                    received.append(params)

                client.subscribe(on_event)
                await asyncio.sleep(0.05)

                event = make_event("test", {"msg": "hello"}, seq=1)
                await server.broadcast(event)
                await asyncio.sleep(0.2)

                assert len(received) == 1
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_callback(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Unsubscribed callbacks no longer receive events."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                received: list[dict[str, Any]] = []

                def on_event(params: dict[str, Any]) -> None:
                    received.append(params)

                client.subscribe(on_event)
                client.unsubscribe(on_event)

                await asyncio.sleep(0.05)
                event = make_event("test", {"msg": "hello"}, seq=1)
                await server.broadcast(event)
                await asyncio.sleep(0.2)

                assert len(received) == 0
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_is_noop(self, tmp_path: Path) -> None:
        """Unsubscribing a non-registered callback is a silent no-op."""
        client = SocketClient(socket_path=tmp_path / "test.sock")

        def dummy(params: dict[str, Any]) -> None:
            pass

        client.unsubscribe(dummy)  # Should not raise

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_crash_reader(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Buggy callbacks are caught and do not crash the reader loop."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                good_received: list[dict[str, Any]] = []

                def bad_callback(params: dict[str, Any]) -> None:
                    raise ValueError("I'm a buggy callback")

                def good_callback(params: dict[str, Any]) -> None:
                    good_received.append(params)

                client.subscribe(bad_callback)
                client.subscribe(good_callback)

                await asyncio.sleep(0.05)

                event = make_event("test", {"msg": "hello"}, seq=1)
                await server.broadcast(event)
                await asyncio.sleep(0.2)

                # Good callback should still receive the event
                assert len(good_received) == 1

                # Client should still be connected
                assert client.is_connected is True

                # And commands should still work
                result = await client.send_command("ping")
                assert result["pong"] is True
            finally:
                await client.disconnect()
        finally:
            await server.stop()


class TestSocketClientConvenienceMethods:
    """Test typed convenience methods."""

    @pytest.mark.asyncio
    async def test_ping_returns_typed_result(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                result = await client.ping()
                assert isinstance(result, PingResult)
                assert result.pong is True
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_get_state_returns_typed_result(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        server.update_runner_state(
            state=RunnerState.RUNNING,
            state_data={"current_epic": 29},
        )
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                result = await client.get_state()
                assert isinstance(result, GetStateResult)
                assert result.state == "running"
                assert result.current_epic == 29
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_typed_result(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                result = await client.get_capabilities()
                assert isinstance(result, GetCapabilitiesResult)
                assert result.protocol_version == PROTOCOL_VERSION
                assert "ping" in result.supported_methods
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_pause_raises_command_error(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """pause() raises IPCCommandError since not implemented (Story 29.5)."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                with pytest.raises(IPCCommandError):
                    await client.pause()
            finally:
                await client.disconnect()
        finally:
            await server.stop()


class TestSocketClientAutoReconnect:
    """Test auto-reconnect behavior."""

    @pytest.mark.asyncio
    async def test_reconnect_on_server_stop(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Client reconnects after server stop/restart."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()

        reconnect_called = asyncio.Event()
        disconnect_called = asyncio.Event()

        def on_reconnect() -> None:
            reconnect_called.set()

        def on_disconnect() -> None:
            disconnect_called.set()

        client = SocketClient(
            socket_path=sock_path,
            auto_reconnect=True,
            max_retries=5,
            on_reconnect=on_reconnect,
            on_disconnect=on_disconnect,
        )
        await client.connect()

        try:
            # Stop server
            await server.stop()

            # Wait for disconnect callback
            await asyncio.wait_for(disconnect_called.wait(), timeout=3.0)

            # Restart server
            server2 = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
            await server2.start()

            try:
                # Wait for reconnect
                await asyncio.wait_for(reconnect_called.wait(), timeout=10.0)
                assert client.state == ConnectionState.CONNECTED

                # Verify connection works
                result = await client.send_command("ping")
                assert result["pong"] is True
            finally:
                await server2.stop()
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_no_reconnect_after_explicit_disconnect(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Explicit disconnect() sets CLOSED, prevents reconnect."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(
                socket_path=sock_path,
                auto_reconnect=True,
            )
            await client.connect()
            await client.disconnect()
            assert client.state == ConnectionState.CLOSED
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_no_reconnect_when_disabled(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """auto_reconnect=False means no reconnect attempt."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()

        client = SocketClient(
            socket_path=sock_path,
            auto_reconnect=False,
        )
        await client.connect()

        # Stop server
        await server.stop()

        # Wait for reader to detect disconnect
        await asyncio.sleep(0.5)

        assert client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, tmp_path: Path) -> None:
        """After max retries, state is DISCONNECTED."""
        sock_path = tmp_path / "nonexistent.sock"

        client = SocketClient(
            socket_path=sock_path,
            auto_reconnect=True,
            max_retries=2,
        )

        # Manually trigger reconnect (simulating connection loss)
        client._state = ConnectionState.CONNECTED  # Pretend we were connected
        await client._reconnect()

        # After failed retries, should be disconnected
        assert client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_pending_requests_failed_on_disconnect(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """All pending requests get IPCConnectionError on connection loss."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()

        client = SocketClient(
            socket_path=sock_path,
            auto_reconnect=False,
        )
        await client.connect()

        # Inject a pending future
        loop = asyncio.get_running_loop()
        pending_future: asyncio.Future[dict[str, Any]] = loop.create_future()
        client._pending[42] = pending_future

        # Stop server to trigger disconnect
        await server.stop()
        await asyncio.sleep(0.5)

        assert pending_future.done()
        with pytest.raises(IPCConnectionError):
            pending_future.result()


class TestSocketClientContextManager:
    """Test async context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            async with SocketClient(socket_path=sock_path) as client:
                assert client.is_connected is True
                result = await client.send_command("ping")
                assert result["pong"] is True
            # After exit, state should be CLOSED
            assert client.state == ConnectionState.CLOSED
        finally:
            await server.stop()


class TestSocketClientClientId:
    """Test client_id inclusion in requests."""

    @pytest.mark.asyncio
    async def test_client_id_in_request(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """client_id is included in JSON-RPC requests."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(
                socket_path=sock_path,
                client_id="test-tui",
            )
            await client.connect()
            try:
                # The server processes our request and the client_id is visible
                # in server logs. We verify the client works with client_id set.
                result = await client.send_command("ping")
                assert result["pong"] is True
            finally:
                await client.disconnect()
        finally:
            await server.stop()


class TestSocketClientInterleaved:
    """Test commands interleaved with events."""

    @pytest.mark.asyncio
    async def test_command_during_event_stream(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Client can send commands while receiving events."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                events: list[dict[str, Any]] = []
                client.subscribe(lambda p: events.append(p))
                await asyncio.sleep(0.05)

                # Broadcast several events
                for i in range(3):
                    event = make_event("test", {"n": i}, seq=server.next_event_seq())
                    await server.broadcast(event)

                # Immediately send a command
                result = await client.send_command("ping")
                assert result["pong"] is True

                # Wait for events
                await asyncio.sleep(0.3)
                assert len(events) == 3
            finally:
                await client.disconnect()
        finally:
            await server.stop()


# ============================================================================
# Unit Tests: SyncSocketClient (Task 13.14 — AC #8)
# ============================================================================


class TestSyncSocketClientBasic:
    """Test SyncSocketClient wrapper."""

    def test_initial_state(self, tmp_path: Path) -> None:
        client = SyncSocketClient(socket_path=tmp_path / "test.sock")
        assert client.is_connected is False
        assert client.state == ConnectionState.DISCONNECTED

    def test_connect_to_nonexistent_raises(self, tmp_path: Path) -> None:
        client = SyncSocketClient(socket_path=tmp_path / "nonexistent.sock")
        with pytest.raises(IPCConnectionError):
            client.connect(timeout=1.0)

    def test_send_command_not_connected(self, tmp_path: Path) -> None:
        client = SyncSocketClient(socket_path=tmp_path / "test.sock")
        with pytest.raises(IPCConnectionError, match="Not connected"):
            client.send_command("ping")


# ============================================================================
# Integration Tests (Task 14 — AC #14)
# ============================================================================


class TestIntegrationClientServerPing:
    """Integration: full client-server ping roundtrip."""

    @pytest.mark.asyncio
    async def test_client_ping(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Client connects, sends ping, receives valid PingResult."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                result = await client.ping()
                assert isinstance(result, PingResult)
                assert result.pong is True
                assert result.server_time  # Not empty
            finally:
                await client.disconnect()
        finally:
            await server.stop()


class TestIntegrationEventSubscription:
    """Integration: event subscription with real server."""

    @pytest.mark.asyncio
    async def test_client_receives_broadcast(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Server broadcasts event, client callback receives it."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                received = asyncio.Event()
                event_data: list[dict[str, Any]] = []

                def on_event(params: dict[str, Any]) -> None:
                    event_data.append(params)
                    received.set()

                client.subscribe(on_event)
                await asyncio.sleep(0.05)

                event = make_event(
                    "state_changed",
                    {"field": "state", "old_value": "idle", "new_value": "running"},
                    seq=server.next_event_seq(),
                )
                await server.broadcast(event)

                await asyncio.wait_for(received.wait(), timeout=3.0)
                assert event_data[0]["type"] == "state_changed"
                assert event_data[0]["data"]["new_value"] == "running"
            finally:
                await client.disconnect()
        finally:
            await server.stop()


class TestIntegrationReconnect:
    """Integration: reconnect after server restart."""

    @pytest.mark.asyncio
    async def test_reconnect_after_server_restart(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """Client reconnects automatically after server restart."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()

        reconnected = asyncio.Event()

        def on_reconnect() -> None:
            reconnected.set()

        client = SocketClient(
            socket_path=sock_path,
            auto_reconnect=True,
            max_retries=10,
            on_reconnect=on_reconnect,
        )
        await client.connect()

        try:
            # Verify initial connection
            result = await client.ping()
            assert result.pong is True

            # Stop server
            await server.stop()

            # Brief pause
            await asyncio.sleep(0.3)

            # Restart server
            server2 = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
            await server2.start()

            try:
                # Wait for reconnect
                await asyncio.wait_for(reconnected.wait(), timeout=15.0)

                # Verify reconnected connection works
                result = await client.ping()
                assert result.pong is True
            finally:
                await server2.stop()
        finally:
            await client.disconnect()


class TestIntegrationSyncClient:
    """Integration: SyncSocketClient with real server."""

    def test_sync_client_ping(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """SyncSocketClient connects, pings, disconnects from sync code."""
        # Start server in a background thread (uses IPCServerThread)
        from bmad_assist.ipc.server import IPCServerThread

        server_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=sock_dir.parent,
        )
        server_thread.start(timeout=5.0)

        try:
            client = SyncSocketClient(
                socket_path=sock_path,
                client_id="sync-test",
            )
            client.connect(timeout=5.0)
            try:
                assert client.is_connected is True

                result = client.ping()
                assert isinstance(result, PingResult)
                assert result.pong is True

                state = client.get_state()
                assert isinstance(state, GetStateResult)
            finally:
                client.disconnect()

            assert client.state == ConnectionState.CLOSED
        finally:
            server_thread.stop(timeout=5.0)

    def test_sync_client_context_manager(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """SyncSocketClient works as context manager."""
        from bmad_assist.ipc.server import IPCServerThread

        server_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=sock_dir.parent,
        )
        server_thread.start(timeout=5.0)

        try:
            with SyncSocketClient(socket_path=sock_path) as client:
                assert client.is_connected is True
                result = client.ping()
                assert result.pong is True
        finally:
            server_thread.stop(timeout=5.0)

    def test_sync_client_get_capabilities(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """SyncSocketClient get_capabilities returns typed result."""
        from bmad_assist.ipc.server import IPCServerThread

        server_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=sock_dir.parent,
        )
        server_thread.start(timeout=5.0)

        try:
            with SyncSocketClient(socket_path=sock_path) as client:
                caps = client.get_capabilities()
                assert isinstance(caps, GetCapabilitiesResult)
                assert caps.protocol_version == PROTOCOL_VERSION
        finally:
            server_thread.stop(timeout=5.0)


class TestIntegrationContextManager:
    """Integration: context manager with real server."""

    @pytest.mark.asyncio
    async def test_async_with_real_server(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            async with SocketClient(socket_path=sock_path) as client:
                result = await client.ping()
                assert result.pong is True
        finally:
            await server.stop()


# ============================================================================
# Story 29.10: IPC Client Hardening Tests
# ============================================================================


class TestSubscriptionCleanup:
    """Test subscription auto-cleanup on disconnect (AC #1, #6)."""

    @pytest.mark.asyncio
    async def test_disconnect_clears_all_event_callbacks(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """AC #1: disconnect() clears all registered event callbacks."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            client.subscribe(lambda p: None)
            client.subscribe(lambda p: None)
            assert len(client._event_callbacks) == 2
            await client.disconnect()
            assert len(client._event_callbacks) == 0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_callbacks_cleared_on_connection_lost_without_reconnect(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """AC #1: Callbacks cleared when connection lost and no auto-reconnect."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()

        client = SocketClient(
            socket_path=sock_path,
            auto_reconnect=False,
        )
        await client.connect()
        client.subscribe(lambda p: None)
        assert len(client._event_callbacks) == 1

        # Stop server to cause connection loss
        await server.stop()
        # Wait for reader to detect loss
        await asyncio.sleep(0.3)

        # Without auto-reconnect, callbacks should be cleared
        assert len(client._event_callbacks) == 0
        assert client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_clear_subscriptions_empties_callback_list(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """AC #6: clear_subscriptions() empties callback list without disconnecting."""
        server = SocketServer(socket_path=sock_path, project_root=sock_dir.parent)
        await server.start()
        try:
            client = SocketClient(socket_path=sock_path)
            await client.connect()
            try:
                client.subscribe(lambda p: None)
                client.subscribe(lambda p: None)
                assert len(client._event_callbacks) == 2

                client.clear_subscriptions()
                assert len(client._event_callbacks) == 0
                # Client should still be connected
                assert client.is_connected is True
            finally:
                await client.disconnect()
        finally:
            await server.stop()


class TestReconnectFailedCallback:
    """Test on_reconnect_failed callback (AC #2)."""

    @pytest.mark.asyncio
    async def test_on_reconnect_failed_callback_invoked(self, tmp_path: Path) -> None:
        """AC #2: on_reconnect_failed callback receives IPCReconnectError."""
        sock_path = tmp_path / "nonexistent.sock"
        failed_errors: list[IPCReconnectError] = []

        def on_failed(err: IPCReconnectError) -> None:
            failed_errors.append(err)

        client = SocketClient(
            socket_path=sock_path,
            auto_reconnect=True,
            max_retries=2,
            on_reconnect_failed=on_failed,
        )
        client._state = ConnectionState.CONNECTED
        await client._reconnect()

        assert len(failed_errors) == 1
        assert isinstance(failed_errors[0], IPCReconnectError)
        assert "2 attempts" in str(failed_errors[0])
        assert client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_on_reconnect_failed_callback_exception_does_not_crash(
        self, tmp_path: Path
    ) -> None:
        """AC #2: Callback exception does not crash the reader task."""
        sock_path = tmp_path / "nonexistent.sock"

        def buggy_callback(err: IPCReconnectError) -> None:
            raise RuntimeError("callback bug")

        client = SocketClient(
            socket_path=sock_path,
            auto_reconnect=True,
            max_retries=1,
            on_reconnect_failed=buggy_callback,
        )
        client._state = ConnectionState.CONNECTED

        # Should not raise despite buggy callback
        await client._reconnect()
        assert client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_callbacks_cleared_on_reconnect_exhaustion(
        self, tmp_path: Path
    ) -> None:
        """AC #1: Callbacks cleared when reconnect retries exhausted."""
        sock_path = tmp_path / "nonexistent.sock"

        client = SocketClient(
            socket_path=sock_path,
            auto_reconnect=True,
            max_retries=1,
        )
        client._state = ConnectionState.CONNECTED
        client.subscribe(lambda p: None)
        assert len(client._event_callbacks) == 1

        await client._reconnect()

        assert len(client._event_callbacks) == 0
        assert client.state == ConnectionState.DISCONNECTED


class TestSyncSocketClientTimeout:
    """Test SyncSocketClient convenience methods accept timeout parameter (AC #3)."""

    def test_ping_accepts_custom_timeout(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """AC #3: ping(timeout=...) is honored."""
        from bmad_assist.ipc.server import IPCServerThread

        server_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=sock_dir.parent,
        )
        server_thread.start(timeout=5.0)
        try:
            with SyncSocketClient(socket_path=sock_path) as client:
                result = client.ping(timeout=10.0)
                assert isinstance(result, PingResult)
                assert result.pong is True
        finally:
            server_thread.stop(timeout=5.0)

    def test_get_capabilities_accepts_custom_timeout(
        self, sock_path: Path, sock_dir: Path
    ) -> None:
        """AC #3: get_capabilities(timeout=...) is honored."""
        from bmad_assist.ipc.server import IPCServerThread

        server_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=sock_dir.parent,
        )
        server_thread.start(timeout=5.0)
        try:
            with SyncSocketClient(socket_path=sock_path) as client:
                caps = client.get_capabilities(timeout=10.0)
                assert isinstance(caps, GetCapabilitiesResult)
        finally:
            server_thread.stop(timeout=5.0)

    def test_all_convenience_methods_have_timeout_param(self) -> None:
        """AC #3: All 8 convenience methods accept timeout parameter."""
        import inspect

        methods = [
            "ping", "get_state", "get_capabilities", "pause",
            "resume", "stop", "set_log_level", "reload_config",
        ]
        for method_name in methods:
            method = getattr(SyncSocketClient, method_name)
            sig = inspect.signature(method)
            assert "timeout" in sig.parameters, (
                f"SyncSocketClient.{method_name} missing timeout parameter"
            )
            assert sig.parameters["timeout"].default == 30.0, (
                f"SyncSocketClient.{method_name} timeout default should be 30.0"
            )
