"""Tests for tui/layout.py LayoutManager."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.tui.ansi import (
    clear_line,
    cursor_position,
    cursor_restore,
    cursor_save,
    cursor_show,
    reset_scroll_region,
    set_scroll_region,
)
from bmad_assist.tui.layout import LayoutManager


@pytest.fixture()
def mock_stdout() -> MagicMock:
    """Mock stdout with write and flush."""
    mock = MagicMock()
    mock.write = MagicMock()
    mock.flush = MagicMock()
    return mock


def _make_manager(mock_stdout: MagicMock, *, status_lines: int = 2) -> LayoutManager:
    """Create a LayoutManager wired to the mock stdout."""
    mgr = LayoutManager(status_lines=status_lines)
    mgr._stdout = mock_stdout
    return mgr


def _collect_output(mock_stdout: MagicMock) -> str:
    """Collect all write calls into a single string."""
    return "".join(c.args[0] for c in mock_stdout.write.call_args_list)


@pytest.fixture()
def layout(mock_stdout):
    """Create a LayoutManager wired to mock stdout, with terminal size 80x24."""
    with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
        mock_size.return_value = MagicMock(columns=80, lines=24)
        mgr = _make_manager(mock_stdout, status_lines=2)
        yield mgr
        if mgr._started:
            mgr.stop()


# --- start() tests ---


class TestStart:
    def test_start_sets_scroll_region(self, layout, mock_stdout) -> None:
        """start() writes DECSTBM with correct region bounds (rows 1 to H-2)."""
        layout.start()
        output = _collect_output(mock_stdout)
        assert set_scroll_region(1, 22) in output

    def test_start_stores_dimensions(self, mock_stdout) -> None:
        """start() stores terminal dimensions."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout)
            mgr.start()
            assert mgr._cols == 80
            assert mgr._rows == 24
            mgr.stop()

    def test_start_sets_started_flag(self, layout, mock_stdout) -> None:
        """start() sets _started to True."""
        assert not layout._started
        layout.start()
        assert layout._started

    def test_start_pushes_content_into_scrollback(self, layout, mock_stdout) -> None:
        """start() pushes existing terminal content into scrollback before scroll region."""
        layout.start()
        calls = mock_stdout.write.call_args_list
        # First write should be newlines to push content (24 lines for 80x24 terminal)
        first_write = calls[0].args[0]
        assert first_write == "\n" * 24
        # Second write contains the scroll region setup
        second_write = calls[1].args[0]
        assert set_scroll_region(1, 22) in second_write

    def test_start_clears_status_lines(self, layout, mock_stdout) -> None:
        """start() clears the reserved status lines."""
        layout.start()
        output = _collect_output(mock_stdout)
        assert cursor_position(23, 1) in output
        assert cursor_position(24, 1) in output
        assert clear_line() in output


# --- stop() tests ---


