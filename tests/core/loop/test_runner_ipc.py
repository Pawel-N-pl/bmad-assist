"""IPC end-to-end integration tests for the runner loop.

Story 29.12: Verifies the complete IPC lifecycle within the run_loop()
context — server startup/shutdown, event delivery, command execution,
goodbye events, graceful degradation, and multi-client broadcast.

These tests exercise the actual integration path that Epic 30 (TUI)
and Epic 31 (Multi-Instance Dashboard) depend on.

Note: conftest.py autouse fixtures (reset_shutdown_state, auto_continue_prompts)
apply automatically to all tests in this directory.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


# =============================================================================
# Shared fixtures (Task 1)
# =============================================================================


@pytest.fixture()
def sock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create and monkeypatch socket directory for IPC tests."""
    d = tmp_path / "sockets"
    d.mkdir(mode=0o700)
    monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: d)
    monkeypatch.setattr("bmad_assist.ipc.discovery.SOCKET_DIR", d)
    monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", d)
    return d


@pytest.fixture()
def sock_path(sock_dir: Path) -> Path:
    """Return path for the test socket file."""
    return sock_dir / "test.sock"


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Create a project root with .bmad-assist/ directory."""
    root = tmp_path / "project"
    root.mkdir()
    (root / ".bmad-assist").mkdir()
    return root


@pytest.fixture()
def mock_cancel_ctx() -> MagicMock:
    """Create a mock CancellationContext with is_cancelled=False."""
    ctx = MagicMock()
    ctx.is_cancelled = False
    return ctx


def _wait_for_events(
    events: list[dict[str, Any]],
    event_type: str,
    timeout: float = 2.0,
    min_count: int = 1,
) -> list[dict[str, Any]]:
    """Synchronously poll an event list for events of a given type."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matched = [e for e in events if e.get("type") == event_type]
        if len(matched) >= min_count:
            return matched
        time.sleep(0.05)
    return [e for e in events if e.get("type") == event_type]


# =============================================================================
# Task 2: Server lifecycle tests (AC #1, #8, #12)
# =============================================================================


