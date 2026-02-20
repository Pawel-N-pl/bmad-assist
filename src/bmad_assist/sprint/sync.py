"""State to SprintStatus synchronization module.

This module implements one-way synchronization from internal state.yaml to
sprint-status.yaml, ensuring the BMAD artifact reflects current loop progress.

Architecture:
- state.yaml is the SOURCE OF TRUTH (runtime authority, crash recovery)
- sprint-status.yaml is a VIEW (human-readable BMAD artifact)
- Sync is strictly ONE-WAY: state → sprint-status (NEVER reverse)

The sync is triggered after state saves to keep sprint-status current with
the development loop progress.

Public API:
    - SyncResult: Dataclass with sync statistics and errors
    - SyncCallback: Type alias for callback functions
    - PHASE_TO_STATUS: Mapping from Phase to sprint-status ValidStatus
    - sync_state_to_sprint: Core sync function (returns updated SprintStatus)
    - trigger_sync: Convenience function (load, sync, write atomically)
    - register_sync_callback: Register callback for after-save hooks
    - clear_sync_callbacks: Clear callbacks (for test isolation)
    - invoke_sync_callbacks: Invoke all registered callbacks
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from bmad_assist.core.state import Phase
from bmad_assist.sprint.models import SprintStatus, SprintStatusEntry, ValidStatus

if TYPE_CHECKING:
    from bmad_assist.core.state import State

logger = logging.getLogger(__name__)

__all__ = [
    "SyncResult",
    "SyncCallback",
    "PHASE_TO_STATUS",
    "sync_state_to_sprint",
    "trigger_sync",
    "register_sync_callback",
    "clear_sync_callbacks",
    "invoke_sync_callbacks",
    "get_sync_callbacks",
]


# =============================================================================
# Type Aliases
# =============================================================================

SyncCallback = Callable[["State", Path], None]
"""Type alias for sync callbacks invoked after state saves.

Callback signature: (state: State, project_root: Path) -> None
Callbacks must NOT raise exceptions (they are caught and logged).
"""


# =============================================================================
# SyncResult Dataclass (AC8)
# =============================================================================


@dataclass(frozen=True)
class SyncResult:
    """Result of state-to-sprint synchronization.

    Frozen dataclass providing statistics about the sync operation.
    All tuple fields allow hashability and immutability.

    Attributes:
        synced_stories: Count of stories with status updated.
        synced_epics: Count of epics with status updated.
        skipped_keys: Story/epic IDs from state not found in sprint-status.
        errors: Any errors encountered during sync.

    Example:
        >>> result = SyncResult(synced_stories=3, synced_epics=1)
        >>> result.summary()
        'Synced 3 stories, 1 epics'

    """

    synced_stories: int = 0
    synced_epics: int = 0
    skipped_keys: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    def __repr__(self) -> str:
        """Return debug-friendly representation."""
        return (
            f"SyncResult(synced_stories={self.synced_stories}, "
            f"synced_epics={self.synced_epics}, "
            f"skipped={len(self.skipped_keys)}, errors={len(self.errors)})"
        )

    def summary(self) -> str:
        """Return human-readable summary.

        Returns:
            Summary string for logging.

        Example:
            >>> result = SyncResult(synced_stories=3, synced_epics=1, skipped_keys=("99.1",))
            >>> result.summary()
            'Synced 3 stories, 1 epics. Skipped 1 missing keys'

        """
        parts = [f"Synced {self.synced_stories} stories, {self.synced_epics} epics"]
        if self.skipped_keys:
            parts.append(f"Skipped {len(self.skipped_keys)} missing keys")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return ". ".join(parts)


# =============================================================================
# Phase to Status Mapping (AC2, AC3)
# =============================================================================

# Mapping from workflow Phase to sprint-status ValidStatus
# Rationale documented in story Dev Notes section
PHASE_TO_STATUS: dict[Phase, ValidStatus] = {
    # Early phases: story being drafted/validated
    Phase.CREATE_STORY: "in-progress",
    Phase.VALIDATE_STORY: "in-progress",
    Phase.VALIDATE_STORY_SYNTHESIS: "in-progress",
    # Development phases
    Phase.ATDD: "in-progress",
    Phase.TEA_FRAMEWORK: "in-progress",  # Epic setup phase
    Phase.TEA_CI: "in-progress",  # Epic setup phase
    Phase.TEA_TEST_DESIGN: "in-progress",  # Epic setup phase (dual-level)
    Phase.TEA_AUTOMATE: "in-progress",  # Epic setup phase (after test_design)
    Phase.DEV_STORY: "in-progress",
    # Review phases: code review in progress
    Phase.CODE_REVIEW: "review",
    Phase.CODE_REVIEW_SYNTHESIS: "review",
    Phase.TEST_REVIEW: "review",
    Phase.TRACE: "review",  # Traceability review at epic end
    Phase.TEA_NFR_ASSESS: "review",  # NFR assessment at epic end
    # Completion: story done only at retrospective
    Phase.RETROSPECTIVE: "done",
    # QA phases (experimental): stories already done at this point
    Phase.QA_PLAN_GENERATE: "done",
    Phase.QA_PLAN_EXECUTE: "done",
    Phase.QA_REMEDIATE: "done",
    Phase.HARDENING: "done",
}
"""Mapping from workflow Phase to sprint-status ValidStatus.

