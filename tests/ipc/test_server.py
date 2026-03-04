"""Unit and integration tests for the IPC socket server.

Story 29.2: Tests cover SocketServer lifecycle, connection handling,
message parsing, error responses, broadcast delivery, stale socket cleanup,
IPCServerThread thread bridge, and real Unix socket integration.
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.ipc.protocol import (
    IDLE_TIMEOUT,
    MAX_CONNECTIONS,
    MAX_MESSAGE_SIZE,
    MAX_PARSE_ERRORS,
    PROTOCOL_VERSION,
    SUPPORTED_METHODS,
    ErrorCode,
    deserialize,
    make_event,
    read_message,
    serialize,
    write_message,
)
from bmad_assist.ipc.server import (
    IPCServerThread,
    SocketServer,
    _BACKPRESSURE_THRESHOLD,
    _BROADCAST_WRITE_TIMEOUT,
)
from bmad_assist.ipc.types import (
    EventPriority,
    GetCapabilitiesResult,
    GetStateResult,
    PingResult,
    RunnerState,
)


# ============================================================================
# Helper: send/receive JSON-RPC messages over Unix socket
# ============================================================================


async def send_rpc(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    method: str,
    params: dict[str, Any] | None = None,
    request_id: int | str = 1,
) -> dict[str, Any]:
    """Send a JSON-RPC request and read the response.

    Args:
        reader: Stream reader.
        writer: Stream writer.
        method: RPC method name.
        params: Optional method parameters.
        request_id: Request ID for correlation.

    Returns:
        Parsed JSON-RPC response dict.

    """
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
# Unit Tests: SocketServer
# ============================================================================


class TestSocketServerProperties:
    """Test SocketServer properties and initial state."""

    def test_initial_state(self, tmp_path: Path) -> None:
        """Server starts in not-running state with zero clients."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        assert server.is_running is False
        assert server.client_count == 0

    def test_update_runner_state(self, tmp_path: Path) -> None:
        """update_runner_state updates cached state."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        server.update_runner_state(
            state=RunnerState.RUNNING,
            state_data={"current_epic": 1, "current_story": "1.1"},
        )
        assert server._runner_state == RunnerState.RUNNING
        assert server._runner_state_data["current_epic"] == 1

    def test_next_event_seq_monotonic(self, tmp_path: Path) -> None:
        """Event sequence numbers are monotonically increasing."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        seq1 = server.next_event_seq()
        seq2 = server.next_event_seq()
        seq3 = server.next_event_seq()
        assert seq1 == 1
        assert seq2 == 2
        assert seq3 == 3


class TestSocketServerStartStop:
    """Test server start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_socket_and_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Server creates socket file and lock file on start."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        await server.start()
        try:
            assert server.is_running is True
            assert sock_path.exists()
            assert Path(f"{sock_path}.lock").exists()

            # Check socket permissions
            mode = sock_path.stat().st_mode & 0o777
            assert mode == 0o600

            # Check lock file content
            lock_content = Path(f"{sock_path}.lock").read_text()
            assert str(os.getpid()) in lock_content
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_stop_removes_socket_and_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Server removes socket file and lock file on stop."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        await server.start()
        assert server.is_running is True

        await server.stop()
        assert server.is_running is False
        assert not sock_path.exists()
        assert not Path(f"{sock_path}.lock").exists()

    @pytest.mark.asyncio
    async def test_start_when_already_running(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Starting an already-running server is a no-op."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        await server.start()
        try:
            await server.start()  # Should not raise
            assert server.is_running is True
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, tmp_path: Path) -> None:
        """Stopping a non-running server is a no-op."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        await server.stop()  # Should not raise


