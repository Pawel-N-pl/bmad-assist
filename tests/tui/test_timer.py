"""Tests for tui/timer.py PauseTimer component."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, call

import pytest

from bmad_assist.tui.layout import LayoutManager
from bmad_assist.tui.status_bar import StatusBar
from bmad_assist.tui.timer import PauseTimer, format_countdown


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_status_bar() -> MagicMock:
    """Create a mock StatusBar."""
    return MagicMock(spec=StatusBar)


@pytest.fixture()
def mock_layout() -> MagicMock:
    """Create a mock LayoutManager."""
    return MagicMock(spec=LayoutManager)


@pytest.fixture()
def timer(mock_status_bar: MagicMock, mock_layout: MagicMock) -> PauseTimer:
    """Create a PauseTimer with mock dependencies."""
    return PauseTimer(mock_status_bar, mock_layout)


# ---------------------------------------------------------------------------
# format_countdown() tests (AC #12)
# ---------------------------------------------------------------------------


class TestFormatCountdown:
    def test_zero_seconds(self) -> None:
        """0 seconds formats as '0s'."""
        assert format_countdown(0) == "0s"

    def test_sub_minute(self) -> None:
        """42 seconds formats as '42s'."""
        assert format_countdown(42) == "42s"

    def test_exact_minute(self) -> None:
        """60 seconds formats as '1m 0s'."""
        assert format_countdown(60) == "1m 0s"

    def test_minutes_and_seconds(self) -> None:
        """125 seconds (2m 5s) formats correctly."""
        assert format_countdown(125) == "2m 5s"

    def test_just_under_hour(self) -> None:
        """3599 seconds formats as '59m 59s'."""
        assert format_countdown(3599) == "59m 59s"

    def test_exact_hour(self) -> None:
        """3600 seconds formats as '1h 0m' (no seconds at hour scale)."""
        assert format_countdown(3600) == "1h 0m"

    def test_hour_and_one_minute(self) -> None:
        """3661 seconds (1h 1m 1s) formats as '1h 1m' — seconds omitted."""
        assert format_countdown(3661) == "1h 1m"

    def test_multi_hour(self) -> None:
        """9930 seconds (2h 45m 30s) formats as '2h 45m'."""
        assert format_countdown(9930) == "2h 45m"

    def test_one_second(self) -> None:
        """1 second formats as '1s'."""
        assert format_countdown(1) == "1s"

    def test_exact_two_hours(self) -> None:
        """7200 seconds formats as '2h 0m'."""
        assert format_countdown(7200) == "2h 0m"


# ---------------------------------------------------------------------------
# PauseTimer.__init__() tests (AC #1)
# ---------------------------------------------------------------------------


class TestPauseTimerInit:
    def test_stores_references(
        self, mock_status_bar: MagicMock, mock_layout: MagicMock
    ) -> None:
        """PauseTimer stores StatusBar and LayoutManager references."""
        pt = PauseTimer(mock_status_bar, mock_layout)
        assert pt._status_bar is mock_status_bar
        assert pt._layout is mock_layout

    def test_default_field_values(self, timer: PauseTimer) -> None:
        """Default field values are correctly initialized."""
        assert timer._remaining_seconds == 0
        assert timer._active is False
        assert timer._running is False
        assert timer._timer_thread is None
        assert timer._pause_callback is None
        assert timer._resume_callback is None

    def test_has_lock(self, timer: PauseTimer) -> None:
        """PauseTimer has a threading lock."""
        assert isinstance(timer._lock, type(threading.Lock()))


# ---------------------------------------------------------------------------
# Callback setters
# ---------------------------------------------------------------------------


class TestCallbackSetters:
    def test_set_pause_callback(self, timer: PauseTimer) -> None:
        """set_pause_callback() stores the callback."""
        cb = MagicMock()
        timer.set_pause_callback(cb)
        assert timer._pause_callback is cb

    def test_set_resume_callback(self, timer: PauseTimer) -> None:
        """set_resume_callback() stores the callback."""
        cb = MagicMock()
        timer.set_resume_callback(cb)
        assert timer._resume_callback is cb


# ---------------------------------------------------------------------------
# activate() tests (AC #2)
# ---------------------------------------------------------------------------


class TestActivate:
    def test_sets_active_and_remaining(
        self,
        timer: PauseTimer,
        mock_status_bar: MagicMock,
    ) -> None:
        """activate() sets _active=True and _remaining_seconds=3600."""
        timer.activate()
        assert timer._active is True
        assert timer._remaining_seconds == 3600

    def test_calls_pause_callback(self, timer: PauseTimer) -> None:
        """activate() calls _pause_callback if set."""
        cb = MagicMock()
        timer.set_pause_callback(cb)
        timer.activate()
        cb.assert_called_once()

    def test_calls_set_paused_true(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """activate() calls set_paused(True) on StatusBar."""
        timer.activate()
        mock_status_bar.set_paused.assert_called_with(True)

    def test_writes_log(
        self, timer: PauseTimer, mock_layout: MagicMock
    ) -> None:
        """activate() writes a PAUSED log message."""
        timer.activate()
        mock_layout.write_log.assert_called()
        log_msg = mock_layout.write_log.call_args[0][0]
        assert "PAUSED" in log_msg
        assert "auto-resume" in log_msg

    def test_updates_countdown_display(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """activate() updates countdown display via set_pause_countdown()."""
        timer.activate()
        mock_status_bar.set_pause_countdown.assert_called()
        # Should show 1h 0m for initial 3600s
        countdown_text = mock_status_bar.set_pause_countdown.call_args[0][0]
        assert countdown_text == "1h 0m"

    def test_callback_exception_does_not_crash(
        self, timer: PauseTimer
    ) -> None:
        """activate() catches callback exceptions (fire-and-forget)."""
        cb = MagicMock(side_effect=RuntimeError("callback error"))
        timer.set_pause_callback(cb)
        timer.activate()  # Should not raise
        assert timer._active is True


# ---------------------------------------------------------------------------
# deactivate() tests (AC #3)
# ---------------------------------------------------------------------------


class TestDeactivate:
    def test_clears_active_and_remaining(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """deactivate() sets _active=False and _remaining_seconds=0."""
        timer.activate()
        timer.deactivate()
        assert timer._active is False
        assert timer._remaining_seconds == 0

    def test_calls_resume_callback(self, timer: PauseTimer) -> None:
        """deactivate() calls _resume_callback if set."""
        cb = MagicMock()
        timer.set_resume_callback(cb)
        timer.activate()
        timer.deactivate()
        cb.assert_called_once()

    def test_calls_set_paused_false(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """deactivate() calls set_paused(False) on StatusBar."""
        timer.activate()
        mock_status_bar.reset_mock()
        timer.deactivate()
        mock_status_bar.set_paused.assert_called_with(False)

    def test_clears_countdown_display(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """deactivate() clears countdown via set_pause_countdown(None)."""
        timer.activate()
        mock_status_bar.reset_mock()
        timer.deactivate()
        mock_status_bar.set_pause_countdown.assert_called_with(None)

    def test_writes_log(
        self, timer: PauseTimer, mock_layout: MagicMock
    ) -> None:
        """deactivate() writes RESUMED log message."""
        timer.activate()
        mock_layout.reset_mock()
        timer.deactivate()
        mock_layout.write_log.assert_called()
        log_msg = mock_layout.write_log.call_args[0][0]
        assert "RESUMED" in log_msg
        assert "manual" in log_msg

    def test_idempotent_when_not_active(
        self,
        timer: PauseTimer,
        mock_status_bar: MagicMock,
        mock_layout: MagicMock,
    ) -> None:
        """deactivate() is a no-op when not active — no callbacks, no logs."""
        cb = MagicMock()
        timer.set_resume_callback(cb)
        timer.deactivate()  # Not active — should be no-op
        cb.assert_not_called()
        mock_status_bar.set_paused.assert_not_called()
        mock_layout.write_log.assert_not_called()

    def test_callback_exception_does_not_crash(
        self, timer: PauseTimer
    ) -> None:
        """deactivate() catches callback exceptions (fire-and-forget)."""
        cb = MagicMock(side_effect=RuntimeError("callback error"))
        timer.set_resume_callback(cb)
        timer.activate()
        timer.deactivate()  # Should not raise
        assert timer._active is False


# ---------------------------------------------------------------------------
# extend() tests (AC #4)
# ---------------------------------------------------------------------------


class TestExtend:
    def test_adds_3600_to_remaining(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """extend() adds 3600 seconds to _remaining_seconds."""
        timer.activate()
        timer.extend()
        assert timer._remaining_seconds == 7200

    def test_writes_log(
        self, timer: PauseTimer, mock_layout: MagicMock
    ) -> None:
        """extend() writes a log message about extension."""
        timer.activate()
        mock_layout.reset_mock()
        timer.extend()
        mock_layout.write_log.assert_called()
        log_msg = mock_layout.write_log.call_args[0][0]
        assert "extended" in log_msg.lower()

    def test_updates_countdown_display(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """extend() updates the countdown display."""
        timer.activate()
        mock_status_bar.reset_mock()
        timer.extend()
        mock_status_bar.set_pause_countdown.assert_called()
        countdown_text = mock_status_bar.set_pause_countdown.call_args[0][0]
        assert countdown_text == "2h 0m"


# ---------------------------------------------------------------------------
# reset_to_minutes() tests (AC #5)
# ---------------------------------------------------------------------------


class TestResetToMinutes:
    def test_resets_hours(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """reset_to_minutes() drops hours: 9930s → 2730s."""
        timer.activate()
        with timer._lock:
            timer._remaining_seconds = 9930  # 2h 45m 30s
        timer.reset_to_minutes()
        assert timer._remaining_seconds == 2730  # 45m 30s

    def test_exact_hour_sets_minimum_60(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """reset_to_minutes() on exact hour (7200s) → 60s (minimum)."""
        timer.activate()
        with timer._lock:
            timer._remaining_seconds = 7200  # 2h 0m 0s
        timer.reset_to_minutes()
        assert timer._remaining_seconds == 60

    def test_noop_when_under_one_hour(
        self, timer: PauseTimer, mock_status_bar: MagicMock, mock_layout: MagicMock
    ) -> None:
        """reset_to_minutes() is a no-op when _remaining_seconds <= 3600."""
        timer.activate()
        with timer._lock:
            timer._remaining_seconds = 2000
        mock_layout.reset_mock()
        timer.reset_to_minutes()
        assert timer._remaining_seconds == 2000
        # Should not write a log message for no-op
        mock_layout.write_log.assert_not_called()

    def test_noop_at_exactly_3600(
        self, timer: PauseTimer, mock_status_bar: MagicMock, mock_layout: MagicMock
    ) -> None:
        """reset_to_minutes() is a no-op at exactly 3600s."""
        timer.activate()  # sets to 3600
        mock_layout.reset_mock()
        timer.reset_to_minutes()
        assert timer._remaining_seconds == 3600
        mock_layout.write_log.assert_not_called()

    def test_writes_log(
        self, timer: PauseTimer, mock_layout: MagicMock
    ) -> None:
        """reset_to_minutes() writes a log message when it resets."""
        timer.activate()
        with timer._lock:
            timer._remaining_seconds = 9930
        mock_layout.reset_mock()
        timer.reset_to_minutes()
        mock_layout.write_log.assert_called()
        log_msg = mock_layout.write_log.call_args[0][0]
        assert "reset" in log_msg.lower()

    def test_updates_countdown_display(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """reset_to_minutes() updates the countdown display."""
        timer.activate()
        with timer._lock:
            timer._remaining_seconds = 9930
        mock_status_bar.reset_mock()
        timer.reset_to_minutes()
        mock_status_bar.set_pause_countdown.assert_called()


# ---------------------------------------------------------------------------
# on_pause_key() tests (AC #7)
# ---------------------------------------------------------------------------


class TestOnPauseKey:
    def test_dispatches_activate_when_not_active(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """on_pause_key() calls activate() when not active."""
        timer.on_pause_key()
        assert timer._active is True
        assert timer._remaining_seconds == 3600
        mock_status_bar.set_paused.assert_called_with(True)

    def test_dispatches_extend_when_active(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """on_pause_key() calls extend() when already active."""
        timer.activate()
        assert timer._remaining_seconds == 3600
        timer.on_pause_key()
        assert timer._remaining_seconds == 7200


# ---------------------------------------------------------------------------
# on_long_press_p() tests (AC #8)
# ---------------------------------------------------------------------------


class TestOnLongPressP:
    def test_dispatches_reset_when_active(
        self, timer: PauseTimer, mock_status_bar: MagicMock
    ) -> None:
        """on_long_press_p() calls reset_to_minutes() when active."""
        timer.activate()
        with timer._lock:
            timer._remaining_seconds = 9930
        timer.on_long_press_p()
        assert timer._remaining_seconds == 2730

    def test_noop_when_not_active(
        self,
        timer: PauseTimer,
        mock_status_bar: MagicMock,
        mock_layout: MagicMock,
    ) -> None:
        """on_long_press_p() is a no-op when not active."""
        timer.on_long_press_p()
        mock_layout.write_log.assert_not_called()


# ---------------------------------------------------------------------------
# Timer thread start/stop tests (AC #9, #13)
# ---------------------------------------------------------------------------


class TestStartStop:
    def test_start_creates_daemon_thread(self, timer: PauseTimer) -> None:
        """start() creates daemon thread named 'tui-pause-timer'."""
        timer.start()
        try:
            assert timer._running is True
            assert timer._timer_thread is not None
            assert timer._timer_thread.daemon is True
            assert timer._timer_thread.name == "tui-pause-timer"
            assert timer._timer_thread.is_alive()
        finally:
            timer.stop()

    def test_start_is_idempotent(self, timer: PauseTimer) -> None:
        """Calling start() twice does not start a second thread."""
        timer.start()
        try:
            first_thread = timer._timer_thread
            timer.start()
            assert timer._timer_thread is first_thread
        finally:
            timer.stop()

    def test_stop_sets_running_false(self, timer: PauseTimer) -> None:
        """stop() sets _running to False."""
        timer.start()
        timer.stop()
        assert timer._running is False

    def test_stop_is_idempotent(self, timer: PauseTimer) -> None:
        """Calling stop() multiple times is safe."""
        timer.start()
        timer.stop()
        timer.stop()  # Should not raise
        timer.stop()  # Should not raise

    def test_stop_never_raises(self, timer: PauseTimer) -> None:
        """stop() never raises even without prior start()."""
        timer.stop()  # Should not raise

    def test_stop_calls_deactivate_if_active(
        self,
        timer: PauseTimer,
        mock_status_bar: MagicMock,
    ) -> None:
        """stop() calls deactivate() if _active is True."""
        timer.activate()
        timer.start()
        cb = MagicMock()
        timer.set_resume_callback(cb)
        timer.stop()
        # Should have been deactivated
        assert timer._active is False
        cb.assert_called_once()

    def test_stop_responds_quickly(self, timer: PauseTimer) -> None:
        """stop() completes within 500ms."""
        timer.start()
        start = time.monotonic()
        timer.stop()
        elapsed = time.monotonic() - start
        assert elapsed < 0.6, f"stop() took {elapsed:.3f}s, expected < 0.6s"


# ---------------------------------------------------------------------------
# Auto-resume tests (AC #10)
# ---------------------------------------------------------------------------


class TestAutoResume:
    def test_auto_resume_when_timer_expires(
        self,
        timer: PauseTimer,
        mock_status_bar: MagicMock,
        mock_layout: MagicMock,
    ) -> None:
        """Timer auto-resumes when countdown reaches 0."""
        cb = MagicMock()
        timer.set_resume_callback(cb)
        timer.activate()
        # Set short remaining for fast test
        with timer._lock:
            timer._remaining_seconds = 2
        timer.start()
        try:
            time.sleep(3.5)  # Wait for timer to expire
            assert timer._active is False
            cb.assert_called_once()
            mock_status_bar.set_paused.assert_called_with(False)
        finally:
            timer.stop()

    def test_auto_resume_writes_log(
        self,
        timer: PauseTimer,
        mock_status_bar: MagicMock,
        mock_layout: MagicMock,
    ) -> None:
        """Auto-resume writes log message."""
        timer.activate()
        with timer._lock:
            timer._remaining_seconds = 2
        timer.start()
        try:
            time.sleep(3.5)
            # Find the auto-resume log message
            log_messages = [
                c[0][0] for c in mock_layout.write_log.call_args_list
            ]
            auto_resume_msgs = [m for m in log_messages if "auto-resumed" in m.lower()]
            assert len(auto_resume_msgs) >= 1
        finally:
            timer.stop()

    def test_auto_resume_clears_countdown(
        self,
        timer: PauseTimer,
        mock_status_bar: MagicMock,
        mock_layout: MagicMock,
    ) -> None:
        """Auto-resume clears countdown display."""
        timer.activate()
        with timer._lock:
            timer._remaining_seconds = 2
        timer.start()
        try:
            time.sleep(3.5)
            # Last set_pause_countdown call should be None
            last_call = mock_status_bar.set_pause_countdown.call_args
            assert last_call == call(None)
        finally:
            timer.stop()


# ---------------------------------------------------------------------------
# Timer thread periodic update tests (AC #9, #11)
# ---------------------------------------------------------------------------


class TestTimerThread:
    def test_timer_updates_display_periodically(
        self,
        timer: PauseTimer,
        mock_status_bar: MagicMock,
    ) -> None:
        """Timer thread calls set_pause_countdown() periodically."""
        timer.activate()
        mock_status_bar.reset_mock()
        timer.start()
        try:
            time.sleep(2.5)  # Wait for ~2 timer ticks
            # Should have been called at least once
            assert mock_status_bar.set_pause_countdown.call_count >= 1
        finally:
            timer.stop()


# ---------------------------------------------------------------------------
# Thread safety tests
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_extend_and_decrement(
        self,
        timer: PauseTimer,
        mock_status_bar: MagicMock,
    ) -> None:
        """Concurrent extend() and timer decrement don't corrupt state."""
        timer.activate()
        with timer._lock:
            timer._remaining_seconds = 100
        timer.start()
        try:
            errors: list[Exception] = []

            def extend_loop() -> None:
                try:
                    for _ in range(10):
                        timer.extend()
                        time.sleep(0.05)
                except Exception as e:
                    errors.append(e)

            t = threading.Thread(target=extend_loop)
            t.start()
            t.join(timeout=5)

            assert not errors, f"Concurrent errors: {errors}"
            # Remaining should be >= 100 (started at 100, added 10*3600, minus some ticks)
            assert timer._remaining_seconds > 0
        finally:
            timer.stop()