Rationale:
- CREATE_STORY through DEV_STORY → "in-progress" (story being worked on)
- CODE_REVIEW through TEST_REVIEW → "review" (code under review)
- RETROSPECTIVE → "done" (story complete, part of epic retrospective)

The "done" status is only set at RETROSPECTIVE because:
1. Even after CODE_REVIEW_SYNTHESIS, the story may need fixes
2. TEST_REVIEW can also require changes
3. Only at RETROSPECTIVE is the story truly complete
"""


# =============================================================================
# Story Key Finder (AC7)
# =============================================================================


def _find_story_key(
    story_id: str,
    entries: dict[str, SprintStatusEntry],
    prefix_map: dict[str, str] | None = None,
) -> str | None:
    """Find sprint-status key matching state story ID.

    Converts state format (e.g., "20.9") to prefix (e.g., "20-9") and searches
    entries for a matching key. Handles both numeric and string epic IDs.

    When prefix_map is provided, uses O(1) lookup instead of O(N) search.

    Args:
        story_id: Story ID from state (e.g., "20.9", "testarch.1").
        entries: Sprint-status entries dict.
        prefix_map: Optional pre-computed prefix-to-key map for O(1) lookup.

    Returns:
        Full sprint-status key if found, None otherwise.

    Examples:
        >>> entries = {"20-9-sync": SprintStatusEntry(...)}
        >>> _find_story_key("20.9", entries)
        '20-9-sync'
        >>> _find_story_key("testarch.1", entries)
        'testarch-1-config'  # if key exists
        >>> _find_story_key("99.1", entries)
        None  # not found

    """
    if not story_id:
        return None

    # Convert dot to dash: "20.9" → "20-9"
    prefix = story_id.replace(".", "-")

    # Fast path: use prefix map if available
    if prefix_map is not None:
        return prefix_map.get(prefix)

    # Fallback: linear search (for standalone usage)
    for key in entries:
        # Match "20-9-*" pattern (prefix followed by dash and more)
        if key.startswith(f"{prefix}-"):
            return key
        # Also match exact prefix (edge case: key == prefix)
        if key == prefix:
            return key

    return None


def _find_epic_key(
    epic_id: int | str,
    entries: dict[str, SprintStatusEntry],
) -> str | None:
    """Find sprint-status key for an epic entry.

    Args:
        epic_id: Epic ID from state (int or string, e.g., 12 or "testarch").
        entries: Sprint-status entries dict.

    Returns:
        Epic key (e.g., "epic-12") if found in entries, None otherwise.

    """
    epic_key = f"epic-{epic_id}"
    return epic_key if epic_key in entries else None


# =============================================================================
# Core Sync Function (AC1-AC5, AC7)
# =============================================================================


def _build_story_prefix_map(
    entries: dict[str, SprintStatusEntry],
) -> dict[str, str]:
    """Build O(1) lookup map from story ID prefix to full key.

    Pre-computes mapping for efficient lookups in sync operations.

    Args:
        entries: Sprint-status entries dict.

    Returns:
        Dict mapping normalized prefix (e.g., "20-9") to full key (e.g., "20-9-sync").

    """
    prefix_map: dict[str, str] = {}
    for key in entries:
        # Extract prefix: "20-9-sync" → "20-9", "testarch-1-config" → "testarch-1"
        parts = key.split("-", 2)
        if len(parts) >= 2:
            prefix = f"{parts[0]}-{parts[1]}"
            # First match wins (handles duplicates)
            if prefix not in prefix_map:
                prefix_map[prefix] = key
    return prefix_map


def sync_state_to_sprint(
    state: State,
    sprint_status: SprintStatus,
) -> tuple[SprintStatus, SyncResult]:
    """Synchronize internal state to sprint-status.

    One-way sync: state.yaml is the SOURCE OF TRUTH, sprint-status is updated
    to reflect current state. NEVER modifies state based on sprint-status.

    Updates:
    1. Current story status based on current_phase (via PHASE_TO_STATUS)
    2. All completed_stories marked as "done"
    3. All completed_epics marked as "done"

    Args:
        state: Current State instance (source of truth).
        sprint_status: SprintStatus to update (will be copied, not mutated).

    Returns:
        Tuple of (updated SprintStatus, SyncResult with statistics).

    Example:
        >>> from bmad_assist.core.state import State, Phase
        >>> state = State(
        ...     current_story="20.9",
        ...     current_phase=Phase.DEV_STORY,
        ...     completed_stories=["20.1", "20.2"],
        ... )
        >>> updated, result = sync_state_to_sprint(state, sprint_status)
        >>> result.synced_stories
        3  # current + 2 completed

    """
    # Create shallow copy of entries dict
    # SprintStatusEntry is immutable Pydantic model, so shallow copy is safe
    new_entries = dict(sprint_status.entries)

    # Build O(1) prefix lookup map to avoid O(N*M) searches
    prefix_map = _build_story_prefix_map(new_entries)

    synced_stories = 0
    synced_epics = 0
    skipped_keys: list[str] = []

    # Step 0: Mark current epic as in-progress (if working on it)
    if state.current_epic is not None and state.current_epic not in state.completed_epics:
        epic_key = _find_epic_key(state.current_epic, new_entries)
        if epic_key is not None:
            entry = new_entries[epic_key]
            if entry.status not in ("done", "in-progress"):
                new_entries[epic_key] = SprintStatusEntry(
                    key=entry.key,
                    status="in-progress",
                    entry_type=entry.entry_type,
                    source=entry.source,
                    comment=entry.comment,
                )
                logger.debug("Marked current epic %s as in-progress", epic_key)
                synced_epics += 1

    # Step 1: Update current story status based on phase (AC2)
    if state.current_story is not None and state.current_phase is not None:
        target_status = PHASE_TO_STATUS.get(state.current_phase)
        if target_status is not None:
            story_key = _find_story_key(state.current_story, new_entries, prefix_map)
            if story_key is not None:
                entry = new_entries[story_key]
                if entry.status != target_status:
                    new_entries[story_key] = SprintStatusEntry(
                        key=entry.key,
                        status=target_status,
                        entry_type=entry.entry_type,
                        source=entry.source,
                        comment=entry.comment,
                    )
                    logger.debug(
                        "Updated %s status: %s → %s",
                        story_key,
                        entry.status,
                        target_status,
                    )
                synced_stories += 1
            else:
                logger.warning(
                    "Current story '%s' not found in sprint-status, skipping",
                    state.current_story,
                )
                skipped_keys.append(state.current_story)

    # Step 2: Mark completed_stories as done (AC3)
    # Skip current_story if already counted in Step 1 to avoid double-counting
    for story_id in state.completed_stories:
        if story_id == state.current_story:
            # Already counted in Step 1, but still update status to done
            story_key = _find_story_key(story_id, new_entries, prefix_map)
            if story_key is not None:
                entry = new_entries[story_key]
                if entry.status != "done":
                    new_entries[story_key] = SprintStatusEntry(
                        key=entry.key,
                        status="done",
                        entry_type=entry.entry_type,
                        source=entry.source,
                        comment=entry.comment,
                    )
                    logger.debug("Marked completed story %s as done", story_key)
            continue  # Don't increment synced_stories again
        story_key = _find_story_key(story_id, new_entries, prefix_map)
        if story_key is not None:
            entry = new_entries[story_key]
            if entry.status != "done":
                new_entries[story_key] = SprintStatusEntry(
                    key=entry.key,
                    status="done",
                    entry_type=entry.entry_type,
                    source=entry.source,
                    comment=entry.comment,
                )
                logger.debug("Marked completed story %s as done", story_key)
            synced_stories += 1
        else:
            logger.warning(
                "Completed story '%s' not found in sprint-status, skipping",
                story_id,
            )
            skipped_keys.append(story_id)

    # Step 3: Mark completed_epics as done (AC4)
    for epic_id in state.completed_epics:
        epic_key = _find_epic_key(epic_id, new_entries)
        if epic_key is not None:
            entry = new_entries[epic_key]
            if entry.status != "done":
                new_entries[epic_key] = SprintStatusEntry(
                    key=entry.key,
                    status="done",
                    entry_type=entry.entry_type,
                    source=entry.source,
                    comment=entry.comment,
                )
                logger.debug("Marked completed epic %s as done", epic_key)
            synced_epics += 1
        else:
            logger.warning(
                "Completed epic 'epic-%s' not found in sprint-status, skipping",
                epic_id,
            )
            skipped_keys.append(f"epic-{epic_id}")

        # Step 3.5: Mark epic retrospective entry as done
        retro_key = f"epic-{epic_id}-retrospective"
        if retro_key in new_entries:
            retro_entry = new_entries[retro_key]
            if retro_entry.status != "done":
                new_entries[retro_key] = SprintStatusEntry(
                    key=retro_entry.key,
                    status="done",
                    entry_type=retro_entry.entry_type,
                    source=retro_entry.source,
                    comment=retro_entry.comment,
                )
                logger.debug("Marked completed epic retrospective %s as done", retro_key)

    # Step 3.6: Mark current epic's retrospective as in-progress when in RETROSPECTIVE phase
    if (
        state.current_phase == Phase.RETROSPECTIVE
        and state.current_epic is not None
        and state.current_epic not in state.completed_epics
    ):
        retro_key = f"epic-{state.current_epic}-retrospective"
        if retro_key in new_entries:
            retro_entry = new_entries[retro_key]
            if retro_entry.status not in ("done", "in-progress"):
                new_entries[retro_key] = SprintStatusEntry(
                    key=retro_entry.key,
                    status="in-progress",
                    entry_type=retro_entry.entry_type,
                    source=retro_entry.source,
                    comment=retro_entry.comment,
                )
                logger.debug("Marked current epic retrospective %s as in-progress", retro_key)

    # Build result
    result = SyncResult(
        synced_stories=synced_stories,
        synced_epics=synced_epics,
        skipped_keys=tuple(skipped_keys),
        errors=(),
    )

    # Create new SprintStatus with updated entries
    updated_status = SprintStatus(
        metadata=sprint_status.metadata,
        entries=new_entries,
    )

    return updated_status, result


# =============================================================================
# Trigger Sync Convenience Function (AC6)
# =============================================================================


def trigger_sync(state: State, project_root: Path) -> SyncResult:
    """Load, sync, and write sprint-status atomically.

    Convenience function that handles the full sync cycle:
    1. Load existing sprint-status (or create empty)
    2. Apply state changes via sync_state_to_sprint()
    3. Write back with atomic writer (comment preservation)

    Args:
        state: Current State instance.
        project_root: Project root directory.

    Returns:
        SyncResult with sync statistics.

    Raises:
        StateError: If write fails (from writer module).

    Example:
        >>> result = trigger_sync(state, Path("/my/project"))
        >>> print(result.summary())
        'Synced 3 stories, 1 epics'

    """
    from bmad_assist.core.paths import get_paths
    from bmad_assist.sprint.parser import parse_sprint_status
    from bmad_assist.sprint.writer import write_sprint_status

    # Find sprint-status location (uses paths singleton for external paths support)
    try:
        sprint_path = get_paths().sprint_status_file
    except RuntimeError:
        # Fallback for tests or early startup when singleton not initialized
        # Check multiple locations for consistency with state_reader.py
        fallback_candidates = [
            project_root
            / "_bmad-output"
            / "implementation-artifacts"
            / "sprint-status.yaml",  # New # noqa: E501
            project_root / "docs" / "sprint-artifacts" / "sprint-status.yaml",  # Legacy
            project_root / "docs" / "sprint-status.yaml",  # Legacy (direct)
        ]
        # Use first existing, or default to new location for creation
        sprint_path = next(
            (p for p in fallback_candidates if p.exists()),
            fallback_candidates[0],  # Default to new location
        )

    # Load or create empty sprint-status
    file_existed = sprint_path.exists()
    if file_existed:
        sprint_status = parse_sprint_status(sprint_path)
        # Safety check: if file has content but parser returned empty, don't overwrite
        # This prevents data loss on corrupted files
        if not sprint_status.entries and sprint_path.stat().st_size > 0:
            logger.warning(
                "Sprint-status file appears corrupted (has content but no entries parsed). "
                "Skipping sync to prevent data loss: %s",
                sprint_path,
            )
            return SyncResult(errors=(f"Corrupted file: {sprint_path}",))
    else:
        sprint_status = SprintStatus.empty(project=project_root.name)
        logger.info("Sprint-status not found, creating new: %s", sprint_path)

    # Sync
    updated_status, result = sync_state_to_sprint(state, sprint_status)

    # Write back atomically with comment preservation
    write_sprint_status(updated_status, sprint_path, preserve_comments=True)
    logger.info("Sprint sync complete: %s", result.summary())

    return result


# =============================================================================
# Callback Pattern for Loop Integration (AC9)
# =============================================================================

# Module-level callback registry
_sync_callbacks: list[SyncCallback] = []


def register_sync_callback(callback: SyncCallback) -> None:
    """Register callback to be invoked after state sync.

    Callbacks are invoked by invoke_sync_callbacks() after state saves.
    Exceptions in callbacks are caught and logged (WARNING), never propagated.

    Args:
        callback: Function with signature (state: State, project_root: Path) -> None.

    Example:
        >>> def my_callback(state, project_root):
        ...     result = trigger_sync(state, project_root)
        ...     print(f"Synced: {result.summary()}")
        >>> register_sync_callback(my_callback)

    """
    _sync_callbacks.append(callback)
    callback_name = getattr(callback, "__name__", repr(callback))
    logger.debug("Registered sync callback: %s", callback_name)


def clear_sync_callbacks() -> None:
    """Clear all registered sync callbacks.

    Primarily for test isolation to prevent callbacks from leaking between tests.

    Example:
        >>> register_sync_callback(my_callback)
        >>> clear_sync_callbacks()
        >>> len(_sync_callbacks)
        0

    """
    _sync_callbacks.clear()
    logger.debug("Cleared all sync callbacks")


def get_sync_callbacks() -> list[SyncCallback]:
    """Get a copy of the registered sync callbacks list.

    Returns a copy to prevent external modification of the internal list.
    Used by repair module to check if callbacks are already registered.

    Returns:
        Copy of the callbacks list.

    Example:
        >>> callbacks = get_sync_callbacks()
        >>> len(callbacks)
        0
        >>> register_sync_callback(my_callback)
        >>> len(get_sync_callbacks())
        1

    """
    return list(_sync_callbacks)


def invoke_sync_callbacks(state: State, project_root: Path) -> None:
    """Invoke all registered sync callbacks.

    Each callback is wrapped in try/except - exceptions are logged at WARNING
    level but NEVER propagated. This ensures sync failures don't break state saves.

    Args:
        state: Current State instance.
        project_root: Project root directory.

    Example:
        >>> # In loop.py after save_state()
        >>> save_state(state, state_path)
        >>> invoke_sync_callbacks(state, project_root)

    """
    for callback in _sync_callbacks:
        try:
            callback(state, project_root)
        except Exception as e:
            # AC9: Exceptions caught and logged, never propagated
            logger.warning(
                "Sync callback '%s' failed: %s",
                getattr(callback, "__name__", "unknown"),
                e,
            )
