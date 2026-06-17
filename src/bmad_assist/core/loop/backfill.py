"""Backfill mode: detect and queue missed/skipped stories.

When --backfill is enabled, after completing the current story the runner
scans for "gap" stories — stories that exist in the epic list but were
never completed and come before the current forward position. These are
queued for execution before normal forward advancement resumes.

Gap stories arise when:
- Sub-stories (3a, 3a-ii, 4b) were not parsed by older regex
- Stories were added to epics after the epic was partially implemented
- Stories were skipped due to parser bugs

Stories with "deferred" status in sprint-status are excluded — they
represent intentionally postponed work.
"""

import logging
from collections.abc import Callable

from bmad_assist.bmad.state_reader import _natural_story_sort_key
from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

# Statuses that indicate a story should NOT be backfilled
_SKIP_STATUSES = {"done", "deferred", "skipped", "cancelled"}


def detect_backfill_stories(
    completed_stories: list[str],
    current_story: str,
    epic_list: list[EpicId],
    epic_stories_loader: Callable[[EpicId], list[str]],
    sprint_statuses: dict[str, str] | None = None,
) -> list[str]:
    """Detect stories that should be backfilled.

    Scans all stories across all epics and finds those that:
    1. Are NOT in completed_stories
    2. Come BEFORE current_story in natural sort order
    3. Are NOT marked as done/deferred/skipped in sprint-status

    Args:
        completed_stories: List of story IDs already completed.
        current_story: The story that was just completed (forward frontier).
        epic_list: Ordered list of all epic IDs.
        epic_stories_loader: Function to get stories for an epic.
        sprint_statuses: Optional dict mapping story IDs to statuses
            from sprint-status.yaml.

    Returns:
        Ordered list of story IDs to backfill, sorted in natural order.
        Empty list if no gaps found.

    """
    completed_set = set(completed_stories)
    if sprint_statuses is None:
        sprint_statuses = {}

    # Collect all stories across all epics in order
    all_stories: list[str] = []
    for epic_id in epic_list:
        stories = epic_stories_loader(epic_id)
        all_stories.extend(stories)

    # Find the position of current_story (the forward frontier)
    # Everything before this position is eligible for backfill
    frontier_key = _story_global_sort_key(current_story)

    gaps: list[str] = []
    for story_id in all_stories:
        # Must come before the frontier
        if _story_global_sort_key(story_id) >= frontier_key:
            continue

        # Must not be already completed
        if story_id in completed_set:
            continue

        # Must not be in a skip status
        status = sprint_statuses.get(story_id, "").lower()
        if status in _SKIP_STATUSES:
            continue

        gaps.append(story_id)

    # Sort gaps in natural order
    gaps.sort(key=_story_global_sort_key)

    if gaps:
        logger.info(
            "Backfill: detected %d gap stories before %s: %s",
            len(gaps),
            current_story,
            ", ".join(gaps),
        )

    return gaps


def _story_global_sort_key(story_id: str) -> tuple[int, int | str, tuple[int, str, list[str]]]:
    """Generate a global sort key for a story ID like '10.3a'.

    Combines epic number and story part for cross-epic ordering.
    """
    parts = story_id.split(".")
    if len(parts) != 2:
        return (0, 0, (0, "", []))

    epic_part = parts[0]
    try:
        epic_num = int(epic_part)
        return (0, epic_num, _natural_story_sort_key(parts[1]))
    except ValueError:
        return (1, epic_part, _natural_story_sort_key(parts[1]))
