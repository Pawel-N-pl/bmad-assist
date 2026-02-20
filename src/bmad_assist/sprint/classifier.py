"""Entry type classification for sprint-status entries.

This module provides the classification system that determines how each
sprint-status entry should be handled during merge/reconciliation operations.

The classification follows a strict priority order to handle edge cases:
1. Invalid input (empty/whitespace) → UNKNOWN with warning
2. `-retrospective` suffix → RETROSPECTIVE (highest priority)
3. `epic-{id}` pattern → EPIC_META
4. `standalone-` prefix → STANDALONE
5. Module prefixes from config → MODULE_STORY
6. `{epic_id}-{story_num}-{slug}` → EPIC_STORY
7. Default → UNKNOWN
"""

import logging
import re
from enum import Enum

logger = logging.getLogger(__name__)

# Default module prefixes when not configured (immutable to prevent mutation bugs)
DEFAULT_MODULE_PREFIXES: tuple[str, ...] = ("testarch",)


class EntryType(Enum):
    """Classification of sprint-status entry types.

    Each type determines how the entry is handled during merge/reconciliation:

    - EPIC_STORY: Stories from epic files. Can be regenerated from source.
        Merge behavior: Update from epics, preserve manual status overrides.

    - MODULE_STORY: Stories from module directories (e.g., testarch, guardian).
        Merge behavior: Preserve (different source than main epics).

    - STANDALONE: Standalone stories that exist only in sprint-status.
        Merge behavior: NEVER DELETE - these have no regeneration source.

    - EPIC_META: Epic-level status entries (e.g., epic-12, epic-testarch).
        Merge behavior: Recalculate from story statuses.

    - RETROSPECTIVE: Retrospective entries for completed epics.
        Merge behavior: Preserve existing status.

    - HARDENING: Hardening entries for completed epics.
        Merge behavior: Preserve existing status.

    - UNKNOWN: Unrecognized patterns.
        Merge behavior: Preserve (safe default to prevent data loss).
    """

    EPIC_STORY = "epic_story"
    MODULE_STORY = "module_story"
    STANDALONE = "standalone"
    EPIC_META = "epic_meta"
    RETROSPECTIVE = "retro"
    HARDENING = "hardening"
    UNKNOWN = "unknown"


# Regex patterns for entry classification
# Epic meta: epic-{id} where id is alphanumeric (e.g., epic-12, epic-testarch)
_EPIC_META_PATTERN = re.compile(r"^epic-([a-z0-9][a-z0-9-]*)$")

# Epic story: {epic_id}-{story_num}-{slug} where epic_id can be string or numeric
# Requires at least: alphanumeric epic id, numeric story number, alphanumeric slug
_EPIC_STORY_PATTERN = re.compile(r"^([a-z0-9][a-z0-9-]*)-(\d+)-([a-z0-9][a-z0-9-]*)$")


def classify_entry(
    key: str,
    module_prefixes: list[str] | None = None,
) -> EntryType:
    """Classify sprint-status entry by key pattern.

    Determines the entry type based on the key's pattern, which controls
    how the entry is handled during merge/reconciliation operations.

    Args:
        key: Sprint-status key (e.g., "12-3-story-name", "standalone-01-refactor").
        module_prefixes: List of module name prefixes that identify module stories.
            Defaults to ["testarch"].

    Returns:
        EntryType indicating how this entry should be handled during reconciliation.
        Returns UNKNOWN for empty/whitespace input with logged warning.

    Examples:
        >>> classify_entry("12-3-story-name")
        EntryType.EPIC_STORY
        >>> classify_entry("standalone-01-refactor")
        EntryType.STANDALONE
        >>> classify_entry("epic-12")
        EntryType.EPIC_META
        >>> classify_entry("testarch-1-config")
        EntryType.MODULE_STORY
        >>> classify_entry("epic-12-retrospective")
        EntryType.RETROSPECTIVE

    """
    # Handle invalid input
    if not key or not key.strip():
        logger.warning("classify_entry called with empty/whitespace key")
        return EntryType.UNKNOWN

    # Normalize key (strip whitespace, lowercase)
    key = key.strip().lower()

    # Use provided prefixes or default (None means use default, [] means no prefixes)
    prefixes = DEFAULT_MODULE_PREFIXES if module_prefixes is None else module_prefixes

    # Priority 1: Check for retrospective suffix (highest priority)
    # This catches: epic-12-retrospective, testarch-retrospective, etc.
    if key.endswith("-retrospective"):
        return EntryType.RETROSPECTIVE

    # Priority 1b: Check for hardening suffix (high priority)
    if key.endswith("-hardening"):
        return EntryType.HARDENING

    # Priority 2: Check for epic meta pattern (epic-{id})
    # Must check before module prefixes since "epic-testarch" should be EPIC_META
    if _EPIC_META_PATTERN.match(key):
        return EntryType.EPIC_META

    # Priority 3: Check for standalone prefix
    if key.startswith("standalone-"):
        return EntryType.STANDALONE

    # Priority 4: Check for module prefixes
    # Optimization: build lowercase prefixes tuple once for startswith()
    if prefixes:
        lowered_prefixes = tuple(f"{p.lower()}-" for p in prefixes)
        if key.startswith(lowered_prefixes):
            return EntryType.MODULE_STORY

    # Priority 5: Check for epic story pattern ({epic_id}-{story_num}-{slug})
    if _EPIC_STORY_PATTERN.match(key):
        return EntryType.EPIC_STORY

    # Default: Unknown pattern - preserve for safety
    return EntryType.UNKNOWN