class TestStop:
    def test_stop_resets_scroll_region(self, layout, mock_stdout) -> None:
        """stop() resets scroll region to full screen."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.stop()
        output = _collect_output(mock_stdout)
        assert reset_scroll_region() in output

    def test_stop_shows_cursor(self, layout, mock_stdout) -> None:
        """stop() shows cursor."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.stop()
        output = _collect_output(mock_stdout)
        assert cursor_show() in output

    def test_stop_moves_cursor_to_bottom(self, layout, mock_stdout) -> None:
        """stop() moves cursor to last line."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.stop()
        output = _collect_output(mock_stdout)
        assert cursor_position(24, 1) in output

    def test_stop_is_idempotent(self, layout, mock_stdout) -> None:
        """Calling stop() twice does not crash."""
        layout.start()
        layout.stop()
        mock_stdout.write.reset_mock()
        layout.stop()
        mock_stdout.write.assert_not_called()

    def test_stop_sets_started_false(self, layout, mock_stdout) -> None:
        """stop() sets _started to False."""
        layout.start()
        assert layout._started
        layout.stop()
        assert not layout._started

    def test_stop_never_raises(self) -> None:
        """stop() is wrapped in try/except and never raises."""
        broken_stdout = MagicMock()
        broken_stdout.write.side_effect = OSError("stdout closed")

        mgr = LayoutManager()
        mgr._stdout = broken_stdout
        mgr._started = True
        mgr._rows = 24
        mgr._cols = 80
        mgr.stop()  # Should not raise


# --- write_log() tests ---


class TestWriteLog:
    def test_write_log_saves_restores_cursor(self, layout, mock_stdout) -> None:
        """write_log() wraps output in cursor save/restore."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.write_log("hello")
        output = _collect_output(mock_stdout)
        assert cursor_save() in output
        assert cursor_restore() in output
        assert output.index(cursor_save()) < output.index(cursor_restore())

    def test_write_log_positions_at_scroll_bottom(self, layout, mock_stdout) -> None:
        """write_log() moves cursor to bottom of scroll region."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.write_log("test line")
        output = _collect_output(mock_stdout)
        assert cursor_position(22, 1) in output

    def test_write_log_includes_text_and_newline(self, layout, mock_stdout) -> None:
        """write_log() writes text followed by newline."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.write_log("hello world")
        output = _collect_output(mock_stdout)
        assert "hello world\n" in output

    def test_write_log_multiline(self, layout, mock_stdout) -> None:
        """write_log() handles multi-line text by splitting on newline."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.write_log("line1\nline2\nline3")
        output = _collect_output(mock_stdout)
        assert "line1\n" in output
        assert "line2\n" in output
        assert "line3\n" in output

    def test_write_log_atomic(self, layout, mock_stdout) -> None:
        """write_log() writes all content in a single write call."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.write_log("test")
        assert mock_stdout.write.call_count == 1

    def test_write_log_truncates_long_lines(self, layout, mock_stdout) -> None:
        """write_log() truncates lines longer than terminal width to prevent overflow."""
        layout.start()
        mock_stdout.write.reset_mock()
        long_text = "x" * 200  # Way longer than 80-col terminal
        layout.write_log(long_text)
        output = _collect_output(mock_stdout)
        # Should not contain the full long text — it must be truncated
        assert long_text not in output
        # Should contain a truncated version ending with "..."
        assert "..." in output


# --- update_phase_elapsed() tests ---


class TestUpdatePhaseElapsed:
    def test_positions_at_correct_line(self, layout, mock_stdout) -> None:
        """update_phase_elapsed() writes to penultimate line (H-1)."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.update_phase_elapsed("13m 57s")
        output = _collect_output(mock_stdout)
        assert cursor_position(23, 1) in output

    def test_clears_line_first(self, layout, mock_stdout) -> None:
        """update_phase_elapsed() clears line before writing."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.update_phase_elapsed("test")
        output = _collect_output(mock_stdout)
        assert clear_line() in output
        assert output.index(clear_line()) < output.index("test")

    def test_truncates_to_terminal_width(self, layout, mock_stdout) -> None:
        """update_phase_elapsed() truncates text to terminal width."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.update_phase_elapsed("x" * 100)
        output = _collect_output(mock_stdout)
        assert "x" * 77 + "..." in output
        assert "x" * 100 not in output

    def test_atomic_write(self, layout, mock_stdout) -> None:
        """update_phase_elapsed() writes in single write call."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.update_phase_elapsed("elapsed")
        assert mock_stdout.write.call_count == 1


# --- update_status_bar() tests ---


