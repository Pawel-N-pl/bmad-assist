"""Reconciliation engine for sprint-status 3-way merge.

This module provides the reconciliation engine that combines:
1. Existing sprint-status entries (from file)
2. Generated entries from epic files
3. Artifact evidence (code reviews, validations, retrospectives)

The reconciler applies type-specific merge rules:
- STANDALONE, MODULE_STORY, UNKNOWN: Preserve from existing (NEVER delete)
- EPIC_STORY: Merge with generated, apply evidence-based inference
- EPIC_META: Recalculate from story statuses
- RETROSPECTIVE: Preserve from existing

Public API:
    - StatusChange: Record of a single status change
    - ReconciliationResult: Full result with merged status and change log
    - ConflictResolution: Enum for conflict resolution strategies
    - reconcile: Main entry point for 3-way merge
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from bmad_assist.sprint.classifier import EntryType
from bmad_assist.sprint.inference import (
    InferenceConfidence,
    infer_epic_status,
    infer_story_status,
)
from bmad_assist.sprint.models import SprintStatus, SprintStatusEntry, ValidStatus

if TYPE_CHECKING:
    from bmad_assist.sprint.generator import GeneratedEntries
    from bmad_assist.sprint.scanner import ArtifactIndex

logger = logging.getLogger(__name__)

__all__ = [
    "StatusChange",
    "ReconciliationResult",
    "ConflictResolution",
    "reconcile",
    # Internal helpers exported for testing
    "STATUS_ORDER",
    "_is_status_advancement",
    "_sort_entries_by_epic_order",
    "_extract_epic_id_from_key",
    "_normalize_story_key",
    "_should_preserve_entry",
    "_merge_epic_story",
    "_recalculate_epic_meta",
    "_detect_removed_stories",
]


# ============================================================================
# ConflictResolution Enum
# ============================================================================


# Status progression order (higher = more advanced)
# Used for forward-only protection: status can only move forward, never backward
STATUS_ORDER: dict[str, int] = {
    "deferred": -1,
    "backlog": 0,
    "ready-for-dev": 1,
    "in-progress": 2,
    "blocked": 2,  # Same level as in-progress
    "review": 3,
    "done": 4,
}


def _is_status_advancement(old_status: str | None, new_status: str) -> bool:
    """Check if new_status is same or more advanced than old_status.

    Returns True if transition should be allowed (forward or same).
    Returns False if this would be a downgrade.

    Args:
        old_status: Current status (None if new entry).
        new_status: Proposed new status.

    Returns:
        True if transition is forward or same level, False if downgrade.

    Examples:
        >>> _is_status_advancement("backlog", "done")
        True
        >>> _is_status_advancement("done", "backlog")
        False
        >>> _is_status_advancement(None, "done")
        True

    """
    if old_status is None:
        return True
    old_order = STATUS_ORDER.get(old_status, 0)
    new_order = STATUS_ORDER.get(new_status, 0)
    return new_order >= old_order


class ConflictResolution(Enum):
    """Strategy for resolving conflicts between sources.

    EVIDENCE_WINS (default):
        When artifact evidence (code reviews, validations) indicates
        a different status than sprint-status file, use the evidence.
        Best for auto-repairing stale sprint-status files.

    PRESERVE_EXISTING:
        Keep the status from existing sprint-status file unless
        it contradicts explicit Status: field in story file.
        Best for manual override scenarios.

    Examples:
        >>> strategy = ConflictResolution.EVIDENCE_WINS
        >>> strategy.value
        'evidence_wins'

    """

    EVIDENCE_WINS = "evidence_wins"
    PRESERVE_EXISTING = "preserve_existing"


# ============================================================================
# StatusChange Dataclass
# ============================================================================


@dataclass(frozen=True)
class StatusChange:
    """Record of a status change during reconciliation.

    Immutable dataclass representing a single change made during the
    reconciliation process. Used for logging, reporting, and audit trail.

    Attributes:
        key: Sprint-status key that changed.
        old_status: Previous status (None if new entry).
        new_status: New status after reconciliation.
        reason: Human-readable reason for change.
        confidence: Inference confidence if from evidence.
        entry_type: Type of entry that changed.

    Examples:
        >>> change = StatusChange(
        ...     key="20-1-setup",
        ...     old_status="backlog",
        ...     new_status="done",
        ...     reason="master_review_exists",
        ...     confidence=InferenceConfidence.STRONG,
        ...     entry_type=EntryType.EPIC_STORY,
        ... )
        >>> change.as_log_line()
        "20-1-setup: backlog → done (STRONG) [master_review_exists]"

    """

    key: str
    old_status: ValidStatus | None
    new_status: ValidStatus
    reason: str
    confidence: InferenceConfidence | None = None
    entry_type: EntryType = EntryType.UNKNOWN

    def __repr__(self) -> str:
        """Return debug-friendly representation."""
        old = self.old_status or "(new)"
        return f"StatusChange(key={self.key!r}, {old} → {self.new_status}, reason={self.reason!r})"

    def as_log_line(self) -> str:
        """Format as single log line for logging/display.

        Returns:
            Formatted string suitable for logging.

        Example:
            >>> change.as_log_line()
            "20-1-setup: backlog → done (STRONG) [master_review_exists]"

        """
        old = self.old_status or "(new)"
        conf = f" ({self.confidence.name})" if self.confidence else ""
        return f"{self.key}: {old} → {self.new_status}{conf} [{self.reason}]"


# ============================================================================
# ReconciliationResult Dataclass
# ============================================================================


@dataclass
class ReconciliationResult:
    """Result of sprint-status reconciliation.

    Container for the reconciled sprint status along with metadata about
    the reconciliation process including counts and change log.

    Attributes:
        status: Reconciled SprintStatus.
        changes: List of all changes made during reconciliation.
        preserved_count: Entries preserved unchanged.
        updated_count: Entries with status updated.
        added_count: New entries added.
        removed_count: Entries marked as deferred (removed from epics).

    Examples:
        >>> result = reconcile(existing, generated, index)
        >>> result.summary()
        "Reconciliation: 42 preserved, 3 updated, 2 added, 0 removed"
        >>> len(result.changes)
        5

    """

    status: SprintStatus
    changes: list[StatusChange] = field(default_factory=list)
    preserved_count: int = 0
    updated_count: int = 0
    added_count: int = 0
    removed_count: int = 0

    def summary(self) -> str:
        """Return human-readable summary of reconciliation.

        Returns:
            Summary string with counts of each operation type.

        Example:
            >>> result.summary()
            "Reconciliation: 42 preserved, 3 updated, 2 added, 0 removed"

        """
        return (
            f"Reconciliation: {self.preserved_count} preserved, "
            f"{self.updated_count} updated, {self.added_count} added, "
            f"{self.removed_count} removed"
        )


# ============================================================================
# Helper Functions
# ============================================================================


def _sort_entries_by_epic_order(
    entries: dict[str, SprintStatusEntry],
) -> dict[str, SprintStatusEntry]:
    """Sort entries by epic grouping: epic-X, X-* stories, epic-X-retrospective.

    Preserves standalone entries at the end in their relative position.
    Uses natural sort for numeric epics, alphabetical for string epics.

    Args:
        entries: Dict of key -> SprintStatusEntry to sort.

    Returns:
        New OrderedDict with entries sorted by epic grouping.

    """

    def _get_epic_id_from_key(key: str) -> str | int | None:
        """Extract epic ID from key for sorting."""
        # epic-X pattern (meta or retrospective)
        if key.startswith("epic-"):
            rest = key[5:]  # Remove "epic-" prefix
            # Handle retrospective: epic-12-retrospective -> 12
            if "-retrospective" in rest:
                rest = rest.replace("-retrospective", "")
            try:
                return int(rest)
            except ValueError:
                return rest
        # Story pattern: X-Y-slug
        match = re.match(r"^([a-z0-9][a-z0-9-]*?)-(\d+)(?:-|$)", key, re.IGNORECASE)
        if match:
            epic_str = match.group(1)
            try:
                return int(epic_str)
            except ValueError:
                return epic_str
        return None

    def _get_story_num(key: str) -> int:
        """Extract story number from key for sorting within epic."""
        match = re.match(r"^[a-z0-9][a-z0-9-]*?-(\d+)(?:-|$)", key, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 0

    def _sort_key(item: tuple[str, SprintStatusEntry]) -> tuple[int, str | int, int, str]:
        """Generate sort key for an entry.

        Returns tuple: (group_order, epic_id, entry_order_within_epic, key)
        - group_order: 0 for numeric epics, 1 for string epics, 2 for standalone
        - epic_id: numeric or string epic id (for sorting within group)
        - entry_order_within_epic: 0=meta, 1-999=story, 1000=retrospective
        - key: original key for stable sort
        """
        key, _entry = item
        epic_id = _get_epic_id_from_key(key)

        # Standalone entries go to the end
        if epic_id is None:
            return (2, "", 0, key)

        # Determine group order (numeric first, then string)
        if isinstance(epic_id, int):
            group_order = 0
            epic_sort_key: str | int = epic_id
        else:
            group_order = 1
            epic_sort_key = epic_id

        # Determine entry order within epic
        if key == f"epic-{epic_id}":
            entry_order = 0  # Epic meta first
        elif key.endswith("-retrospective"):
            entry_order = 1000  # Retrospective last
        else:
            entry_order = _get_story_num(key)  # Stories in the middle

        return (group_order, epic_sort_key, entry_order, key)

    # Sort and return new dict
    sorted_items = sorted(entries.items(), key=_sort_key)
    return dict(sorted_items)


def _extract_epic_id_from_key(key: str) -> str | int | None:
    """Extract epic ID from story key pattern.

    Parses story keys like "20-1-setup" or "testarch-1-config" to extract
    the epic ID component.

    Args:
        key: Story key in format {epic}-{story}-{slug}.

    Returns:
        Epic ID as int if numeric, str otherwise. None if pattern doesn't match.

    Examples:
        >>> _extract_epic_id_from_key("20-1-setup")
        20
        >>> _extract_epic_id_from_key("testarch-1-config")
        'testarch'
        >>> _extract_epic_id_from_key("standalone-01-refactor")
        'standalone'

    """
    # Match pattern: {epic_id}-{story_num}[-...] (slug is optional)
    match = re.match(r"^([a-z0-9][a-z0-9-]*?)-(\d+)(?:-|$)", key, re.IGNORECASE)
    if match:
        epic_str = match.group(1)
        try:
            return int(epic_str)
        except ValueError:
            return epic_str
    return None


def _normalize_story_key(key: str) -> str:
    """Normalize story key to short format for matching.

    Converts full keys like "20-1-setup" to short format "20-1".

    Args:
        key: Full or short story key.

    Returns:
        Short story key in format "{epic}-{story}".

    Examples:
        >>> _normalize_story_key("20-1-setup")
        '20-1'
        >>> _normalize_story_key("testarch-1-config")
        'testarch-1'

    """
    match = re.match(r"^([a-z0-9-]+?)-(\d+)", key, re.IGNORECASE)
    if match:
        return f"{match.group(1).lower()}-{match.group(2)}"
    return key.lower()


def _should_preserve_entry(entry_type: EntryType) -> bool:
    """Check if entry type should be preserved without modification.

    These entry types are NEVER deleted and only copied from existing:
    - STANDALONE: Only exists in sprint-status
    - MODULE_STORY: From different source than main epics
    - UNKNOWN: Safe default to prevent data loss
    - RETROSPECTIVE: Status should be preserved

    Args:
        entry_type: Type of the entry.

    Returns:
        True if entry should be preserved unconditionally.

    """
    return entry_type in (
        EntryType.STANDALONE,
        EntryType.MODULE_STORY,
        EntryType.UNKNOWN,
        EntryType.RETROSPECTIVE,
        EntryType.HARDENING,
    )


def _merge_epic_story(
    existing_entry: SprintStatusEntry | None,
    generated_entry: SprintStatusEntry | None,
    story_key: str,
    index: ArtifactIndex,
    strategy: ConflictResolution,
) -> tuple[SprintStatusEntry, StatusChange | None]:
    """Merge a single EPIC_STORY entry using evidence-based inference.

    Applies the decision tree:
    1. Check story file Status: field (EXPLICIT confidence) → use it
    2. Check artifact evidence via infer_story_status() → if MEDIUM+, use it
    3. Apply conflict resolution strategy

    Args:
        existing_entry: Entry from existing sprint-status (may be None).
        generated_entry: Entry from epic generation (may be None).
        story_key: Story key for lookup.
        index: ArtifactIndex for evidence lookup.
        strategy: Conflict resolution strategy.

    Returns:
        Tuple of (merged_entry, status_change or None if no change).

    Raises:
        ValueError: If both existing_entry and generated_entry are None.

    """
    if existing_entry is None and generated_entry is None:
        raise ValueError(f"Both entries are None for key: {story_key}")

    # Determine the base entry
    old_status: ValidStatus | None = None
    if existing_entry is not None:
        old_status = existing_entry.status

    # Step 1: Check for explicit status in story file (EXPLICIT confidence)
    inferred_status, inferred_confidence = infer_story_status(story_key, index)

    # Track whether to report confidence (None when not from inference)
    report_confidence: InferenceConfidence | None = None

    if inferred_confidence == InferenceConfidence.EXPLICIT:
        # EXPLICIT always wins
        new_status = inferred_status
        reason = "explicit_status_in_story_file"
        report_confidence = inferred_confidence
    elif inferred_confidence >= InferenceConfidence.MEDIUM:
        # Evidence-based inference with good confidence
        if strategy == ConflictResolution.EVIDENCE_WINS:
            # Forward-only: only apply if advancement or same level
            if _is_status_advancement(old_status, inferred_status):
                new_status = inferred_status
                reason = f"evidence_inference_{inferred_confidence.name.lower()}"
                report_confidence = inferred_confidence
            else:
                # Preserve existing status - don't downgrade
                # Note: old_status cannot be None here because _is_status_advancement(None, x)
                # always returns True, so we only reach this branch when old_status exists
                assert old_status is not None
                new_status = old_status
                reason = "preserve_higher_status_forward_only"
                report_confidence = None
        elif existing_entry is not None:
            # PRESERVE_EXISTING: keep existing unless no entry
            new_status = existing_entry.status
            reason = "preserve_existing"
            report_confidence = None  # Not from inference
        else:
            # No existing, use inferred
            new_status = inferred_status
            reason = f"evidence_inference_{inferred_confidence.name.lower()}"
            report_confidence = inferred_confidence
    else:
        # Low confidence (WEAK or NONE)
        if existing_entry is not None:
            new_status = existing_entry.status
            reason = "preserve_existing_low_confidence"
            report_confidence = None
        elif generated_entry is not None:
            new_status = generated_entry.status
            reason = "from_epic_definition"
            report_confidence = None
        else:
            new_status = "backlog"
            reason = "default_backlog"
            report_confidence = None

    # Build the result entry
    source_entry = existing_entry or generated_entry
    assert source_entry is not None  # At least one must exist

    result_entry = SprintStatusEntry(
        key=source_entry.key,
        status=new_status,
        entry_type=EntryType.EPIC_STORY,
        source="reconciled",
        comment=existing_entry.comment if existing_entry else None,
    )

    # Generate change record if status changed
    change: StatusChange | None = None
    if old_status != new_status or existing_entry is None:
        change = StatusChange(
            key=source_entry.key,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            confidence=report_confidence,
            entry_type=EntryType.EPIC_STORY,
        )

    return result_entry, change


def _has_explicit_non_done_stories(
    epic_id: str | int,
    result_entries: dict[str, SprintStatusEntry],
    index: ArtifactIndex,
) -> bool:
    """Check if any stories in the epic have explicit non-done statuses.

    This detects when stories have been explicitly marked as not done via
    their Status: field in the story file, which should trigger epic downgrade
    even if the epic was previously marked as done.

    Args:
        epic_id: Epic identifier (int or str).
        result_entries: Current result entries dict for story status lookup.
        index: ArtifactIndex for story status lookup.

    Returns:
        True if any story has an explicit non-done status.

    """
    from bmad_assist.sprint.inference import InferenceConfidence, infer_story_status_detailed

    prefix_pattern = re.compile(rf"^{re.escape(str(epic_id))}-(\d+)(?:-|$)")

    for key, entry in result_entries.items():
        if (
            entry.entry_type in (EntryType.EPIC_STORY, EntryType.MODULE_STORY)
            and prefix_pattern.match(key)
            and entry.status != "done"
        ):
            result = infer_story_status_detailed(key, index)
            # EXPLICIT confidence means Status: field is set in story file
            if result.confidence == InferenceConfidence.EXPLICIT:
                logger.debug(
                    "Story %s has explicit non-done status '%s' - epic should downgrade",
                    key,
                    entry.status,
                )
                return True
    return False


def _recalculate_epic_meta(
    epic_id: str | int,
    result_entries: dict[str, SprintStatusEntry],
    index: ArtifactIndex,
    existing_entry: SprintStatusEntry | None,
) -> tuple[SprintStatusEntry, StatusChange | None]:
    """Recalculate epic meta entry status from story statuses.

    Uses infer_epic_status() to determine the overall epic status based on:
    1. Retrospective exists → done (STRONG)
    2. All stories done → done (MEDIUM)
    3. Any story done → in-progress (MEDIUM)
    4. Any active stories → in-progress (MEDIUM)
    5. Default → backlog

    Args:
        epic_id: Epic identifier (int or str).
        result_entries: Current result entries dict for story status lookup.
        index: ArtifactIndex for retrospective check.
        existing_entry: Existing epic meta entry (may be None).

    Returns:
        Tuple of (epic_meta_entry, status_change or None).

    """
    epic_key = f"epic-{epic_id}"
    old_status = existing_entry.status if existing_entry else None

    # Build story_statuses dict from result entries
    story_statuses: dict[str, ValidStatus] = {}
    # Pattern matches both full keys (20-1-setup) and short keys (20-1)
    prefix_pattern = re.compile(rf"^{re.escape(str(epic_id))}-(\d+)(?:-|$)")

    for key, entry in result_entries.items():
        if entry.entry_type in (
            EntryType.EPIC_STORY,
            EntryType.MODULE_STORY,
        ) and prefix_pattern.match(key):
            story_statuses[key] = entry.status

    # Use inference module for epic status
    new_status, confidence = infer_epic_status(epic_id, index, story_statuses)

    # Don't downgrade 'done' epics without STRONG evidence (e.g., retrospective contradiction)
    # This prevents completed epics from being marked as in-progress due to:
    # - Deferred stories that were removed from epic
    # - Missing artifact evidence during merge-only operations
    # - Story status discrepancies that don't indicate actual regression
    #
    # EXCEPTION: If any story has EXPLICIT non-done status (from Status: field),
    # allow the downgrade. This handles cases where sprint-planning or correct-course
    # has identified stories that are legitimately not done.
    if old_status == "done" and new_status != "done" and confidence < InferenceConfidence.STRONG:
        # Check for explicit non-done story statuses
        if _has_explicit_non_done_stories(epic_id, result_entries, index):
            logger.debug(
                "Allowing epic %s downgrade to '%s' - explicit non-done stories found",
                epic_id,
                new_status,
            )
            # Keep the inferred status (don't preserve as done)
        else:
            logger.debug(
                "Preserving epic %s status 'done' - would downgrade to '%s' with %s confidence",
                epic_id,
                new_status,
                confidence.name,
            )
            new_status = "done"
            confidence = InferenceConfidence.WEAK  # Mark as preserved, not inferred

    result_entry = SprintStatusEntry(
        key=epic_key,
        status=new_status,
        entry_type=EntryType.EPIC_META,
        source="reconciled",
        comment=existing_entry.comment if existing_entry else None,
    )

    # Generate change record if status changed or new entry
    change: StatusChange | None = None
    if old_status != new_status or existing_entry is None:
        reason = "recalculated_from_stories"
        if index.has_retrospective(epic_id):
            reason = "retrospective_exists"
        change = StatusChange(
            key=epic_key,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            confidence=confidence,
            entry_type=EntryType.EPIC_META,
        )

    return result_entry, change


def _detect_removed_stories(
    existing_epic_stories: dict[str, SprintStatusEntry],
    generated_short_keys: set[str],
) -> list[tuple[str, SprintStatusEntry, StatusChange]]:
    """Detect stories that were removed from epics.

    Finds EPIC_STORY entries in existing that are not in generated.
    These are marked as 'deferred' with reason "story_removed_from_epic".

    Uses short key matching (e.g., "12-4") to handle slug variations.

    Args:
        existing_epic_stories: Dict of existing EPIC_STORY entries.
        generated_short_keys: Set of SHORT keys from generated entries.

    Returns:
        List of (key, updated_entry, change) tuples for removed stories.

    """
    removed: list[tuple[str, SprintStatusEntry, StatusChange]] = []

    for key, entry in existing_epic_stories.items():
        short_key = _normalize_story_key(key)
        if short_key not in generated_short_keys:
            # Story was removed from epic definition
            logger.warning(
                "Story %s removed from epics - marking as deferred",
                key,
            )

            updated_entry = SprintStatusEntry(
                key=entry.key,
                status="deferred",
                entry_type=entry.entry_type,
                source="reconciled",
                comment=entry.comment,
            )

            change = StatusChange(
                key=key,
                old_status=entry.status,
                new_status="deferred",
                reason="story_removed_from_epic",
                confidence=None,
                entry_type=EntryType.EPIC_STORY,
            )

            removed.append((key, updated_entry, change))

    return removed


# ============================================================================
# Main Reconcile Function
# ============================================================================


def reconcile(
    existing: SprintStatus,
    from_epics: GeneratedEntries,
    index: ArtifactIndex,
    strategy: ConflictResolution = ConflictResolution.EVIDENCE_WINS,
) -> ReconciliationResult:
    """Perform 3-way merge of sprint-status entries.

    Merges existing sprint-status, generated entries from epics, and artifact
    evidence to produce a reconciled sprint-status. Applies type-specific
    merge rules and generates a change log.

    Merge Rules by Entry Type:
        - STANDALONE, MODULE_STORY, UNKNOWN: Preserve from existing (NEVER delete)
        - EPIC_STORY: Merge with generated, apply evidence-based inference
        - EPIC_META: Recalculate from story statuses
        - RETROSPECTIVE: Preserve from existing

    Args:
        existing: Current SprintStatus from file.
        from_epics: GeneratedEntries from epic file scanning.
        index: ArtifactIndex with artifact evidence.
        strategy: Conflict resolution strategy (default: EVIDENCE_WINS).

    Returns:
        ReconciliationResult with merged status and change log.

    Examples:
        >>> result = reconcile(existing, from_epics, index)
        >>> print(result.summary())
        "Reconciliation: 42 preserved, 3 updated, 2 added, 0 removed"

        >>> for change in result.changes:
        ...     print(change.as_log_line())
        "20-1-setup: backlog → done (STRONG) [master_review_exists]"

    """
    result_entries: dict[str, SprintStatusEntry] = {}
    changes: list[StatusChange] = []
    preserved_count = 0
    updated_count = 0
    added_count = 0
    removed_count = 0

    # Build lookup dicts
    generated_by_key: dict[str, SprintStatusEntry] = {e.key: e for e in from_epics.entries}
    generated_keys = set(generated_by_key.keys())

    # Track which epic IDs we encounter for meta recalculation
    epic_ids_seen: set[str | int] = set()

    # ========================================================================
    # Step 1: Process existing entries by type
    # ========================================================================

    # Separate existing entries by type
    existing_preserve: dict[str, SprintStatusEntry] = {}
    existing_epic_stories: dict[str, SprintStatusEntry] = {}
    existing_epic_meta: dict[str, SprintStatusEntry] = {}

    for key, entry in existing.entries.items():
        if _should_preserve_entry(entry.entry_type):
            existing_preserve[key] = entry
        elif entry.entry_type == EntryType.EPIC_STORY:
            existing_epic_stories[key] = entry
        elif entry.entry_type == EntryType.EPIC_META:
            existing_epic_meta[key] = entry
            # Extract epic ID for later recalculation
            if key.startswith("epic-"):
                epic_id_str = key[5:]  # Remove "epic-" prefix
                try:
                    epic_ids_seen.add(int(epic_id_str))
                except ValueError:
                    epic_ids_seen.add(epic_id_str)

    # ========================================================================
    # Step 2: Preserve STANDALONE, MODULE_STORY, UNKNOWN, RETROSPECTIVE
    # ========================================================================

    for key, entry in existing_preserve.items():
        result_entries[key] = entry
        preserved_count += 1
        logger.debug(
            "Preserved %s entry: %s",
            entry.entry_type.value,
            key,
        )

    # ========================================================================
    # Step 3: Merge EPIC_STORY entries (using short key matching)
    # ========================================================================

    # Build short key → full key mappings for fuzzy matching
    # This handles slug variations like "12-4-refactor-create-story-compiler"
    # vs "12-4-refactor-createstorycompiler" - both normalize to "12-4"
    existing_by_short: dict[str, str] = {}  # short_key → full_key
    for full_key in existing_epic_stories:
        short_key = _normalize_story_key(full_key)
        if short_key not in existing_by_short:
            existing_by_short[short_key] = full_key

    generated_by_short: dict[str, str] = {}  # short_key → full_key
    for full_key, entry in generated_by_key.items():
        if entry.entry_type == EntryType.EPIC_STORY:
            short_key = _normalize_story_key(full_key)
            if short_key not in generated_by_short:
                generated_by_short[short_key] = full_key

    # All SHORT keys that need processing (union of existing and generated)
    all_short_keys = set(existing_by_short.keys()) | set(generated_by_short.keys())

    for short_key in all_short_keys:
        # Resolve to full keys - prefer existing key to avoid unnecessary renames
        existing_full_key = existing_by_short.get(short_key)
        generated_full_key = generated_by_short.get(short_key)

        # Use existing key if available, otherwise generated key
        canonical_key = existing_full_key or generated_full_key
        if canonical_key is None:
            continue  # Should never happen

        existing_entry = existing_epic_stories.get(existing_full_key) if existing_full_key else None
        generated_entry = generated_by_key.get(generated_full_key) if generated_full_key else None

        # Track epic IDs for meta recalculation
        epic_id = _extract_epic_id_from_key(canonical_key)
        if epic_id is not None:
            epic_ids_seen.add(epic_id)

        # Check if this is a removed story
        if existing_entry is not None and generated_entry is None:
            # Handled separately in Step 5, but only if we have generated entries
            # If from_epics is empty, preserve these entries to avoid data loss
            if generated_keys:
                continue
            # No generated entries - preserve existing EPIC_STORY
            result_entries[canonical_key] = existing_entry
            preserved_count += 1
            continue

        # Merge the entry
        merged_entry, change = _merge_epic_story(
            existing_entry,
            generated_entry,
            canonical_key,
            index,
            strategy,
        )

        result_entries[canonical_key] = merged_entry

        if change is not None:
            changes.append(change)
            if existing_entry is None:
                added_count += 1
            else:
                updated_count += 1
        else:
            preserved_count += 1

    # ========================================================================
    # Step 4: Add new entries from generated that don't exist
    # ========================================================================

    # Track which short keys were already processed in Step 3
    processed_short_keys: set[str] = set(existing_by_short.keys()) | set(generated_by_short.keys())

    for key, entry in generated_by_key.items():
        if key in result_entries:
            continue  # Already processed by exact key

        if entry.entry_type == EntryType.EPIC_META:
            # Epic meta entries are recalculated, track the ID
            if key.startswith("epic-"):
                epic_id_str = key[5:]
                try:
                    epic_ids_seen.add(int(epic_id_str))
                except ValueError:
                    epic_ids_seen.add(epic_id_str)
            continue  # Will be handled in Step 6

        # For EPIC_STORY entries, check if short key was already processed
        if entry.entry_type == EntryType.EPIC_STORY:
            short_key = _normalize_story_key(key)
            if short_key in processed_short_keys:
                # Already handled in Step 3 via short key matching
                continue

        # Add new entry (MODULE_STORY or other non-EPIC_STORY)
        result_entries[key] = entry
        added_count += 1
        changes.append(
            StatusChange(
                key=key,
                old_status=None,
                new_status=entry.status,
                reason="new_entry_from_epic",
                confidence=None,
                entry_type=entry.entry_type,
            )
        )

    # ========================================================================
    # Step 5: Handle removed stories (using short key matching)
    # ========================================================================

    # Only check for removed if we have generated entries
    if from_epics.entries:
        removed_entries = _detect_removed_stories(
            existing_epic_stories,
            set(generated_by_short.keys()),  # Use short keys for matching
        )

        for key, updated_entry, change in removed_entries:
            result_entries[key] = updated_entry
            changes.append(change)
            removed_count += 1

    # ========================================================================
    # Step 6: Recalculate EPIC_META entries
    # ========================================================================

    for epic_id in epic_ids_seen:
        epic_key = f"epic-{epic_id}"
        existing_meta = existing_epic_meta.get(epic_key)

        meta_entry, change = _recalculate_epic_meta(
            epic_id,
            result_entries,
            index,
            existing_meta,
        )

        result_entries[epic_key] = meta_entry

        if change is not None:
            changes.append(change)
            if existing_meta is None:
                added_count += 1
            else:
                updated_count += 1
        else:
            preserved_count += 1

    # ========================================================================
    # Step 7: Sort entries by epic order
    # ========================================================================

    result_entries = _sort_entries_by_epic_order(result_entries)

    # ========================================================================
    # Build result SprintStatus
    # ========================================================================

    # Check edge case: empty generated but existing has content
    if not from_epics.entries and existing.entries:
        logger.warning(
            "No entries generated from epics - preserving all %d existing entries",
            len(existing.entries),
        )

    result_status = SprintStatus(
        metadata=existing.metadata,
        entries=result_entries,
    )

    return ReconciliationResult(
        status=result_status,
        changes=changes,
        preserved_count=preserved_count,
        updated_count=updated_count,
        added_count=added_count,
        removed_count=removed_count,
    )