class TestServerLifecycle:
    """Tests for _start_ipc_server() lifecycle and graceful degradation."""

    def test_start_ipc_server_creates_functional_server(
        self,
        project_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC #1: _start_ipc_server() creates server that responds to ping."""
        import tempfile

        from bmad_assist.core.loop.runner import _start_ipc_server

        # Use a short temp dir to stay under 107-byte sun_path limit.
        # tmp_path from pytest can be too long for Unix domain sockets.
        with tempfile.TemporaryDirectory(prefix="ipc") as short_tmp:
            sock_dir = Path(short_tmp) / "s"
            sock_dir.mkdir(mode=0o700)
            # Patch get_socket_dir in BOTH server and protocol modules — _start_ipc_server
            # imports get_socket_path from protocol which calls get_socket_dir internally.
            monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)
            monkeypatch.setattr("bmad_assist.ipc.protocol.get_socket_dir", lambda: sock_dir)
            monkeypatch.setattr("bmad_assist.ipc.cleanup.SOCKET_DIR", sock_dir)

            ipc_thread = _start_ipc_server(project_root)
            assert ipc_thread is not None

            try:
                # Find the actual socket file (hash-based name from get_socket_path)
                sock_files = list(sock_dir.glob("*.sock"))
                assert len(sock_files) == 1

                # Verify client can connect and ping
                async def _verify() -> None:
                    from bmad_assist.ipc.client import SocketClient

                    client = SocketClient(sock_files[0], auto_reconnect=False)
                    await client.connect(timeout=5.0)
                    try:
                        result = await client.ping()
                        assert result.pong is True
                    finally:
                        await client.disconnect()

                asyncio.run(_verify())
            finally:
                ipc_thread.stop(timeout=5.0)

    def test_start_ipc_server_returns_none_on_path_too_long(
        self,
        project_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """AC #8: _start_ipc_server() returns None when socket path exceeds limit."""
        from bmad_assist.core.loop.runner import _start_ipc_server

        # Create a socket dir with a very deep path that causes the resulting
        # socket path (dir + 32-char hash + ".sock") to exceed 107 bytes.
        too_long = tmp_path / ("a" * 80) / "sockets"
        monkeypatch.setattr(
            "bmad_assist.ipc.server.get_socket_dir", lambda: too_long
        )
        monkeypatch.setattr(
            "bmad_assist.ipc.protocol.get_socket_dir", lambda: too_long
        )

        result = _start_ipc_server(project_root)
        assert result is None  # Graceful degradation, no crash

    def test_start_ipc_server_calls_clear_active_socket_on_failure(
        self,
        project_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """AC #8: clear_active_socket() is called when _start_ipc_server() fails."""
        from bmad_assist.core.loop.runner import _start_ipc_server

        too_long = tmp_path / ("a" * 80) / "sockets"
        monkeypatch.setattr(
            "bmad_assist.ipc.server.get_socket_dir", lambda: too_long
        )
        monkeypatch.setattr(
            "bmad_assist.ipc.protocol.get_socket_dir", lambda: too_long
        )

        clear_called: list[bool] = []
        original_clear = None

        def track_clear() -> None:
            clear_called.append(True)
            if original_clear is not None:
                original_clear()

        from bmad_assist.ipc import cleanup

        original_clear = cleanup.clear_active_socket
        monkeypatch.setattr("bmad_assist.ipc.cleanup.clear_active_socket", track_clear)

        result = _start_ipc_server(project_root)
        assert result is None
        assert len(clear_called) >= 1

    def test_server_cleanup_after_exception(
        self,
        sock_path: Path,
        project_root: Path,
    ) -> None:
        """AC #12: Socket and lock files are removed after crash."""
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
        )
        ipc_thread.start(timeout=5.0)

        # Verify socket file exists
        assert sock_path.exists()
        lock_path = Path(f"{sock_path}.lock")
        assert lock_path.exists()

        # Stop the server (simulates the finally block cleanup in run_loop)
        ipc_thread.stop(timeout=5.0)

        # Verify both files are cleaned up
        assert not sock_path.exists()
        assert not lock_path.exists()


# =============================================================================
# Task 3: Event delivery tests (AC #2, #7, #9, #11)
# =============================================================================


class TestEventDelivery:
    """Tests for event delivery to connected clients."""

    async def test_client_receives_phase_events(
        self, sock_path: Path, project_root: Path
    ) -> None:
        """AC #2: Connected client receives phase_started and phase_completed events."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.events import EventEmitter
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received: list[dict[str, Any]] = []

            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect(timeout=5.0)
            client.subscribe(lambda params: received.append(params))

            try:
                emitter = EventEmitter(ipc_thread)
                emitter.emit_phase_started("dev_story", 29, "29.12")
                emitter.emit_phase_completed("dev_story", 29, "29.12", 42.5)

                await asyncio.sleep(0.3)

                started = [e for e in received if e["type"] == "phase_started"]
                completed = [e for e in received if e["type"] == "phase_completed"]
                assert len(started) >= 1
                assert started[0]["data"]["phase"] == "dev_story"
                assert started[0]["data"]["epic_id"] == 29
                assert started[0]["data"]["story_id"] == "29.12"
                assert len(completed) >= 1
                assert completed[0]["data"]["duration_seconds"] == 42.5
                assert completed[0]["data"]["epic_id"] == 29
                assert completed[0]["data"]["story_id"] == "29.12"
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    async def test_log_event_forwarded_via_ipc_log_handler(
        self, sock_path: Path, project_root: Path
    ) -> None:
        """AC #7: Log events forwarded via IPCLogHandler to connected client."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.events import EventEmitter, IPCLogHandler
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received: list[dict[str, Any]] = []

            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect(timeout=5.0)
            client.subscribe(lambda params: received.append(params))

            try:
                emitter = EventEmitter(ipc_thread)
                handler = IPCLogHandler(emitter, level=logging.WARNING)
                test_logger = logging.getLogger("test.ipc.log_handler")
                test_logger.addHandler(handler)

                try:
                    test_logger.warning("Test warning message for IPC")

                    await asyncio.sleep(0.3)

                    log_events = [e for e in received if e["type"] == "log"]
                    assert len(log_events) >= 1
                    assert log_events[0]["data"]["level"] == "WARNING"
                    assert "Test warning message for IPC" in log_events[0]["data"]["message"]
                    assert log_events[0]["data"]["logger"] == "test.ipc.log_handler"
                finally:
                    test_logger.removeHandler(handler)
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    async def test_multiple_clients_receive_broadcast(
        self, sock_path: Path, project_root: Path
    ) -> None:
        """AC #9: Two simultaneous clients both receive broadcast event."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.events import EventEmitter
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received_1: list[dict[str, Any]] = []
            received_2: list[dict[str, Any]] = []

            client_1 = SocketClient(sock_path, auto_reconnect=False, client_id="c1")
            client_2 = SocketClient(sock_path, auto_reconnect=False, client_id="c2")

            await client_1.connect(timeout=5.0)
            await client_2.connect(timeout=5.0)

            client_1.subscribe(lambda params: received_1.append(params))
            client_2.subscribe(lambda params: received_2.append(params))

            try:
                emitter = EventEmitter(ipc_thread)
                emitter.emit_phase_started("code_review", 29, "29.12")

                await asyncio.sleep(0.3)

                # Both clients must receive the event
                events_1 = [e for e in received_1 if e["type"] == "phase_started"]
                events_2 = [e for e in received_2 if e["type"] == "phase_started"]
                assert len(events_1) >= 1, f"Client 1 received: {received_1}"
                assert len(events_2) >= 1, f"Client 2 received: {received_2}"
                assert events_1[0]["data"]["phase"] == "code_review"
                assert events_2[0]["data"]["phase"] == "code_review"
            finally:
                await client_1.disconnect()
                await client_2.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    async def test_metrics_event_delivery(
        self, sock_path: Path, project_root: Path
    ) -> None:
        """AC #11: Metrics event received within metrics interval."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.events import EventEmitter
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received: list[dict[str, Any]] = []

            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect(timeout=5.0)
            client.subscribe(lambda params: received.append(params))

            try:
                emitter = EventEmitter(ipc_thread)

                def state_getter() -> dict[str, Any]:
                    return {
                        "llm_sessions": 5,
                        "elapsed_seconds": 120.0,
                        "phase": "dev_story",
                        "pause_state": False,
                    }

                emitter.start_metrics(interval=0.3, state_getter=state_getter)

                try:
                    # Wait for at least one metrics event
                    await asyncio.sleep(0.8)

                    metrics = [e for e in received if e["type"] == "metrics"]
                    assert len(metrics) >= 1, f"Expected metrics event, got: {received}"
                    assert "elapsed_seconds" in metrics[0]["data"]
                    assert "phase" in metrics[0]["data"]
                    assert metrics[0]["data"]["elapsed_seconds"] == 120.0
                    assert metrics[0]["data"]["phase"] == "dev_story"
                finally:
                    emitter.stop_metrics()
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)


