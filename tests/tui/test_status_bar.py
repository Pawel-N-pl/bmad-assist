"""Tests for tui/status_bar.py StatusBar component."""

from __future__ import annotations

import shutil
import threading
import time
from unittest.mock import MagicMock, call, patch

import pytest

from bmad_assist.ipc.types import RunnerState
from bmad_assist.tui.layout import LayoutManager
from bmad_assist.tui.status_bar import (
    PHASE_SHORTCUTS,
    StatusBar,
    format_run_elapsed,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_layout() -> MagicMock:
    """Create a mock LayoutManager."""
    layout = MagicMock(spec=LayoutManager)
    return layout


@pytest.fixture()
def status_bar(mock_layout: MagicMock) -> StatusBar:
    """Create a StatusBar with mock layout."""
    return StatusBar(mock_layout)


# ---------------------------------------------------------------------------
# format_run_elapsed() tests (AC #11)
# ---------------------------------------------------------------------------


class TestFormatRunElapsed:
    def test_zero_seconds(self) -> None:
        """0 seconds formats as '0s'."""
        assert format_run_elapsed(0) == "0s"

    def test_seconds_only(self) -> None:
        """42 seconds formats as '42s'."""
        assert format_run_elapsed(42) == "42s"

    def test_minutes_and_seconds(self) -> None:
        """125 seconds formats as '2m 5s'."""
        assert format_run_elapsed(125) == "2m 5s"

    def test_exact_minute(self) -> None:
        """60 seconds formats as '1m 0s'."""
        assert format_run_elapsed(60) == "1m 0s"

    def test_hours_minutes_seconds(self) -> None:
        """3661 seconds formats as '1h 1m 1s'."""
        assert format_run_elapsed(3661) == "1h 1m 1s"

    def test_exact_hour(self) -> None:
        """3600 seconds formats as '1h 0m 0s'."""
        assert format_run_elapsed(3600) == "1h 0m 0s"

    def test_days_hours_minutes_seconds(self) -> None:
        """130523 seconds formats as '1d 12h 15m 23s'."""
        assert format_run_elapsed(130523) == "1d 12h 15m 23s"

    def test_exact_day(self) -> None:
        """86400 seconds formats as '1d 0h 0m 0s'."""
        assert format_run_elapsed(86400) == "1d 0h 0m 0s"

    def test_multi_day(self) -> None:
        """Multiple days."""
        # 2d 0h 0m 0s = 172800s
        assert format_run_elapsed(172800) == "2d 0h 0m 0s"

    def test_float_input_truncated(self) -> None:
        """Float seconds truncated to int."""
        assert format_run_elapsed(42.9) == "42s"

    def test_large_duration(self) -> None:
        """Large duration: 10d+ formats correctly."""
        # 10d 5h 30m 15s = 864000 + 18000 + 1800 + 15 = 883815
        assert format_run_elapsed(883815) == "10d 5h 30m 15s"

    def test_negative_seconds_clamped_to_zero(self) -> None:
        """Negative input is clamped to 0s."""
        assert format_run_elapsed(-5) == "0s"
        assert format_run_elapsed(-100.5) == "0s"


# ---------------------------------------------------------------------------
# PHASE_SHORTCUTS constant tests (AC #8)
# ---------------------------------------------------------------------------


class TestPhaseShortcuts:
    def test_all_known_phases_present(self) -> None:
        """All 18 known phase shortcuts are defined."""
        expected_phases = [
            "create_story",
            "validate_story",
            "validate_story_synthesis",
            "dev_story",
            "code_review",
            "code_review_synthesis",
            "retrospective",
            "tea_framework",
            "tea_ci",
            "tea_test_design",
            "atdd",
            "tea_automate",
            "test_review",
            "trace",
            "tea_nfr_assess",
            "qa_plan_generate",
            "qa_plan_execute",
            "qa_remediate",
        ]
        for phase in expected_phases:
            assert phase in PHASE_SHORTCUTS, f"Missing shortcut for {phase}"

    def test_specific_shortcuts(self) -> None:
        """Verify specific phase shortcut mappings."""
        assert PHASE_SHORTCUTS["create_story"] == "Create"
        assert PHASE_SHORTCUTS["validate_story"] == "Validate"
        assert PHASE_SHORTCUTS["validate_story_synthesis"] == "Val Synth"
        assert PHASE_SHORTCUTS["dev_story"] == "Develop"
        assert PHASE_SHORTCUTS["code_review"] == "Review"
        assert PHASE_SHORTCUTS["code_review_synthesis"] == "Rev Synth"
        assert PHASE_SHORTCUTS["retrospective"] == "Retro"
        assert PHASE_SHORTCUTS["tea_framework"] == "Framework"
        assert PHASE_SHORTCUTS["tea_ci"] == "CI"
        assert PHASE_SHORTCUTS["tea_test_design"] == "Test Design"
        assert PHASE_SHORTCUTS["atdd"] == "ATDD"
        assert PHASE_SHORTCUTS["tea_automate"] == "Automate"
        assert PHASE_SHORTCUTS["test_review"] == "Test Review"
        assert PHASE_SHORTCUTS["trace"] == "Trace"
        assert PHASE_SHORTCUTS["tea_nfr_assess"] == "NFR"
        assert PHASE_SHORTCUTS["qa_plan_generate"] == "QA Plan"
        assert PHASE_SHORTCUTS["qa_plan_execute"] == "QA Exec"
        assert PHASE_SHORTCUTS["qa_remediate"] == "QA Fix"

    def test_shortcut_count(self) -> None:
        """Exactly 18 shortcuts defined."""
        assert len(PHASE_SHORTCUTS) == 18


# ---------------------------------------------------------------------------
# StatusBar.__init__() tests (AC #1, #3)
# ---------------------------------------------------------------------------


class TestStatusBarInit:
    def test_stores_layout_reference(self, mock_layout: MagicMock) -> None:
        """StatusBar stores the LayoutManager reference."""
        sb = StatusBar(mock_layout)
        assert sb._layout is mock_layout

    def test_default_field_values(self, status_bar: StatusBar) -> None:
        """Default field values are correctly initialized."""
        assert status_bar._run_start_time == 0.0
        assert status_bar._phase is None
        assert status_bar._epic_id is None
        assert status_bar._story_id is None
        assert status_bar._phase_start_time == 0.0
        assert status_bar._llm_sessions == 0
        assert status_bar._log_level == "WARNING"
        assert status_bar._paused is False
        assert status_bar._runner_state == RunnerState.IDLE
        assert status_bar._running is False
        assert status_bar._timer_thread is None

    def test_has_lock(self, status_bar: StatusBar) -> None:
        """StatusBar has a threading lock."""
        assert isinstance(status_bar._lock, type(threading.Lock()))


# ---------------------------------------------------------------------------
# Setter tests (AC #3)
# ---------------------------------------------------------------------------


class TestSetters:
    def test_set_run_start_time(self, status_bar: StatusBar, mock_layout: MagicMock) -> None:
        """set_run_start_time() updates _run_start_time and triggers render."""
        t = time.monotonic()
        status_bar.set_run_start_time(t)
        assert status_bar._run_start_time == t
        mock_layout.update_status_bar.assert_called()

    def test_set_phase_info(self, status_bar: StatusBar, mock_layout: MagicMock) -> None:
        """set_phase_info() updates phase, epic_id, story_id, and resets phase_start_time."""
        before = time.monotonic()
        status_bar.set_phase_info("dev_story", 30, "30.4")
        after = time.monotonic()

        assert status_bar._phase == "dev_story"
        assert status_bar._epic_id == 30
        assert status_bar._story_id == "30.4"
        assert before <= status_bar._phase_start_time <= after
        mock_layout.update_status_bar.assert_called()

    def test_set_phase_info_resets_phase_start_time(
        self, status_bar: StatusBar, mock_layout: MagicMock
    ) -> None:
        """set_phase_info() resets _phase_start_time on each call (AC #4)."""
        status_bar.set_phase_info("create_story", 1, "1.1")
        first_time = status_bar._phase_start_time

        time.sleep(0.01)  # Ensure monotonic advances
        status_bar.set_phase_info("dev_story", 1, "1.1")
        second_time = status_bar._phase_start_time

        assert second_time > first_time

    def test_set_llm_sessions(self, status_bar: StatusBar, mock_layout: MagicMock) -> None:
        """set_llm_sessions() updates count and triggers render."""
        status_bar.set_llm_sessions(7)
        assert status_bar._llm_sessions == 7
        mock_layout.update_status_bar.assert_called()

    def test_set_log_level(self, status_bar: StatusBar, mock_layout: MagicMock) -> None:
        """set_log_level() updates level and triggers render."""
        status_bar.set_log_level("DEBUG")
        assert status_bar._log_level == "DEBUG"
        mock_layout.update_status_bar.assert_called()

    def test_set_paused(self, status_bar: StatusBar, mock_layout: MagicMock) -> None:
        """set_paused() updates flag and triggers render."""
        status_bar.set_paused(True)
        assert status_bar._paused is True
        mock_layout.update_status_bar.assert_called()

    def test_set_runner_state(self, status_bar: StatusBar, mock_layout: MagicMock) -> None:
        """set_runner_state() updates state and triggers render."""
        status_bar.set_runner_state(RunnerState.RUNNING)
        assert status_bar._runner_state == RunnerState.RUNNING
        mock_layout.update_status_bar.assert_called()


# ---------------------------------------------------------------------------
# Thread safety tests (AC #1, #7)
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_setter_acquires_lock(self, mock_layout: MagicMock) -> None:
        """Setters acquire the lock before modifying fields."""
        sb = StatusBar(mock_layout)
        mock_lock = MagicMock()
        sb._lock = mock_lock

        sb.set_llm_sessions(5)
        mock_lock.__enter__.assert_called()
        mock_lock.__exit__.assert_called()

    def test_render_acquires_lock(self, mock_layout: MagicMock) -> None:
        """_render() acquires the lock to read fields."""
        sb = StatusBar(mock_layout)
        mock_lock = MagicMock()
        sb._lock = mock_lock

        sb._render()
        mock_lock.__enter__.assert_called()
        mock_lock.__exit__.assert_called()

    def test_concurrent_setters_no_corruption(self, mock_layout: MagicMock) -> None:
        """Concurrent setter calls don't corrupt data."""
        sb = StatusBar(mock_layout)
        sb.set_run_start_time(time.monotonic())
        sb.set_phase_info("dev_story", 30, "30.4")

        errors: list[Exception] = []

        def set_sessions() -> None:
            try:
                for i in range(100):
                    sb.set_llm_sessions(i)
            except Exception as e:
                errors.append(e)

        def set_level() -> None:
            try:
                for level in ["DEBUG", "INFO", "WARNING"] * 33 + ["DEBUG"]:
                    sb.set_log_level(level)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=set_sessions)
        t2 = threading.Thread(target=set_level)
        t1.start()
        t2.start()
        t1.join(timeout=2)
        t2.join(timeout=2)

        assert not errors, f"Concurrent setter errors: {errors}"


