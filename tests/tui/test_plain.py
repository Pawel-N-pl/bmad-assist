"""Tests for PlainRenderer implementation."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.ipc.types import RunnerState
from bmad_assist.tui.plain import PlainRenderer


@pytest.fixture
def renderer() -> PlainRenderer:
    """Create a PlainRenderer instance."""
    return PlainRenderer()


class TestStartStop:
    """Test start/stop are no-ops."""

    def test_start_is_noop(self, renderer: PlainRenderer) -> None:
        """start() completes without error."""
        renderer.start()  # Should not raise

    def test_stop_is_noop(self, renderer: PlainRenderer) -> None:
        """stop() completes without error."""
        renderer.stop()  # Should not raise


class TestUpdateStatus:
    """Test update_status is a no-op."""

    def test_update_status_is_noop(self, renderer: PlainRenderer) -> None:
        """update_status() completes without error for all states."""
        for state in RunnerState:
            renderer.update_status(state)  # Should not raise


class TestRenderLog:
    """Test render_log delegates to Python logging."""

    def test_render_log_info(self, renderer: PlainRenderer, caplog: pytest.LogCaptureFixture) -> None:
        """render_log at INFO level produces a log record."""
        ts = datetime.now(UTC)
        with caplog.at_level(logging.INFO, logger="test.logger"):
            renderer.render_log("INFO", "test message", "test.logger", ts)

        assert len(caplog.records) == 1
        assert caplog.records[0].message == "test message"
        assert caplog.records[0].levelno == logging.INFO

    def test_render_log_warning(self, renderer: PlainRenderer, caplog: pytest.LogCaptureFixture) -> None:
        """render_log at WARNING level produces a warning record."""
        ts = datetime.now(UTC)
        with caplog.at_level(logging.WARNING, logger="test.warn"):
            renderer.render_log("WARNING", "warn msg", "test.warn", ts)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING

    def test_render_log_debug(self, renderer: PlainRenderer, caplog: pytest.LogCaptureFixture) -> None:
        """render_log at DEBUG level produces a debug record."""
        ts = datetime.now(UTC)
        with caplog.at_level(logging.DEBUG, logger="test.debug"):
            renderer.render_log("DEBUG", "debug msg", "test.debug", ts)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.DEBUG

    def test_render_log_unknown_level_defaults_to_info(
        self, renderer: PlainRenderer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """render_log with unknown level falls back to INFO."""
        ts = datetime.now(UTC)
        with caplog.at_level(logging.DEBUG, logger="test.unknown"):
            renderer.render_log("BOGUS", "fallback msg", "test.unknown", ts)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.INFO

    def test_render_log_ignores_timestamp(
        self, renderer: PlainRenderer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """render_log does not use the provided timestamp (Python logging manages its own)."""
        old_ts = datetime(2020, 1, 1, tzinfo=UTC)
        with caplog.at_level(logging.INFO, logger="test.ts"):
            renderer.render_log("INFO", "ts test", "test.ts", old_ts)

        # The log record's created time should be recent, not 2020
        assert caplog.records[0].created > datetime(2025, 1, 1, tzinfo=UTC).timestamp()


class TestRenderPhaseStarted:
    """Test render_phase_started produces correct banner format."""

    def test_banner_format_numeric_epic(self, renderer: PlainRenderer) -> None:
        """Banner matches _print_phase_banner format with numeric epic."""
        with patch("bmad_assist.tui.plain.console") as mock_console:
            renderer.render_phase_started("create_story", 1, "1.1")
            mock_console.print.assert_called_once_with(
                "[CREATE STORY] Epic 1 Story 1.1",
                style="bold bright_white",
            )

    def test_banner_format_string_epic(self, renderer: PlainRenderer) -> None:
        """Banner handles string epic IDs."""
        with patch("bmad_assist.tui.plain.console") as mock_console:
            renderer.render_phase_started("dev_story", "testarch", "T.1")
            mock_console.print.assert_called_once_with(
                "[DEV STORY] Epic testarch Story T.1",
                style="bold bright_white",
            )

    def test_banner_underscore_to_space(self, renderer: PlainRenderer) -> None:
        """Phase names with underscores are converted to spaces."""
        with patch("bmad_assist.tui.plain.console") as mock_console:
            renderer.render_phase_started("validate_story_synthesis", 2, "2.3")
            mock_console.print.assert_called_once_with(
                "[VALIDATE STORY SYNTHESIS] Epic 2 Story 2.3",
                style="bold bright_white",
            )

    def test_banner_fallback_on_console_error(self, renderer: PlainRenderer) -> None:
        """Falls back to print() when console.print raises."""
        with patch("bmad_assist.tui.plain.console") as mock_console:
            mock_console.print.side_effect = RuntimeError("console broken")
            with patch("builtins.print") as mock_print:
                renderer.render_phase_started("code_review", 3, "3.1")
                mock_print.assert_called_once_with("[CODE REVIEW] Epic 3 Story 3.1")


class TestRenderPhaseCompleted:
    """Test render_phase_completed formats duration correctly."""

    def test_seconds_only(self, renderer: PlainRenderer, caplog: pytest.LogCaptureFixture) -> None:
        """Short durations format as seconds with epic/story context."""
        with caplog.at_level(logging.INFO, logger="bmad_assist.tui.plain"):
            renderer.render_phase_completed("create_story", 1, "1.1", 42.0)

        assert len(caplog.records) == 1
        assert "[CREATE STORY] Epic 1 Story 1.1 completed in 42s" in caplog.records[0].message

    def test_minutes_and_seconds(self, renderer: PlainRenderer, caplog: pytest.LogCaptureFixture) -> None:
        """Medium durations format as Xm Ys."""
        with caplog.at_level(logging.INFO, logger="bmad_assist.tui.plain"):
            renderer.render_phase_completed("dev_story", 2, "2.1", 444.0)

        assert "[DEV STORY] Epic 2 Story 2.1 completed in 7m 24s" in caplog.records[0].message

    def test_hours_minutes_seconds(self, renderer: PlainRenderer, caplog: pytest.LogCaptureFixture) -> None:
        """Long durations format as Xh Ym Zs."""
        with caplog.at_level(logging.INFO, logger="bmad_assist.tui.plain"):
            renderer.render_phase_completed("code_review", 3, "3.1", 4437.0)

        assert "[CODE REVIEW] Epic 3 Story 3.1 completed in 1h 13m 57s" in caplog.records[0].message

    def test_zero_duration(self, renderer: PlainRenderer, caplog: pytest.LogCaptureFixture) -> None:
        """Zero duration formats correctly."""
        with caplog.at_level(logging.INFO, logger="bmad_assist.tui.plain"):
            renderer.render_phase_completed("create_story", 1, "1.1", 0.0)

        assert "[CREATE STORY] Epic 1 Story 1.1 completed in 0s" in caplog.records[0].message


class TestSetLogLevel:
    """Test set_log_level delegates to update_log_level."""

    def test_set_log_level_delegates(self, renderer: PlainRenderer) -> None:
        """set_log_level calls update_log_level from cli_utils."""
        with patch("bmad_assist.tui.plain.update_log_level") as mock_update:
            renderer.set_log_level("DEBUG")
            mock_update.assert_called_once_with("DEBUG")

    def test_set_log_level_changes_root_and_handlers(self, renderer: PlainRenderer) -> None:
        """set_log_level actually changes the root logger level AND handler levels."""
        import bmad_assist.cli_utils as _cu

        # Reset global state to ensure test isolation regardless of prior calls
        original_global_level = _cu._current_log_level
        _cu._current_log_level = "WARNING"

        root = logging.getLogger()
        original_level = root.level

        # Add a handler to verify it gets updated too
        test_handler = logging.StreamHandler()
        test_handler.setLevel(logging.WARNING)
        root.addHandler(test_handler)

        try:
            renderer.set_log_level("DEBUG")

            # Root logger should be at DEBUG
            assert root.level == logging.DEBUG

            # All handlers should also be at DEBUG
            for handler in root.handlers:
                assert handler.level == logging.DEBUG
        finally:
            root.removeHandler(test_handler)
            # Restore original level
            root.setLevel(original_level)
            for handler in root.handlers:
                handler.setLevel(original_level)
            # Restore global state
            _cu._current_log_level = original_global_level
