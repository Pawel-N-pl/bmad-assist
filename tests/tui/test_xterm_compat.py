"""xterm.js compatibility verification tests for TUI ANSI sequences.

Validates that all ANSI escape sequences emitted by tui/ansi.py and consumed
by tui/layout.py match xterm.js 5.3.0 supported formats. Pure unit tests —
no browser or terminal required.

Story 30.7: xterm.js Compatibility Testing
"""

from __future__ import annotations

import inspect
import re
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.tui import ansi
from bmad_assist.tui.ansi import (
    clear_line,
    clear_screen,
    clear_to_eol,
    cursor_down,
    cursor_hide,
    cursor_home,
    cursor_position,
    cursor_restore,
    cursor_save,
    cursor_show,
    cursor_up,
    reset_scroll_region,
    set_scroll_region,
)
from bmad_assist.tui.layout import LayoutManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_output(mock_stdout: MagicMock) -> str:
    """Collect all write calls into a single string."""
    return "".join(c.args[0] for c in mock_stdout.write.call_args_list)


def _make_started_layout(mock_stdout: MagicMock, rows: int = 24, cols: int = 80) -> LayoutManager:
    """Create a LayoutManager wired to mock stdout, already started."""
    with patch("bmad_assist.tui.layout.shutil.get_terminal_size") as mock_size:
        mock_size.return_value = MagicMock(columns=cols, lines=rows)
        mgr = LayoutManager(status_lines=2)
        mgr._stdout = mock_stdout
        mgr.start()
        assert mgr._started, "LayoutManager.start() failed — tests will be invalid"
    return mgr


# ===========================================================================
# AC#3: Verify every sequence in ansi.py starts with ESC
# ===========================================================================


class TestAllSequencesStartWithEsc:
    """Every ansi.py function output must start with ESC (\\033)."""

    @pytest.mark.parametrize(
        "func,args",
        [
            (cursor_up, (1,)),
            (cursor_down, (1,)),
            (cursor_position, (1, 1)),
            (cursor_home, ()),
            (set_scroll_region, (1, 22)),
            (reset_scroll_region, ()),
            (clear_line, ()),
            (clear_to_eol, ()),
            (clear_screen, ()),
            (cursor_save, ()),
            (cursor_restore, ()),
            (cursor_show, ()),
            (cursor_hide, ()),
        ],
    )
    def test_sequence_starts_with_esc(self, func, args) -> None:
        result = func(*args)
        assert result.startswith("\033"), (
            f"{func.__name__} output does not start with ESC: {result!r}"
        )


# ===========================================================================
# AC#3: Verify DEC private variants used (ESC 7/8), NOT CSI variants (CSI s/u)
# ===========================================================================


class TestDecPrivateVariants:
    """Critical: cursor_save/restore must use DEC variants for xterm.js."""

    def test_cursor_save_is_dec_variant(self) -> None:
        """cursor_save() must return ESC 7 (DECSC), NOT CSI s (SCOSC)."""
        result = cursor_save()
        assert result == "\0337", f"Expected DECSC (ESC 7), got {result!r}"
        assert result != "\033[s", "Must NOT use CSI s — partial xterm.js support"

    def test_cursor_restore_is_dec_variant(self) -> None:
        """cursor_restore() must return ESC 8 (DECRC), NOT CSI u (SCORC)."""
        result = cursor_restore()
        assert result == "\0338", f"Expected DECRC (ESC 8), got {result!r}"
        assert result != "\033[u", "Must NOT use CSI u — partial xterm.js support"


# ===========================================================================
# AC#3: Verify scroll region sequence format
# ===========================================================================


class TestScrollRegionFormat:
    """set_scroll_region must produce \\033[{top};{bottom}r with 1-indexed params."""

    def test_basic_scroll_region(self) -> None:
        result = set_scroll_region(1, 22)
        assert result == "\033[1;22r"

    def test_scroll_region_format_pattern(self) -> None:
        """Output matches DECSTBM pattern: ESC [ top ; bottom r."""
        result = set_scroll_region(5, 40)
        assert re.match(r"\033\[\d+;\d+r$", result), f"Bad format: {result!r}"

    def test_reset_scroll_region_bare(self) -> None:
        """reset_scroll_region() produces bare \\033[r (no params)."""
        result = reset_scroll_region()
        assert result == "\033[r"


# ===========================================================================
# AC#3: Verify no forbidden sequences in ansi.py
# ===========================================================================


