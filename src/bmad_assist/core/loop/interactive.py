"""Interactive continuation prompts for phase execution.

Provides simple continuation prompts at story and epic boundaries.
Uses cross-platform input() - no termios/tty/prompt_toolkit dependencies.

Key functions:
- prompt_continuation(): Display [Y/q] prompt and get user choice
- checkpoint_and_prompt(): Save state THEN prompt (Ctrl+C safe)

"""

import logging
import sys
from pathlib import Path

from bmad_assist.cli_utils import console
from bmad_assist.core.state import State, save_state

logger = logging.getLogger(__name__)

# Global flag to force non-interactive mode (set via -n flag)
_force_non_interactive: bool = False

# Global flag to skip story boundary prompts but keep epic boundary prompts
_skip_story_prompts: bool = False

# Global flag to enable backfill mode (implement missed stories before forward progress)
_backfill_enabled: bool = False

# The forward frontier story — set when backfill starts, used as the fixed
# reference point for gap detection throughout the backfill pass.
_backfill_frontier: str | None = None


def set_non_interactive(enabled: bool) -> None:
    """Set the global non-interactive mode.

    When enabled, all interactive prompts are skipped and auto-continue is used.
    This is set by the -n/--no-interactive CLI flag.

    Args:
        enabled: True to disable all interactive prompts.

    """
    global _force_non_interactive
    _force_non_interactive = enabled


def is_non_interactive() -> bool:
    """Check if non-interactive mode is forced."""
    return _force_non_interactive


def set_skip_story_prompts(enabled: bool) -> None:
    """Set the global skip-story-prompts mode.

    When enabled, story boundary prompts are skipped (auto-continue),
    but epic boundary prompts are still shown.

    Args:
        enabled: True to skip story boundary prompts.

    """
    global _skip_story_prompts
    _skip_story_prompts = enabled


def is_skip_story_prompts() -> bool:
    """Check if story boundary prompts should be skipped."""
    return _skip_story_prompts


def set_backfill_enabled(enabled: bool) -> None:
    """Set the global backfill mode.

    When enabled, after completing the current story the runner scans
    for missed/skipped stories before the current position and implements
    them before continuing forward.

    Args:
        enabled: True to enable backfill mode.

    """
    global _backfill_enabled
    _backfill_enabled = enabled


def is_backfill_enabled() -> bool:
    """Check if backfill mode is enabled."""
    return _backfill_enabled


def set_backfill_frontier(story: str | None) -> None:
    """Set or clear the backfill forward frontier story.

    The frontier is the story that was current when backfill started.
    Gap detection always uses this as the reference point, not the
    currently-executing backfill story.

    Args:
        story: Story ID like "10.6", or None to clear.

    """
    global _backfill_frontier
    _backfill_frontier = story


def get_backfill_frontier() -> str | None:
    """Get the backfill forward frontier story, or None if not in backfill."""
    return _backfill_frontier


def is_in_backfill() -> bool:
    """Check if currently executing backfill stories (frontier is set)."""
    return _backfill_frontier is not None


def prompt_continuation(message: str) -> bool:
    """Display continuation prompt and get user choice.

    Accepts Y/y (continue), q/Q (quit), empty (continue).
    Re-prompts on invalid input. Handles EOF and KeyboardInterrupt.

    Args:
        message: Question to display (e.g., "Story 1.2 complete. Continue?")

    Returns:
        True to continue, False to quit.

    """
    if is_non_interactive():
        logger.debug("Skipping prompt in non-interactive mode: %s", message)
        return True

    logger.info("Prompting user: %s", message)
    # Use print() instead of console.print() to avoid Rich buffering issues
    # that can cause truncated output before input()
    print(f"\n{message} [Y/q] ", end="", flush=True)
    sys.stdout.flush()  # Double-ensure flush before blocking on input()

    while True:
        try:
            choice = input().strip().lower()

            if choice in ("y", ""):
                logger.info("User chose to continue")
                return True
            elif choice == "q":
                logger.info("User chose to quit")
                return False
            else:
                # Invalid input - re-prompt
                print("Invalid choice. Enter Y to continue or q to quit: ", end="", flush=True)

        except (EOFError, KeyboardInterrupt):
            # Treat EOF/Ctrl+C as quit
            console.print()  # Newline after ^C
            logger.info("User interrupted (EOF/Ctrl+C)")
            return False


def checkpoint_and_prompt(state: State, state_path: Path, message: str) -> bool:
    """Save state, then prompt for continuation.

    CRITICAL: This function MUST save state BEFORE prompting.
    This ensures Ctrl+C is always safe - state is already persisted.

    Args:
        state: Current loop state to save.
        state_path: Path to state.yaml file.
        message: Continuation prompt message.

    Returns:
        True to continue, False to quit (with exit message).

    Raises:
        Exception: If save_state() fails (fail-fast, no silent data loss).

    """
    # Save state FIRST (fail-fast on error)
    save_state(state, state_path)
    logger.debug("State saved before prompt")

    # Now prompt (safe to Ctrl+C)
    should_continue = prompt_continuation(message)

    if not should_continue:
        console.print("\n[bold green]State saved.[/bold green] Run 'bmad-assist run' to continue.")

    return should_continue
