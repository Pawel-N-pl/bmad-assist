"""ANSI escape sequence helpers for terminal control.

Pure-function string generators — no I/O, no side effects.
All functions return escape sequence strings for xterm.js-compatible terminals.

Uses DEC private variants for cursor save/restore (ESC 7 / ESC 8)
instead of CSI s/u which have only partial xterm.js support.
"""

from __future__ import annotations

__all__ = [
    "clear_line",
    "clear_screen",
    "clear_to_eol",
    "cursor_down",
    "cursor_hide",
    "cursor_home",
    "cursor_position",
    "cursor_restore",
    "cursor_save",
    "cursor_show",
    "cursor_up",
    "reset_scroll_region",
    "set_scroll_region",
]


def cursor_up(n: int) -> str:
    """Move cursor up n lines (CUU)."""
    return f"\033[{n}A"


def cursor_down(n: int) -> str:
    """Move cursor down n lines (CUD)."""
    return f"\033[{n}B"


def cursor_position(row: int, col: int) -> str:
    """Move cursor to row, col (CUP). 1-indexed."""
    return f"\033[{row};{col}H"


def cursor_home() -> str:
    """Move cursor to top-left (1,1)."""
    return "\033[H"


def set_scroll_region(top: int, bottom: int) -> str:
    """Set scroll region (DECSTBM). 1-indexed, inclusive.

    Note: Setting scroll region always moves cursor to position (1,1).
    You must explicitly reposition the cursor after calling this.
    """
    return f"\033[{top};{bottom}r"


def reset_scroll_region() -> str:
    """Reset scroll region to full screen."""
    return "\033[r"


def clear_line() -> str:
    """Clear entire current line (EL 2)."""
    return "\033[2K"


def clear_to_eol() -> str:
    """Clear from cursor to end of line (EL 0)."""
    return "\033[K"


def clear_screen() -> str:
    """Clear entire screen (ED 2)."""
    return "\033[2J"


def cursor_save() -> str:
    """Save cursor position (DECSC — DEC private variant).

    Uses ESC 7 (not CSI s) for full xterm.js compatibility.
    """
    return "\0337"


def cursor_restore() -> str:
    """Restore cursor position (DECRC — DEC private variant).

    Uses ESC 8 (not CSI u) for full xterm.js compatibility.
    """
    return "\0338"


def cursor_show() -> str:
    """Show cursor (DECTCEM)."""
    return "\033[?25h"


def cursor_hide() -> str:
    """Hide cursor (DECTCEM)."""
    return "\033[?25l"
