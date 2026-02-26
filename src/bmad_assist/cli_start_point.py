"""Start point override logic for bmad-assist CLI.

This module handles --epic and --story flag processing, including:
- Epic/story validation
- Done story handling (interactive prompts)
- Epic lifecycle status checking
- State updates
"""

import logging
import sys
from pathlib import Path

import typer

from bmad_assist.bmad import read_project_state
from bmad_assist.bmad.parser import EpicStory
from bmad_assist.bmad.state_reader import ProjectState
from bmad_assist.cli_utils import (
    EXIT_CONFIG_ERROR,
    _error,
    _info,
    _warning,
    console,
)
from bmad_assist.core.config import Config
from bmad_assist.core.epic_lifecycle import EpicLifecycleStatus
from bmad_assist.core.loop.interactive import is_non_interactive
from bmad_assist.core.state import Phase, get_state_path, load_state, save_state, update_position
from bmad_assist.core.types import EpicId, parse_epic_id

logger = logging.getLogger(__name__)

# Status to phase mapping for start point override
_STATUS_TO_PHASE: dict[str | None, Phase] = {
    None: Phase.CREATE_STORY,
    "backlog": Phase.CREATE_STORY,
    "ready-for-dev": Phase.DEV_STORY,
    "in-progress": Phase.DEV_STORY,
    "review": Phase.CODE_REVIEW,
}


def apply_start_point_override(
    config: Config,
    project_path: Path,
    bmad_path: Path,
    epic_id: str | None,
    story_id: str | None,
    epic_list: list[EpicId],
    stories_by_epic: dict[EpicId, list[str]],
    force_restart: bool = False,
) -> None:
    """Override state.yaml with specified epic/story starting point.

    Loads current state, applies override based on sprint-status.yaml,
    and saves state atomically. Phase is determined by story status.

    Args:
        config: Loaded configuration.
        project_path: Path to project root.
        bmad_path: Path to BMAD docs directory (for read_project_state).
        epic_id: Epic identifier from --epic flag (e.g., "22" or "testarch").
        story_id: Story number from --story flag (e.g., "3" for story 22-3).
        epic_list: List of available epics.
        stories_by_epic: Mapping of epic to story IDs.
        force_restart: If True, force restart even if story is done.

    Raises:
        typer.Exit: With EXIT_CONFIG_ERROR if epic/story not found.

    """
    if epic_id is None:
        return

    # Parse epic_id
    epic = parse_epic_id(epic_id)

    # Load project state for status lookup
    project_state = read_project_state(bmad_path, use_sprint_status=True)

    # Check if epic has any stories (including done ones)
    # Note: Don't use epic_list here - it only contains epics with non-done stories
    # User may want to re-run a completed epic explicitly
    epic_stories = [s for s in project_state.all_stories if s.number.startswith(f"{epic}.")]
    if not epic_stories:
        _error(f"Epic {epic} not found or has no stories")
        raise typer.Exit(code=EXIT_CONFIG_ERROR)

    # Determine story_key and status
    if story_id is not None:
        story_key, status = _handle_story_specified(epic, story_id, epic_stories, force_restart)
    else:
        result = _handle_epic_only(
            epic, epic_stories, config, project_path, project_state, force_restart
        )
        if result is None:
            return  # Early exit - state already saved by _handle_epic_only
        story_key, status = result

    # Load current state
    state_path = get_state_path(config, project_root=project_path)
    state = load_state(state_path)

    # Determine phase from status
    phase = _STATUS_TO_PHASE.get(status, Phase.CREATE_STORY)

    # Update position
    update_position(state, epic=epic, story=story_key, phase=phase)

    # Save state atomically
    save_state(state, state_path)

    logger.info("Starting from epic=%s story=%s phase=%s", epic, story_key, phase.value)


def _handle_story_specified(
    epic: EpicId,
    story_id: str,
    epic_stories: list[EpicStory],
    force_restart: bool,
) -> tuple[str, str | None]:
    """Handle case when both epic and story are specified.

    Returns:
        Tuple of (story_key, status).

    Raises:
        typer.Exit: If story not found or cancelled.

    """
    # Validate story_id is numeric
    if not story_id.isdigit():
        _error(f"Story number must be numeric, got: {story_id}")
        raise typer.Exit(code=EXIT_CONFIG_ERROR)

    # User specified both epic and story
    story_key = f"{epic}.{story_id}"

    # Find story in epic_stories (includes done stories)
    story = next((s for s in epic_stories if s.number == story_key), None)
    if story is None:
        _error(f"Story {story_key} not found in epic {epic}")
        raise typer.Exit(code=EXIT_CONFIG_ERROR)

    status = story.status

    # Handle done stories with user interaction
    if status == "done":
        story_key, status = _handle_done_story(story_key, epic, epic_stories, force_restart)

    return story_key, status


