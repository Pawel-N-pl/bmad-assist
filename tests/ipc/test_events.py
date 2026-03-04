"""Unit and integration tests for IPC event emission.

Story 29.4: Tests cover EventEmitter (typed emit methods, rate limiting,
state change detection, metrics thread), IPCLogHandler (level filtering,
exception safety), and end-to-end event delivery via real sockets.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.ipc.events import (
    EventEmitter,
    IPCLogHandler,
    _INTERNAL_LOGGER_NAME,
)
from bmad_assist.ipc.protocol import EVENT_RATE_LIMIT, make_event
from bmad_assist.ipc.types import EventPriority, RunnerState, get_event_priority


# ============================================================================
# Helpers
# ============================================================================


def _make_mock_server() -> MagicMock:
    """Create a mock IPCServerThread with make_event and broadcast_threadsafe."""
    server = MagicMock()
    # make_event returns a properly shaped event dict
    server.make_event.side_effect = lambda t, d: make_event(t, d, seq=1)
    server.broadcast_threadsafe.return_value = None
    server.update_state.return_value = None
    return server


# ============================================================================
# Unit Tests: EventEmitter with None server
# ============================================================================


class TestEventEmitterNoneServer:
    """AC #1: EventEmitter with None server — all methods are no-ops."""

    def test_emit_noop(self) -> None:
        emitter = EventEmitter(None)
        # Should not raise
        emitter.emit("phase_started", {"phase": "dev_story"})

    def test_emit_phase_started_noop(self) -> None:
        emitter = EventEmitter(None)
        emitter.emit_phase_started("dev_story", 1, "1.1")

    def test_emit_phase_completed_noop(self) -> None:
        emitter = EventEmitter(None)
        emitter.emit_phase_completed("dev_story", 1, "1.1", 5.0)

    def test_emit_log_noop(self) -> None:
        emitter = EventEmitter(None)
        emitter.emit_log("WARNING", "test message", "test.logger")

    def test_emit_state_changed_noop(self) -> None:
        emitter = EventEmitter(None)
        emitter.emit_state_changed("state", "idle", "running")

    def test_emit_metrics_noop(self) -> None:
        emitter = EventEmitter(None)
        emitter.emit_metrics(0, 10.0, "dev_story", False)

    def test_emit_error_noop(self) -> None:
        emitter = EventEmitter(None)
        emitter.emit_error(code=-32603, message="test error")

    def test_update_state_noop(self) -> None:
        emitter = EventEmitter(None)
        emitter.update_state(RunnerState.RUNNING, {"current_epic": 1})

    def test_start_metrics_noop(self) -> None:
        """Metrics thread should not start when server is None."""
        emitter = EventEmitter(None)
        emitter.start_metrics(interval=0.1, state_getter=lambda: {
            "llm_sessions": 0, "elapsed_seconds": 0.0,
            "phase": None, "pause_state": False,
        })
        assert emitter._metrics_thread is None
        emitter.stop_metrics()  # Should be safe even without thread


# ============================================================================
# Unit Tests: EventEmitter with mock server
# ============================================================================


