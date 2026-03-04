"""Tests for InputHandler — non-blocking keyboard input.

All tests mock terminal operations (termios, tty, select, sys.stdin).
No actual terminal manipulation occurs during testing.
"""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock, call, patch

import pytest

from bmad_assist.tui.input import InputHandler, _LONG_PRESS_THRESHOLD, _REPEAT_WINDOW


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_stdin() -> MagicMock:
    """Mock stdin with fileno, isatty, read."""
    mock = MagicMock()
    mock.fileno.return_value = 0
    mock.isatty.return_value = True
    mock.read.return_value = ""
    return mock


def _make_handler(mock_stdin: MagicMock) -> InputHandler:
    """Create an InputHandler wired to mock stdin."""
    handler = InputHandler()
    handler._stdin = mock_stdin
    return handler


# ---------------------------------------------------------------------------
# Task 1: Basic class structure and register()
# ---------------------------------------------------------------------------


class TestInputHandlerInit:
    """Test InputHandler.__init__ initialises all required fields."""

    def test_callbacks_dict_empty(self) -> None:
        handler = InputHandler()
        assert handler._callbacks == {}

    def test_long_press_callbacks_empty(self) -> None:
        handler = InputHandler()
        assert handler._long_press_callbacks == {}

    def test_running_initially_false(self) -> None:
        handler = InputHandler()
        assert handler._running is False

    def test_old_settings_initially_none(self) -> None:
        handler = InputHandler()
        assert handler._old_settings is None

    def test_restored_initially_false(self) -> None:
        handler = InputHandler()
        assert handler._restored is False

    def test_thread_initially_none(self) -> None:
        handler = InputHandler()
        assert handler._thread is None

    def test_stdin_captured_at_init(self) -> None:
        """_stdin is captured from sys.stdin at __init__ time."""
        handler = InputHandler()
        import sys

        assert handler._stdin is sys.stdin

    def test_atexit_registered_initially_false(self) -> None:
        handler = InputHandler()
        assert handler._atexit_registered is False

    def test_long_press_tracking_fields(self) -> None:
        handler = InputHandler()
        assert handler._last_key is None
        assert handler._last_key_time == 0.0
        assert handler._repeat_count == 0
        assert handler._long_press_fired is False
        assert handler._last_key_was_repeat is False


class TestRegister:
    """Test register() key→callback mapping."""

    def test_register_stores_callback(self) -> None:
        handler = InputHandler()
        cb = MagicMock()
        handler.register("p", cb)
        assert handler._callbacks["p"] is cb

    def test_register_overwrites_previous(self) -> None:
        handler = InputHandler()
        cb1 = MagicMock()
        cb2 = MagicMock()
        handler.register("p", cb1)
        handler.register("p", cb2)
        assert handler._callbacks["p"] is cb2

    def test_register_case_sensitive(self) -> None:
        handler = InputHandler()
        cb_lower = MagicMock()
        cb_upper = MagicMock()
        handler.register("p", cb_lower)
        handler.register("P", cb_upper)
        assert handler._callbacks["p"] is cb_lower
        assert handler._callbacks["P"] is cb_upper

    def test_register_multiple_keys(self) -> None:
        handler = InputHandler()
        cbs = {k: MagicMock() for k in "pscrl"}
        for k, cb in cbs.items():
            handler.register(k, cb)
        for k, cb in cbs.items():
            assert handler._callbacks[k] is cb


class TestRegisterLongPress:
    """Test register_long_press() stores long-press callbacks."""

    def test_register_long_press_stores_callback(self) -> None:
        handler = InputHandler()
        cb = MagicMock()
        handler.register_long_press("p", cb)
        assert handler._long_press_callbacks["p"] is cb

    def test_register_long_press_overwrites(self) -> None:
        handler = InputHandler()
        cb1 = MagicMock()
        cb2 = MagicMock()
        handler.register_long_press("p", cb1)
        handler.register_long_press("p", cb2)
        assert handler._long_press_callbacks["p"] is cb2


# ---------------------------------------------------------------------------
# Task 2: start() with cbreak mode
# ---------------------------------------------------------------------------


