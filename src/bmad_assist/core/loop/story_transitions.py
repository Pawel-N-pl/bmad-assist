"""Story completion and transition functions.

Story 6.3: Story completion and transition functions.

"""

import logging
from datetime import UTC, datetime
from pathlib import Path

from bmad_assist.core.exceptions import StateError
from bmad_assist.core.state import Phase, State, save_state

logger = logging.getLogger(__name__)


__all__ = [
    "complete_story",
    "is_last_story_in_epic",
    "get_next_story_id",
    "advance_to_next_story",
    "persist_story_completion",
    "handle_story_completion",
]


# =============================================================================
# Story 6.3: Story Completion and Transition Functions
# =============================================================================


def complete_story(state: State) -> State:
    """Mark the current story as completed and return updated state.

    Adds current_story to completed_stories list and updates timestamp.
    Uses immutable pattern - returns a NEW State object via model_copy.

    Args:
        state: Current loop state with story to complete.

    Returns:
        New State with current_story added to completed_stories
        and updated_at set to current naive UTC timestamp.

    Raises:
        StateError: If current_story is None.

    Example:
        >>> state = State(current_story="2.3", completed_stories=["2.1", "2.2"])
        >>> new_state = complete_story(state)
        >>> new_state.completed_stories
        ['2.1', '2.2', '2.3']

    """
    if state.current_story is None:
        raise StateError("Cannot complete story: no current story set")

    # Idempotent: only add if not already present (crash-safe retry)
    if state.current_story in state.completed_stories:
        logger.warning(
            "Story %s already in completed_stories (retry after crash/resume)",
            state.current_story,
        )
        new_completed = list(state.completed_stories)
    else:
        new_completed = [*state.completed_stories, state.current_story]

    # Get naive UTC timestamp (project convention per state.py)
    now = datetime.now(UTC).replace(tzinfo=None)

    # Return NEW state via Pydantic model_copy (immutable pattern)
    return state.model_copy(
        update={
            "completed_stories": new_completed,
            "updated_at": now,
        }
    )


def is_last_story_in_epic(state: State, epic_stories: list[str]) -> bool:
    """Check if current story is the last INCOMPLETE story in the epic.

    Filters out already completed stories (in state.completed_stories) before
    checking if this is the last one. This prevents premature RETROSPECTIVE
    trigger when epic_stories list is static but stories are being marked done.

    Args:
        state: Current loop state with current_story and completed_stories set.
        epic_stories: Ordered list of story IDs in the epic.

    Returns:
        True if current_story is the last story not in completed_stories.

    Raises:
        StateError: If current_story is None.
        StateError: If epic_stories is empty.

    Example:
        >>> state = State(current_story="2.4", completed_stories=["2.1", "2.2", "2.3"])
        >>> is_last_story_in_epic(state, ["2.1", "2.2", "2.3", "2.4", "2.5"])
        False  # 2.5 is after 2.4
        >>> state = State(current_story="2.4", completed_stories=["2.1", "2.2", "2.3"])
        >>> is_last_story_in_epic(state, ["2.1", "2.2", "2.3", "2.4"])
        True  # 2.4 is last incomplete story

    """
    if state.current_story is None:
        raise StateError("Cannot check last story: no current story set")

    if not epic_stories:
        # Empty epic_stories means all stories were filtered out as "done"
        # This happens after crash/resume when epic completes
        logger.info("Epic has no active stories (all done), treating as last story")
        return True

    # Filter out already completed stories to find actual last incomplete story
    incomplete_stories = [s for s in epic_stories if s not in state.completed_stories]

    if not incomplete_stories:
        # All stories done - treat current as last (will trigger RETROSPECTIVE)
        return True

    # Check if current story is the last INCOMPLETE story
    return state.current_story == incomplete_stories[-1]


def get_next_story_id(current_story: str, epic_stories: list[str]) -> str | None:
    """Get the next story ID after current_story in the epic sequence.

    Pure function that calculates the next story without accessing State.

    Args:
        current_story: The current story ID.
        epic_stories: Ordered list of story IDs in the epic.

    Returns:
        Next story ID if one exists, None if current is last.

    Raises:
        StateError: If epic_stories is empty.
        StateError: If current_story is not found in epic_stories.

    Example:
        >>> get_next_story_id("2.2", ["2.1", "2.2", "2.3", "2.4"])
        '2.3'
        >>> get_next_story_id("2.4", ["2.1", "2.2", "2.3", "2.4"])
        None

    """
    if not epic_stories:
        raise StateError("Cannot get next story: epic has no stories")

    try:
        current_index = epic_stories.index(current_story)
    except ValueError as e:
        raise StateError(f"Current story {current_story} not found in epic stories") from e

    # Check if there's a next story
    next_index = current_index + 1
    if next_index >= len(epic_stories):
        return None

    return epic_stories[next_index]


