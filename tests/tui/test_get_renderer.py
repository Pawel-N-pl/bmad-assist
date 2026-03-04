"""Tests for get_renderer() factory function and TTY detection."""

from __future__ import annotations

from unittest.mock import patch

from bmad_assist.tui import InteractiveRenderer, PlainRenderer, get_renderer


class TestGetRendererPlainFlag:
    """Test get_renderer with plain=True."""

    def test_plain_true_returns_plain_renderer(self) -> None:
        """plain=True always returns PlainRenderer."""
        renderer = get_renderer(plain=True)
        assert isinstance(renderer, PlainRenderer)

    def test_plain_true_ignores_tty(self) -> None:
        """plain=True returns PlainRenderer and never checks isatty()."""
        # plain=True short-circuits before TTY check
        renderer = get_renderer(plain=True)
        assert isinstance(renderer, PlainRenderer)
        # Verify isatty() is never called when plain=True
        with patch("bmad_assist.tui.sys") as mock_sys:
            get_renderer(plain=True)
            mock_sys.stdout.isatty.assert_not_called()


class TestGetRendererTTYDetection:
    """Test get_renderer TTY auto-detection."""

    def test_non_tty_returns_plain(self) -> None:
        """Non-TTY stdout (CI, pipes) returns PlainRenderer."""
        with patch("bmad_assist.tui.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = False
            renderer = get_renderer()
            assert isinstance(renderer, PlainRenderer)

    def test_tty_returns_interactive(self) -> None:
        """TTY stdout returns InteractiveRenderer."""
        with patch("bmad_assist.tui.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = True
            renderer = get_renderer()
            assert isinstance(renderer, InteractiveRenderer)

    def test_plain_false_with_tty(self) -> None:
        """Explicit plain=False with TTY returns InteractiveRenderer."""
        with patch("bmad_assist.tui.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = True
            renderer = get_renderer(plain=False)
            assert isinstance(renderer, InteractiveRenderer)

    def test_plain_false_without_tty(self) -> None:
        """Explicit plain=False without TTY returns PlainRenderer."""
        with patch("bmad_assist.tui.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = False
            renderer = get_renderer(plain=False)
            assert isinstance(renderer, PlainRenderer)

    def test_none_stdout_returns_plain(self) -> None:
        """None stdout (GUI apps) returns PlainRenderer without crash."""
        with patch("bmad_assist.tui.sys") as mock_sys:
            mock_sys.stdout = None
            renderer = get_renderer()
            assert isinstance(renderer, PlainRenderer)


class TestGetRendererReturnTypes:
    """Test return type guarantees."""

    def test_returns_new_instance_each_call(self) -> None:
        """get_renderer creates a new instance each call (no singleton)."""
        r1 = get_renderer(plain=True)
        r2 = get_renderer(plain=True)
        assert r1 is not r2