class TestStart:
    """Test start() enters cbreak mode and launches input thread."""

    def test_start_enters_cbreak(self, mock_stdin: MagicMock) -> None:
        """start() calls tty.setcbreak() (NOT setraw)."""
        handler = _make_handler(mock_stdin)

        mock_termios = MagicMock()
        mock_termios.tcgetattr.return_value = [1, 2, 3]
        mock_tty = MagicMock()

        with (
            patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}),
            patch("bmad_assist.tui.input.atexit"),
            patch("threading.Thread") as mock_thread_cls,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            handler.start()

            mock_termios.tcgetattr.assert_called_once_with(0)
            mock_tty.setcbreak.assert_called_once_with(0)
            assert handler._running is True
            assert handler._old_settings == [1, 2, 3]

    def test_start_launches_daemon_thread(self, mock_stdin: MagicMock) -> None:
        """start() creates and starts a daemon thread named 'tui-input'."""
        handler = _make_handler(mock_stdin)

        mock_termios = MagicMock()
        mock_termios.tcgetattr.return_value = [1, 2, 3]
        mock_tty = MagicMock()

        with (
            patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}),
            patch("bmad_assist.tui.input.atexit"),
            patch("threading.Thread") as mock_thread_cls,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            handler.start()

            mock_thread_cls.assert_called_once_with(
                target=handler._input_loop,
                name="tui-input",
                daemon=True,
            )
            mock_thread.start.assert_called_once()

    def test_start_registers_atexit(self, mock_stdin: MagicMock) -> None:
        """start() registers atexit handler for terminal restoration."""
        handler = _make_handler(mock_stdin)

        mock_termios = MagicMock()
        mock_termios.tcgetattr.return_value = [1, 2, 3]
        mock_tty = MagicMock()

        with (
            patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}),
            patch("bmad_assist.tui.input.atexit") as mock_atexit,
            patch("threading.Thread") as mock_thread_cls,
        ):
            mock_thread_cls.return_value = MagicMock()
            handler.start()

            mock_atexit.register.assert_called_once_with(handler._restore_terminal)
            assert handler._atexit_registered is True

    def test_start_noop_when_not_tty(self, mock_stdin: MagicMock) -> None:
        """start() is no-op when stdin is not a TTY."""
        mock_stdin.isatty.return_value = False
        handler = _make_handler(mock_stdin)

        handler.start()

        assert handler._running is False
        assert handler._thread is None

    def test_start_noop_when_stdin_is_none(self) -> None:
        """start() is no-op when sys.stdin is None (GUI environments)."""
        handler = InputHandler()
        handler._stdin = None  # type: ignore[assignment]

        handler.start()

        assert handler._running is False
        assert handler._thread is None

    def test_start_idempotent(self, mock_stdin: MagicMock) -> None:
        """Calling start() twice does not re-enter cbreak or start second thread."""
        handler = _make_handler(mock_stdin)

        mock_termios = MagicMock()
        mock_termios.tcgetattr.return_value = [1, 2, 3]
        mock_tty = MagicMock()

        with (
            patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}),
            patch("bmad_assist.tui.input.atexit"),
            patch("threading.Thread") as mock_thread_cls,
        ):
            mock_thread_cls.return_value = MagicMock()

            handler.start()
            mock_termios.tcgetattr.reset_mock()
            mock_tty.setcbreak.reset_mock()
            mock_thread_cls.reset_mock()

            handler.start()  # Second call

            mock_termios.tcgetattr.assert_not_called()
            mock_tty.setcbreak.assert_not_called()
            mock_thread_cls.assert_not_called()

    def test_start_noop_when_termios_import_fails(self, mock_stdin: MagicMock) -> None:
        """start() is no-op when termios is not available (Windows)."""
        handler = _make_handler(mock_stdin)

        # Simulate ImportError for termios
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name in ("termios", "tty"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_fake_import):
            handler.start()

        assert handler._running is False
        assert handler._thread is None

    def test_start_handles_tcgetattr_failure(self, mock_stdin: MagicMock) -> None:
        """start() returns gracefully if tcgetattr fails."""
        handler = _make_handler(mock_stdin)

        mock_termios = MagicMock()
        mock_termios.error = OSError
        mock_termios.tcgetattr.side_effect = OSError("not a terminal")
        mock_tty = MagicMock()

        with (
            patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}),
        ):
            handler.start()

        assert handler._running is False
        assert handler._old_settings is None

    def test_start_handles_setcbreak_failure(self, mock_stdin: MagicMock) -> None:
        """start() returns gracefully if setcbreak fails, no settings saved."""
        handler = _make_handler(mock_stdin)

        mock_termios = MagicMock()
        mock_termios.error = OSError
        mock_termios.tcgetattr.return_value = [1, 2, 3]
        mock_tty = MagicMock()
        mock_tty.setcbreak.side_effect = OSError("cbreak failed")

        with (
            patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}),
        ):
            handler.start()

        assert handler._running is False
        assert handler._old_settings is None  # Cleared on cbreak failure