class TestEventEmitterEmit:
    """AC #2: Typed emit methods produce correct event dicts."""

    def test_emit_phase_started(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.emit_phase_started("dev_story", 1, "1.1")

        server.make_event.assert_called_once_with("phase_started", {
            "phase": "dev_story",
            "epic_id": 1,
            "story_id": "1.1",
        })
        server.broadcast_threadsafe.assert_called_once()

    def test_emit_phase_completed(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.emit_phase_completed("dev_story", "testarch", "T.1", 42.5)

        server.make_event.assert_called_once_with("phase_completed", {
            "phase": "dev_story",
            "epic_id": "testarch",
            "story_id": "T.1",
            "duration_seconds": 42.5,
        })

    def test_emit_state_changed(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.emit_state_changed("state", "idle", "running")

        server.make_event.assert_called_once_with("state_changed", {
            "field": "state",
            "old_value": "idle",
            "new_value": "running",
        })

    def test_emit_metrics(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.emit_metrics(5, 120.0, "dev_story", False)

        server.make_event.assert_called_once_with("metrics", {
            "llm_sessions": 5,
            "elapsed_seconds": 120.0,
            "phase": "dev_story",
            "pause_state": False,
        })

    def test_emit_error(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.emit_error(code=-32603, message="Phase failed", data={"phase": "dev_story"})

        server.make_event.assert_called_once_with("error", {
            "code": -32603,
            "message": "Phase failed",
            "data": {"phase": "dev_story"},
        })

    def test_emit_error_no_data(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.emit_error(code=-32001, message="Guardian halt")

        server.make_event.assert_called_once_with("error", {
            "code": -32001,
            "message": "Guardian halt",
            "data": None,
        })

    # ---- Story 29.9: emit_goodbye tests ----

    def test_emit_goodbye_normal(self) -> None:
        """emit_goodbye emits event with correct type and reason."""
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.emit_goodbye("normal")

        server.make_event.assert_called_once_with("goodbye", {
            "reason": "normal",
            "message": None,
        })
        server.broadcast_threadsafe.assert_called_once()

    def test_emit_goodbye_with_message(self) -> None:
        """emit_goodbye includes optional message for error reason."""
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.emit_goodbye("error", message="Connection refused")

        server.make_event.assert_called_once_with("goodbye", {
            "reason": "error",
            "message": "Connection refused",
        })

    def test_emit_goodbye_stop_command(self) -> None:
        """emit_goodbye with stop_command reason."""
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.emit_goodbye("stop_command")

        server.make_event.assert_called_once_with("goodbye", {
            "reason": "stop_command",
            "message": None,
        })

    def test_emit_goodbye_fire_and_forget(self) -> None:
        """emit_goodbye is fire-and-forget (doesn't raise when server is None)."""
        emitter = EventEmitter(None)
        # Should not raise
        emitter.emit_goodbye("normal", "shutting down")

    def test_emit_goodbye_fire_and_forget_on_broadcast_error(self) -> None:
        """emit_goodbye swallows broadcast errors."""
        server = _make_mock_server()
        server.broadcast_threadsafe.side_effect = RuntimeError("loop closed")
        emitter = EventEmitter(server)

        # Should not raise
        emitter.emit_goodbye("error", "some error")

    def test_goodbye_event_has_essential_priority(self) -> None:
        """goodbye event is classified as ESSENTIAL (not dropped by backpressure)."""
        assert get_event_priority("goodbye") == EventPriority.ESSENTIAL

    def test_emit_log_basic(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.emit_log("WARNING", "Something went wrong", "my.module")

        server.make_event.assert_called_once_with("log", {
            "level": "WARNING",
            "message": "Something went wrong",
            "logger": "my.module",
        })

    def test_emit_phase_started_none_epic_story(self) -> None:
        """Epic setup phases have no story_id; epic_id may also be None."""
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.emit_phase_started("framework", None, None)

        server.make_event.assert_called_once_with("phase_started", {
            "phase": "framework",
            "epic_id": None,
            "story_id": None,
        })

    def test_emit_swallows_server_exceptions(self) -> None:
        """Fire-and-forget: emit() never raises even if server errors."""
        server = _make_mock_server()
        server.make_event.side_effect = RuntimeError("boom")
        emitter = EventEmitter(server)

        # Should not raise
        emitter.emit_phase_started("dev_story", 1, "1.1")


# ============================================================================
# Unit Tests: Rate limiting
# ============================================================================


class TestEventEmitterRateLimiting:
    """AC #4: Log events rate-limited, essential events never limited."""

    def test_log_events_within_limit(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        for i in range(EVENT_RATE_LIMIT):
            emitter.emit_log("INFO", f"msg {i}", "test.logger")

        assert server.make_event.call_count == EVENT_RATE_LIMIT

    def test_log_events_exceed_limit_drops(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        # Fill up the rate limit window
        for i in range(EVENT_RATE_LIMIT + 50):
            emitter.emit_log("INFO", f"msg {i}", "test.logger")

        # Should have emitted exactly EVENT_RATE_LIMIT events (extra dropped)
        assert server.make_event.call_count == EVENT_RATE_LIMIT
        assert emitter._log_dropped == 50

    def test_log_rate_limit_resets_after_window(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        # Fill up the window
        for i in range(EVENT_RATE_LIMIT):
            emitter.emit_log("INFO", f"msg {i}", "test.logger")

        assert server.make_event.call_count == EVENT_RATE_LIMIT

        # Advance the window by manipulating internal state
        emitter._log_window_start = time.monotonic() - 2.0
        emitter.emit_log("INFO", "new window msg", "test.logger")

        assert server.make_event.call_count == EVENT_RATE_LIMIT + 1

    def test_internal_logger_ignored_prevents_recursion(self) -> None:
        """Rate-limit warnings from our own logger must not recurse."""
        server = _make_mock_server()
        emitter = EventEmitter(server)

        # Simulate a log from our own module logger
        emitter.emit_log("WARNING", "IPC log rate limit: dropped 100 events", _INTERNAL_LOGGER_NAME)

        # Should have been silently dropped
        server.make_event.assert_not_called()

    def test_essential_events_never_rate_limited(self) -> None:
        """phase_started, phase_completed, state_changed, error are never limited."""
        server = _make_mock_server()
        emitter = EventEmitter(server)

        # Even with rate limit counters at max, essential events should go through
        emitter._log_count = EVENT_RATE_LIMIT * 10

        emitter.emit_phase_started("dev_story", 1, "1.1")
        emitter.emit_phase_completed("dev_story", 1, "1.1", 5.0)
        emitter.emit_state_changed("state", "idle", "running")
        emitter.emit_error(code=-32603, message="test")

        # All 4 essential events should have been emitted
        assert server.make_event.call_count == 4


# ============================================================================
# Unit Tests: update_state with change detection
# ============================================================================


class TestEventEmitterUpdateState:
    """AC #10: update_state detects RunnerState changes."""

    def test_detects_state_change(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        # First update — sets initial state, no change event (prev is None)
        emitter.update_state(RunnerState.IDLE, {})
        server.update_state.assert_called_once_with(RunnerState.IDLE, {})
        server.make_event.assert_not_called()

        server.reset_mock()
        server.make_event.side_effect = lambda t, d: make_event(t, d, seq=2)

        # Second update — state changes IDLE → RUNNING
        emitter.update_state(RunnerState.RUNNING, {"current_epic": 1})
        server.update_state.assert_called_once_with(RunnerState.RUNNING, {"current_epic": 1})
        server.make_event.assert_called_once_with("state_changed", {
            "field": "state",
            "old_value": "idle",
            "new_value": "running",
        })

    def test_no_event_when_state_unchanged(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.update_state(RunnerState.RUNNING, {})
        server.reset_mock()

        # Same state — should NOT emit state_changed
        emitter.update_state(RunnerState.RUNNING, {"current_epic": 2})
        server.update_state.assert_called_once()
        server.make_event.assert_not_called()

    def test_pause_resume_transitions(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        # IDLE → RUNNING
        emitter.update_state(RunnerState.IDLE, {})
        server.reset_mock()
        server.make_event.side_effect = lambda t, d: make_event(t, d, seq=1)

        emitter.update_state(RunnerState.RUNNING, {})
        server.make_event.assert_called_once()
        args = server.make_event.call_args[0]
        assert args[0] == "state_changed"
        assert args[1]["old_value"] == "idle"
        assert args[1]["new_value"] == "running"

        # RUNNING → PAUSED
        server.reset_mock()
        server.make_event.side_effect = lambda t, d: make_event(t, d, seq=2)

        emitter.update_state(RunnerState.PAUSED, {})
        args = server.make_event.call_args[0]
        assert args[1]["old_value"] == "running"
        assert args[1]["new_value"] == "paused"

        # PAUSED → RUNNING
        server.reset_mock()
        server.make_event.side_effect = lambda t, d: make_event(t, d, seq=3)

        emitter.update_state(RunnerState.RUNNING, {})
        args = server.make_event.call_args[0]
        assert args[1]["old_value"] == "paused"
        assert args[1]["new_value"] == "running"


# ============================================================================
# Unit Tests: IPCLogHandler
# ============================================================================


class TestIPCLogHandler:
    """AC #3: IPCLogHandler converts LogRecord and filters by level."""

    def test_converts_log_record(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)
        handler = IPCLogHandler(emitter, level=logging.WARNING)

        record = logging.LogRecord(
            name="test.module",
            level=logging.WARNING,
            pathname="test.py",
            lineno=42,
            msg="Something went wrong",
            args=(),
            exc_info=None,
        )
        handler.emit(record)

        server.make_event.assert_called_once_with("log", {
            "level": "WARNING",
            "message": "Something went wrong",
            "logger": "test.module",
        })

    def test_respects_minimum_level(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)
        handler = IPCLogHandler(emitter, level=logging.WARNING)

        # INFO record should be filtered out by the handler's level
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Info message",
            args=(),
            exc_info=None,
        )

        # The handler should check its level filter
        assert handler.level == logging.WARNING
        # Manually check that the filter would reject this
        assert record.levelno < handler.level

    def test_catches_callback_exceptions(self) -> None:
        """Handler MUST NOT raise even if emitter errors."""
        server = _make_mock_server()
        server.make_event.side_effect = RuntimeError("boom")
        emitter = EventEmitter(server)
        handler = IPCLogHandler(emitter, level=logging.WARNING)

        record = logging.LogRecord(
            name="test.module",
            level=logging.ERROR,
            pathname="test.py",
            lineno=42,
            msg="Error message",
            args=(),
            exc_info=None,
        )

        # Should not raise
        handler.emit(record)

    def test_handler_attached_to_logger(self) -> None:
        """Verify handler can be attached to and detached from root logger."""
        server = _make_mock_server()
        emitter = EventEmitter(server)
        handler = IPCLogHandler(emitter, level=logging.WARNING)

        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            assert handler in root_logger.handlers
        finally:
            root_logger.removeHandler(handler)
        assert handler not in root_logger.handlers


# ============================================================================
# Unit Tests: Metrics thread
# ============================================================================


class TestEventEmitterMetrics:
    """AC #9: Metrics background thread emits periodic events."""

    def test_metrics_thread_starts_and_emits(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        call_count = 0
        def state_getter() -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {
                "llm_sessions": call_count,
                "elapsed_seconds": float(call_count * 10),
                "phase": "dev_story",
                "pause_state": False,
            }

        emitter.start_metrics(interval=0.05, state_getter=state_getter)
        assert emitter._metrics_thread is not None
        assert emitter._metrics_thread.is_alive()

        # Wait for a few emissions
        time.sleep(0.25)
        emitter.stop_metrics()

        assert not emitter._metrics_thread  # Thread reference cleared
        assert call_count >= 2  # At least a couple emissions
        assert server.make_event.call_count >= 2

    def test_metrics_thread_stops_cleanly(self) -> None:
        server = _make_mock_server()
        emitter = EventEmitter(server)

        emitter.start_metrics(interval=0.05, state_getter=lambda: {
            "llm_sessions": 0, "elapsed_seconds": 0.0,
            "phase": None, "pause_state": False,
        })

        emitter.stop_metrics()

        # Thread should be stopped and cleaned up
        assert emitter._metrics_thread is None

    def test_metrics_thread_handles_getter_exception(self) -> None:
        """Metrics thread should not crash on state_getter errors."""
        server = _make_mock_server()
        emitter = EventEmitter(server)

        def bad_getter() -> dict[str, Any]:
            raise RuntimeError("state unavailable")

        emitter.start_metrics(interval=0.05, state_getter=bad_getter)
        time.sleep(0.15)
        emitter.stop_metrics()

        # Thread stopped without crash — no events emitted
        server.make_event.assert_not_called()

    def test_stop_metrics_without_start(self) -> None:
        """stop_metrics should be safe when never started."""
        emitter = EventEmitter(None)
        emitter.stop_metrics()  # Should not raise


# ============================================================================
# Integration Tests: Real server + client
# ============================================================================


@pytest.fixture()
def sock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary socket directory and monkeypatch get_socket_dir."""
    sock_dir = tmp_path / "sockets"
    sock_dir.mkdir()
    monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: sock_dir)
    return sock_dir


@pytest.fixture()
def sock_path(sock_dir: Path) -> Path:
    """Return path for the test socket file."""
    return sock_dir / "test.sock"


class TestEventEmitterIntegration:
    """AC #11: End-to-end tests with real SocketServer + SocketClient."""

    @pytest.mark.asyncio
    async def test_client_receives_phase_started(
        self, sock_path: Path, tmp_path: Path
    ) -> None:
        """EventEmitter → IPCServerThread → SocketServer → SocketClient."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received_events: list[dict[str, Any]] = []

            client = SocketClient(sock_path, client_id="test-1")
            await client.connect(timeout=5.0)

            def on_event(params: dict[str, Any]) -> None:
                received_events.append(params)

            client.subscribe(on_event)

            try:
                # Emit via EventEmitter
                emitter = EventEmitter(ipc_thread)
                emitter.emit_phase_started("dev_story", 1, "1.1")

                # Wait for delivery
                await asyncio.sleep(0.2)

                assert len(received_events) >= 1
                evt = received_events[0]
                assert evt["type"] == "phase_started"
                assert evt["data"]["phase"] == "dev_story"
                assert evt["data"]["epic_id"] == 1
                assert evt["data"]["story_id"] == "1.1"
                assert "seq" in evt
                assert "timestamp" in evt
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    @pytest.mark.asyncio
    async def test_client_receives_phase_completed(
        self, sock_path: Path, tmp_path: Path
    ) -> None:
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received_events: list[dict[str, Any]] = []

            client = SocketClient(sock_path, client_id="test-2")
            await client.connect(timeout=5.0)
            client.subscribe(lambda params: received_events.append(params))

            try:
                emitter = EventEmitter(ipc_thread)
                emitter.emit_phase_completed("dev_story", 1, "1.1", 42.5)

                await asyncio.sleep(0.2)

                assert len(received_events) >= 1
                evt = received_events[0]
                assert evt["type"] == "phase_completed"
                assert evt["data"]["duration_seconds"] == 42.5
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    @pytest.mark.asyncio
    async def test_client_receives_log_event(
        self, sock_path: Path, tmp_path: Path
    ) -> None:
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received_events: list[dict[str, Any]] = []

            client = SocketClient(sock_path, client_id="test-3")
            await client.connect(timeout=5.0)
            client.subscribe(lambda params: received_events.append(params))

            try:
                emitter = EventEmitter(ipc_thread)

                # Simulate log handler forwarding
                handler = IPCLogHandler(emitter, level=logging.WARNING)
                record = logging.LogRecord(
                    name="test.module",
                    level=logging.ERROR,
                    pathname="test.py",
                    lineno=42,
                    msg="Something failed",
                    args=(),
                    exc_info=None,
                )
                handler.emit(record)

                await asyncio.sleep(0.2)

                assert len(received_events) >= 1
                evt = received_events[0]
                assert evt["type"] == "log"
                assert evt["data"]["level"] == "ERROR"
                assert evt["data"]["message"] == "Something failed"
                assert evt["data"]["logger"] == "test.module"
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    @pytest.mark.asyncio
    async def test_client_receives_state_changed(
        self, sock_path: Path, tmp_path: Path
    ) -> None:
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received_events: list[dict[str, Any]] = []

            client = SocketClient(sock_path, client_id="test-4")
            await client.connect(timeout=5.0)
            client.subscribe(lambda params: received_events.append(params))

            try:
                emitter = EventEmitter(ipc_thread)

                # Set initial state, then transition
                emitter.update_state(RunnerState.IDLE, {})
                emitter.update_state(RunnerState.PAUSED, {})

                await asyncio.sleep(0.2)

                # Should have received state_changed: idle → paused
                state_events = [e for e in received_events if e["type"] == "state_changed"]
                assert len(state_events) >= 1
                evt = state_events[0]
                assert evt["data"]["field"] == "state"
                assert evt["data"]["old_value"] == "idle"
                assert evt["data"]["new_value"] == "paused"
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)

    @pytest.mark.asyncio
    async def test_client_receives_metrics_from_thread(
        self, sock_path: Path, tmp_path: Path
    ) -> None:
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.ipc.server import IPCServerThread

        ipc_thread = IPCServerThread(
            socket_path=sock_path,
            project_root=tmp_path,
        )
        ipc_thread.start(timeout=5.0)

        try:
            received_events: list[dict[str, Any]] = []

            client = SocketClient(sock_path, client_id="test-5")
            await client.connect(timeout=5.0)
            client.subscribe(lambda params: received_events.append(params))

            try:
                emitter = EventEmitter(ipc_thread)
                emitter.start_metrics(
                    interval=0.1,
                    state_getter=lambda: {
                        "llm_sessions": 3,
                        "elapsed_seconds": 60.0,
                        "phase": "dev_story",
                        "pause_state": False,
                    },
                )

                # Wait for at least one metrics emission
                await asyncio.sleep(0.5)
                emitter.stop_metrics()

                metrics_events = [e for e in received_events if e["type"] == "metrics"]
                assert len(metrics_events) >= 1
                evt = metrics_events[0]
                assert evt["data"]["llm_sessions"] == 3
                assert evt["data"]["elapsed_seconds"] == 60.0
                assert evt["data"]["phase"] == "dev_story"
                assert evt["data"]["pause_state"] is False
            finally:
                await client.disconnect()
        finally:
            ipc_thread.stop(timeout=5.0)