def advance_to_next_story(state: State, epic_stories: list[str]) -> State | None:
    """Transition to the next story in the epic.

    Returns a new State with current_story set to next story and
    current_phase reset to CREATE_STORY. Returns None if current
    story is last in epic (signals epic completion needed).

    Uses immutable pattern - returns a NEW State object via model_copy.

    Args:
        state: Current loop state.
        epic_stories: Ordered list of story IDs in the epic.

    Returns:
        New State with next story and phase=CREATE_STORY,
        or None if current story is last in epic.

    Raises:
        StateError: If current_story is None.
        StateError: If epic_stories is empty.

    Example:
        >>> state = State(current_story="2.3", current_phase=Phase.CODE_REVIEW_SYNTHESIS)
        >>> new_state = advance_to_next_story(state, ["2.1", "2.2", "2.3", "2.4"])
        >>> new_state.current_story
        '2.4'
        >>> new_state.current_phase
        <Phase.CREATE_STORY: 'create_story'>

    """
    if not epic_stories:
        raise StateError("Cannot advance story: epic has no stories")

    if state.current_story is None:
        raise StateError("Cannot advance story: no current story set")

    next_story = get_next_story_id(state.current_story, epic_stories)

    if next_story is None:
        logger.info(
            "Story %s is last in epic %s",
            state.current_story,
            state.current_epic,
        )
        return None

    logger.info("Advancing to story %s", next_story)

    # Get naive UTC timestamp (project convention)
    now = datetime.now(UTC).replace(tzinfo=None)

    # Return NEW state with next story and reset phase
    return state.model_copy(
        update={
            "current_story": next_story,
            "current_phase": Phase.CREATE_STORY,
            "updated_at": now,
        }
    )


def persist_story_completion(state: State, state_path: Path) -> None:
    """Persist state after story completion.

    Thin wrapper around save_state() for semantic clarity in loop orchestration.
    This is a void operation - saves state atomically or raises exception.

    Args:
        state: State to persist.
        state_path: Path to state file.

    Raises:
        StateError: If state persistence fails.

    """
    save_state(state, state_path)


def handle_story_completion(
    state: State,
    epic_stories: list[str],
    state_path: Path,
) -> tuple[State, bool]:
    """Orchestrate full story completion flow with single atomic persist.

    Executes the complete story completion sequence:
    1. Mark current story as completed
    2. If NOT last story: advance to next story
    3. If last story: signal epic completion
    4. Persist FINAL state (single atomic persist)

    CRITICAL: Uses single atomic persist pattern to prevent race conditions.
    The entire flow completes in memory before persisting, ensuring state
    consistency even if a crash occurs.

    Args:
        state: Current loop state after story's CODE_REVIEW_SYNTHESIS completes.
        epic_stories: Ordered list of story IDs in the epic.
        state_path: Path to state file for persistence.

    Returns:
        Tuple of (new_state, is_epic_complete):
        - new_state: State with completion applied (and transition if not last)
        - is_epic_complete: True if this was the last story in epic

    Raises:
        StateError: If current_story is None.
        StateError: If epic_stories is empty.
        StateError: If state persistence fails.

    Example:
        >>> state = State(current_story="2.3", completed_stories=["2.1", "2.2"])
        >>> new_state, is_epic_complete = handle_story_completion(
        ...     state, ["2.1", "2.2", "2.3", "2.4"], Path("state.yaml")
        ... )
        >>> new_state.current_story
        '2.4'
        >>> is_epic_complete
        False

    """
    # Step 1: Mark story as completed
    state_with_completion = complete_story(state)

    # Step 2: Check if this is the last story
    is_last = is_last_story_in_epic(state_with_completion, epic_stories)

    if is_last:
        # Epic complete - log and persist completed state
        logger.info(
            "Epic %s stories complete, retrospective needed",
            state.current_epic,
        )
        persist_story_completion(state_with_completion, state_path)
        return state_with_completion, True

    # Step 3: Not last story - advance to next
    advanced_state = advance_to_next_story(state_with_completion, epic_stories)

    # Type narrowing: If is_last=False, advance_to_next_story never returns None
    # Use explicit exception instead of assertion (assertions stripped with -O flag)
    if advanced_state is None:
        raise StateError(
            f"Logic error: advance_to_next_story returned None for non-last story "
            f"{state.current_story} in epic {state.current_epic}"
        )

    # Step 4: Persist FINAL state (single atomic persist)
    persist_story_completion(advanced_state, state_path)

    return advanced_state, False