# ---------------------------------------------------------------------------
# Task 3: _input_loop()
# ---------------------------------------------------------------------------


class TestInputLoop:
    """Test _input_loop() polls stdin and dispatches keys."""

    @staticmethod
    def _make_select_mock(handler: InputHandler, mock_stdin: MagicMock, readable_count: int = 1) -> MagicMock:
        """Create a mock select module that returns readable for N calls then stops."""
        mock_select_mod = MagicMock()
        call_count = 0

        def _fake_select(rlist: list[object], *_: object) -> tuple[list[object], list[object], list[object]]:
            nonlocal call_count
            call_count += 1
            if call_count <= readable_count:
                return (rlist, [], [])
            handler._running = False
            return ([], [], [])

        mock_select_mod.select = _fake_select
        return mock_select_mod

    def test_calls_registered_callback(self, mock_stdin: MagicMock) -> None:
        """_input_loop dispatches to registered callback via _process_key."""
        handler = _make_handler(mock_stdin)
        cb = MagicMock()
        handler.register("p", cb)
        handler._running = True
        mock_stdin.read.return_value = "p"

        mock_select_mod = self._make_select_mock(handler, mock_stdin, readable_count=1)

        with patch.dict("sys.modules", {"select": mock_select_mod}):
            handler._input_loop()

        cb.assert_called_once()

    def test_unregistered_keys_silently_ignored(self, mock_stdin: MagicMock) -> None:
        """Unregistered keys are ignored without error or log."""
        handler = _make_handler(mock_stdin)
        handler._running = True
        mock_stdin.read.return_value = "x"  # Unregistered key

        mock_select_mod = self._make_select_mock(handler, mock_stdin, readable_count=1)

        with patch.dict("sys.modules", {"select": mock_select_mod}):
            handler._input_loop()  # Should not raise

    def test_eof_exits_cleanly(self, mock_stdin: MagicMock) -> None:
        """When stdin.read returns empty string (EOF), thread exits."""
        handler = _make_handler(mock_stdin)
        handler._running = True
        mock_stdin.read.return_value = ""  # EOF

        mock_select_mod = MagicMock()
        mock_select_mod.select.return_value = ([mock_stdin], [], [])

        with patch.dict("sys.modules", {"select": mock_select_mod}):
            handler._input_loop()

        assert handler._running is False

    def test_callback_exception_does_not_crash_thread(
        self, mock_stdin: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Callback that raises does not crash the input loop."""
        handler = _make_handler(mock_stdin)

        def _bad_callback() -> None:
            raise ValueError("callback broke")

        handler.register("p", _bad_callback)
        handler._running = True
        mock_stdin.read.return_value = "p"

        mock_select_mod = self._make_select_mock(handler, mock_stdin, readable_count=1)

        with (
            patch.dict("sys.modules", {"select": mock_select_mod}),
            caplog.at_level(logging.WARNING, logger="bmad_assist.tui.input"),
        ):
            handler._input_loop()  # Should not raise

        assert "Callback exception" in caplog.text

    def test_select_exception_during_shutdown_breaks(self, mock_stdin: MagicMock) -> None:
        """Exception during shutdown (not _running) breaks loop cleanly."""
        handler = _make_handler(mock_stdin)
        handler._running = True  # Start running so loop enters

        call_count = 0

        def _fail_then_shutdown(*_: object) -> tuple[list[object], list[object], list[object]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                handler._running = False  # Simulate shutdown
                raise OSError("fd closed")
            return ([], [], [])

        mock_select_mod = MagicMock()
        mock_select_mod.select.side_effect = _fail_then_shutdown

        with patch.dict("sys.modules", {"select": mock_select_mod}):
            handler._input_loop()  # Should exit cleanly

        assert handler._running is False
        assert call_count == 1  # Broke out after exception during shutdown

    def test_loop_exits_when_running_false(self, mock_stdin: MagicMock) -> None:
        """Loop exits immediately when _running is False."""
        handler = _make_handler(mock_stdin)
        handler._running = False

        mock_select_mod = MagicMock()
        mock_select_mod.select.return_value = ([], [], [])

        with patch.dict("sys.modules", {"select": mock_select_mod}):
            handler._input_loop()

        # select should never have been called since _running was False
        mock_select_mod.select.assert_not_called()

    def test_loop_continues_after_transient_exception(
        self, mock_stdin: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Transient select() exception while _running=True logs and continues."""
        handler = _make_handler(mock_stdin)
        handler._running = True
        call_count = 0

        def _fail_then_stop(*_: object) -> tuple[list[object], list[object], list[object]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("EINTR")  # Transient error
            # Second call: stop the loop
            handler._running = False
            return ([], [], [])

        mock_select_mod = MagicMock()
        mock_select_mod.select.side_effect = _fail_then_stop

        with (
            patch.dict("sys.modules", {"select": mock_select_mod}),
            caplog.at_level(logging.WARNING, logger="bmad_assist.tui.input"),
        ):
            handler._input_loop()

        assert "Input loop error" in caplog.text
        assert call_count == 2  # Loop continued after exception


# ---------------------------------------------------------------------------
# Task 4: Long-press detection
# ---------------------------------------------------------------------------


class TestProcessKey:
    """Test _process_key() dispatch logic including long-press."""

    def test_normal_callback_on_new_key(self) -> None:
        """First press of a key triggers normal callback."""
        handler = InputHandler()
        cb = MagicMock()
        handler.register("p", cb)

        with patch("bmad_assist.tui.input.time") as mock_time:
            mock_time.monotonic.return_value = 1.0
            handler._process_key("p")

        cb.assert_called_once()

    def test_no_callback_for_unregistered_key(self) -> None:
        """Unregistered key does not trigger any callback."""
        handler = InputHandler()
        cb = MagicMock()
        handler.register("p", cb)

        with patch("bmad_assist.tui.input.time") as mock_time:
            mock_time.monotonic.return_value = 1.0
            handler._process_key("x")

        cb.assert_not_called()

    def test_long_press_fires_at_threshold(self) -> None:
        """Long-press callback fires after _LONG_PRESS_THRESHOLD rapid repeats."""
        handler = InputHandler()
        normal_cb = MagicMock()
        lp_cb = MagicMock()
        handler.register("p", normal_cb)
        handler.register_long_press("p", lp_cb)

        with patch("bmad_assist.tui.input.time") as mock_time:
            # 1st press — normal fires
            mock_time.monotonic.return_value = 0.0
            handler._process_key("p")
            assert normal_cb.call_count == 1

            # 2nd-4th presses — within repeat window, accumulating
            for i in range(1, _LONG_PRESS_THRESHOLD - 1):
                mock_time.monotonic.return_value = 0.1 * i
                handler._process_key("p")

            lp_cb.assert_not_called()

            # 5th press — long-press fires
            mock_time.monotonic.return_value = 0.1 * (_LONG_PRESS_THRESHOLD - 1)
            handler._process_key("p")

        lp_cb.assert_called_once()

    def test_long_press_fires_only_once(self) -> None:
        """Long-press callback fires exactly once per hold sequence."""
        handler = InputHandler()
        lp_cb = MagicMock()
        handler.register("p", MagicMock())
        handler.register_long_press("p", lp_cb)

        with patch("bmad_assist.tui.input.time") as mock_time:
            # Press key many times rapidly
            for i in range(10):
                mock_time.monotonic.return_value = 0.05 * i
                handler._process_key("p")

        lp_cb.assert_called_once()

    def test_no_normal_callback_during_accumulation(self) -> None:
        """Normal callback does NOT fire for repeat counts 2-4."""
        handler = InputHandler()
        cb = MagicMock()
        handler.register("p", cb)

        with patch("bmad_assist.tui.input.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            handler._process_key("p")
            assert cb.call_count == 1  # First press fires

            # 2nd-4th — within window, accumulating — no more normal fires
            for i in range(1, 4):
                mock_time.monotonic.return_value = 0.05 * i
                handler._process_key("p")

        assert cb.call_count == 1  # Still only 1 call

    def test_same_key_after_window_fires_normal_callback(self) -> None:
        """Same key pressed after window expires DOES fire normal callback.

        This ensures toggle controls (e.g., pause/resume with same key) work.
        The OS keyboard repeat initial delay (~500ms) may cause an extra
        callback fire, but this is acceptable to preserve toggleability.
        """
        handler = InputHandler()
        cb = MagicMock()
        handler.register("p", cb)

        with patch("bmad_assist.tui.input.time") as mock_time:
            # 1st press at t=0 — normal fires
            mock_time.monotonic.return_value = 0.0
            handler._process_key("p")
            assert cb.call_count == 1

            # Same key at t=0.6 (>150ms window) — fires again (new press)
            mock_time.monotonic.return_value = 0.6
            handler._process_key("p")
            assert cb.call_count == 2  # Both presses fire

    def test_different_key_fires_normal_callback(self) -> None:
        """Pressing a different key triggers its normal callback."""
        handler = InputHandler()
        cb_p = MagicMock()
        cb_s = MagicMock()
        handler.register("p", cb_p)
        handler.register("s", cb_s)

        with patch("bmad_assist.tui.input.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            handler._process_key("p")
            mock_time.monotonic.return_value = 0.5
            handler._process_key("s")

        cb_p.assert_called_once()
        cb_s.assert_called_once()

    def test_different_key_resets_long_press_tracking(self) -> None:
        """Pressing a different key resets repeat count and long-press state."""
        handler = InputHandler()
        lp_cb = MagicMock()
        handler.register("p", MagicMock())
        handler.register("s", MagicMock())
        handler.register_long_press("p", lp_cb)

        with patch("bmad_assist.tui.input.time") as mock_time:
            # 3 rapid presses of 'p'
            for i in range(3):
                mock_time.monotonic.return_value = 0.05 * i
                handler._process_key("p")

            # Switch to 's' — resets repeat count
            mock_time.monotonic.return_value = 0.15
            handler._process_key("s")

            # Back to 'p' — starts fresh
            for i in range(3):
                mock_time.monotonic.return_value = 0.2 + 0.05 * i
                handler._process_key("p")

        lp_cb.assert_not_called()  # Never reached threshold in either sequence

    def test_long_press_rearms_after_different_key(self) -> None:
        """Long-press can fire again after switching to a different key and back."""
        handler = InputHandler()
        lp_cb = MagicMock()
        handler.register("p", MagicMock())
        handler.register("s", MagicMock())
        handler.register_long_press("p", lp_cb)

        with patch("bmad_assist.tui.input.time") as mock_time:
            # First hold sequence — reaches threshold, fires once
            for i in range(_LONG_PRESS_THRESHOLD):
                mock_time.monotonic.return_value = _REPEAT_WINDOW * 0.5 * i
                handler._process_key("p")
            assert lp_cb.call_count == 1

            # Press different key — should reset _long_press_fired
            mock_time.monotonic.return_value = 2.0
            handler._process_key("s")
            assert handler._long_press_fired is False

            # Second hold sequence — should fire again
            base = 3.0
            for i in range(_LONG_PRESS_THRESHOLD):
                mock_time.monotonic.return_value = base + _REPEAT_WINDOW * 0.5 * i
                handler._process_key("p")
            assert lp_cb.call_count == 2  # Fired again after rearm

    def test_long_press_without_callback_does_not_crash(self) -> None:
        """Reaching long-press threshold without registered callback is safe."""
        handler = InputHandler()
        handler.register("p", MagicMock())
        # No long-press callback registered

        with patch("bmad_assist.tui.input.time") as mock_time:
            for i in range(_LONG_PRESS_THRESHOLD + 2):
                mock_time.monotonic.return_value = 0.05 * i
                handler._process_key("p")  # Should not raise

    def test_callback_exception_in_process_key_caught(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Exception in normal callback is caught and logged."""
        handler = InputHandler()

        def _bad() -> None:
            raise RuntimeError("boom")

        handler.register("p", _bad)

        with (
            patch("bmad_assist.tui.input.time") as mock_time,
            caplog.at_level(logging.WARNING, logger="bmad_assist.tui.input"),
        ):
            mock_time.monotonic.return_value = 0.0
            handler._process_key("p")  # Should not raise

        assert "Callback exception" in caplog.text

    def test_long_press_callback_exception_caught(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Exception in long-press callback is caught and logged."""
        handler = InputHandler()
        handler.register("p", MagicMock())

        def _bad_lp() -> None:
            raise RuntimeError("lp boom")

        handler.register_long_press("p", _bad_lp)

        with (
            patch("bmad_assist.tui.input.time") as mock_time,
            caplog.at_level(logging.WARNING, logger="bmad_assist.tui.input"),
        ):
            for i in range(_LONG_PRESS_THRESHOLD):
                mock_time.monotonic.return_value = 0.05 * i
                handler._process_key("p")

        assert "Long-press callback exception" in caplog.text
        # long_press_fired should still be set even though callback raised
        assert handler._long_press_fired is True


# ---------------------------------------------------------------------------
# Task 5: stop() and terminal restoration
# ---------------------------------------------------------------------------


class TestStop:
    """Test stop() restores terminal and stops input thread."""

    def test_stop_sets_running_false(self, mock_stdin: MagicMock) -> None:
        handler = _make_handler(mock_stdin)
        handler._running = True
        handler._old_settings = [1, 2, 3]

        mock_termios = MagicMock()
        with patch.dict("sys.modules", {"termios": mock_termios}):
            handler.stop()

        assert handler._running is False

    def test_stop_joins_thread(self, mock_stdin: MagicMock) -> None:
        """stop() joins the input thread with 200ms timeout."""
        handler = _make_handler(mock_stdin)
        handler._running = True
        handler._old_settings = [1, 2, 3]
        handler._thread = MagicMock()

        mock_termios = MagicMock()
        with patch.dict("sys.modules", {"termios": mock_termios}):
            handler.stop()

        handler._thread.join.assert_called_once_with(timeout=0.2)

    def test_stop_restores_terminal_with_tcsaflush(self, mock_stdin: MagicMock) -> None:
        """stop() restores terminal using TCSAFLUSH."""
        handler = _make_handler(mock_stdin)
        handler._running = True
        old_settings = [1, 2, 3]
        handler._old_settings = old_settings

        mock_termios = MagicMock()
        mock_termios.TCSAFLUSH = 2  # Standard value

        with patch.dict("sys.modules", {"termios": mock_termios}):
            handler.stop()

        mock_termios.tcsetattr.assert_called_once_with(0, 2, old_settings)

    def test_stop_idempotent(self, mock_stdin: MagicMock) -> None:
        """Calling stop() twice does not crash."""
        handler = _make_handler(mock_stdin)
        handler._running = True
        handler._old_settings = [1, 2, 3]

        mock_termios = MagicMock()
        mock_termios.TCSAFLUSH = 2

        with patch.dict("sys.modules", {"termios": mock_termios}):
            handler.stop()  # First call
            mock_termios.tcsetattr.reset_mock()
            handler.stop()  # Second call — should be no-op

        mock_termios.tcsetattr.assert_not_called()

    def test_stop_never_raises_on_termios_error(self, mock_stdin: MagicMock) -> None:
        """stop() never raises even if termios.tcsetattr fails."""
        handler = _make_handler(mock_stdin)
        handler._running = True
        handler._old_settings = [1, 2, 3]

        mock_termios = MagicMock()
        mock_termios.TCSAFLUSH = 2
        mock_termios.tcsetattr.side_effect = OSError("terminal gone")

        with patch.dict("sys.modules", {"termios": mock_termios}):
            handler.stop()  # Should not raise

    def test_stop_unregisters_atexit(self, mock_stdin: MagicMock) -> None:
        """stop() unregisters atexit handler."""
        handler = _make_handler(mock_stdin)
        handler._running = True
        handler._old_settings = [1, 2, 3]
        handler._atexit_registered = True

        mock_termios = MagicMock()
        mock_termios.TCSAFLUSH = 2

        with (
            patch.dict("sys.modules", {"termios": mock_termios}),
            patch("bmad_assist.tui.input.atexit") as mock_atexit,
        ):
            handler.stop()

        mock_atexit.unregister.assert_called_once_with(handler._restore_terminal)
        assert handler._atexit_registered is False

    def test_stop_noop_when_never_started(self) -> None:
        """stop() is safe when handler was never started."""
        handler = InputHandler()
        handler.stop()  # Should not raise


class TestRestoreTerminal:
    """Test _restore_terminal() idempotency and error handling."""

    def test_restore_is_idempotent(self, mock_stdin: MagicMock) -> None:
        """Calling _restore_terminal() twice only restores once."""
        handler = _make_handler(mock_stdin)
        handler._old_settings = [1, 2, 3]

        mock_termios = MagicMock()
        mock_termios.TCSAFLUSH = 2

        with patch.dict("sys.modules", {"termios": mock_termios}):
            handler._restore_terminal()
            mock_termios.tcsetattr.reset_mock()
            handler._restore_terminal()

        mock_termios.tcsetattr.assert_not_called()

    def test_restore_noop_when_no_settings(self) -> None:
        """_restore_terminal() is no-op when _old_settings is None."""
        handler = InputHandler()
        handler._restore_terminal()  # Should not raise
        assert handler._restored is False  # No settings to restore

    def test_restore_handles_exception(self, mock_stdin: MagicMock) -> None:
        """_restore_terminal() swallows exceptions but does NOT mark as restored."""
        handler = _make_handler(mock_stdin)
        handler._old_settings = [1, 2, 3]

        mock_termios = MagicMock()
        mock_termios.TCSAFLUSH = 2
        mock_termios.tcsetattr.side_effect = OSError("nope")

        with patch.dict("sys.modules", {"termios": mock_termios}):
            handler._restore_terminal()  # Should not raise

        assert handler._restored is False  # NOT marked as restored on failure
        assert handler._old_settings is None  # Settings cleared regardless

    def test_restore_clears_old_settings(self, mock_stdin: MagicMock) -> None:
        """_restore_terminal() sets _old_settings to None after restore."""
        handler = _make_handler(mock_stdin)
        handler._old_settings = [1, 2, 3]

        mock_termios = MagicMock()
        mock_termios.TCSAFLUSH = 2

        with patch.dict("sys.modules", {"termios": mock_termios}):
            handler._restore_terminal()

        assert handler._old_settings is None


# ---------------------------------------------------------------------------
# Task 7: Additional integration-style tests
# ---------------------------------------------------------------------------


class TestStartStopIntegration:
    """Integration tests for start/stop lifecycle."""

    def test_start_then_stop_full_cycle(self, mock_stdin: MagicMock) -> None:
        """Full start→stop cycle without actual terminal or threads."""
        handler = _make_handler(mock_stdin)

        mock_termios = MagicMock()
        mock_termios.tcgetattr.return_value = [1, 2, 3]
        mock_termios.TCSAFLUSH = 2
        mock_tty = MagicMock()

        with (
            patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}),
            patch("bmad_assist.tui.input.atexit"),
            patch("threading.Thread") as mock_thread_cls,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            handler.start()
            assert handler._running is True
            assert handler._atexit_registered is True

            handler.stop()
            assert handler._running is False
            assert handler._restored is True
            mock_termios.tcsetattr.assert_called_once()

    def test_register_before_and_after_start(self, mock_stdin: MagicMock) -> None:
        """register() works both before and after start()."""
        handler = _make_handler(mock_stdin)
        cb_before = MagicMock()
        cb_after = MagicMock()

        handler.register("p", cb_before)

        mock_termios = MagicMock()
        mock_termios.tcgetattr.return_value = [1, 2, 3]
        mock_tty = MagicMock()

        with (
            patch.dict("sys.modules", {"termios": mock_termios, "tty": mock_tty}),
            patch("bmad_assist.tui.input.atexit"),
            patch("threading.Thread") as mock_thread_cls,
        ):
            mock_thread_cls.return_value = MagicMock()
            handler.start()

        handler.register("s", cb_after)
        assert handler._callbacks["p"] is cb_before
        assert handler._callbacks["s"] is cb_after


class TestConstants:
    """Verify module constants match story spec."""

    def test_repeat_window(self) -> None:
        assert _REPEAT_WINDOW == 0.15

    def test_long_press_threshold(self) -> None:
        assert _LONG_PRESS_THRESHOLD == 5