# ---------------------------------------------------------------------------
# Normal mode formatting tests (AC #2, #7, #8)
# ---------------------------------------------------------------------------


class TestNormalModeFormatting:
    def test_normal_mode_all_segments(self, mock_layout: MagicMock) -> None:
        """Normal mode status bar contains all segments in correct order."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic() - 100)  # 1m 40s ago
            sb.set_phase_info("dev_story", 30, "30.4")
            sb.set_llm_sessions(7)
            sb.set_log_level("WARNING")

        # Get the last call to update_status_bar
        status_text = mock_layout.update_status_bar.call_args[0][0]

        # All segments present
        assert "[p] pause" in status_text
        assert "[s] stop" in status_text
        assert "[c] config reload" in status_text
        assert "run:" in status_text
        assert "30.4 Develop" in status_text
        assert "LLM: 7" in status_text
        assert "[l] WARNING" in status_text

    def test_normal_mode_segment_order(self, mock_layout: MagicMock) -> None:
        """Segments appear in correct order: run → phase → LLM → commands → log."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic() - 60)
            sb.set_phase_info("dev_story", 30, "30.4")
            sb.set_llm_sessions(3)
            sb.set_log_level("INFO")

        status_text = mock_layout.update_status_bar.call_args[0][0]

        # Verify ordering: run < phase < LLM < commands < log
        idx_run = status_text.index("run:")
        idx_phase = status_text.index("30.4 Develop")
        idx_llm = status_text.index("LLM: 3")
        idx_cmd = status_text.index("[p] pause")
        idx_log = status_text.index("[l] INFO")

        assert idx_run < idx_phase < idx_llm < idx_cmd < idx_log

    def test_separator_is_space_slash_space(self, mock_layout: MagicMock) -> None:
        """Segments are separated by ' / '."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic() - 42)
            sb.set_phase_info("create_story", 1, "1.1")
            sb.set_llm_sessions(0)
            sb.set_log_level("WARNING")

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert " / " in status_text

    def test_phase_shortcut_used(self, mock_layout: MagicMock) -> None:
        """Phase info uses shortcut names, not raw phase_ids."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic())
            sb.set_phase_info("validate_story_synthesis", 5, "5.2")
            sb.set_llm_sessions(0)

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "5.2 Val Synth" in status_text
        assert "validate_story_synthesis" not in status_text

    def test_unknown_phase_fallback(self, mock_layout: MagicMock) -> None:
        """Unknown phase falls back to UPPER_SNAKE_CASE format."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic())
            sb.set_phase_info("custom_workflow_phase", 1, "1.1")

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "1.1 CUSTOM WORKFLOW PHASE" in status_text


# ---------------------------------------------------------------------------
# Phase elapsed line tests (AC #4)
# ---------------------------------------------------------------------------


class TestPhaseElapsedLine:
    def test_format_with_active_phase(self, mock_layout: MagicMock) -> None:
        """Phase elapsed line shows 'current phase elapsed: Xm Ys'."""
        sb = StatusBar(mock_layout)
        # Simulate phase started 65 seconds ago
        sb._phase = "dev_story"
        sb._phase_start_time = time.monotonic() - 65

        sb._render()

        phase_text = mock_layout.update_phase_elapsed.call_args[0][0]
        assert phase_text.startswith("current phase elapsed:")
        assert "1m" in phase_text

    def test_empty_when_no_phase(self, mock_layout: MagicMock) -> None:
        """Phase elapsed line is empty when no phase is active."""
        sb = StatusBar(mock_layout)
        sb._phase = None

        sb._render()

        phase_text = mock_layout.update_phase_elapsed.call_args[0][0]
        assert phase_text == ""

    def test_resets_on_new_phase(self, mock_layout: MagicMock) -> None:
        """Phase elapsed resets to ~0s when set_phase_info() is called."""
        sb = StatusBar(mock_layout)
        sb._phase = "create_story"
        sb._phase_start_time = time.monotonic() - 300  # 5 minutes ago

        sb.set_phase_info("dev_story", 30, "30.4")

        phase_text = mock_layout.update_phase_elapsed.call_args[0][0]
        # Should show near-zero elapsed since phase just started
        assert "current phase elapsed:" in phase_text
        # After reset, should be 0s or 1s (depending on timing)
        assert "0s" in phase_text or "1s" in phase_text

    def test_shows_paused_when_paused(self, mock_layout: MagicMock) -> None:
        """Phase elapsed shows 'PAUSED' when paused (AC #10)."""
        sb = StatusBar(mock_layout)
        sb._phase = "dev_story"
        sb._phase_start_time = time.monotonic() - 60
        sb.set_paused(True)

        phase_text = mock_layout.update_phase_elapsed.call_args[0][0]
        assert phase_text == "PAUSED"


# ---------------------------------------------------------------------------
# Paused mode tests (AC #10)
# ---------------------------------------------------------------------------


class TestPausedMode:
    def test_paused_shows_resume(self, mock_layout: MagicMock) -> None:
        """Paused mode shows '[r] resume' instead of '[p] pause'."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic() - 100)
            sb.set_phase_info("dev_story", 30, "30.4")
            sb.set_llm_sessions(3)
            sb.set_paused(True)

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "[r] resume" in status_text
        assert "[p] pause" not in status_text

    def test_paused_shows_paused_text(self, mock_layout: MagicMock) -> None:
        """Paused mode shows 'PAUSED' instead of phase info."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic() - 100)
            sb.set_phase_info("dev_story", 30, "30.4")
            sb.set_llm_sessions(0)
            sb.set_paused(True)

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "PAUSED" in status_text
        # Phase info should NOT appear
        assert "30.4 Develop" not in status_text

    def test_paused_still_shows_run_elapsed(self, mock_layout: MagicMock) -> None:
        """Paused mode still shows run elapsed time."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic() - 100)
            sb.set_paused(True)

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "run:" in status_text

    def test_paused_still_shows_llm_and_log(self, mock_layout: MagicMock) -> None:
        """Paused mode still shows LLM count and log level."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic())
            sb.set_llm_sessions(5)
            sb.set_log_level("DEBUG")
            sb.set_paused(True)

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "LLM: 5" in status_text
        assert "[l] DEBUG" in status_text


# ---------------------------------------------------------------------------
# Truncation tests (AC #9)
# ---------------------------------------------------------------------------


class TestTruncation:
    def test_narrow_terminal_drops_commands_first(self, mock_layout: MagicMock) -> None:
        """With narrow terminal, command hints are dropped first."""
        sb = StatusBar(mock_layout)
        sb.set_run_start_time(time.monotonic() - 60)
        sb.set_phase_info("dev_story", 30, "30.4")
        sb.set_llm_sessions(7)
        sb.set_log_level("WARNING")

        # Get formatted text with narrow width
        text = sb._format_status_bar(cols=60)

        assert "[p] pause" not in text
        assert "run:" in text
        assert "30.4 Develop" in text

    def test_very_narrow_drops_log_level(self, mock_layout: MagicMock) -> None:
        """Very narrow terminal drops log level after commands."""
        sb = StatusBar(mock_layout)
        sb.set_run_start_time(time.monotonic() - 60)
        sb.set_phase_info("dev_story", 30, "30.4")
        sb.set_llm_sessions(7)
        sb.set_log_level("WARNING")

        text = sb._format_status_bar(cols=40)

        assert "[p] pause" not in text
        assert "[l]" not in text
        assert "run:" in text

    def test_minimum_viable_has_run_and_phase(self, mock_layout: MagicMock) -> None:
        """Minimum viable format includes run elapsed and phase info."""
        sb = StatusBar(mock_layout)
        sb.set_run_start_time(time.monotonic() - 60)
        sb.set_phase_info("dev_story", 30, "30.4")
        sb.set_llm_sessions(7)
        sb.set_log_level("WARNING")

        text = sb._format_status_bar(cols=30)

        assert "run:" in text
        assert "Develop" in text

    def test_wide_terminal_shows_all(self, mock_layout: MagicMock) -> None:
        """Wide terminal shows all segments."""
        sb = StatusBar(mock_layout)
        sb.set_run_start_time(time.monotonic() - 60)
        sb.set_phase_info("dev_story", 30, "30.4")
        sb.set_llm_sessions(7)
        sb.set_log_level("WARNING")

        text = sb._format_status_bar(cols=200)

        assert "[p] pause" in text
        assert "[s] stop" in text
        assert "[c] config reload" in text
        assert "run:" in text
        assert "30.4 Develop" in text
        assert "LLM: 7" in text
        assert "[l] WARNING" in text


# ---------------------------------------------------------------------------
# _render() tests (AC #7)
# ---------------------------------------------------------------------------


class TestRender:
    def test_render_calls_both_layout_methods(self, mock_layout: MagicMock) -> None:
        """_render() calls layout.update_phase_elapsed() and layout.update_status_bar()."""
        sb = StatusBar(mock_layout)
        sb.set_run_start_time(time.monotonic())
        sb.set_phase_info("dev_story", 30, "30.4")

        mock_layout.reset_mock()
        sb._render()

        mock_layout.update_phase_elapsed.assert_called_once()
        mock_layout.update_status_bar.assert_called_once()

    def test_render_passes_correct_phase_text(self, mock_layout: MagicMock) -> None:
        """_render() passes correct phase elapsed text."""
        sb = StatusBar(mock_layout)
        sb._phase = "dev_story"
        sb._phase_start_time = time.monotonic()

        sb._render()

        phase_text = mock_layout.update_phase_elapsed.call_args[0][0]
        assert "current phase elapsed:" in phase_text

    def test_render_passes_correct_status_text(self, mock_layout: MagicMock) -> None:
        """_render() passes correct status bar text."""
        sb = StatusBar(mock_layout)
        sb._run_start_time = time.monotonic() - 42
        sb._phase = "dev_story"
        sb._story_id = "30.4"
        sb._llm_sessions = 3
        sb._log_level = "INFO"

        sb._render()

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "run:" in status_text
        assert "30.4 Develop" in status_text
        assert "LLM: 3" in status_text
        assert "[l] INFO" in status_text


# ---------------------------------------------------------------------------
# start() / stop() tests (AC #5, #6)
# ---------------------------------------------------------------------------


class TestStartStop:
    def test_start_creates_daemon_thread(self, mock_layout: MagicMock) -> None:
        """start() creates a daemon thread named 'tui-status-timer'."""
        sb = StatusBar(mock_layout)
        sb.start()
        try:
            assert sb._running is True
            assert sb._timer_thread is not None
            assert sb._timer_thread.daemon is True
            assert sb._timer_thread.name == "tui-status-timer"
            assert sb._timer_thread.is_alive()
        finally:
            sb.stop()

    def test_start_is_idempotent(self, mock_layout: MagicMock) -> None:
        """Calling start() twice does not start a second thread."""
        sb = StatusBar(mock_layout)
        sb.start()
        try:
            first_thread = sb._timer_thread
            sb.start()  # Second call
            assert sb._timer_thread is first_thread
        finally:
            sb.stop()

    def test_stop_sets_running_false(self, mock_layout: MagicMock) -> None:
        """stop() sets _running to False."""
        sb = StatusBar(mock_layout)
        sb.start()
        sb.stop()
        assert sb._running is False

    def test_stop_joins_thread(self, mock_layout: MagicMock) -> None:
        """stop() joins the timer thread."""
        sb = StatusBar(mock_layout)
        sb.start()
        sb.stop()
        assert sb._timer_thread is None or not sb._timer_thread.is_alive()

    def test_stop_is_idempotent(self, mock_layout: MagicMock) -> None:
        """Calling stop() multiple times is safe."""
        sb = StatusBar(mock_layout)
        sb.start()
        sb.stop()
        sb.stop()  # Should not raise
        sb.stop()  # Should not raise

    def test_stop_never_raises(self, mock_layout: MagicMock) -> None:
        """stop() never raises even without prior start()."""
        sb = StatusBar(mock_layout)
        sb.stop()  # Should not raise

    def test_timer_thread_calls_render(self, mock_layout: MagicMock) -> None:
        """Timer thread calls _render() periodically (~1 second)."""
        sb = StatusBar(mock_layout)
        sb._run_start_time = time.monotonic()
        sb._phase = "dev_story"
        sb._story_id = "30.4"
        sb.start()
        try:
            # Wait slightly more than 1 second for the timer to fire
            time.sleep(1.3)
            # The timer should have called _render at least once
            assert mock_layout.update_status_bar.call_count >= 1
        finally:
            sb.stop()

    def test_stop_responds_quickly(self, mock_layout: MagicMock) -> None:
        """stop() completes within 500ms (thanks to 0.1s sleep increments)."""
        sb = StatusBar(mock_layout)
        sb.start()

        start = time.monotonic()
        sb.stop()
        elapsed = time.monotonic() - start

        assert elapsed < 0.5, f"stop() took {elapsed:.3f}s, expected < 0.5s"


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_lifecycle(self, mock_layout: MagicMock) -> None:
        """Full lifecycle: start → set data → render → stop."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.start()
            try:
                sb.set_run_start_time(time.monotonic())
                sb.set_phase_info("create_story", 30, "30.1")
                sb.set_llm_sessions(1)
                sb.set_log_level("INFO")

                # Verify render was called
                assert mock_layout.update_status_bar.call_count >= 1
                assert mock_layout.update_phase_elapsed.call_count >= 1

                # Change phase
                sb.set_phase_info("dev_story", 30, "30.1")
                sb.set_llm_sessions(3)

                # Pause
                sb.set_paused(True)
                status_text = mock_layout.update_status_bar.call_args[0][0]
                assert "[r] resume" in status_text
                assert "PAUSED" in status_text

                # Resume
                sb.set_paused(False)
                status_text = mock_layout.update_status_bar.call_args[0][0]
                assert "[p] pause" in status_text
            finally:
                sb.stop()

    def test_string_epic_id(self, mock_layout: MagicMock) -> None:
        """StatusBar handles string epic IDs (e.g., 'testarch')."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic())
            sb.set_phase_info("tea_framework", "testarch", "testarch.1")

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "testarch.1 Framework" in status_text

    def test_no_phase_shows_minimal(self, mock_layout: MagicMock) -> None:
        """With no phase set, status bar shows what it can."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic())

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "run:" in status_text
        # No phase info segment
        assert "LLM: 0" in status_text


# ---------------------------------------------------------------------------
# set_pause_countdown() tests (Story 30.5, AC #14)
# ---------------------------------------------------------------------------


class TestSetPauseCountdown:
    def test_set_pause_countdown_updates_field(self, mock_layout: MagicMock) -> None:
        """set_pause_countdown() stores countdown text in data model."""
        sb = StatusBar(mock_layout)
        sb.set_pause_countdown("59m 32s")
        assert sb._pause_countdown == "59m 32s"

    def test_set_pause_countdown_none_clears(self, mock_layout: MagicMock) -> None:
        """set_pause_countdown(None) clears countdown."""
        sb = StatusBar(mock_layout)
        sb.set_pause_countdown("1h 0m")
        sb.set_pause_countdown(None)
        assert sb._pause_countdown is None

    def test_set_pause_countdown_triggers_render(
        self, mock_layout: MagicMock
    ) -> None:
        """set_pause_countdown() triggers a render cycle."""
        sb = StatusBar(mock_layout)
        mock_layout.reset_mock()
        sb.set_pause_countdown("5m 0s")
        mock_layout.update_status_bar.assert_called()

    def test_default_pause_countdown_is_none(self, mock_layout: MagicMock) -> None:
        """Initial _pause_countdown is None."""
        sb = StatusBar(mock_layout)
        assert sb._pause_countdown is None

    def test_paused_with_countdown_shows_resume_in_countdown(
        self, mock_layout: MagicMock
    ) -> None:
        """Paused mode with countdown shows '[r] resume in {countdown}'."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic() - 100)
            sb.set_llm_sessions(3)
            sb.set_paused(True)
            sb.set_pause_countdown("59m 32s")

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "[r] resume in 59m 32s" in status_text
        assert "[p] pause" not in status_text

    def test_paused_without_countdown_shows_plain_resume(
        self, mock_layout: MagicMock
    ) -> None:
        """Paused mode without countdown shows plain '[r] resume'."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic() - 100)
            sb.set_llm_sessions(3)
            sb.set_paused(True)

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "[r] resume / [s] stop" in status_text
        # Should NOT have "resume in"
        assert "resume in" not in status_text

    def test_not_paused_with_countdown_ignores_countdown(
        self, mock_layout: MagicMock
    ) -> None:
        """Normal mode ignores countdown even if set."""
        sb = StatusBar(mock_layout)
        with patch("bmad_assist.tui.status_bar.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=200, lines=24)
            sb.set_run_start_time(time.monotonic())
            sb.set_pause_countdown("10m 0s")

        status_text = mock_layout.update_status_bar.call_args[0][0]
        assert "[p] pause" in status_text
        assert "resume in" not in status_text

    def test_countdown_acquires_lock(self, mock_layout: MagicMock) -> None:
        """set_pause_countdown() acquires lock before modification."""
        sb = StatusBar(mock_layout)
        mock_lock = MagicMock()
        sb._lock = mock_lock

        sb.set_pause_countdown("1h 0m")
        mock_lock.__enter__.assert_called()
        mock_lock.__exit__.assert_called()