def _handle_done_story(
    story_key: str,
    epic: EpicId,
    epic_stories: list[EpicStory],
    force_restart: bool,
) -> tuple[str, str | None]:
    """Handle a story that is already done.

    Returns:
        Tuple of (story_key, status) - may be different story if user skips.

    Raises:
        typer.Exit: If cancelled or no stories available.

    """
    if force_restart:
        _warning(
            f"Story {story_key} has status 'done' --force specified, restarting from CREATE_STORY"
        )
        return story_key, "backlog"

    if is_non_interactive():
        # Auto-skip to next not-done story in non-interactive mode
        next_story = next((s for s in epic_stories if s.status != "done"), None)
        if next_story:
            _info(
                f"Story {story_key} is done, auto-skipping to next "
                f"not-done story {next_story.number}"
            )
            return next_story.number, next_story.status
        else:
            _error(f"Story {story_key} is done and no other stories in epic {epic} are available")
            raise typer.Exit(code=EXIT_CONFIG_ERROR)

    # Interactive mode - prompt user
    console.print(f"\n[bold yellow]Story {story_key} is already 'done'.[/bold yellow]")
    console.print(
        "[bold](r)[/bold]estart story  [bold](s)[/bold]kip to next not-done  "
        "[bold](c)[/bold]ancel: ",
        end="",
    )

    choice = _read_choice(["r", "s", "c"])

    if choice == "r":
        _info(f"Restarting story {story_key} from CREATE_STORY")
        return story_key, "backlog"
    elif choice == "s":
        # Skip to next not-done story
        next_story = next((s for s in epic_stories if s.status != "done"), None)
        if next_story:
            _info(f"Skipping to next not-done story {next_story.number}")
            return next_story.number, next_story.status
        else:
            _error(f"No other stories in epic {epic} are available")
            raise typer.Exit(code=EXIT_CONFIG_ERROR)
    else:  # choice == "c"
        _info("Cancelled by user")
        raise typer.Exit(code=0)


def _handle_epic_only(
    epic: EpicId,
    epic_stories: list[EpicStory],
    config: Config,
    project_path: Path,
    project_state: "ProjectState",
    force_restart: bool,
) -> tuple[str, str | None] | None:
    """Handle case when only epic is specified (no story).

    Returns:
        Tuple of (story_key, status), or None if state was saved and we should exit early.

    Raises:
        typer.Exit: If cancelled.

    """
    # Find first incomplete story
    story = next((s for s in epic_stories if s.status != "done"), None)

    if story is not None:
        return story.number, story.status

    # All stories done - check full lifecycle status
    from bmad_assist.core.epic_lifecycle import get_epic_lifecycle_status

    lifecycle = get_epic_lifecycle_status(epic, project_state, config, project_path)

    if lifecycle.is_fully_completed:
        return _handle_fully_completed_epic(epic, epic_stories, force_restart)

    # Epic has pending post-story phases
    return _handle_pending_phases(
        epic, epic_stories, config, project_path, lifecycle, force_restart
    )


def _handle_fully_completed_epic(
    epic: EpicId,
    epic_stories: list[EpicStory],
    force_restart: bool,
) -> tuple[str, str]:
    """Handle an epic that is fully completed (all phases done).

    Returns:
        Tuple of (story_key, status).

    Raises:
        typer.Exit: If cancelled.

    """
    if force_restart:
        story = epic_stories[0]
        _warning(
            f"Epic {epic} is fully completed. --force specified, restarting from {story.number}"
        )
        return story.number, "backlog"

    if is_non_interactive():
        _error(f"Epic {epic} is fully completed (all phases done). Use --force to restart.")
        raise typer.Exit(code=EXIT_CONFIG_ERROR)

    console.print(f"\n[bold green]Epic {epic} is fully completed![/bold green]")
    console.print("  [dim]- All stories done[/dim]")
    console.print("  [dim]- Retrospective done[/dim]")
    console.print("  [dim]- QA plan generated[/dim]")
    console.print("  [dim]- QA plan executed[/dim]")
    console.print("\n[bold](f)[/bold]orce restart  [bold](c)[/bold]ancel: ", end="")

    choice = _read_choice(["f", "c"])

    if choice == "f":
        story = epic_stories[0]
        _info(f"Force restarting from story {story.number}")
        return story.number, "backlog"
    else:
        _info("Cancelled by user")
        raise typer.Exit(code=0)


def _handle_pending_phases(
    epic: EpicId,
    epic_stories: list[EpicStory],
    config: Config,
    project_path: Path,
    lifecycle: "EpicLifecycleStatus",
    force_restart: bool,
) -> tuple[str, str | None] | None:
    """Handle an epic with pending post-story phases.

    Returns:
        Tuple of (story_key, status), or None if state was saved and we should exit early.

    Raises:
        typer.Exit: If cancelled.

    """
    next_phase = lifecycle.next_phase
    assert next_phase is not None  # Type narrowing

    if force_restart:
        _warning(
            f"Epic {epic} {lifecycle.describe()}. --force specified, forcing next phase: {next_phase.value}"
        )
        story_key = lifecycle.last_story
        assert story_key is not None
        _save_phase_state(config, project_path, epic, story_key, next_phase)
        return None

    if is_non_interactive():
        # Auto-start next pending phase
        _info(f"Epic {epic} {lifecycle.describe()}. Starting {next_phase.value.upper()} phase.")
        story_key = lifecycle.last_story
        assert story_key is not None
        _save_phase_state(config, project_path, epic, story_key, next_phase)
        return None  # Exit early - state already saved

    # Interactive mode - show status and options
    return _interactive_phase_selection(epic, epic_stories, config, project_path, lifecycle)


