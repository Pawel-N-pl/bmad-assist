"""Terminal layout manager using ANSI escape sequences.

Manages a scrollable log region (top) and fixed status lines (bottom)
using DECSTBM scroll regions. Compatible with xterm.js.

All terminal I/O goes through a single threading.Lock for thread safety.
Does NOT use alternate screen buffer or cursor position queries.
"""

from __future__ import annotations

import shutil
import signal
import sys
import threading
from types import FrameType

from bmad_assist.tui.ansi import (
    clear_line,
    cursor_position,
    cursor_restore,
    cursor_save,
    cursor_show,
    reset_scroll_region,
    set_scroll_region,
)


class LayoutManager:
    """Manages terminal layout with scroll region and fixed status lines.

    Terminal layout:
        Row 1..H-N  : Scroll region (log output, auto-scrolls)
        Row H-N+1   : Phase elapsed line (first status line)
        ...
        Row H       : Status bar (last status line)

    Where H = terminal height, N = status_lines (default 2).

    Args:
        status_lines: Number of reserved bottom lines (default: 2).
    """

    def __init__(self, status_lines: int = 2) -> None:
        self._status_lines = status_lines
        self._lock = threading.Lock()
        self._rows: int = 0
        self._cols: int = 0
        self._started: bool = False
        self._resize_event = threading.Event()
        self._prev_sigwinch: signal.Handlers | None = None
        self._stdout = sys.stdout  # Captured at init for testability
        self._last_phase_text: str = ""
        self._last_status_text: str = ""
        self._debug_lines: int = 0
        self._last_debug_content: list[str] = []

    @property
    def _total_fixed(self) -> int:
        """Total fixed lines at bottom: status lines + debug panel."""
        return self._status_lines + self._debug_lines

    def start(self) -> None:
        """Set up the terminal layout.

        Queries terminal size, sets scroll region, clears status lines,
        and registers SIGWINCH handler. Safe to call multiple times —
        subsequent calls are no-ops to prevent SIGWINCH handler corruption.
        """
        if self._started:
            return

        size = shutil.get_terminal_size(fallback=(80, 24))
        self._cols = size.columns
        self._rows = size.lines

        # Guard against terminals too small for fixed lines
        if self._rows <= self._total_fixed:
            self._rows = self._total_fixed + 1

        scroll_bottom = self._rows - self._total_fixed

        # Push existing terminal content into scrollback so the TUI
        # starts with a clean visible area (old text preserved in scrollback).
        self._write("\n" * self._rows)

        # Build setup sequence
        buf = (
            set_scroll_region(1, scroll_bottom)
            + cursor_position(scroll_bottom, 1)  # Position at bottom of scroll region
        )

        # Clear all fixed lines (status + debug)
        for i in range(self._total_fixed):
            line = self._rows - self._total_fixed + 1 + i
            buf += cursor_position(line, 1) + clear_line()

        # Move cursor back to bottom of scroll region (ready for log output)
        buf += cursor_position(scroll_bottom, 1)

        self._write(buf)
        self._started = True

        # Register SIGWINCH handler (Unix only, main thread only)
        if hasattr(signal, "SIGWINCH"):
            try:
                self._prev_sigwinch = signal.signal(
                    signal.SIGWINCH, self._on_sigwinch
                )
            except (ValueError, OSError):
                pass  # Not main thread or signal not available

    def stop(self) -> None:
        """Restore terminal state.

        Resets scroll region, shows cursor, clears status lines.
        Safe to call multiple times (idempotent). Never raises.
        """
        if not self._started:
            return

        try:
            buf = (
                reset_scroll_region()
                + cursor_show()
            )

            # Clear all fixed lines (status + debug)
            for i in range(self._total_fixed):
                line = self._rows - self._total_fixed + 1 + i
                buf += cursor_position(line, 1) + clear_line()

            # Move cursor to bottom
            buf += cursor_position(self._rows, 1)

            self._write(buf)
        except (OSError, ValueError):
            pass  # stdout may be closed or broken pipe

        self._started = False

        # Restore previous SIGWINCH handler
        if self._prev_sigwinch is not None and hasattr(signal, "SIGWINCH"):
            try:
                signal.signal(signal.SIGWINCH, self._prev_sigwinch)
            except (ValueError, OSError):
                pass

    def write_log(self, text: str) -> None:
        """Write text to the scroll region.

        Saves cursor position, moves to bottom of scroll region,
        writes text with newline (triggers auto-scroll within region),
        then restores cursor. Multi-line text is split into lines and
        concatenated into a single atomic write to prevent interleaving.

        No-op if called before start().

        Args:
            text: Log text to write (may contain newlines).
        """
        if not self._started:
            return
        scroll_bottom = self._rows - self._total_fixed
        lines = text.splitlines()

        buf = cursor_save() + cursor_position(scroll_bottom, 1)
        for line in lines:
            buf += self._truncate(line, self._cols) + "\n"
        buf += cursor_restore()

        self._write(buf)

    def update_phase_elapsed(self, text: str) -> None:
        """Write to the phase-elapsed line (penultimate line).

        Clears the line first, then writes truncated text.
        No-op if called before start().

        Args:
            text: Phase elapsed text to display.
        """
        if not self._started:
            return
        self._last_phase_text = text
        line = self._rows - self._total_fixed + 1
        truncated = self._truncate(text, self._cols)

        buf = (
            cursor_save()
            + cursor_position(line, 1)
            + clear_line()
            + truncated
            + cursor_restore()
        )

        self._write(buf)

    def update_status_bar(self, text: str) -> None:
        """Write to the status bar line (last line).

        Clears the line first, then writes truncated text.
        No-op if called before start().

        Args:
            text: Status bar text to display.
        """
        if not self._started:
            return
        self._last_status_text = text
        line = self._rows - self._debug_lines
        truncated = self._truncate(text, self._cols)

        buf = (
            cursor_save()
            + cursor_position(line, 1)
            + clear_line()
            + truncated
            + cursor_restore()
        )

        self._write(buf)

    def check_resize(self) -> bool:
        """Check for terminal resize and adjust layout if needed.

        Should be called periodically from the main loop or a timer thread.
        Returns True if the terminal was resized. No-op if called before start().
        """
        if not self._started:
            return False

        size = shutil.get_terminal_size(fallback=(80, 24))
        new_cols = size.columns
        new_rows = size.lines

        resized = self._resize_event.is_set() or (
            new_cols != self._cols or new_rows != self._rows
        )

        if not resized:
            return False

        self._resize_event.clear()
        self._cols = new_cols
        self._rows = new_rows

        # Guard against terminals too small for fixed lines
        if self._rows <= self._total_fixed:
            self._rows = self._total_fixed + 1

        self._recalculate_layout()

        return True

    def update_debug_panel(self, lines: list[str]) -> None:
        """Update the debug session panel below the status bar.

        Dynamically resizes scroll region when panel height changes.
        Lines are written to fixed rows below the status bar.
        """
        if not self._started:
            return

        new_height = len(lines)
        self._last_debug_content = lines

        if new_height != self._debug_lines:
            self._debug_lines = new_height
            self._recalculate_layout()
            return

        # Same height — just update content
        for i, line_text in enumerate(lines):
            row = self._rows - self._debug_lines + 1 + i
            truncated = self._truncate(line_text, self._cols)
            buf = (
                cursor_save()
                + cursor_position(row, 1)
                + clear_line()
                + truncated
                + cursor_restore()
            )
            self._write(buf)

    def _recalculate_layout(self) -> None:
        """Recalculate scroll region and redraw all fixed lines."""
        if self._rows <= self._total_fixed:
            self._rows = self._total_fixed + 1

        scroll_bottom = self._rows - self._total_fixed
        buf = set_scroll_region(1, scroll_bottom)

        # Clear all fixed lines
        for i in range(self._total_fixed):
            line = scroll_bottom + 1 + i
            buf += cursor_position(line, 1) + clear_line()

        # Position cursor in scroll region
        buf += cursor_position(scroll_bottom, 1)
        self._write(buf)

        # Redraw cached content
        if self._last_phase_text:
            self.update_phase_elapsed(self._last_phase_text)
        if self._last_status_text:
            self.update_status_bar(self._last_status_text)
        for i, line_text in enumerate(self._last_debug_content):
            row = self._rows - self._debug_lines + 1 + i
            truncated = self._truncate(line_text, self._cols)
            buf = (
                cursor_save()
                + cursor_position(row, 1)
                + clear_line()
                + truncated
                + cursor_restore()
            )
            self._write(buf)

    def _truncate(self, text: str, width: int) -> str:
        """Truncate text to fit within width.

        If text exceeds width and width > 3, returns text[:width-3] + "...".
        If width <= 3, returns text[:width].

        Args:
            text: Text to truncate.
            width: Maximum width.

        Returns:
            Truncated text.
        """
        if len(text) <= width:
            return text
        if width > 3:
            return text[: width - 3] + "..."
        return text[:width]

    def _write(self, data: str) -> None:
        """Thread-safe write to stdout.

        Acquires lock, writes data, flushes. Single atomic operation.
        Silently handles broken pipe and I/O errors to prevent crashes.

        Args:
            data: String to write to stdout.
        """
        with self._lock:
            try:
                self._stdout.write(data)
                self._stdout.flush()
            except (OSError, ValueError):
                pass  # stdout closed or broken pipe

    def _on_sigwinch(self, signum: int, frame: FrameType | None) -> None:
        """SIGWINCH signal handler. Only sets flag — no I/O, no locks."""
        self._resize_event.set()


# --- Manual test script ---

if __name__ == "__main__":
    import time

    if "--test" not in sys.argv:
        print("Usage: python -m bmad_assist.tui.layout --test")
        sys.exit(1)

    layout = LayoutManager(status_lines=2)
    print("Starting layout manager demo (10 seconds or Ctrl+C)...")
    layout.start()

    try:
        start_time = time.monotonic()
        line_num = 0

        while time.monotonic() - start_time < 10:
            # Check for resize
            if layout.check_resize():
                layout.write_log(f"Resized to {layout._cols}x{layout._rows}")

            # Write log lines
            line_num += 1
            layout.write_log(f"[{line_num:04d}] Log message at {time.monotonic() - start_time:.1f}s")

            # Update status lines
            elapsed = time.monotonic() - start_time
            mins = int(elapsed) // 60
            secs = int(elapsed) % 60
            layout.update_phase_elapsed(f"  Phase elapsed: {mins}m {secs:02d}s")
            layout.update_status_bar("  [p] pause / [s] stop / [q] quit / [+/-] log level")

            time.sleep(0.5)

    except KeyboardInterrupt:
        pass
    finally:
        layout.stop()
        print("\nLayout manager stopped cleanly.")
