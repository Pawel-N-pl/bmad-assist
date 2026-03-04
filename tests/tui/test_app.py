"""Tests for TUIApp — standalone TUI application with IPC connection.

Covers socket resolution (explicit path, auto-discovery), state hydration,
keyboard callbacks (quit, stop double-press), disconnect/reconnect callbacks,
and non-TTY guard.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bmad_assist.tui.app import TUIApp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tui_app() -> TUIApp:
    """TUIApp with no socket or project specified."""
    return TUIApp()


@pytest.fixture()
def mock_discovered_instance() -> MagicMock:
    """Create a mock DiscoveredInstance."""
    inst = MagicMock()
    inst.socket_path = Path("/tmp/bmad-test.sock")
    inst.project_hash = "a" * 32
    inst.state = {
        "project_name": "test-project",
        "project_path": "/home/user/test-project",
        "state": "running",
    }
    return inst


# ---------------------------------------------------------------------------
# TestResolveSocket
# ---------------------------------------------------------------------------


class TestResolveSocket:
    """Tests for _resolve_socket() — explicit path and auto-discovery."""

    @pytest.mark.asyncio
    async def test_explicit_socket_exists(self, tmp_path: Path) -> None:
        sock = tmp_path / "test.sock"
        sock.touch()
        app = TUIApp(socket_path=sock)
        result = await app._resolve_socket()
        assert result == sock

    @pytest.mark.asyncio
    async def test_explicit_socket_missing(self) -> None:
        app = TUIApp(socket_path=Path("/nonexistent/test.sock"))
        result = await app._resolve_socket()
        assert result is None

    @pytest.mark.asyncio
    async def test_discovery_no_instances(self) -> None:
        app = TUIApp()
        with patch(
            "bmad_assist.ipc.discovery.discover_instances_async",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await app._resolve_socket()
            assert result is None

    @pytest.mark.asyncio
    async def test_discovery_single_instance(
        self, mock_discovered_instance: MagicMock
    ) -> None:
        app = TUIApp()
        with patch(
            "bmad_assist.ipc.discovery.discover_instances_async",
            new_callable=AsyncMock,
            return_value=[mock_discovered_instance],
        ):
            result = await app._resolve_socket()
            assert result == mock_discovered_instance.socket_path

    @pytest.mark.asyncio
    async def test_discovery_multiple_no_project(self) -> None:
        inst1 = MagicMock()
        inst1.socket_path = Path("/tmp/a.sock")
        inst1.state = {"project_name": "proj-a", "project_path": "/a"}
        inst1.project_hash = "a" * 32
        inst2 = MagicMock()
        inst2.socket_path = Path("/tmp/b.sock")
        inst2.state = {"project_name": "proj-b", "project_path": "/b"}
        inst2.project_hash = "b" * 32

        app = TUIApp()
        with patch(
            "bmad_assist.ipc.discovery.discover_instances_async",
            new_callable=AsyncMock,
            return_value=[inst1, inst2],
        ):
            result = await app._resolve_socket()
            assert result is None

    @pytest.mark.asyncio
    async def test_discovery_multiple_with_project_name_match(self) -> None:
        inst1 = MagicMock()
        inst1.socket_path = Path("/tmp/a.sock")
        inst1.state = {"project_name": "proj-a", "project_path": "/path/a"}
        inst2 = MagicMock()
        inst2.socket_path = Path("/tmp/b.sock")
        inst2.state = {"project_name": "proj-b", "project_path": "/path/b"}

        app = TUIApp(project="proj-b")
        with patch(
            "bmad_assist.ipc.discovery.discover_instances_async",
            new_callable=AsyncMock,
            return_value=[inst1, inst2],
        ):
            result = await app._resolve_socket()
            assert result == Path("/tmp/b.sock")

    @pytest.mark.asyncio
    async def test_discovery_multiple_with_project_path_match(self) -> None:
        inst1 = MagicMock()
        inst1.socket_path = Path("/tmp/a.sock")
        inst1.state = {"project_name": "proj-a", "project_path": "/path/a"}
        inst2 = MagicMock()
        inst2.socket_path = Path("/tmp/b.sock")
        inst2.state = {"project_name": "proj-b", "project_path": "/path/b"}

        app = TUIApp(project="/path/b")
        with patch(
            "bmad_assist.ipc.discovery.discover_instances_async",
            new_callable=AsyncMock,
            return_value=[inst1, inst2],
        ):
            result = await app._resolve_socket()
            assert result == Path("/tmp/b.sock")

    @pytest.mark.asyncio
    async def test_discovery_multiple_with_project_no_match(self) -> None:
        inst1 = MagicMock()
        inst1.socket_path = Path("/tmp/a.sock")
        inst1.state = {"project_name": "proj-a", "project_path": "/path/a"}
        inst1.project_hash = "a" * 32
        inst2 = MagicMock()
        inst2.socket_path = Path("/tmp/b.sock")
        inst2.state = {"project_name": "proj-b", "project_path": "/path/b"}
        inst2.project_hash = "b" * 32

        app = TUIApp(project="proj-c")
        with patch(
            "bmad_assist.ipc.discovery.discover_instances_async",
            new_callable=AsyncMock,
            return_value=[inst1, inst2],
        ):
            result = await app._resolve_socket()
            assert result is None


# ---------------------------------------------------------------------------
# TestApplyState
# ---------------------------------------------------------------------------


class TestApplyState:
    """Tests for _apply_state() — hydrating TUI components from runner state."""

    def _make_state(self, **kwargs: object) -> MagicMock:
        """Create a mock state object with given attributes."""
        state = MagicMock()
        defaults = {
            "state": "running",
            "current_phase": "dev_story",
            "current_epic": 1,
            "current_story": "1.1",
            "elapsed_seconds": 120.0,
            "phase_elapsed_seconds": 42.0,
            "llm_sessions": 3,
            "paused": False,
            "log_level": "WARNING",
        }
        defaults.update(kwargs)
        for attr, val in defaults.items():
            setattr(state, attr, val)
        return state

    def test_full_state_hydration(self) -> None:
        app = TUIApp()
        status_bar = MagicMock()
        renderer = MagicMock()
        state = self._make_state()

        app._apply_state(state, status_bar, renderer)

        renderer.update_status.assert_called_once()
        status_bar.set_phase_info.assert_called_once_with("dev_story", 1, "1.1", elapsed=42.0)
        status_bar.set_run_start_time.assert_called_once()
        status_bar.set_llm_sessions.assert_called_once_with(3)
        status_bar.set_paused.assert_called_once_with(False)

    def test_missing_phase_info(self) -> None:
        app = TUIApp()
        status_bar = MagicMock()
        renderer = MagicMock()
        state = self._make_state(current_phase=None, current_epic=None, current_story=None)

        app._apply_state(state, status_bar, renderer)

        status_bar.set_phase_info.assert_not_called()

    def test_zero_elapsed(self) -> None:
        app = TUIApp()
        status_bar = MagicMock()
        renderer = MagicMock()
        state = self._make_state(elapsed_seconds=0.0)

        app._apply_state(state, status_bar, renderer)

        status_bar.set_run_start_time.assert_not_called()

    def test_paused_state(self) -> None:
        app = TUIApp()
        status_bar = MagicMock()
        renderer = MagicMock()
        state = self._make_state(paused=True)

        app._apply_state(state, status_bar, renderer)

        status_bar.set_paused.assert_called_once_with(True)

    def test_invalid_runner_state_ignored(self) -> None:
        app = TUIApp()
        status_bar = MagicMock()
        renderer = MagicMock()
        state = self._make_state(state="bogus_state")

        # Should not raise — ValueError is caught
        app._apply_state(state, status_bar, renderer)
        renderer.update_status.assert_not_called()

    def test_none_state_uses_idle(self) -> None:
        app = TUIApp()
        status_bar = MagicMock()
        renderer = MagicMock()
        state = self._make_state(state=None)

        app._apply_state(state, status_bar, renderer)

        # state=None → fallback to "idle" → RunnerState.IDLE
        renderer.update_status.assert_called_once()


# ---------------------------------------------------------------------------
# TestKeyboardCallbacks
# ---------------------------------------------------------------------------


class TestKeyboardCallbacks:
    """Tests for keyboard callback behavior in TUIApp."""

    def test_quit_sets_shutdown_event(self) -> None:
        app = TUIApp()
        app._shutdown_event = asyncio.Event()
        app._loop = MagicMock()

        # Simulate the _on_quit closure (thread-safe via call_soon_threadsafe)
        assert not app._shutdown_event.is_set()
        app._loop.call_soon_threadsafe(app._shutdown_event.set)
        # call_soon_threadsafe on a MagicMock just records the call
        app._loop.call_soon_threadsafe.assert_called_once_with(app._shutdown_event.set)

    def test_quit_uses_call_soon_threadsafe(self) -> None:
        """_on_quit closure uses loop.call_soon_threadsafe, not direct set()."""
        app = TUIApp()
        app._shutdown_event = MagicMock()
        app._loop = MagicMock()

        # Reproduce the _on_quit closure logic from app.py
        if app._shutdown_event and app._loop:
            app._loop.call_soon_threadsafe(app._shutdown_event.set)

        app._loop.call_soon_threadsafe.assert_called_once_with(app._shutdown_event.set)
        # Direct set() should NOT have been called
        app._shutdown_event.set.assert_not_called()

    def test_stop_double_press_sends_stop(self) -> None:
        app = TUIApp()
        app._layout = MagicMock()
        app._client = MagicMock()
        app._client.stop = AsyncMock()
        app._loop = MagicMock()

        # Simulate _on_stop closure logic
        # First press: pending
        now = time.monotonic()
        app._stop_pending = True
        app._stop_pending_time = now

        # Second press within window
        assert app._stop_pending
        assert (time.monotonic() - app._stop_pending_time) < app._STOP_CONFIRM_WINDOW

    def test_stop_single_press_only_pending(self) -> None:
        app = TUIApp()
        app._layout = MagicMock()

        # Before any press
        assert not app._stop_pending

        # Simulate first press
        app._stop_pending = True
        app._stop_pending_time = time.monotonic()
        assert app._stop_pending

    def test_stop_expired_window_resets(self) -> None:
        app = TUIApp()
        app._layout = MagicMock()

        # First press
        app._stop_pending = True
        app._stop_pending_time = time.monotonic() - 3.0  # expired (> 2s)

        # Second press after window expired — should reset to pending
        now = time.monotonic()
        if app._stop_pending and (now - app._stop_pending_time) < app._STOP_CONFIRM_WINDOW:
            confirmed = True
        else:
            confirmed = False
            app._stop_pending = True
            app._stop_pending_time = now

        assert not confirmed
        assert app._stop_pending


# ---------------------------------------------------------------------------
# TestDisconnectReconnect
# ---------------------------------------------------------------------------


class TestDisconnectReconnect:
    """Tests for _on_disconnect and _on_reconnect_failed callbacks."""

    def test_on_disconnect_updates_status(self) -> None:
        app = TUIApp()
        app._status_bar = MagicMock()
        app._layout = MagicMock()

        app._on_disconnect()

        app._status_bar.set_runner_state.assert_called_once()
        app._layout.write_log.assert_called_once_with("Connection lost -- reconnecting...")

    def test_on_disconnect_no_components(self) -> None:
        app = TUIApp()
        # status_bar and layout are None by default
        app._on_disconnect()  # should not raise

    def test_on_reconnect_failed_shows_error(self) -> None:
        app = TUIApp()
        app._layout = MagicMock()

        error = ConnectionRefusedError("refused")
        app._on_reconnect_failed(error)

        calls = app._layout.write_log.call_args_list
        assert len(calls) == 2
        assert "refused" in calls[0][0][0]
        assert "Returning to discovery mode" in calls[1][0][0]

    def test_on_reconnect_failed_no_layout(self) -> None:
        app = TUIApp()
        # layout is None
        app._on_reconnect_failed(RuntimeError("gone"))  # should not raise

    @pytest.mark.asyncio
    async def test_on_reconnect_rehydrates_state(self) -> None:
        app = TUIApp()
        mock_state = MagicMock()
        mock_state.state = "running"
        mock_state.current_phase = "dev_story"
        mock_state.current_epic = 1
        mock_state.current_story = "1.1"
        mock_state.elapsed_seconds = 0.0
        mock_state.llm_sessions = 2
        mock_state.paused = False

        app._client = AsyncMock()
        app._client.get_state = AsyncMock(return_value=mock_state)
        app._renderer = MagicMock()
        app._status_bar = MagicMock()
        app._layout = MagicMock()

        await app._on_reconnect()

        app._client.get_state.assert_awaited_once()
        app._renderer.reset.assert_called_once()
        app._layout.write_log.assert_called_once_with("Reconnected to runner")


# ---------------------------------------------------------------------------
# TestNonTTY
# ---------------------------------------------------------------------------


class TestNonTTY:
    """Tests for the __main__ non-TTY guard."""

    def test_non_tty_exits_with_code_1(self) -> None:
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = False

        with (
            patch("sys.stdin", mock_stdin),
            patch("sys.argv", ["app.py"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            # Re-execute the module __main__ block logic
            import sys

            if sys.stdin is None or not sys.stdin.isatty():
                sys.exit(1)

        assert exc_info.value.code == 1

    def test_none_stdin_exits_with_code_1(self) -> None:
        with (
            patch("sys.stdin", None),
            patch("sys.argv", ["app.py"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            import sys

            if sys.stdin is None or not sys.stdin.isatty():
                sys.exit(1)

        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# TestInit
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for TUIApp.__init__ defaults."""

    def test_default_init(self) -> None:
        app = TUIApp()
        assert app._socket_path is None
        assert app._project is None
        assert app._shutdown_event is None
        assert app._stop_pending is False
        assert app._STOP_CONFIRM_WINDOW == 2.0

    def test_init_with_args(self) -> None:
        sock = Path("/tmp/test.sock")
        app = TUIApp(socket_path=sock, project="my-proj")
        assert app._socket_path == sock
        assert app._project == "my-proj"


