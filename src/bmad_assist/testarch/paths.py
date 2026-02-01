"""Centralized artifact path patterns for TEA context loading.

This module provides a single source of truth for artifact patterns
used by both TEA handlers (when saving) and TEA context resolvers
(when loading). This ensures consistency and prevents pattern drift.

Addresses:
- F8 Fix: Single source of truth for patterns
- F2 Fix: EpicId type normalization (int|str)
- F7 Fix: Story ID format normalization (dot/hyphen)
- F17 Fix: Path traversal prevention
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

# Artifact patterns for each TEA artifact type
# Each entry has (subdir, patterns) - subdir is relative to implementation_artifacts
# Patterns support {epic_id}, {story_dotted}, {story_hyphen} placeholders
ARTIFACT_CONFIGS: dict[str, tuple[str, list[str]]] = {
    "test-design": (
        "test-designs",
        [
            "test-design-epic-{epic_id}.md",  # Epic-specific (higher priority)
        ],
    ),
    # Internal type: used as fallback by TestDesignResolver when no epic-specific design exists
    # Not exposed in VALID_ARTIFACT_TYPES - users configure "test-design" instead
    "test-design-system": (
        "",  # Root of implementation_artifacts
        [
            "test-design-architecture.md",
            "test-design-qa.md",
        ],
    ),
    "atdd": (
        "atdd-checklists",
        [
            "*atdd-checklist*{story_dotted}*.md",
            "*atdd-checklist*{story_hyphen}*.md",
        ],
    ),
    "test-review": (
        "test-reviews",
        [
            "test-review-{story_dotted}.md",
            "test-review-{story_hyphen}.md",
        ],
    ),
    "trace": (
        "traceability",
        [
            "trace-matrix-epic-{epic_id}.md",
        ],
    ),
}

# For backward compatibility: simple pattern mapping (flattened)
ARTIFACT_PATTERNS: dict[str, list[str]] = {
    k: v[1] for k, v in ARTIFACT_CONFIGS.items()
}

# Valid artifact types (for config validation) - exclude internal test-design-system
VALID_ARTIFACT_TYPES: frozenset[str] = frozenset(
    k for k in ARTIFACT_CONFIGS if k != "test-design-system"
)

# Legacy constant (deprecated, kept for backward compatibility)
TESTARCH_BASE_DIR = "testarch"


def normalize_story_id(story_id: str | None) -> tuple[str, str]:
    """Return (dotted, hyphenated) versions of story ID.

    Handles both "25.1" and "25-1" formats, returning both versions
    for pattern matching flexibility.

    Args:
        story_id: Story identifier in either format, or None.

    Returns:
        Tuple of (dotted_format, hyphenated_format).
        Returns ("", "") if story_id is None or empty.

    Examples:
        >>> normalize_story_id("25.1")
        ('25.1', '25-1')
        >>> normalize_story_id("25-1")
        ('25.1', '25-1')
        >>> normalize_story_id(None)
        ('', '')

    """
    if not story_id:
        return ("", "")

    story_str = str(story_id)

    if "." in story_str:
        return (story_str, story_str.replace(".", "-"))
    elif "-" in story_str:
        return (story_str.replace("-", "."), story_str)
    else:
        # No separator found - return as-is for both
        return (story_str, story_str)


def get_artifact_dir(artifact_type: str) -> str:
    """Get subdirectory for artifact type.

    Args:
        artifact_type: Type of artifact.

    Returns:
        Subdirectory relative to implementation_artifacts, or "" for root.

    """
    if artifact_type not in ARTIFACT_CONFIGS:
        return ""
    return ARTIFACT_CONFIGS[artifact_type][0]


def get_artifact_patterns(
    artifact_type: str,
    epic_id: EpicId,
    story_id: str | None = None,
) -> list[str]:
    """Format patterns with context variables.

    Args:
        artifact_type: Type of artifact (test-design, atdd, test-review, trace).
        epic_id: Epic identifier (int or str).
        story_id: Optional story identifier.

    Returns:
        List of formatted patterns to try (in priority order).

    Raises:
        ValueError: If artifact_type is not valid.

    Examples:
        >>> get_artifact_patterns("test-design", 25)
        ['test-design-epic-25.md']
        >>> get_artifact_patterns("atdd", "testarch", "1")
        ['*atdd-checklist*1*.md', '*atdd-checklist*1*.md']

    """
    if artifact_type not in ARTIFACT_CONFIGS:
        raise ValueError(
            f"Invalid artifact type: {artifact_type}. "
            f"Valid types: {sorted(VALID_ARTIFACT_TYPES)}"
        )

    _, patterns = ARTIFACT_CONFIGS[artifact_type]

    # Normalize epic_id to string (F2 Fix)
    epic_str = str(epic_id)

    # Normalize story_id to both formats (F7 Fix)
    story_dotted, story_hyphen = normalize_story_id(story_id)

    formatted: list[str] = []
    for pattern in patterns:
        formatted_pattern = pattern.format(
            epic_id=epic_str,
            story_dotted=story_dotted,
            story_hyphen=story_hyphen,
        )
        formatted.append(formatted_pattern)

    return formatted


def validate_artifact_path(path: Path, base_dir: Path) -> bool:
    """Validate path is within base_dir (prevent path traversal).

    Args:
        path: Path to validate.
        base_dir: Base directory that path must be within.

    Returns:
        True if path is within base_dir, False otherwise.

    Note:
        This resolves both paths to absolute form before comparison,
        handling symlinks and relative components like '..'.

    Examples:
        >>> base = Path("/project/artifacts")
        >>> validate_artifact_path(Path("/project/artifacts/test.md"), base)
        True
        >>> validate_artifact_path(Path("/project/artifacts/../secrets/key"), base)
        False

    """
    try:
        resolved_path = path.resolve()
        resolved_base = base_dir.resolve()
        # Check if resolved path starts with resolved base
        resolved_path.relative_to(resolved_base)
        return True
    except ValueError:
        # relative_to raises ValueError if path is not relative to base
        logger.debug("Path %s is outside base directory %s", path, base_dir)
        return False


def get_testarch_dir(impl_artifacts: Path) -> Path:
    """Get the testarch artifacts directory.

    Args:
        impl_artifacts: Implementation artifacts base path.

    Returns:
        Path to testarch directory.

    """
    return impl_artifacts / TESTARCH_BASE_DIR