class TestStaleSocketDetection:
    """Test stale socket detection and cleanup."""

    def test_no_existing_socket(self, tmp_path: Path) -> None:
        """No stale check needed when socket doesn't exist."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        # Should not raise
        server._check_stale_socket()

    def test_stale_socket_dead_process(self, tmp_path: Path) -> None:
        """Stale socket from dead process is removed."""
        sock_path = tmp_path / "test.sock"
        lock_path = Path(f"{sock_path}.lock")

        # Create fake socket and lock with dead PID
        sock_path.write_text("fake socket")
        lock_path.write_text("99999999\n2026-01-01T00:00:00Z\n")

        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        with patch("bmad_assist.ipc.server._is_pid_alive", return_value=False):
            server._check_stale_socket()

        assert not sock_path.exists()
        assert not lock_path.exists()

    def test_active_socket_raises(self, tmp_path: Path) -> None:
        """Active socket from live process raises StateError."""
        from bmad_assist.core.exceptions import StateError

        sock_path = tmp_path / "test.sock"
        lock_path = Path(f"{sock_path}.lock")

        sock_path.write_text("fake socket")
        lock_path.write_text(f"{os.getpid()}\n2026-01-01T00:00:00Z\n")

        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        with pytest.raises(StateError, match="Another IPC server"):
            server._check_stale_socket()

    def test_stale_socket_no_lock_file(self, tmp_path: Path) -> None:
        """Socket without lock file is treated as stale (PID=None, not alive)."""
        sock_path = tmp_path / "test.sock"
        sock_path.write_text("fake socket")

        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        # No lock file means _read_socket_lock_pid returns None
        # _is_pid_alive(None) is never called, pid=None means stale
        server._check_stale_socket()
        assert not sock_path.exists()

    def test_stale_socket_invalid_lock_content(self, tmp_path: Path) -> None:
        """Socket with invalid lock file content is treated as stale."""
        sock_path = tmp_path / "test.sock"
        lock_path = Path(f"{sock_path}.lock")

        sock_path.write_text("fake socket")
        lock_path.write_text("not-a-pid\n")

        server = SocketServer(socket_path=sock_path, project_root=tmp_path)
        server._check_stale_socket()
        assert not sock_path.exists()


class TestMethodRouting:
    """Test method routing for ping, get_capabilities, get_state."""

    @pytest.mark.asyncio
    async def test_ping_response(self, tmp_path: Path) -> None:
        """ping method returns PingResult with pong=True."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "method": "ping", "id": 1}
        )
        assert response is not None
        assert response["id"] == 1
        result = response["result"]
        assert result["pong"] is True
        assert "server_time" in result

    @pytest.mark.asyncio
    async def test_get_capabilities_response(self, tmp_path: Path) -> None:
        """get_capabilities returns protocol version, server version, methods."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "method": "get_capabilities", "id": 2}
        )
        assert response is not None
        result = response["result"]
        assert result["protocol_version"] == PROTOCOL_VERSION
        assert isinstance(result["server_version"], str)
        assert isinstance(result["supported_methods"], list)
        assert "ping" in result["supported_methods"]
        assert "get_state" in result["supported_methods"]

    @pytest.mark.asyncio
    async def test_get_capabilities_features_dict_populated(self, tmp_path: Path) -> None:
        """AC #4: get_capabilities returns populated features dict with expected keys."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "method": "get_capabilities", "id": 2}
        )
        assert response is not None
        features = response["result"]["features"]
        assert "goodbye_event" in features
        assert "project_identity" in features
        assert "reload_config" in features

    @pytest.mark.asyncio
    async def test_get_capabilities_features_values_are_booleans(self, tmp_path: Path) -> None:
        """AC #4: All values in features dict are boolean."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "method": "get_capabilities", "id": 2}
        )
        assert response is not None
        features = response["result"]["features"]
        for key, value in features.items():
            assert isinstance(value, bool), f"features[{key}] must be bool, got {type(value)}"
        assert features["goodbye_event"] is True
        assert features["project_identity"] is True
        assert features["reload_config"] is True

    @pytest.mark.asyncio
    async def test_get_state_response_idle(self, tmp_path: Path) -> None:
        """get_state returns idle state by default."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "method": "get_state", "id": 3}
        )
        assert response is not None
        result = response["result"]
        assert result["state"] == "idle"
        assert result["running"] is False
        assert result["paused"] is False

    @pytest.mark.asyncio
    async def test_get_state_with_runner_data(self, tmp_path: Path) -> None:
        """get_state reflects updated runner state."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        server.update_runner_state(
            state=RunnerState.RUNNING,
            state_data={
                "current_epic": 29,
                "current_story": "29.2",
                "current_phase": "dev_story",
            },
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "method": "get_state", "id": 4}
        )
        result = response["result"]
        assert result["state"] == "running"
        assert result["running"] is True
        assert result["current_epic"] == 29
        assert result["current_story"] == "29.2"
        assert result["current_phase"] == "dev_story"

    @pytest.mark.asyncio
    async def test_supported_method_without_handler_returns_internal_error(self, tmp_path: Path) -> None:
        """Supported methods without handler return INTERNAL_ERROR (Story 29.5)."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
            handler=None,
        )
        for method in ["pause", "resume", "stop", "reload_config", "set_log_level"]:
            response = await server._route_message(
                {"jsonrpc": "2.0", "method": method, "id": 10}
            )
            assert response is not None
            assert "error" in response
            assert response["error"]["code"] == ErrorCode.INTERNAL_ERROR.code
            assert "No command handler configured" in response["error"]["data"]["reason"]

    @pytest.mark.asyncio
    async def test_unknown_method(self, tmp_path: Path) -> None:
        """Unknown methods return METHOD_NOT_FOUND."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "method": "nonexistent", "id": 5}
        )
        assert response is not None
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.METHOD_NOT_FOUND.code

    @pytest.mark.asyncio
    async def test_invalid_request_no_method(self, tmp_path: Path) -> None:
        """Request without method field returns INVALID_REQUEST."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "id": 6}
        )
        assert response is not None
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.INVALID_REQUEST.code

    @pytest.mark.asyncio
    async def test_notification_no_response(self, tmp_path: Path) -> None:
        """Notifications (no id, not event method) return None."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "method": "some_notification"}
        )
        assert response is None


class TestBroadcast:
    """Test event broadcast to connected clients."""

    @pytest.mark.asyncio
    async def test_broadcast_no_clients(self, tmp_path: Path) -> None:
        """Broadcast with no clients is a no-op."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        event = make_event("test", {"msg": "hello"}, seq=1)
        # Should not raise
        await server.broadcast(event)

    @pytest.mark.asyncio
    async def test_broadcast_removes_broken_clients(self, tmp_path: Path) -> None:
        """Broadcast removes clients that raise on write."""
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )

        # Create a mock writer that raises on write
        mock_writer = MagicMock(spec=asyncio.StreamWriter)
        mock_transport = MagicMock()
        mock_transport.get_write_buffer_size.return_value = 0
        mock_writer.transport = mock_transport

        # Simulate write_message raising ConnectionResetError
        # write_message calls writer.write() and writer.drain()
        mock_writer.write.side_effect = ConnectionResetError("broken pipe")

        server._clients.add(mock_writer)
        server._client_ids[mock_writer] = "test-client"

        event = make_event("test", {"msg": "hello"}, seq=1)
        await server.broadcast(event)

        assert mock_writer not in server._clients


