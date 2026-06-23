"""Epic completion and transition functions.

Story 6.4: Epic completion and transition functions.

"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from bmad_assist.core.exceptions import StateError
from bmad_assist.core.state import Phase, State, save_state
from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)


__all__ = [
    "complete_epic",
    "is_last_epic",
    "get_next_epic",
    "advance_to_next_epic",
    "persist_epic_completion",
    "handle_epic_completion",
]


# =============================================================================
# Story 6.4: Epic Completion and Transition Functions
# =============================================================================


def complete_epic(state: State) -> State:
    """Mark the current epic as completed and return updated state.

    Adds current_epic to completed_epics list and updates timestamp.
    Uses immutable pattern - returns a NEW State object via model_copy.
    Idempotent: calling multiple times won't create duplicates.

    Args:
        state: Current loop state with epic to complete.

    Returns:
        New State with current_epic added to completed_epics
        and updated_at set to current naive UTC timestamp.

    Raises:
        StateError: If current_epic is None.

    Example:
        >>> state = State(current_epic=2, completed_epics=[1])
        >>> new_state = complete_epic(state)
        >>> new_state.completed_epics
        [1, 2]

    """
    if state.current_epic is None:
        raise StateError("Cannot complete epic: no current epic set")

    # Idempotent: only add if not already present (crash-safe retry)
    if state.current_epic in state.completed_epics:
        logger.info(
            "Epic %s already in completed_epics - skipping duplicate (idempotent retry)",
            state.current_epic,
        )
        new_completed = list(state.completed_epics)
    else:
        new_completed = [*state.completed_epics, state.current_epic]

    # Get naive UTC timestamp (project convention per state.py)
    now = datetime.now(UTC).replace(tzinfo=None)

    # Return NEW state via Pydantic model_copy (immutable pattern)
    return state.model_copy(
        update={
            "completed_epics": new_completed,
            "updated_at": now,
        }
    )


def is_last_epic(current_epic: EpicId, epic_list: list[EpicId]) -> bool:
    """Check if current epic is the last epic in the project.

    Pure function that checks if the given epic is the final one.

    Args:
        current_epic: The current epic identifier.
        epic_list: Ordered list of epic numbers in the project.

    Returns:
        True if current_epic is the last item in epic_list.

    Raises:
        StateError: If epic_list is empty.
        StateError: If current_epic is not found in epic_list.

    Example:
        >>> is_last_epic(4, [1, 2, 3, 4])
        True
        >>> is_last_epic(3, [1, 2, 3, 4])
        False

    """
    if not epic_list:
        raise StateError("Cannot check last epic: no epics in project")

    if current_epic not in epic_list:
        raise StateError(f"Current epic {current_epic} not found in epic list")

    return current_epic == epic_list[-1]


def get_next_epic(current_epic: EpicId, epic_list: list[EpicId]) -> EpicId | None:
    """Get the next epic number after current_epic in the project sequence.

    Pure function that calculates the next epic without accessing State.

    Args:
        current_epic: The current epic identifier.
        epic_list: Ordered list of epic numbers in the project.

    Returns:
        Next epic number if one exists, None if current is last.

    Raises:
        StateError: If epic_list is empty.
        StateError: If current_epic is not found in epic_list.

    Example:
        >>> get_next_epic(2, [1, 2, 3, 4])
        3
        >>> get_next_epic(4, [1, 2, 3, 4])
        None

    """
    if not epic_list:
        raise StateError("Cannot get next epic: no epics in project")

    try:
        current_index = epic_list.index(current_epic)
    except ValueError as e:
        raise StateError(f"Current epic {current_epic} not found in epic list") from e

    # Check if there's a next epic
    next_index = current_index + 1
    if next_index >= len(epic_list):
        return None

    return epic_list[next_index]


def advance_to_next_epic(
    state: State,
    epic_list: list[EpicId],
    epic_stories_loader: Callable[[EpicId], list[str]],
) -> State | None:
    """Transition to the next incomplete epic in the project.

    Returns a new State with current_epic set to next epic, current_story
    set to the first story of that epic, and current_phase reset to
    CREATE_STORY. Returns None if all remaining epics are completed
    (signals project completion).

    Skips epics that are already in completed_epics to prevent re-execution
    of done work.

    Uses immutable pattern - returns a NEW State object via model_copy.

    Args:
        state: Current loop state.
        epic_list: Ordered list of epic numbers in the project.
        epic_stories_loader: Callable that takes epic number and returns
            list of story IDs for that epic.

    Returns:
        New State with next epic, first story, and phase=CREATE_STORY,
        or None if current epic is last or all remaining epics are completed.

    Raises:
        StateError: If current_epic is None.
        StateError: If epic_list is empty.

    Example:
        >>> loader = lambda epic: [f"{epic}.1", f"{epic}.2"]
        >>> state = State(current_epic=2, current_story="2.4")
        >>> new_state = advance_to_next_epic(state, [1, 2, 3, 4], loader)
        >>> new_state.current_epic
        3
        >>> new_state.current_story
        '3.1'

    """
    if not epic_list:
        raise StateError("Cannot advance epic: no epics in project")

    if state.current_epic is None:
        raise StateError("Cannot advance epic: no current epic set")

    # Find the next incomplete epic (skip already completed ones)
    next_epic: EpicId | None
    if state.current_epic not in epic_list:
        next_epic = epic_list[0]
        logger.info(
            "Current epic %s not in epic_list (likely done), advancing to %s",
            state.current_epic,
            next_epic,
        )
    else:
        candidate_epic = state.current_epic
        next_epic = get_next_epic(candidate_epic, epic_list)

    while True:
        if next_epic is None:
            logger.info("Epic %s is final epic in project", state.current_epic)
            return None

        # Check if next epic is already completed - skip it
        if next_epic in state.completed_epics:
            logger.info(
                "Skipping epic %s - already in completed_epics",
                next_epic,
            )
            candidate_epic = next_epic
            next_epic = get_next_epic(candidate_epic, epic_list)
            continue

        # Load stories for the next epic
        stories = epic_stories_loader(next_epic)

        if not stories:
            # Epic has no non-done stories - either it's fully completed or has no stories at all
            # Skip it and continue searching for next epic with incomplete stories
            logger.info(
                "Skipping epic %s - no incomplete stories (already completed)",
                next_epic,
            )
            candidate_epic = next_epic
            next_epic = get_next_epic(candidate_epic, epic_list)
            continue

        # Check if ALL stories for this epic are already completed
        # If so, skip directly to first epic_teardown phase (per ADR-006)
        incomplete_stories = [s for s in stories if s not in state.completed_stories]

        if not incomplete_stories:
            # All stories done - go directly to first teardown phase
            # Get first teardown phase from loop config
            from bmad_assist.core.config import get_loop_config

            loop_config = get_loop_config()
            if loop_config.epic_teardown:
                first_teardown_phase = Phase(loop_config.epic_teardown[0])
            else:
                # No teardown phases configured - skip directly to CREATE_STORY of next epic
                # This is an edge case where someone has empty epic_teardown
                logger.info(
                    "All stories in epic %s already completed, no teardown phases configured",
                    next_epic,
                )
                # Continue searching for next epic with incomplete stories
                candidate_epic = next_epic
                next_epic = get_next_epic(candidate_epic, epic_list)
                continue

            last_story = stories[-1]
            logger.info(
                "All stories in epic %s already completed, advancing to %s",
                next_epic,
                first_teardown_phase.name,
            )

            now = datetime.now(UTC).replace(tzinfo=None)
            return state.model_copy(
                update={
                    "current_epic": next_epic,
                    "current_story": last_story,
                    "current_phase": first_teardown_phase,
                    "epic_setup_complete": False,  # Reset for new epic
                    "code_review_rework_count": 0,  # Reset rework counter
                    "synthesis_retry_count": 0,
                    "last_synthesis_resolution": None,
                    "last_synthesis_verdict": None,
                    "last_synthesis_report_path": None,
                    "last_synthesis_story": None,
                    "last_synthesis_extraction_quality": None,
                    "last_synthesis_failure_class": None,
                    "updated_at": now,
                }
            )

        # Found an epic with incomplete stories - break and use it
        break

    # Some stories not done - start with first incomplete story
    first_incomplete = incomplete_stories[0]
    logger.info("Advancing to epic %s, story %s", next_epic, first_incomplete)

    # Get naive UTC timestamp (project convention)
    now = datetime.now(UTC).replace(tzinfo=None)

    # Return NEW state with next epic, first incomplete story, and CREATE_STORY phase
    return state.model_copy(
        update={
            "current_epic": next_epic,
            "current_story": first_incomplete,
            "current_phase": Phase.CREATE_STORY,
            "epic_setup_complete": False,  # Reset for new epic
            "code_review_rework_count": 0,  # Reset rework counter
            "synthesis_retry_count": 0,
            "last_synthesis_resolution": None,
            "last_synthesis_verdict": None,
            "last_synthesis_report_path": None,
            "last_synthesis_story": None,
            "last_synthesis_extraction_quality": None,
            "last_synthesis_failure_class": None,
            "updated_at": now,
        }
    )


def persist_epic_completion(state: State, state_path: Path) -> None:
    """Persist state after epic completion.

    Thin wrapper around save_state() for semantic clarity in loop orchestration.
    This is a void operation - saves state atomically or raises exception.

    Args:
        state: State to persist.
        state_path: Path to state file.

    Raises:
        StateError: If state persistence fails.

    """
    save_state(state, state_path)


def handle_epic_completion(
    state: State,
    epic_list: list[EpicId],
    epic_stories_loader: Callable[[EpicId], list[str]],
    state_path: Path,
) -> tuple[State, bool]:
    """Orchestrate full epic completion flow with single atomic persist.

    Executes the complete epic completion sequence:
    1. Mark current epic as completed
    2. If NOT last epic: advance to next epic's first story
    3. If last epic: signal project completion
    4. Persist FINAL state (single atomic persist)

    CRITICAL: Uses single atomic persist pattern to prevent race conditions.
    The entire flow completes in memory before persisting, ensuring state
    consistency even if a crash occurs.

    Note: epic_list only contains epics with incomplete stories. If current_epic
    is not in epic_list (all its stories are done), we treat it as project
    completion since there are no more epics with active work.

    Args:
        state: Current loop state after epic's RETROSPECTIVE completes.
        epic_list: Ordered list of epic numbers with incomplete stories.
        epic_stories_loader: Callable that takes epic number and returns
            list of story IDs for that epic.
        state_path: Path to state file for persistence.

    Returns:
        Tuple of (new_state, is_project_complete):
        - new_state: State with completion applied (and transition if not last)
        - is_project_complete: True if this was the last epic in project

    Raises:
        StateError: If current_epic is None.
        StateError: If state persistence fails.

    Example:
        >>> loader = lambda epic: [f"{epic}.1", f"{epic}.2"]
        >>> state = State(current_epic=2, completed_epics=[1])
        >>> new_state, is_complete = handle_epic_completion(
        ...     state, [1, 2, 3, 4], loader, Path("state.yaml")
        ... )
        >>> new_state.current_epic
        3
        >>> is_complete
        False

    """
    # Step 1: Mark epic as completed
    state_with_completion = complete_epic(state)

    # Step 2: Handle case where current epic is not in epic_list
    # This happens when all stories in current epic are done (epic_list only
    # contains epics with incomplete stories).
    #
    # IMPORTANT: Do NOT automatically jump to earlier epics with incomplete stories!
    # Epics should be processed in order. If current epic is complete and not in
    # epic_list, the current epic's work is done - signal project completion.
    if state.current_epic not in epic_list:
        logger.info(
            "Epic %s completed (was not in epic_list, likely filtered as done).",
            state.current_epic,
        )
        if not epic_list:
            logger.info("Project complete! No remaining epics with incomplete stories.")
            persist_epic_completion(state_with_completion, state_path)
            return state_with_completion, True

        # If epic_list is NOT empty, proceed to advance_to_next_epic below

    # Step 3: Try to advance to next incomplete epic (normal flow)
    # advance_to_next_epic handles skipping already-completed epics
    advanced_state = advance_to_next_epic(state_with_completion, epic_list, epic_stories_loader)

    # Step 4: Check if there are any remaining epics
    if advanced_state is None:
        # No more incomplete epics - project is complete
        # This can happen even if current epic isn't "last" in epic_list,
        # because later epics may already be in completed_epics
        logger.info(
            "Project complete! All epics finished (no incomplete epics remaining).",
        )
        persist_epic_completion(state_with_completion, state_path)
        return state_with_completion, True

    # Step 5: Persist FINAL state (single atomic persist)
    persist_epic_completion(advanced_state, state_path)

    return advanced_state, False