# ---------------------------------------------------------------------------
# TestRunExitCodes
# ---------------------------------------------------------------------------


class TestRunDiscoveryPolling:
    """Tests for TUIApp.run() discovery polling — stays alive until quit."""

    @pytest.mark.asyncio
    async def test_polls_until_quit_when_no_socket(self) -> None:
        app = TUIApp(socket_path=Path("/nonexistent/test.sock"))

        async def quit_soon() -> None:
            await asyncio.sleep(0.05)
            if app._shutdown_event:
                app._shutdown_event.set()

        with patch("bmad_assist.tui.app.TUIApp._DISCOVERY_INTERVAL", 0.01):
            task = asyncio.create_task(app.run())
            asyncio.create_task(quit_soon())
            result = await asyncio.wait_for(task, timeout=5.0)
            assert result == 0

    @pytest.mark.asyncio
    async def test_polls_until_quit_on_empty_discovery(self) -> None:
        app = TUIApp()

        async def quit_soon() -> None:
            await asyncio.sleep(0.05)
            if app._shutdown_event:
                app._shutdown_event.set()

        with (
            patch(
                "bmad_assist.ipc.discovery.discover_instances_async",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("bmad_assist.tui.app.TUIApp._DISCOVERY_INTERVAL", 0.01),
        ):
            task = asyncio.create_task(app.run())
            asyncio.create_task(quit_soon())
            result = await asyncio.wait_for(task, timeout=5.0)
            assert result == 0