# ============================================================================
# Integration Tests: Real Unix Socket
# ============================================================================


class TestIntegrationPing:
    """Integration test: full ping round-trip over real Unix socket."""

    @pytest.mark.asyncio
    async def test_ping_roundtrip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client connects, sends ping, receives pong, server stops clean."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        await server.start()
        try:
            # Connect as client
            reader, writer = await asyncio.open_unix_connection(str(sock_path))
            try:
                # Send ping
                response = await send_rpc(reader, writer, "ping", request_id=42)

                assert response["jsonrpc"] == "2.0"
                assert response["id"] == 42
                assert response["result"]["pong"] is True
                assert "server_time" in response["result"]
            finally:
                writer.close()
                await writer.wait_closed()

            # Give server a moment to process disconnect
            await asyncio.sleep(0.05)
            assert server.client_count == 0
        finally:
            await server.stop()

        # Socket file should be removed
        assert not sock_path.exists()
        assert not Path(f"{sock_path}.lock").exists()

    @pytest.mark.asyncio
    async def test_get_capabilities_roundtrip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_capabilities returns expected fields over real socket."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        await server.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(sock_path))
            try:
                response = await send_rpc(reader, writer, "get_capabilities", request_id=1)

                result = response["result"]
                assert result["protocol_version"] == PROTOCOL_VERSION
                assert isinstance(result["supported_methods"], list)
                assert len(result["supported_methods"]) > 0
                # Our client should be in connected_clients
                assert len(result["connected_clients"]) == 1
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_get_state_roundtrip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_state returns runner state over real socket."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)
        server.update_runner_state(
            state=RunnerState.RUNNING,
            state_data={"current_epic": 29, "current_story": "29.2"},
        )

        await server.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(sock_path))
            try:
                response = await send_rpc(reader, writer, "get_state", request_id=1)
                result = response["result"]
                assert result["state"] == "running"
                assert result["running"] is True
                assert result["current_epic"] == 29
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()