# =============================================================================
# Task 4: Goodbye event tests (AC #3, #4, #5)
# =============================================================================


class TestGoodbyeEvents:
    """Tests for goodbye event delivery on various exit conditions."""

    async def test_goodbye_normal_exit(
        self, sock_path: Path, project_root: Path
    ) -> None:
        """AC #3: Goodbye event with reason='normal' on clean exit."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.events import EventEmitter
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received: list[dict[str, Any]] = []

            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect(timeout=5.0)
            client.subscribe(lambda params: received.append(params))

            try:
                emitter = EventEmitter(ipc_thread)
                emitter.emit_goodbye("normal", None)

                await asyncio.sleep(0.3)

                goodbyes = [e for e in received if e["type"] == "goodbye"]
                assert len(goodbyes) >= 1
                assert goodbyes[0]["data"]["reason"] == "normal"
                assert goodbyes[0]["type"] == "goodbye"
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    async def test_goodbye_stop_command(
        self, sock_path: Path, project_root: Path
    ) -> None:
        """AC #4: Goodbye event with reason='stop_command' when stop sent via IPC."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.events import EventEmitter
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received: list[dict[str, Any]] = []

            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect(timeout=5.0)
            client.subscribe(lambda params: received.append(params))

            try:
                emitter = EventEmitter(ipc_thread)
                emitter.emit_goodbye("stop_command", None)

                await asyncio.sleep(0.3)

                goodbyes = [e for e in received if e["type"] == "goodbye"]
                assert len(goodbyes) >= 1
                assert goodbyes[0]["data"]["reason"] == "stop_command"
                assert goodbyes[0]["type"] == "goodbye"
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    async def test_goodbye_error(
        self, sock_path: Path, project_root: Path
    ) -> None:
        """AC #5: Goodbye event with reason='error' and non-empty message."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.events import EventEmitter
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received: list[dict[str, Any]] = []

            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect(timeout=5.0)
            client.subscribe(lambda params: received.append(params))

            try:
                emitter = EventEmitter(ipc_thread)
                emitter.emit_goodbye("error", "Something went wrong")

                await asyncio.sleep(0.3)

                goodbyes = [e for e in received if e["type"] == "goodbye"]
                assert len(goodbyes) >= 1
                assert goodbyes[0]["data"]["reason"] == "error"
                assert goodbyes[0]["data"]["message"] == "Something went wrong"
                assert goodbyes[0]["type"] == "goodbye"
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    async def test_goodbye_suppresses_subsequent_events(
        self, sock_path: Path, project_root: Path
    ) -> None:
        """After goodbye is sent, subsequent events are suppressed."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.events import EventEmitter
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received: list[dict[str, Any]] = []

            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect(timeout=5.0)
            client.subscribe(lambda params: received.append(params))

            try:
                emitter = EventEmitter(ipc_thread)
                emitter.emit_goodbye("normal", None)

                # Try to emit another event after goodbye
                emitter.emit_phase_started("dev_story", 29, "29.12")

                await asyncio.sleep(0.3)

                goodbyes = [e for e in received if e["type"] == "goodbye"]
                phase_events = [e for e in received if e["type"] == "phase_started"]
                assert len(goodbyes) >= 1
                assert len(phase_events) == 0, "Events after goodbye should be suppressed"
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)


