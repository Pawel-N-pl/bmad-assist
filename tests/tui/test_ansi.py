"""Tests for tui/ansi.py ANSI escape sequence helpers."""

from __future__ import annotations


def test_cursor_up() -> None:
    from bmad_assist.tui.ansi import cursor_up

    assert cursor_up(1) == "\033[1A"
    assert cursor_up(5) == "\033[5A"
    assert cursor_up(0) == "\033[0A"


def test_cursor_down() -> None:
    from bmad_assist.tui.ansi import cursor_down

    assert cursor_down(1) == "\033[1B"
    assert cursor_down(3) == "\033[3B"


def test_cursor_position() -> None:
    from bmad_assist.tui.ansi import cursor_position

    # 1-indexed: row=1, col=1 is top-left
    assert cursor_position(1, 1) == "\033[1;1H"
    assert cursor_position(5, 10) == "\033[5;10H"
    assert cursor_position(24, 80) == "\033[24;80H"


def test_cursor_home() -> None:
    from bmad_assist.tui.ansi import cursor_home

    assert cursor_home() == "\033[H"


def test_set_scroll_region() -> None:
    from bmad_assist.tui.ansi import set_scroll_region

    assert set_scroll_region(1, 22) == "\033[1;22r"
    assert set_scroll_region(1, 10) == "\033[1;10r"


def test_reset_scroll_region() -> None:
    from bmad_assist.tui.ansi import reset_scroll_region

    assert reset_scroll_region() == "\033[r"


def test_clear_line() -> None:
    from bmad_assist.tui.ansi import clear_line

    assert clear_line() == "\033[2K"


def test_clear_to_eol() -> None:
    from bmad_assist.tui.ansi import clear_to_eol

    assert clear_to_eol() == "\033[K"


def test_clear_screen() -> None:
    from bmad_assist.tui.ansi import clear_screen

    assert clear_screen() == "\033[2J"


def test_cursor_save_is_dec_variant() -> None:
    """DEC private variant ESC 7, NOT CSI s."""
    from bmad_assist.tui.ansi import cursor_save

    assert cursor_save() == "\0337"
    assert cursor_save() != "\033[s"  # Must NOT be CSI variant


def test_cursor_restore_is_dec_variant() -> None:
    """DEC private variant ESC 8, NOT CSI u."""
    from bmad_assist.tui.ansi import cursor_restore

    assert cursor_restore() == "\0338"
    assert cursor_restore() != "\033[u"  # Must NOT be CSI variant


def test_cursor_show() -> None:
    from bmad_assist.tui.ansi import cursor_show

    assert cursor_show() == "\033[?25h"


def test_cursor_hide() -> None:
    from bmad_assist.tui.ansi import cursor_hide

    assert cursor_hide() == "\033[?25l"


def test_all_functions_return_str() -> None:
    """All ANSI helpers return str, no side effects."""
    from bmad_assist.tui import ansi

    results = [
        ansi.cursor_up(1),
        ansi.cursor_down(1),
        ansi.cursor_position(1, 1),
        ansi.cursor_home(),
        ansi.set_scroll_region(1, 24),
        ansi.reset_scroll_region(),
        ansi.clear_line(),
        ansi.clear_to_eol(),
        ansi.clear_screen(),
        ansi.cursor_save(),
        ansi.cursor_restore(),
        ansi.cursor_show(),
        ansi.cursor_hide(),
    ]
    for result in results:
        assert isinstance(result, str)


def test_module_exports_all() -> None:
    """Module defines __all__ listing all exported functions."""
    from bmad_assist.tui import ansi

    assert hasattr(ansi, "__all__")
    expected = {
        "cursor_up",
        "cursor_down",
        "cursor_position",
        "cursor_home",
        "set_scroll_region",
        "reset_scroll_region",
        "clear_line",
        "clear_to_eol",
        "clear_screen",
        "cursor_save",
        "cursor_restore",
        "cursor_show",
        "cursor_hide",
    }
    assert set(ansi.__all__) == expected