class TestIntegrationMultiClient:
    """Integration test: multiple concurrent clients."""

    @pytest.mark.asyncio
    async def test_two_clients_ping(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two clients connect, both can send/receive independently."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        await server.start()
        try:
            # Connect two clients
            r1, w1 = await asyncio.open_unix_connection(str(sock_path))
            r2, w2 = await asyncio.open_unix_connection(str(sock_path))

            await asyncio.sleep(0.05)
            assert server.client_count == 2

            try:
                # Both send ping
                resp1 = await send_rpc(r1, w1, "ping", request_id=1)
                resp2 = await send_rpc(r2, w2, "ping", request_id=2)

                assert resp1["result"]["pong"] is True
                assert resp2["result"]["pong"] is True
                assert resp1["id"] == 1
                assert resp2["id"] == 2
            finally:
                w1.close()
                await w1.wait_closed()
                w2.close()
                await w2.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_broadcast_to_clients(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Broadcast event is received by all connected clients."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        await server.start()
        try:
            r1, w1 = await asyncio.open_unix_connection(str(sock_path))
            r2, w2 = await asyncio.open_unix_connection(str(sock_path))

            await asyncio.sleep(0.05)

            try:
                # Broadcast an event
                event = make_event(
                    "phase_started",
                    {"phase": "dev_story"},
                    seq=server.next_event_seq(),
                )
                await server.broadcast(event)

                # Both clients should receive the event
                raw1 = await asyncio.wait_for(read_message(r1), timeout=2.0)
                raw2 = await asyncio.wait_for(read_message(r2), timeout=2.0)

                msg1 = deserialize(raw1)
                msg2 = deserialize(raw2)

                assert msg1["method"] == "event"
                assert msg1["params"]["type"] == "phase_started"
                assert msg2["method"] == "event"
                assert msg2["params"]["type"] == "phase_started"
            finally:
                w1.close()
                await w1.wait_closed()
                w2.close()
                await w2.wait_closed()
        finally:
            await server.stop()


class TestIntegrationConnectionLimit:
    """Integration test: connection limit enforcement."""

    @pytest.mark.asyncio
    async def test_reject_beyond_max_connections(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Connections beyond MAX_CONNECTIONS receive error and are closed."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)
        # Use a small limit for testing
        monkeypatch.setattr("bmad_assist.ipc.server.MAX_CONNECTIONS", 2)

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        await server.start()
        clients: list[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = []
        try:
            # Connect MAX (2) clients
            for _ in range(2):
                r, w = await asyncio.open_unix_connection(str(sock_path))
                clients.append((r, w))

            await asyncio.sleep(0.05)
            assert server.client_count == 2

            # Third connection should get error
            r3, w3 = await asyncio.open_unix_connection(str(sock_path))
            try:
                raw = await asyncio.wait_for(read_message(r3), timeout=2.0)
                msg = deserialize(raw)
                assert "error" in msg
                assert msg["error"]["code"] == ErrorCode.RUNNER_BUSY.code
            finally:
                w3.close()
                await w3.wait_closed()
        finally:
            for r, w in clients:
                w.close()
                await w.wait_closed()
            await server.stop()


class TestIntegrationParseErrors:
    """Integration test: parse error handling."""

    @pytest.mark.asyncio
    async def test_parse_error_response(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid JSON triggers PARSE_ERROR response."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        await server.start()
        try:
            r, w = await asyncio.open_unix_connection(str(sock_path))
            try:
                # Send invalid JSON (raw bytes with length prefix)
                invalid_json = b"not valid json{{"
                header = struct.pack(">I", len(invalid_json))
                w.write(header + invalid_json)
                await w.drain()

                # Should get PARSE_ERROR response
                raw = await asyncio.wait_for(read_message(r), timeout=2.0)
                msg = deserialize(raw)
                assert "error" in msg
                assert msg["error"]["code"] == ErrorCode.PARSE_ERROR.code

                # Connection should still be open (1 error < MAX_PARSE_ERRORS)
                # Send a valid request to verify
                resp = await send_rpc(r, w, "ping", request_id=1)
                assert resp["result"]["pong"] is True
            finally:
                w.close()
                await w.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_max_parse_errors_closes_connection(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Connection closed after MAX_PARSE_ERRORS consecutive parse errors."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=tmp_path)

        await server.start()
        try:
            r, w = await asyncio.open_unix_connection(str(sock_path))
            try:
                # Send MAX_PARSE_ERRORS invalid messages
                for _ in range(MAX_PARSE_ERRORS):
                    invalid = b"[invalid"
                    header = struct.pack(">I", len(invalid))
                    w.write(header + invalid)
                    await w.drain()
                    # Read error response
                    try:
                        raw = await asyncio.wait_for(read_message(r), timeout=2.0)
                    except (asyncio.IncompleteReadError, ConnectionError):
                        break

                # Connection should be closed — next read should fail
                await asyncio.sleep(0.1)
                with pytest.raises((asyncio.IncompleteReadError, ConnectionError)):
                    await asyncio.wait_for(read_message(r), timeout=1.0)
            finally:
                w.close()
                try:
                    await w.wait_closed()
                except Exception:
                    pass
        finally:
            await server.stop()


# ============================================================================
# IPCServerThread Tests
# ============================================================================


class TestIPCServerThread:
    """Test the thread bridge for sync-to-async communication."""

    def test_initial_state(self, tmp_path: Path) -> None:
        """Thread starts in not-running state."""
        thread = IPCServerThread(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        assert thread.is_running is False
        assert thread.client_count == 0

    def test_start_and_stop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Thread starts server and stops cleanly."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "thread-test.sock"
        thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )

        thread.start(timeout=5.0)
        try:
            assert thread.is_running is True
            assert sock_path.exists()
        finally:
            thread.stop(timeout=5.0)

        assert thread.is_running is False
        assert not sock_path.exists()

    def test_update_state(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """update_state updates server runner state from main thread."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "state-test.sock"
        thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )

        thread.start(timeout=5.0)
        try:
            thread.update_state(
                state=RunnerState.RUNNING,
                state_data={"current_epic": 1},
            )
            assert thread._server._runner_state == RunnerState.RUNNING
        finally:
            thread.stop(timeout=5.0)

    def test_broadcast_threadsafe(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """broadcast_threadsafe does not raise even with no clients."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "broadcast-test.sock"
        thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )

        thread.start(timeout=5.0)
        try:
            event = thread.make_event("test", {"msg": "hello"})
            thread.broadcast_threadsafe(event)  # Should not raise
        finally:
            thread.stop(timeout=5.0)

    def test_broadcast_when_not_running(self, tmp_path: Path) -> None:
        """broadcast_threadsafe is no-op when not running."""
        thread = IPCServerThread(
            socket_path=tmp_path / "test.sock",
            project_root=tmp_path,
        )
        # Should not raise
        thread.broadcast_threadsafe({"test": True})

    def test_make_event_returns_valid_event(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """make_event returns proper JSON-RPC event with sequence number."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "event-test.sock"
        thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )

        thread.start(timeout=5.0)
        try:
            event1 = thread.make_event("test_event", {"key": "value"})
            event2 = thread.make_event("another", {"x": 1})

            assert event1["method"] == "event"
            assert event1["params"]["type"] == "test_event"
            assert event1["params"]["seq"] < event2["params"]["seq"]
        finally:
            thread.stop(timeout=5.0)

    def test_start_twice_no_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Starting an already-running thread is a no-op."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "twice-test.sock"
        thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )

        thread.start(timeout=5.0)
        try:
            thread.start(timeout=5.0)  # Should be no-op
            assert thread.is_running is True
        finally:
            thread.stop(timeout=5.0)


class TestIPCServerThreadIntegration:
    """Integration test: IPCServerThread with real client connection."""

    def test_client_ping_via_thread(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client connects to thread-managed server and sends ping."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "thread-int.sock"
        thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )

        thread.start(timeout=5.0)
        try:
            # Use asyncio.run to interact with the server from the test thread
            async def _test() -> dict[str, Any]:
                r, w = await asyncio.open_unix_connection(str(sock_path))
                try:
                    return await send_rpc(r, w, "ping", request_id=99)
                finally:
                    w.close()
                    await w.wait_closed()

            response = asyncio.run(_test())
            assert response["result"]["pong"] is True
            assert response["id"] == 99
        finally:
            thread.stop(timeout=5.0)

    def test_broadcast_received_by_client(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """broadcast_threadsafe delivers event to connected client."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        sock_path = sock_dir / "bcast-int.sock"
        thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )

        thread.start(timeout=5.0)
        try:

            async def _test() -> dict[str, Any]:
                r, w = await asyncio.open_unix_connection(str(sock_path))
                try:
                    # Give server time to register client
                    await asyncio.sleep(0.05)

                    # Broadcast from main thread
                    event = thread.make_event(
                        "phase_started", {"phase": "dev_story"}
                    )
                    thread.broadcast_threadsafe(event)

                    # Read the broadcast event
                    raw = await asyncio.wait_for(read_message(r), timeout=3.0)
                    return deserialize(raw)
                finally:
                    w.close()
                    await w.wait_closed()

            msg = asyncio.run(_test())
            assert msg["method"] == "event"
            assert msg["params"]["type"] == "phase_started"
            assert msg["params"]["data"]["phase"] == "dev_story"
        finally:
            thread.stop(timeout=5.0)


# ============================================================================
# Socket path length validation integration (Story 29.7)
# ============================================================================


# ============================================================================
# Story 29.9: Project identity in get_state response
# ============================================================================


class TestGetStateProjectIdentity:
    """Story 29.9 AC #1-2: get_state includes project_name and project_path."""

    @pytest.mark.asyncio
    async def test_get_state_includes_project_name(self, tmp_path: Path) -> None:
        """get_state response includes project_name matching project_root.name."""
        project = tmp_path / "my-cool-project"
        project.mkdir()
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=project,
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "method": "get_state", "id": 1}
        )
        assert response is not None
        result = response["result"]
        assert result["project_name"] == "my-cool-project"

    @pytest.mark.asyncio
    async def test_get_state_includes_project_path(self, tmp_path: Path) -> None:
        """get_state response includes project_path matching str(project_root)."""
        project = tmp_path / "my-project"
        project.mkdir()
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=project,
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "method": "get_state", "id": 1}
        )
        assert response is not None
        result = response["result"]
        assert result["project_path"] == str(project)

    @pytest.mark.asyncio
    async def test_project_identity_static_not_from_state_data(self, tmp_path: Path) -> None:
        """project_name/path come from server init, not from state_data dict."""
        project = tmp_path / "test-proj"
        project.mkdir()
        server = SocketServer(
            socket_path=tmp_path / "test.sock",
            project_root=project,
        )
        # Update state_data WITHOUT project fields — should still appear
        server.update_runner_state(
            state=RunnerState.RUNNING,
            state_data={"current_epic": 1},
        )
        response = await server._route_message(
            {"jsonrpc": "2.0", "method": "get_state", "id": 1}
        )
        result = response["result"]
        assert result["project_name"] == "test-proj"
        assert result["project_path"] == str(project)
        assert result["state"] == "running"

    @pytest.mark.asyncio
    async def test_get_state_project_identity_over_real_socket(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_state returns project identity fields over real socket."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)

        project = tmp_path / "live-project"
        project.mkdir()
        sock_path = sock_dir / "test.sock"
        server = SocketServer(socket_path=sock_path, project_root=project)

        await server.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(sock_path))
            try:
                response = await send_rpc(reader, writer, "get_state", request_id=1)
                result = response["result"]
                assert result["project_name"] == "live-project"
                assert result["project_path"] == str(project)
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()


class TestSocketPathLengthIntegration:
    """Integration test: SocketServer.start() rejects oversized socket paths."""

    @pytest.mark.asyncio
    async def test_start_rejects_long_socket_path(self, tmp_path):
        """SocketServer.start() raises IPCError for socket path > 107 bytes."""
        from bmad_assist.ipc.protocol import IPCError

        # Build a socket path that exceeds 107 bytes when resolved
        long_dir = tmp_path / ("x" * 80)
        long_dir.mkdir(parents=True, exist_ok=True)
        long_sock = long_dir / ("y" * 30 + ".sock")
        resolved_len = len(str(long_sock.resolve()).encode("utf-8"))
        assert resolved_len > 107, f"Test setup error: path only {resolved_len} bytes"

        server = SocketServer(
            socket_path=long_sock,
            project_root=tmp_path,
        )

        with pytest.raises(IPCError, match="107-byte sun_path limit"):
            await server.start()