class TestNoForbiddenSequences:
    """ansi.py must not contain alternate screen buffer or cursor query sequences."""

    def test_no_alternate_screen_buffer(self) -> None:
        """No \\033[?1049h or \\033[?1049l (alternate screen) in any export."""
        source = inspect.getsource(ansi)
        assert "\\033[?1049" not in source, (
            "ansi.py must not use alternate screen buffer — breaks terminal history"
        )
        assert "\033[?1049" not in source

    def test_no_cursor_position_query(self) -> None:
        """No \\033[6n (cursor position query) in any export."""
        source = inspect.getsource(ansi)
        assert "\\033[6n" not in source, (
            "ansi.py must not use cursor position query — async response issues in xterm.js"
        )
        assert "\033[6n" not in source

    def test_no_csi_s_u_in_exports(self) -> None:
        """No CSI s or CSI u sequences returned by any exported function."""
        all_outputs: list[str] = []
        for name in ansi.__all__:
            func = getattr(ansi, name)
            sig = inspect.signature(func)
            # Build minimal args
            args = []
            for param in sig.parameters.values():
                if param.default is inspect.Parameter.empty:
                    args.append(1)
            all_outputs.append(func(*args))

        combined = "".join(all_outputs)
        assert "\033[s" not in combined, "Found CSI s (SCOSC) — must use DECSC instead"
        assert "\033[u" not in combined, "Found CSI u (SCORC) — must use DECRC instead"


# ===========================================================================
# AC#3: Verify LayoutManager.write_log() output structure
# ===========================================================================


class TestWriteLogXtermCompat:
    """write_log() must produce xterm.js-renderable output:
    save -> position -> content+newline -> restore.
    """

    def test_output_structure(self) -> None:
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout)
        mock_stdout.write.reset_mock()

        mgr.write_log("test message")
        output = _collect_output(mock_stdout)

        # Verify structural elements present
        assert "\0337" in output, "Missing DECSC (cursor save)"
        assert "\0338" in output, "Missing DECRC (cursor restore)"
        assert "test message\n" in output, "Missing content with newline"

        # Verify ordering: save before content, content before restore
        save_idx = output.index("\0337")
        content_idx = output.index("test message\n")
        restore_idx = output.index("\0338")
        assert save_idx < content_idx < restore_idx, (
            f"Wrong order: save@{save_idx}, content@{content_idx}, restore@{restore_idx}"
        )

        mgr.stop()

    def test_positions_at_scroll_bottom(self) -> None:
        """write_log() positions cursor at bottom of scroll region (row H-2)."""
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout, rows=24)
        mock_stdout.write.reset_mock()

        mgr.write_log("line")
        output = _collect_output(mock_stdout)

        # Scroll bottom = rows - status_lines = 24 - 2 = 22
        assert cursor_position(22, 1) in output

        mgr.stop()


# ===========================================================================
# AC#3: Verify LayoutManager.update_status_bar() output structure
# ===========================================================================


class TestUpdateStatusBarXtermCompat:
    """update_status_bar() must produce xterm.js-renderable output:
    save -> position -> clear_line -> content -> restore.
    """

    def test_output_structure(self) -> None:
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout)
        mock_stdout.write.reset_mock()

        mgr.update_status_bar("[p] pause / [s] stop")
        output = _collect_output(mock_stdout)

        # Verify all structural elements
        assert "\0337" in output, "Missing DECSC"
        assert "\0338" in output, "Missing DECRC"
        assert "\033[2K" in output, "Missing EL 2 (clear line)"
        assert "[p] pause / [s] stop" in output

        # Verify ordering: save -> position -> clear -> content -> restore
        save_idx = output.index("\0337")
        clear_idx = output.index("\033[2K")
        content_idx = output.index("[p] pause / [s] stop")
        restore_idx = output.index("\0338")
        assert save_idx < clear_idx < content_idx < restore_idx

        mgr.stop()

    def test_positions_at_last_line(self) -> None:
        """update_status_bar() writes to last line (row H)."""
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout, rows=24)
        mock_stdout.write.reset_mock()

        mgr.update_status_bar("status")
        output = _collect_output(mock_stdout)

        assert cursor_position(24, 1) in output

        mgr.stop()


# ===========================================================================
# AC#3: Verify LayoutManager.update_phase_elapsed() output structure
# ===========================================================================