# =============================================================================
# Task 5: Command integration tests (AC #6, #10)
# =============================================================================


class TestCommandIntegration:
    """Tests for IPC command execution affecting runner behavior."""

    async def test_pause_creates_flag_file(
        self,
        sock_path: Path,
        project_root: Path,
        mock_cancel_ctx: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC #6: Pause command creates pause.flag and runner state becomes paused."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.commands import CommandHandlerImpl
        from bmad_assist.ipc.server import IPCServerThread
        from bmad_assist.ipc.types import RunnerState

        handler = CommandHandlerImpl(
            project_root=project_root,
            cancel_ctx=mock_cancel_ctx,
        )
        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
            handler=handler,
        )
        ipc_thread.start(timeout=5.0)

        try:
            assert ipc_thread._server is not None
            handler.set_server(ipc_thread._server)

            # Set runner state to RUNNING so pause is valid
            ipc_thread._server.update_runner_state(state=RunnerState.RUNNING)

            # Mock validate_state_for_pause — config isn't loaded in test context
            # The lazy import resolves from bmad_assist.core.loop.pause
            monkeypatch.setattr(
                "bmad_assist.core.loop.pause.validate_state_for_pause",
                lambda _path: True,
            )
            # Mock _get_state_path which calls get_config() (not loaded in tests)
            monkeypatch.setattr(
                handler,
                "_get_state_path",
                lambda: project_root / ".bmad-assist" / "state.yaml",
            )

            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect(timeout=5.0)

            try:
                result = await client.pause()
                assert result.status == "paused"

                # Verify pause.flag was created
                pause_flag = project_root / ".bmad-assist" / "pause.flag"
                assert pause_flag.exists(), "pause.flag should be created"
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    async def test_resume_removes_flag_file(
        self, sock_path: Path, project_root: Path, mock_cancel_ctx: MagicMock
    ) -> None:
        """AC #6: Resume command removes pause.flag and state returns to running."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.commands import CommandHandlerImpl
        from bmad_assist.ipc.server import IPCServerThread
        from bmad_assist.ipc.types import RunnerState

        handler = CommandHandlerImpl(
            project_root=project_root,
            cancel_ctx=mock_cancel_ctx,
        )
        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
            handler=handler,
        )
        ipc_thread.start(timeout=5.0)

        try:
            assert ipc_thread._server is not None
            handler.set_server(ipc_thread._server)

            # Set to PAUSED state
            ipc_thread._server.update_runner_state(state=RunnerState.PAUSED)

            # Create pause.flag
            pause_flag = project_root / ".bmad-assist" / "pause.flag"
            pause_flag.touch()
            assert pause_flag.exists()

            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect(timeout=5.0)

            try:
                result = await client.resume()
                assert result.status == "running"

                # Verify pause.flag was removed
                assert not pause_flag.exists(), "pause.flag should be removed after resume"
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    async def test_get_state_returns_runner_state(
        self, sock_path: Path, project_root: Path
    ) -> None:
        """AC #10: get_state returns correct runner state fields."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.server import IPCServerThread
        from bmad_assist.ipc.types import RunnerState

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
        )
        ipc_thread.start(timeout=5.0)

        try:
            assert ipc_thread._server is not None
            ipc_thread._server.update_runner_state(
                state=RunnerState.RUNNING,
                state_data={
                    "current_epic": 29,
                    "current_story": "29.12",
                    "current_phase": "dev_story",
                },
            )

            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect(timeout=5.0)

            try:
                state = await client.get_state()
                assert state.state == "running"
                assert state.running is True
                assert state.paused is False
                assert state.project_name == project_root.resolve().name
                assert state.project_path == str(project_root.resolve())
                assert state.current_epic == 29
                assert state.current_story == "29.12"
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    async def test_get_state_shows_paused(
        self, sock_path: Path, project_root: Path
    ) -> None:
        """AC #10: get_state correctly reflects paused state."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.server import IPCServerThread
        from bmad_assist.ipc.types import RunnerState

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=project_root,
        )
        ipc_thread.start(timeout=5.0)

        try:
            assert ipc_thread._server is not None
            ipc_thread._server.update_runner_state(state=RunnerState.PAUSED)

            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect(timeout=5.0)

            try:
                state = await client.get_state()
                assert state.state == "paused"
                assert state.running is False
                assert state.paused is True
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)