def _interactive_phase_selection(
    epic: EpicId,
    epic_stories: list[EpicStory],
    config: Config,
    project_path: Path,
    lifecycle: "EpicLifecycleStatus",
) -> tuple[str, str | None] | None:
    """Interactive menu for selecting phase when epic has pending phases.

    Returns:
        Tuple of (story_key, status), or None if state was saved and we should exit early.

    Raises:
        typer.Exit: If cancelled.

    """
    from bmad_assist.core.epic_lifecycle import is_qa_enabled

    qa_mode = is_qa_enabled()

    console.print(f"\n[bold yellow]Epic {epic} - {lifecycle.describe()}[/bold yellow]")
    console.print("  [dim]- All stories done: [green]yes[/green][/dim]")
    retro_status = (
        "[green]done[/green]" if lifecycle.retro_completed else "[yellow]pending[/yellow]"
    )  # noqa: E501
    console.print(f"  [dim]- Retrospective: {retro_status}[/dim]")
    # Only show QA status when --qa flag is enabled
    if qa_mode:
        qa_gen = lifecycle.qa_plan_generated
        qa_plan_status = "[green]generated[/green]" if qa_gen else "[yellow]pending[/yellow]"
        console.print(f"  [dim]- QA plan: {qa_plan_status}[/dim]")
        qa_exec_status = (
            "[green]done[/green]" if lifecycle.qa_plan_executed else "[yellow]pending[/yellow]"
        )
        console.print(f"  [dim]- QA execution: {qa_exec_status}[/dim]")

    # Build options based on what's pending
    options = []
    valid_choices = []
    if not lifecycle.retro_completed:
        options.append("[bold](r)[/bold]un retrospective")
        valid_choices.append("r")
    if lifecycle.hardening_enabled and not lifecycle.hardening_completed:
        options.append("[bold](h)[/bold]arden epic")
        valid_choices.append("h")
    # QA options only when --qa flag is enabled
    if qa_mode:
        if lifecycle.retro_completed and not lifecycle.qa_plan_generated:
            options.append("[bold](g)[/bold]enerate QA plan")
            valid_choices.append("g")
        if lifecycle.qa_plan_generated and not lifecycle.qa_plan_executed:
            options.append("[bold](e)[/bold]xecute QA plan")
            valid_choices.append("e")
    options.append("[bold](f)[/bold]orce restart")
    valid_choices.append("f")
    options.append("[bold](c)[/bold]ancel")
    valid_choices.append("c")

    console.print("\n" + "  ".join(options) + ": ", end="")

    choice = _read_choice(valid_choices)

    if choice == "r":
        target_phase = Phase.RETROSPECTIVE
    elif choice == "h":
        target_phase = Phase.HARDENING
    elif choice == "g":
        target_phase = Phase.QA_PLAN_GENERATE
    elif choice == "e":
        target_phase = Phase.QA_PLAN_EXECUTE
    elif choice == "f":
        story = epic_stories[0]
        _info(f"Force restarting from story {story.number}")
        return story.number, "backlog"
    else:  # choice == "c"
        _info("Cancelled by user")
        raise typer.Exit(code=0)

    _info(f"Starting {target_phase.value.upper()} for epic {epic}")
    story_key = lifecycle.last_story
    assert story_key is not None
    _save_phase_state(config, project_path, epic, story_key, target_phase)
    return None  # Exit early - state already saved


def _save_phase_state(
    config: Config,
    project_path: Path,
    epic: EpicId,
    story_key: str,
    phase: Phase,
) -> None:
    """Save state with specified phase."""
    state_path = get_state_path(config, project_root=project_path)
    state = load_state(state_path)
    update_position(state, epic=epic, story=story_key, phase=phase)
    save_state(state, state_path)
    logger.info("Starting %s for epic=%s", phase.value, epic)


def _read_choice(valid_choices: list[str]) -> str:
    """Read user choice from stdin.

    Args:
        valid_choices: List of valid single-character choices.

    Returns:
        The chosen character (lowercase).

    Raises:
        typer.Exit: If interrupted by Ctrl+C or EOF.

    """
    while True:
        try:
            choice = sys.stdin.readline().strip().lower()
            if choice in valid_choices:
                return choice
            choices_str = ", ".join(valid_choices)
            console.print(
                f"[yellow]Invalid choice. Please enter one of {choices_str}:[/yellow] ",
                end="",
            )
        except (KeyboardInterrupt, EOFError):
            console.print()  # New line after ^C or ^D
            _info("Cancelled by user")
            raise typer.Exit(code=0) from None