class TestUpdateStatusBar:
    def test_positions_at_last_line(self, layout, mock_stdout) -> None:
        """update_status_bar() writes to last line (H)."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.update_status_bar("[p] pause / [s] stop")
        output = _collect_output(mock_stdout)
        assert cursor_position(24, 1) in output

    def test_clears_line_first(self, layout, mock_stdout) -> None:
        """update_status_bar() clears line before writing."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.update_status_bar("status")
        output = _collect_output(mock_stdout)
        assert clear_line() in output

    def test_truncates_to_terminal_width(self, layout, mock_stdout) -> None:
        """update_status_bar() truncates text to terminal width."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.update_status_bar("y" * 100)
        output = _collect_output(mock_stdout)
        assert "y" * 77 + "..." in output
        assert "y" * 100 not in output

    def test_atomic_write(self, layout, mock_stdout) -> None:
        """update_status_bar() writes in single write call."""
        layout.start()
        mock_stdout.write.reset_mock()
        layout.update_status_bar("status text")
        assert mock_stdout.write.call_count == 1


# --- Text truncation tests ---


class TestTruncation:
    def test_no_truncation_when_fits(self) -> None:
        """Text shorter than width is not truncated."""
        mgr = LayoutManager()
        assert mgr._truncate("hello", 80) == "hello"

    def test_truncation_with_ellipsis(self) -> None:
        """Text longer than width gets truncated with '...'."""
        mgr = LayoutManager()
        result = mgr._truncate("a" * 100, 80)
        assert len(result) == 80
        assert result.endswith("...")
        assert result == "a" * 77 + "..."

    def test_truncation_exact_width(self) -> None:
        """Text exactly at width is not truncated."""
        mgr = LayoutManager()
        assert mgr._truncate("x" * 80, 80) == "x" * 80

    def test_truncation_very_narrow(self) -> None:
        """Very narrow width (<=3) truncates without ellipsis."""
        mgr = LayoutManager()
        assert mgr._truncate("hello", 3) == "hel"
        assert mgr._truncate("hello", 1) == "h"

    def test_truncation_width_4(self) -> None:
        """Width=4 with long text gets 1 char + '...'."""
        mgr = LayoutManager()
        result = mgr._truncate("hello world", 4)
        assert result == "h..."
        assert len(result) == 4


# --- SIGWINCH resize tests ---


class TestResize:
    def test_sigwinch_handler_registered(self, mock_stdout) -> None:
        """start() registers SIGWINCH handler (Unix only)."""
        import signal

        with (
            patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size,
            patch("bmad_assist.tui.layout.signal.signal") as mock_signal,
        ):
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout)
            mgr.start()
            mock_signal.assert_any_call(signal.SIGWINCH, mgr._on_sigwinch)
            mgr.stop()

    def test_sigwinch_handler_restored_on_stop(self, mock_stdout) -> None:
        """stop() restores previous SIGWINCH handler."""
        import signal

        prev_handler = MagicMock()

        with (
            patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size,
            patch("bmad_assist.tui.layout.signal.signal", return_value=prev_handler) as mock_signal,
        ):
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout)
            mgr.start()
            mock_signal.reset_mock()
            mgr.stop()
            mock_signal.assert_any_call(signal.SIGWINCH, prev_handler)

    def test_on_sigwinch_sets_event(self) -> None:
        """SIGWINCH handler sets the resize event."""
        mgr = LayoutManager()
        assert not mgr._resize_event.is_set()
        mgr._on_sigwinch(0, None)
        assert mgr._resize_event.is_set()

    def test_check_resize_no_change(self, layout, mock_stdout) -> None:
        """check_resize() returns False when no resize happened."""
        layout.start()
        result = layout.check_resize()
        assert result is False

    def test_check_resize_after_event(self, mock_stdout) -> None:
        """check_resize() updates dimensions and re-sets scroll region on resize."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout, status_lines=2)
            mgr.start()

            # Simulate resize
            mock_size.return_value = MagicMock(columns=120, lines=40)
            mgr._resize_event.set()
            mock_stdout.write.reset_mock()

            result = mgr.check_resize()

            assert result is True
            assert mgr._cols == 120
            assert mgr._rows == 40

            output = _collect_output(mock_stdout)
            assert set_scroll_region(1, 38) in output

            mgr.stop()

    def test_check_resize_clears_event(self, mock_stdout) -> None:
        """check_resize() clears the resize event after processing."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout)
            mgr.start()
            mgr._resize_event.set()
            mgr.check_resize()
            assert not mgr._resize_event.is_set()
            mgr.stop()

    def test_check_resize_detects_size_change_without_event(self, mock_stdout) -> None:
        """check_resize() detects size change even without SIGWINCH event."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout, status_lines=2)
            mgr.start()

            mock_size.return_value = MagicMock(columns=100, lines=30)
            mock_stdout.write.reset_mock()

            result = mgr.check_resize()
            assert result is True
            assert mgr._cols == 100
            assert mgr._rows == 30

            mgr.stop()


# --- Custom status_lines tests ---


