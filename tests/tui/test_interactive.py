"""Tests for InteractiveRenderer stub and render_log/set_log_level."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from bmad_assist.ipc.types import RunnerState
from bmad_assist.tui.input import InputHandler
from bmad_assist.tui.interactive import InteractiveRenderer
from bmad_assist.tui.layout import LayoutManager
from bmad_assist.tui.log_level import LogLevelToggle
from bmad_assist.tui.status_bar import StatusBar
from bmad_assist.tui.timer import PauseTimer


@pytest.fixture
def renderer() -> InteractiveRenderer:
    """Create an InteractiveRenderer instance."""
    return InteractiveRenderer()


@pytest.fixture
def mock_layout() -> MagicMock:
    """Create a mock LayoutManager."""
    return MagicMock(spec=LayoutManager)


@pytest.fixture
def mock_toggle() -> MagicMock:
    """Create a mock LogLevelToggle."""
    mock = MagicMock(spec=LogLevelToggle)
    mock.get_level.return_value = "WARNING"
    return mock


@pytest.fixture
def wired_renderer(mock_layout: MagicMock, mock_toggle: MagicMock) -> InteractiveRenderer:
    """Create an InteractiveRenderer with components wired."""
    r = InteractiveRenderer()
    r.set_components(mock_layout, mock_toggle)
    return r


class TestInteractiveRendererCallable:
    """Verify all methods are callable without error."""

    def test_start(self, renderer: InteractiveRenderer) -> None:
        """start() completes without error."""
        renderer.start()

    def test_stop(self, renderer: InteractiveRenderer) -> None:
        """stop() completes without error."""
        renderer.stop()

    def test_render_log(self, renderer: InteractiveRenderer) -> None:
        """render_log() completes without error."""
        renderer.render_log("INFO", "test", "test.logger", datetime.now(UTC))

    def test_render_phase_started(self, renderer: InteractiveRenderer) -> None:
        """render_phase_started() completes without error."""
        renderer.render_phase_started("create_story", 1, "1.1")

    def test_render_phase_completed(self, renderer: InteractiveRenderer) -> None:
        """render_phase_completed() completes without error."""
        renderer.render_phase_completed("dev_story", 2, "2.1", 42.0)

    def test_update_status(self, renderer: InteractiveRenderer) -> None:
        """update_status() completes without error for all states."""
        for state in RunnerState:
            renderer.update_status(state)

    def test_set_log_level(self, renderer: InteractiveRenderer) -> None:
        """set_log_level() completes without error."""
        renderer.set_log_level("DEBUG")


class TestInteractiveRendererDebugLogs:
    """Verify stub methods log at DEBUG level."""

    def test_start_logs_debug(
        self, renderer: InteractiveRenderer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """start() logs 'not implemented' at DEBUG."""
        with caplog.at_level(logging.DEBUG, logger="bmad_assist.tui.interactive"):
            renderer.start()
        assert any("InteractiveRenderer.start: not implemented" in r.message for r in caplog.records)

    def test_render_log_logs_debug(
        self, renderer: InteractiveRenderer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """render_log() logs 'not implemented' at DEBUG."""
        with caplog.at_level(logging.DEBUG, logger="bmad_assist.tui.interactive"):
            renderer.render_log("INFO", "msg", "logger", datetime.now(UTC))
        assert any(
            "InteractiveRenderer.render_log: not implemented" in r.message for r in caplog.records
        )

    def test_render_phase_started_logs_debug(
        self, renderer: InteractiveRenderer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """render_phase_started() logs 'not implemented' at DEBUG."""
        with caplog.at_level(logging.DEBUG, logger="bmad_assist.tui.interactive"):
            renderer.render_phase_started("create_story", 1, "1.1")
        assert any(
            "InteractiveRenderer.render_phase_started: not implemented" in r.message
            for r in caplog.records
        )

    def test_update_status_logs_debug(
        self, renderer: InteractiveRenderer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """update_status() logs 'not implemented' at DEBUG."""
        with caplog.at_level(logging.DEBUG, logger="bmad_assist.tui.interactive"):
            renderer.update_status(RunnerState.RUNNING)
        assert any(
            "InteractiveRenderer.update_status: not implemented" in r.message
            for r in caplog.records
        )

    def test_stop_logs_debug(
        self, renderer: InteractiveRenderer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """stop() logs 'not implemented' at DEBUG."""
        with caplog.at_level(logging.DEBUG, logger="bmad_assist.tui.interactive"):
            renderer.stop()
        assert any(
            "InteractiveRenderer.stop: not implemented" in r.message
            for r in caplog.records
        )

    def test_render_phase_completed_logs_debug(
        self, renderer: InteractiveRenderer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """render_phase_completed() logs 'not implemented' at DEBUG."""
        with caplog.at_level(logging.DEBUG, logger="bmad_assist.tui.interactive"):
            renderer.render_phase_completed("dev_story", 2, "2.1", 42.0)
        assert any(
            "InteractiveRenderer.render_phase_completed: not implemented" in r.message
            for r in caplog.records
        )

    def test_set_log_level_logs_debug(
        self, renderer: InteractiveRenderer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """set_log_level() logs 'not implemented' at DEBUG when not wired."""
        with caplog.at_level(logging.DEBUG, logger="bmad_assist.tui.interactive"):
            renderer.set_log_level("INFO")
        assert any(
            "InteractiveRenderer.set_log_level: not implemented" in r.message
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# set_components() tests (AC #8, #9)
# ---------------------------------------------------------------------------


class TestSetComponents:
    def test_set_components_stores_layout(
        self, renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """set_components() stores layout reference."""
        renderer.set_components(mock_layout, mock_toggle)
        assert renderer._layout is mock_layout

    def test_set_components_stores_toggle(
        self, renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """set_components() stores log_toggle reference."""
        renderer.set_components(mock_layout, mock_toggle)
        assert renderer._log_level_toggle is mock_toggle


# ---------------------------------------------------------------------------
# render_log() filtering tests (AC #7, #9, #13)
# ---------------------------------------------------------------------------


class TestRenderLogFiltering:
    def test_warning_shown_at_warning_level(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() with WARNING level displays when filter is WARNING."""
        mock_toggle.get_level.return_value = "WARNING"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("WARNING", "test message", "test.logger", ts)
        mock_layout.write_log.assert_called_once()

    def test_info_suppressed_at_warning_level(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() with INFO level is suppressed when filter is WARNING."""
        mock_toggle.get_level.return_value = "WARNING"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("INFO", "test message", "test.logger", ts)
        mock_layout.write_log.assert_not_called()

    def test_debug_suppressed_at_warning_level(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() with DEBUG level is suppressed when filter is WARNING."""
        mock_toggle.get_level.return_value = "WARNING"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("DEBUG", "test message", "test.logger", ts)
        mock_layout.write_log.assert_not_called()

    def test_info_shown_at_info_level(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() with INFO level displays when filter is INFO."""
        mock_toggle.get_level.return_value = "INFO"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("INFO", "test message", "test.logger", ts)
        mock_layout.write_log.assert_called_once()

    def test_debug_suppressed_at_info_level(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() with DEBUG level is suppressed when filter is INFO."""
        mock_toggle.get_level.return_value = "INFO"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("DEBUG", "test message", "test.logger", ts)
        mock_layout.write_log.assert_not_called()

    def test_debug_shown_at_debug_level(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() with DEBUG level displays when filter is DEBUG."""
        mock_toggle.get_level.return_value = "DEBUG"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("DEBUG", "test message", "test.logger", ts)
        mock_layout.write_log.assert_called_once()

    def test_error_shown_at_warning_level(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() with ERROR level always displays (above all filter levels)."""
        mock_toggle.get_level.return_value = "WARNING"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("ERROR", "test error", "test.logger", ts)
        mock_layout.write_log.assert_called_once()


# ---------------------------------------------------------------------------
# render_log() format tests (AC #9)
# ---------------------------------------------------------------------------


class TestRenderLogFormat:
    def test_timestamp_format(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() formats timestamp as [HH:MM:SS]."""
        mock_toggle.get_level.return_value = "DEBUG"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("INFO", "hello world", "test.logger", ts)
        formatted = mock_layout.write_log.call_args[0][0]
        assert formatted.startswith("[11:22:33]")

    def test_level_padding_warning(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() pads WARNING to 8 chars."""
        mock_toggle.get_level.return_value = "DEBUG"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("WARNING", "msg", "test.logger", ts)
        formatted = mock_layout.write_log.call_args[0][0]
        assert "WARNING " in formatted

    def test_level_padding_info(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() pads INFO to 8 chars."""
        mock_toggle.get_level.return_value = "DEBUG"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("INFO", "msg", "test.logger", ts)
        formatted = mock_layout.write_log.call_args[0][0]
        assert "INFO    " in formatted

    def test_level_padding_debug(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() pads DEBUG to 8 chars."""
        mock_toggle.get_level.return_value = "DEBUG"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("DEBUG", "msg", "test.logger", ts)
        formatted = mock_layout.write_log.call_args[0][0]
        assert "DEBUG   " in formatted

    def test_full_format(
        self, wired_renderer: InteractiveRenderer, mock_layout: MagicMock, mock_toggle: MagicMock
    ) -> None:
        """render_log() produces full formatted output."""
        mock_toggle.get_level.return_value = "DEBUG"
        ts = datetime(2026, 2, 19, 11, 22, 33, tzinfo=UTC)
        wired_renderer.render_log("INFO", "test message", "test.logger", ts)
        formatted = mock_layout.write_log.call_args[0][0]
        assert formatted == "[11:22:33] INFO     test message"


# ---------------------------------------------------------------------------
# render_log() fallback tests (AC #9 - stub behavior preserved)
# ---------------------------------------------------------------------------


class TestRenderLogFallback:
    def test_fallback_when_not_wired(
        self, renderer: InteractiveRenderer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """render_log() falls back to debug log when components not wired."""
        with caplog.at_level(logging.DEBUG, logger="bmad_assist.tui.interactive"):
            renderer.render_log("INFO", "msg", "logger", datetime.now(UTC))
        assert any(
            "InteractiveRenderer.render_log: not implemented" in r.message
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# set_log_level() delegation tests (AC #8)
# ---------------------------------------------------------------------------


class TestSetLogLevelDelegation:
    def test_delegates_to_toggle(
        self, wired_renderer: InteractiveRenderer, mock_toggle: MagicMock
    ) -> None:
        """set_log_level() delegates to LogLevelToggle.set_level()."""
        wired_renderer.set_log_level("DEBUG")
        mock_toggle.set_level.assert_called_once_with("DEBUG")

    def test_delegates_info(
        self, wired_renderer: InteractiveRenderer, mock_toggle: MagicMock
    ) -> None:
        """set_log_level('INFO') delegates correctly."""
        wired_renderer.set_log_level("INFO")
        mock_toggle.set_level.assert_called_once_with("INFO")

    def test_fallback_when_not_wired(
        self, renderer: InteractiveRenderer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """set_log_level() falls back to debug log when toggle not wired."""
        with caplog.at_level(logging.DEBUG, logger="bmad_assist.tui.interactive"):
            renderer.set_log_level("INFO")
        assert any(
            "InteractiveRenderer.set_log_level: not implemented" in r.message
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# set_components() with 5-arg signature tests
# ---------------------------------------------------------------------------


class TestSetComponentsFiveArgs:
    """Test extended set_components() with optional status_bar, input_handler, pause_timer."""

    def test_five_arg_stores_all(self) -> None:
        """set_components() with 5 args stores all references."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)
        sb = MagicMock(spec=StatusBar)
        ih = MagicMock(spec=InputHandler)
        pt = MagicMock(spec=PauseTimer)

        r.set_components(layout, toggle, status_bar=sb, input_handler=ih, pause_timer=pt)

        assert r._layout is layout
        assert r._log_level_toggle is toggle
        assert r._status_bar is sb
        assert r._input_handler is ih
        assert r._pause_timer is pt

    def test_two_arg_backward_compat(self) -> None:
        """set_components() with 2 args works (backward compatible)."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)

        r.set_components(layout, toggle)

        assert r._layout is layout
        assert r._log_level_toggle is toggle
        assert r._status_bar is None
        assert r._input_handler is None
        assert r._pause_timer is None

    def test_partial_optional_args(self) -> None:
        """set_components() with some optional args."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)
        sb = MagicMock(spec=StatusBar)

        r.set_components(layout, toggle, status_bar=sb)

        assert r._status_bar is sb
        assert r._input_handler is None
        assert r._pause_timer is None


# ---------------------------------------------------------------------------
# start() with full components
# ---------------------------------------------------------------------------


class TestStartFullComponents:
    """Test start() calls all component .start() methods."""

    def test_start_calls_all_components(self) -> None:
        """start() calls layout, status_bar, input_handler, pause_timer start()."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)
        sb = MagicMock(spec=StatusBar)
        ih = MagicMock(spec=InputHandler)
        pt = MagicMock(spec=PauseTimer)

        r.set_components(layout, toggle, status_bar=sb, input_handler=ih, pause_timer=pt)
        r.start()

        layout.start.assert_called_once()
        sb.start.assert_called_once()
        ih.start.assert_called_once()
        pt.start.assert_called_once()

    def test_start_idempotent(self) -> None:
        """Second start() call is a no-op."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)
        sb = MagicMock(spec=StatusBar)

        r.set_components(layout, toggle, status_bar=sb)
        r.start()
        r.start()  # Second call

        layout.start.assert_called_once()
        sb.start.assert_called_once()

    def test_start_skips_none_components(self) -> None:
        """start() with only layout wired skips None components."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)

        r.set_components(layout, toggle)
        r.start()

        layout.start.assert_called_once()
        # No crash despite status_bar/input_handler/pause_timer being None


# ---------------------------------------------------------------------------
# stop() with full components
# ---------------------------------------------------------------------------


class TestStopFullComponents:
    """Test stop() in reverse order, idempotent."""

    def test_stop_calls_all_in_reverse(self) -> None:
        """stop() calls stop on components in reverse order of start."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)
        sb = MagicMock(spec=StatusBar)
        ih = MagicMock(spec=InputHandler)
        pt = MagicMock(spec=PauseTimer)

        r.set_components(layout, toggle, status_bar=sb, input_handler=ih, pause_timer=pt)
        r.start()
        r.stop()

        pt.stop.assert_called_once()
        ih.stop.assert_called_once()
        sb.stop.assert_called_once()
        layout.stop.assert_called_once()

    def test_stop_idempotent(self) -> None:
        """Double stop() does not crash or double-call components."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)
        sb = MagicMock(spec=StatusBar)

        r.set_components(layout, toggle, status_bar=sb)
        r.start()
        r.stop()
        r.stop()  # Second call — no-op

        layout.stop.assert_called_once()
        sb.stop.assert_called_once()

    def test_stop_handles_component_exception(self) -> None:
        """stop() continues even if a component raises."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)
        sb = MagicMock(spec=StatusBar)
        ih = MagicMock(spec=InputHandler)
        ih.stop.side_effect = RuntimeError("input cleanup failed")

        r.set_components(layout, toggle, status_bar=sb, input_handler=ih)
        r.start()
        r.stop()  # Should not raise

        sb.stop.assert_called_once()
        layout.stop.assert_called_once()


# ---------------------------------------------------------------------------
# render_phase_started() with full components
# ---------------------------------------------------------------------------


class TestRenderPhaseStartedFull:
    """Test render_phase_started() with StatusBar and LayoutManager wired."""

    def test_updates_status_bar(self) -> None:
        """render_phase_started() calls status_bar.set_phase_info()."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)
        sb = MagicMock(spec=StatusBar)

        r.set_components(layout, toggle, status_bar=sb)
        r.render_phase_started("dev_story", 15, "15.3")

        sb.set_phase_info.assert_called_once_with("dev_story", 15, "15.3")

    def test_writes_banner_to_layout(self) -> None:
        """render_phase_started() writes banner to layout.write_log()."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)

        r.set_components(layout, toggle)
        r.render_phase_started("create_story", 10, "10.1")

        layout.write_log.assert_called_once()
        banner = layout.write_log.call_args[0][0]
        assert "create_story" in banner
        assert "10" in banner


# ---------------------------------------------------------------------------
# render_phase_completed() with full components
# ---------------------------------------------------------------------------


class TestRenderPhaseCompletedFull:
    """Test render_phase_completed() with LayoutManager wired."""

    def test_writes_completion_to_layout(self) -> None:
        """render_phase_completed() writes completion message to layout."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)

        r.set_components(layout, toggle)
        r.render_phase_completed("dev_story", 15, "15.3", 125.0)

        layout.write_log.assert_called_once()
        msg = layout.write_log.call_args[0][0]
        assert "dev_story" in msg
        assert "2m 5s" in msg


# ---------------------------------------------------------------------------
# update_status() with full components
# ---------------------------------------------------------------------------


class TestUpdateStatusFull:
    """Test update_status() delegates to StatusBar."""

    def test_delegates_to_status_bar(self) -> None:
        """update_status() calls status_bar.set_runner_state()."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)
        sb = MagicMock(spec=StatusBar)

        r.set_components(layout, toggle, status_bar=sb)
        r.update_status(RunnerState.RUNNING)

        sb.set_runner_state.assert_called_once_with(RunnerState.RUNNING)

    def test_all_states(self) -> None:
        """update_status() works for all RunnerState values."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)
        sb = MagicMock(spec=StatusBar)

        r.set_components(layout, toggle, status_bar=sb)
        for state in RunnerState:
            r.update_status(state)

        assert sb.set_runner_state.call_count == len(RunnerState)


# ---------------------------------------------------------------------------
# reset() tests
# ---------------------------------------------------------------------------


class TestReset:
    """Test reset() clears all displayed state for reconnect hydration."""

    def test_reset_clears_status_bar(self) -> None:
        """reset() resets status bar phase, LLM count, paused state."""
        r = InteractiveRenderer()
        layout = MagicMock(spec=LayoutManager)
        toggle = MagicMock(spec=LogLevelToggle)
        sb = MagicMock(spec=StatusBar)

        r.set_components(layout, toggle, status_bar=sb)
        r.reset()

        sb.set_phase_info.assert_called_once_with("", 0, "")
        sb.set_llm_sessions.assert_called_once_with(0)
        sb.set_paused.assert_called_once_with(False)
        sb.set_pause_countdown.assert_called_once_with(None)

    def test_reset_no_status_bar(self) -> None:
        """reset() with no status bar does not crash."""
        r = InteractiveRenderer()
        r.reset()  # Should not raise