class TestUpdatePhaseElapsedXtermCompat:
    """update_phase_elapsed() must produce xterm.js-renderable output:
    save -> position -> clear_line -> content -> restore.
    """

    def test_output_structure(self) -> None:
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout)
        mock_stdout.write.reset_mock()

        mgr.update_phase_elapsed("Phase: 5m 30s")
        output = _collect_output(mock_stdout)

        # Verify structural elements
        assert "\0337" in output, "Missing DECSC"
        assert "\0338" in output, "Missing DECRC"
        assert "\033[2K" in output, "Missing EL 2 (clear line)"
        assert "Phase: 5m 30s" in output

        # Verify ordering
        save_idx = output.index("\0337")
        clear_idx = output.index("\033[2K")
        content_idx = output.index("Phase: 5m 30s")
        restore_idx = output.index("\0338")
        assert save_idx < clear_idx < content_idx < restore_idx

        mgr.stop()

    def test_positions_at_penultimate_line(self) -> None:
        """update_phase_elapsed() writes to penultimate line (row H-1)."""
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout, rows=24)
        mock_stdout.write.reset_mock()

        mgr.update_phase_elapsed("elapsed")
        output = _collect_output(mock_stdout)

        # Penultimate = rows - status_lines + 1 = 24 - 2 + 1 = 23
        assert cursor_position(23, 1) in output

        mgr.stop()


# ===========================================================================
# AC#3: Verify LayoutManager.start() sets scroll region with DECSTBM
# ===========================================================================


class TestStartScrollRegion:
    """start() must set scroll region using DECSTBM."""

    def test_start_emits_decstbm(self) -> None:
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout, rows=24)
        output = _collect_output(mock_stdout)

        # scroll_bottom = 24 - 2 = 22
        assert "\033[1;22r" in output, (
            "start() must emit DECSTBM \\033[1;{scroll_bottom}r"
        )

        mgr.stop()

    def test_start_custom_rows(self) -> None:
        """Verify scroll region adapts to terminal height."""
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout, rows=40)
        output = _collect_output(mock_stdout)

        # scroll_bottom = 40 - 2 = 38
        assert "\033[1;38r" in output

        mgr.stop()


# ===========================================================================
# AC#3: Verify LayoutManager.stop() resets scroll region
# ===========================================================================


class TestStopScrollRegion:
    """stop() must reset scroll region using bare DECSTBM."""

    def test_stop_emits_reset(self) -> None:
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout, rows=24)
        mock_stdout.write.reset_mock()

        mgr.stop()
        output = _collect_output(mock_stdout)

        assert "\033[r" in output, "stop() must emit \\033[r (reset scroll region)"


# ===========================================================================
# Additional xterm.js compatibility verifications
# ===========================================================================


class TestAdditionalCompat:
    """Additional compatibility checks for xterm.js rendering."""

    def test_write_log_single_atomic_write(self) -> None:
        """write_log() emits single write() call — avoids interleaved rendering."""
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout)
        mock_stdout.write.reset_mock()

        mgr.write_log("atomic test")
        assert mock_stdout.write.call_count == 1, (
            "write_log must use single atomic write to prevent xterm.js interleaving"
        )

        mgr.stop()

    def test_status_bar_single_atomic_write(self) -> None:
        """update_status_bar() emits single write() call."""
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout)
        mock_stdout.write.reset_mock()

        mgr.update_status_bar("atomic status")
        assert mock_stdout.write.call_count == 1

        mgr.stop()

    def test_phase_elapsed_single_atomic_write(self) -> None:
        """update_phase_elapsed() emits single write() call."""
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout)
        mock_stdout.write.reset_mock()

        mgr.update_phase_elapsed("atomic elapsed")
        assert mock_stdout.write.call_count == 1

        mgr.stop()

    def test_multiline_write_log_still_atomic(self) -> None:
        """Multi-line write_log() is still a single write() call."""
        mock_stdout = MagicMock()
        mgr = _make_started_layout(mock_stdout)
        mock_stdout.write.reset_mock()

        mgr.write_log("line1\nline2\nline3")
        assert mock_stdout.write.call_count == 1

        mgr.stop()

    def test_all_ansi_exports_count(self) -> None:
        """ansi.py exports exactly 13 functions — matches test matrix."""
        assert len(ansi.__all__) == 13, (
            f"Expected 13 exports, got {len(ansi.__all__)}. "
            "Update test matrix if ansi.py adds new sequences."
        )
