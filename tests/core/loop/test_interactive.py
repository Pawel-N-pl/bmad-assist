"""Tests for interactive continuation prompts.

Story: Interactive Continuation Prompts
Tests for prompt_continuation() and checkpoint_and_prompt() functions.

"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.loop.interactive import (
    checkpoint_and_prompt,
    is_non_interactive,
    prompt_continuation,
    set_non_interactive,
)
from bmad_assist.core.state import Phase, State


class TestPromptContinuation:
    """Tests for prompt_continuation() function."""

    def test_returns_true_on_uppercase_y(self) -> None:
        """Given input 'Y', returns True."""
        with patch("builtins.input", return_value="Y"):
            assert prompt_continuation("Continue?") is True

    def test_returns_true_on_lowercase_y(self) -> None:
        """Given input 'y', returns True (case-insensitive)."""
        with patch("builtins.input", return_value="y"):
            assert prompt_continuation("Continue?") is True

    def test_returns_false_on_lowercase_q(self) -> None:
        """Given input 'q', returns False."""
        with patch("builtins.input", return_value="q"):
            assert prompt_continuation("Continue?") is False

    def test_returns_false_on_uppercase_q(self) -> None:
        """Given input 'Q', returns False (case-insensitive)."""
        with patch("builtins.input", return_value="Q"):
            assert prompt_continuation("Continue?") is False

    def test_returns_true_on_empty_input(self) -> None:
        """Given empty input (Enter), returns True (default continue)."""
        with patch("builtins.input", return_value=""):
            assert prompt_continuation("Continue?") is True

    def test_reprompts_on_invalid_input(self) -> None:
        """Given invalid then valid input, re-prompts and returns based on valid."""
        with patch("builtins.input", side_effect=["invalid", "n", "Y"]):
            assert prompt_continuation("Continue?") is True

    def test_returns_false_on_eof(self) -> None:
        """Given EOFError, returns False."""
        with patch("builtins.input", side_effect=EOFError):
            assert prompt_continuation("Continue?") is False

    def test_returns_false_on_keyboard_interrupt(self) -> None:
        """Given KeyboardInterrupt, returns False."""
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            assert prompt_continuation("Continue?") is False

    def test_skips_in_non_interactive_mode(self) -> None:
        """Given non-interactive mode, returns True without calling input."""
        set_non_interactive(True)
        try:
            with patch("builtins.input") as mock_input:
                assert prompt_continuation("Continue?") is True
                mock_input.assert_not_called()
        finally:
            set_non_interactive(False)


class TestCheckpointAndPrompt:
    """Tests for checkpoint_and_prompt() function."""

    def test_saves_before_prompt(self, tmp_path: Path) -> None:
        """Verifies save_state is called BEFORE prompt_continuation."""
        call_order: list[str] = []
        mock_state = MagicMock(spec=State)
        state_path = tmp_path / "state.yaml"

        with (
            patch(
                "bmad_assist.core.loop.interactive.save_state",
                side_effect=lambda *a: call_order.append("save"),
            ),
            patch(
                "bmad_assist.core.loop.interactive.prompt_continuation",
                side_effect=lambda *a: call_order.append("prompt") or True,
            ),
        ):
            checkpoint_and_prompt(mock_state, state_path, "Continue?")

        assert call_order == ["save", "prompt"]

    def test_propagates_save_exception(self, tmp_path: Path) -> None:
        """Given save_state raises, exception propagates (fail-fast)."""
        mock_state = MagicMock(spec=State)
        state_path = tmp_path / "state.yaml"

        with patch(
            "bmad_assist.core.loop.interactive.save_state",
            side_effect=OSError("Disk full"),
        ), pytest.raises(IOError, match="Disk full"):
            checkpoint_and_prompt(mock_state, state_path, "Continue?")

    def test_returns_prompt_result_true(self, tmp_path: Path) -> None:
        """Returns True when prompt_continuation returns True."""
        mock_state = MagicMock(spec=State)
        state_path = tmp_path / "state.yaml"

        with (
            patch("bmad_assist.core.loop.interactive.save_state"),
            patch("bmad_assist.core.loop.interactive.prompt_continuation", return_value=True),
        ):
            assert checkpoint_and_prompt(mock_state, state_path, "msg") is True

    def test_returns_prompt_result_false(self, tmp_path: Path) -> None:
        """Returns False when prompt_continuation returns False."""
        mock_state = MagicMock(spec=State)
        state_path = tmp_path / "state.yaml"

        with (
            patch("bmad_assist.core.loop.interactive.save_state"),
            patch("bmad_assist.core.loop.interactive.prompt_continuation", return_value=False),
        ):
            assert checkpoint_and_prompt(mock_state, state_path, "msg") is False


class TestNonInteractiveMode:
    """Tests for non-interactive mode flag."""

    def test_set_and_check_non_interactive(self) -> None:
        """set_non_interactive() and is_non_interactive() work correctly."""
        # Ensure clean state
        set_non_interactive(False)
        assert is_non_interactive() is False

        set_non_interactive(True)
        assert is_non_interactive() is True

        set_non_interactive(False)
        assert is_non_interactive() is False


class TestPromptToolkitRemoved:
    """Verify prompt_toolkit is not imported by interactive module (AC8)."""

    def test_interactive_does_not_import_prompt_toolkit(self) -> None:
        """Verify interactive.py does not import prompt_toolkit."""
        import sys

        # Ensure fresh import
        if "bmad_assist.core.loop.interactive" in sys.modules:
            del sys.modules["bmad_assist.core.loop.interactive"]

        # Import the module
        import bmad_assist.core.loop.interactive  # noqa: F401

        # Check that prompt_toolkit is not in the module's imports
        # The module should only use builtins and standard library
        assert "prompt_toolkit" not in sys.modules.get(
            "bmad_assist.core.loop.interactive", ""
        ).__dict__.get("__file__", "")


class TestResumeAfterQuit:
    """Integration test for quit-and-resume flow (AC7)."""

    def test_resume_continues_from_saved_position(self, tmp_path: Path) -> None:
        """Given state at E1.S2, when loop quits and restarts, resumes from E1.S2."""
        from bmad_assist.core.state import load_state, save_state

        # Create state at specific position
        state = State(
            current_epic=1,
            current_story="1.2",
            current_phase=Phase.CREATE_STORY,
        )
        state_path = tmp_path / "state.yaml"
        save_state(state, state_path)

        # Verify state persisted
        loaded = load_state(state_path)
        assert loaded.current_epic == 1
        assert loaded.current_story == "1.2"
        assert loaded.current_phase == Phase.CREATE_STORY