class TestCustomStatusLines:
    def test_three_status_lines(self, mock_stdout) -> None:
        """LayoutManager with 3 status lines sets scroll region to H-3."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout, status_lines=3)
            mgr.start()

            output = _collect_output(mock_stdout)
            assert set_scroll_region(1, 21) in output

            mgr.stop()


# --- Debug panel tests ---


class TestDebugPanel:
    def test_update_debug_panel_writes_below_status_bar(self, mock_stdout) -> None:
        """Debug panel lines appear below the status bar."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout, status_lines=2)
            mgr.start()
            mock_stdout.write.reset_mock()

            # With 2 debug lines: total_fixed=4, scroll=20, phase=21, status=22, debug=23,24
            mgr.update_debug_panel(["line-A", "line-B"])

            output = _collect_output(mock_stdout)
            # Scroll region should be recalculated to 1..20
            assert set_scroll_region(1, 20) in output
            # Debug lines at rows 23 and 24
            assert cursor_position(23, 1) in output
            assert cursor_position(24, 1) in output
            assert "line-A" in output
            assert "line-B" in output

            mgr.stop()

    def test_debug_panel_resizes_scroll_region(self, mock_stdout) -> None:
        """Debug panel changes scroll region when height changes."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout, status_lines=2)
            mgr.start()

            # No debug: scroll region = 1..22
            output = _collect_output(mock_stdout)
            assert set_scroll_region(1, 22) in output

            mock_stdout.write.reset_mock()
            mgr.update_debug_panel(["debug1"])

            # 1 debug line: scroll region = 1..21
            output = _collect_output(mock_stdout)
            assert set_scroll_region(1, 21) in output

            mock_stdout.write.reset_mock()
            mgr.update_debug_panel(["d1", "d2", "d3"])

            # 3 debug lines: scroll region = 1..19
            output = _collect_output(mock_stdout)
            assert set_scroll_region(1, 19) in output

            mgr.stop()

    def test_debug_panel_zero_lines_clears(self, mock_stdout) -> None:
        """Empty debug panel restores original scroll region."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout, status_lines=2)
            mgr.start()

            mgr.update_debug_panel(["debug1", "debug2"])
            mock_stdout.write.reset_mock()
            mgr.update_debug_panel([])

            # Back to original: scroll region = 1..22
            output = _collect_output(mock_stdout)
            assert set_scroll_region(1, 22) in output

            mgr.stop()

    def test_debug_panel_same_height_no_scroll_change(self, mock_stdout) -> None:
        """Same-height update doesn't recalculate scroll region."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout, status_lines=2)
            mgr.start()

            mgr.update_debug_panel(["line1"])
            mock_stdout.write.reset_mock()
            mgr.update_debug_panel(["updated"])

            output = _collect_output(mock_stdout)
            # No scroll region change
            assert set_scroll_region(1, 21) not in output
            # But content is updated
            assert "updated" in output

            mgr.stop()

    def test_check_resize_redraws_debug_panel(self, mock_stdout) -> None:
        """Resize redraws cached debug panel content."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout, status_lines=2)
            mgr.start()

            mgr.update_debug_panel(["cached-debug"])

            # Simulate resize
            mock_size.return_value = MagicMock(columns=120, lines=40)
            mgr._resize_event.set()
            mock_stdout.write.reset_mock()
            mgr.check_resize()

            output = _collect_output(mock_stdout)
            assert "cached-debug" in output

            mgr.stop()

    def test_stop_clears_debug_panel_lines(self, mock_stdout) -> None:
        """stop() clears debug panel lines too."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout, status_lines=2)
            mgr.start()

            mgr.update_debug_panel(["debug1", "debug2"])
            mock_stdout.write.reset_mock()
            mgr.stop()

            output = _collect_output(mock_stdout)
            # Should clear all 4 fixed lines (2 status + 2 debug)
            assert cursor_position(21, 1) in output
            assert cursor_position(22, 1) in output
            assert cursor_position(23, 1) in output
            assert cursor_position(24, 1) in output

    def test_status_bar_position_shifts_with_debug_panel(self, mock_stdout) -> None:
        """Status bar moves up when debug panel is active."""
        with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
            mock_size.return_value = MagicMock(columns=80, lines=24)
            mgr = _make_manager(mock_stdout, status_lines=2)
            mgr.start()

            mgr.update_debug_panel(["debug1", "debug2"])
            mock_stdout.write.reset_mock()
            mgr.update_status_bar("status text")

            output = _collect_output(mock_stdout)
            # Status bar at row 22 (24 - 2 debug lines)
            assert cursor_position(22, 1) in output

            mgr.stop()


# --- Thread safety tests ---


class TestThreadSafety:
    def test_has_lock(self) -> None:
        """LayoutManager has a threading.Lock."""
        mgr = LayoutManager()
        assert isinstance(mgr._lock, type(threading.Lock()))
