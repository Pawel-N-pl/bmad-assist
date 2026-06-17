"""Artifact scanner and index for evidence-based status inference.

This module provides functionality to scan project artifact directories and
build an index of story files, code reviews, validations, and retrospectives.
The index enables evidence-based status inference in the reconciliation engine.

Artifact locations (scanned in order, new location takes precedence):
1. Legacy: docs/sprint-artifacts/{stories,code-reviews,story-validations,retrospectives}
2. New: _bmad-output/implementation-artifacts/{stories,code-reviews,...}

Public API:
    - StoryArtifact: Dataclass for story file metadata
    - CodeReviewArtifact: Dataclass for code review file metadata
    - ValidationArtifact: Dataclass for validation report metadata
    - RetrospectiveArtifact: Dataclass for retrospective file metadata
    - ArtifactIndex: Container with indexed artifacts and query methods
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

__all__ = [
    "StoryArtifact",
    "CodeReviewArtifact",
    "ValidationArtifact",
    "RetrospectiveArtifact",
    "ArtifactIndex",
]


# ============================================================================
# Filename Parsing Patterns
# ============================================================================

# Story files: {epic}-{story}-{slug}.md
# Examples: 20-1-entry-classification-system.md, testarch-1-config.md, 10-3a-ii-command-registry.md
STORY_FILENAME_PATTERN = re.compile(
    r"^(?P<epic>[a-z0-9]+)-(?P<story>\d+(?:[a-z](?:-[ivx]{2,})*)?)-(?P<slug>[a-z0-9-]+)\.md$", re.IGNORECASE
)

# Code review synthesis: synthesis-{epic}-{story}[-timestamp].md
# Examples: synthesis-20-4.md, synthesis-16-13-20260107_1112.md, synthesis-10-3a-ii-20260410.md
SYNTHESIS_PATTERN = re.compile(
    r"^synthesis-(?P<epic>[a-z0-9]+)-(?P<story>\d+(?:[a-z](?:-[ivx]{2,})*)?)(?:-(?P<timestamp>[\dT_]+))?\.md$",
    re.IGNORECASE,
)

# Code review: code-review-{epic}-{story}-{role_id}-{timestamp}.md
# Examples: code-review-22-11-a-20260115T155525Z.md
CODE_REVIEW_PATTERN = re.compile(
    r"^code-review-(?P<epic>[a-z0-9]+)-(?P<story>[a-z0-9]+)-(?P<role_id>[a-z])-"
    r"(?P<timestamp>[\dT_Z-]+)\.md$",
    re.IGNORECASE,
)

# Legacy code review: code-review-{epic}-{story}-{reviewer}-{timestamp}.md
# Examples: code-review-1-4-master-20251209-233000.md, code-review-20-4-validator_g-20260107_1738.md
# Note: sub-story suffix is single letter + optional roman numeral (e.g., 3a, 3a-ii)
LEGACY_REVIEW_PATTERN = re.compile(
    r"^code-review-(?P<epic>[a-z0-9]+)-(?P<story>\d+(?:[a-z](?:-[ivx]{2,})*)?)-(?P<reviewer>[a-z0-9_-]+?)-"
    r"(?P<timestamp>\d[\dT_Z-]+)\.md$",
    re.IGNORECASE,
)

# New validation: validation-{epic}-{story}-{role_id}-{timestamp}.md
# Examples: validation-22-11-a-20260115T155525Z.md
NEW_VALIDATION_PATTERN = re.compile(
    r"^validation-(?P<epic>[a-z0-9]+)-(?P<story>[a-z0-9]+)-(?P<role_id>[a-z])-"
    r"(?P<timestamp>[\dT_Z-]*)\.md$",
    re.IGNORECASE,
)

# Legacy validation: story-validation-{epic}-{story}-{reviewer}-{timestamp}.md
LEGACY_VALIDATION_PATTERN = re.compile(
    r"^story-validation-(?P<epic>[a-z0-9]+)-(?P<story>\d+(?:[a-z](?:-[ivx]{2,})*)?)-(?P<reviewer>[a-z0-9_]+)-"
    r"(?P<timestamp>[\dT_-]+)\.md$",
    re.IGNORECASE,
)

# Retrospective: epic-{id}-retro[-timestamp].md
# Examples: epic-15-retro-20260106.md, epic-testarch-retro-20260105.md
RETRO_PATTERN = re.compile(
    r"^epic-(?P<epic_id>[a-z0-9-]+)-retro(?:spective)?(?:-(?P<timestamp>[\dT_]*))?\.md$",
    re.IGNORECASE,
)


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass(frozen=True)
class StoryArtifact:
    """Represents a discovered story file.

    Attributes:
        path: Absolute path to the story file.
        story_key: Full story key extracted from filename (e.g., "20-1-entry-classification").
        status: Extracted Status: field value (lowercase), or None if not found.

    Example:
        >>> artifact = StoryArtifact(
        ...     path=Path("/project/stories/20-1-setup.md"),
        ...     story_key="20-1-setup",
        ...     status="done",
        ... )

    """

    path: Path
    story_key: str
    status: str | None


@dataclass(frozen=True)
class CodeReviewArtifact:
    """Represents a discovered code review file.

    Attributes:
        path: Absolute path to the code review file.
        story_key: Short story key extracted from filename (e.g., "20-1").
        reviewer: Reviewer identifier (e.g., "master", "validator_a").
        is_synthesis: True for synthesis-* files (authoritative).
        is_master: True for master reviews or synthesis files.
        timestamp: Timestamp from filename, if present.

    Example:
        >>> artifact = CodeReviewArtifact(
        ...     path=Path("/project/code-reviews/synthesis-20-4.md"),
        ...     story_key="20-4",
        ...     reviewer=None,
        ...     is_synthesis=True,
        ...     is_master=True,
        ...     timestamp="20260107_1112",
        ... )

    """

    path: Path
    story_key: str
    reviewer: str | None
    is_synthesis: bool
    is_master: bool
    timestamp: str | None


@dataclass(frozen=True)
class ValidationArtifact:
    """Represents a discovered validation report.

    Attributes:
        path: Absolute path to the validation file.
        story_key: Short story key extracted from filename (e.g., "20-1").
        reviewer: Reviewer identifier, if present.
        is_synthesis: True for synthesis-* files (authoritative).
        timestamp: Timestamp from filename, if present.

    Example:
        >>> artifact = ValidationArtifact(
        ...     path=Path("/project/story-validations/synthesis-20-1-20260107.md"),
        ...     story_key="20-1",
        ...     reviewer=None,
        ...     is_synthesis=True,
        ...     timestamp="20260107T154829",
        ... )

    """

    path: Path
    story_key: str
    reviewer: str | None
    is_synthesis: bool
    timestamp: str | None


@dataclass(frozen=True)
class RetrospectiveArtifact:
    """Represents a discovered retrospective file.

    Attributes:
        path: Absolute path to the retrospective file.
        epic_id: Epic identifier (int or str, e.g., 12 or "testarch").
        timestamp: Timestamp from filename, if present.

    Example:
        >>> artifact = RetrospectiveArtifact(
        ...     path=Path("/project/retrospectives/epic-12-retro-20260106.md"),
        ...     epic_id=12,
        ...     timestamp="20260106",
        ... )

    """

    path: Path
    epic_id: EpicId
    timestamp: str | None


# ============================================================================
# Helper Functions
# ============================================================================


def _normalize_story_key(story_key: str) -> str:
    """Extract short key (epic-story) from full or short key.

    Normalizes story keys for consistent indexing and lookup. Full keys
    include slugs (e.g., "20-1-entry-classification-system"), while short
    keys are just epic-story numbers (e.g., "20-1").

    All keys are normalized to lowercase for consistent dictionary lookups.

    Args:
        story_key: Full or short story key.

    Returns:
        Short story key in format "{epic}-{story}" (lowercase).

    Examples:
        >>> _normalize_story_key("20-1-entry-classification-system")
        '20-1'
        >>> _normalize_story_key("20-1")
        '20-1'
        >>> _normalize_story_key("testarch-1-config")
        'testarch-1'
        >>> _normalize_story_key("standalone-01-reconciler-refactoring")
        'standalone-01'
        >>> _normalize_story_key("TestArch-1-Config")
        'testarch-1'

    """
    # Match epic-story pattern at start (sub-story: single letter + optional roman numeral)
    # The letter suffix and roman numerals are grouped: 3a, 3a-ii — never 3-ii alone
    match = re.match(r"^([a-z0-9-]+?)-(\d+(?:[a-z](?:-[ivx]{2,})*)?)", story_key, re.IGNORECASE)
    if match:
        return f"{match.group(1).lower()}-{match.group(2)}"
    return story_key.lower()


def _extract_story_status(path: Path) -> str | None:
    """Extract Status: field value from story markdown file.

    Scans the first lines of the file for 'Status:' (case-insensitive).
    Returns the normalized (lowercase, stripped) status value.

    Uses line-by-line reading with early exit for efficiency - Status is
    typically in the first 10 lines of a story file.

    Args:
        path: Path to the story markdown file.

    Returns:
        Normalized status value or None if not found or on error.

    Example:
        >>> _extract_story_status(Path("/project/stories/20-1-setup.md"))
        'done'

    """
    try:
        with path.open(encoding="utf-8") as f:
            # Status is typically in first 10 lines; check up to 50 for safety
            for i, line in enumerate(f):
                if i >= 50:
                    break
                stripped = line.strip()
                if stripped.lower().startswith("status:"):
                    # Extract value after colon
                    status = stripped.split(":", 1)[1].strip()
                    # Normalize: lowercase, strip whitespace
                    return status.lower() if status else None
        return None
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Failed to read story file %s: %s", path, e)
        return None


def _parse_epic_id(epic_str: str) -> EpicId:
    """Parse epic ID from string, returning int if numeric.

    Args:
        epic_str: String representation of epic ID.

    Returns:
        Integer if value is numeric, otherwise the original string.

    Examples:
        >>> _parse_epic_id("12")
        12
        >>> _parse_epic_id("testarch")
        'testarch'

    """
    try:
        return int(epic_str)
    except ValueError:
        return epic_str


def _get_artifact_locations(project_root: Path) -> dict[str, list[Path]]:
    """Get all artifact directories to scan.

    Returns dict mapping artifact type to list of directories.
    Legacy location is scanned first, new location last (takes precedence).

    Args:
        project_root: Root path of the project (used as fallback).

    Returns:
        Dict mapping artifact type to list of directory paths.

    """
    # Get paths with fallback for when singleton not initialized
    try:
        from bmad_assist.core.paths import get_paths

        paths = get_paths()
        legacy_base = paths.legacy_sprint_artifacts
        new_base = paths.implementation_artifacts
    except RuntimeError:
        # Paths not initialized (e.g., in tests) - use project_root defaults
        legacy_base = project_root / "docs" / "sprint-artifacts"
        new_base = project_root / "_bmad-output" / "implementation-artifacts"

    locations: dict[str, list[Path]] = {
        "stories": [],
        "code_reviews": [],
        "validations": [],
        "retrospectives": [],
    }

    # Legacy location
    if legacy_base.exists():
        if (legacy_base / "stories").exists():
            locations["stories"].append(legacy_base / "stories")
        if (legacy_base / "code-reviews").exists():
            locations["code_reviews"].append(legacy_base / "code-reviews")
        if (legacy_base / "story-validations").exists():
            locations["validations"].append(legacy_base / "story-validations")
        if (legacy_base / "retrospectives").exists():
            locations["retrospectives"].append(legacy_base / "retrospectives")

    # New location
    if new_base.exists():
        # Stories can be in stories/ subdirectory OR directly in implementation-artifacts/
        if (new_base / "stories").exists():
            locations["stories"].append(new_base / "stories")
        # Also check implementation-artifacts/ directly (BMAD stores stories there)
        locations["stories"].append(new_base)
        if (new_base / "code-reviews").exists():
            locations["code_reviews"].append(new_base / "code-reviews")
        if (new_base / "story-validations").exists():
            locations["validations"].append(new_base / "story-validations")
        if (new_base / "retrospectives").exists():
            locations["retrospectives"].append(new_base / "retrospectives")

    return locations


# ============================================================================
# Individual Scanners
# ============================================================================


def _scan_stories(paths: list[Path]) -> dict[str, StoryArtifact]:
    """Scan directories for story files.

    Extracts story key from filename pattern and Status field from content.
    Later paths overwrite earlier ones (new location takes precedence).

    Args:
        paths: List of directories to scan for story files.

    Returns:
        Dict mapping full story key to StoryArtifact.

    """
    results: dict[str, StoryArtifact] = {}

    for directory in paths:
        if not directory.exists() or not directory.is_dir():
            continue

        for file_path in directory.iterdir():
            if not file_path.is_file() or file_path.suffix.lower() != ".md":
                continue

            # Skip non-story files
            filename = file_path.name
            if filename.lower() in ("readme.md", "index.md"):
                continue

            match = STORY_FILENAME_PATTERN.match(filename)
            if not match:
                logger.debug("Skipping non-story file: %s", filename)
                continue

            # Full key is filename without extension
            story_key = file_path.stem

            # Extract status from file content
            status = _extract_story_status(file_path)

            artifact = StoryArtifact(
                path=file_path,
                story_key=story_key,
                status=status,
            )
            results[story_key] = artifact

    return results


def _scan_code_reviews(paths: list[Path]) -> dict[str, list[CodeReviewArtifact]]:
    """Scan directories for code review files.

    Parses story key from filename patterns. Supports both legacy master format
    and new validator/synthesis formats.

    Args:
        paths: List of directories to scan for code review files.

    Returns:
        Dict mapping short story key to list of CodeReviewArtifact.

    """
    results: dict[str, list[CodeReviewArtifact]] = {}

    for directory in paths:
        if not directory.exists() or not directory.is_dir():
            continue

        for file_path in directory.iterdir():
            if not file_path.is_file() or file_path.suffix.lower() != ".md":
                continue

            filename = file_path.name
            artifact: CodeReviewArtifact | None = None

            # Try synthesis pattern first (authoritative)
            match = SYNTHESIS_PATTERN.match(filename)
            if match:
                story_key = f"{match.group('epic')}-{match.group('story')}"
                artifact = CodeReviewArtifact(
                    path=file_path,
                    story_key=story_key,
                    reviewer=None,
                    is_synthesis=True,
                    is_master=True,
                    timestamp=match.group("timestamp"),
                )
            else:
                # Try new role_id pattern (a, b, c...)
                match = CODE_REVIEW_PATTERN.match(filename)
                if match:
                    story_key = f"{match.group('epic')}-{match.group('story')}"
                    reviewer = match.group("role_id")  # Single letter: a, b, c...
                    artifact = CodeReviewArtifact(
                        path=file_path,
                        story_key=story_key,
                        reviewer=reviewer,
                        is_synthesis=False,
                        is_master=False,
                        timestamp=match.group("timestamp"),
                    )
                else:
                    # Try legacy pattern
                    match = LEGACY_REVIEW_PATTERN.match(filename)
                    if match:
                        story_key = f"{match.group('epic')}-{match.group('story')}"
                        reviewer = match.group("reviewer")
                        is_master = reviewer.lower() == "master"
                        artifact = CodeReviewArtifact(
                            path=file_path,
                            story_key=story_key,
                            reviewer=reviewer,
                            is_synthesis=False,
                            is_master=is_master,
                            timestamp=match.group("timestamp"),
                        )

            if artifact:
                if artifact.story_key not in results:
                    results[artifact.story_key] = []
                results[artifact.story_key].append(artifact)
            else:
                logger.debug("Skipping unrecognized code review file: %s", filename)

    return results


def _scan_validations(paths: list[Path]) -> dict[str, list[ValidationArtifact]]:
    """Scan directories for validation report files.

    Parses story key from filename patterns. Supports both legacy story-validation
    format and new validation/synthesis formats.

    Args:
        paths: List of directories to scan for validation files.

    Returns:
        Dict mapping short story key to list of ValidationArtifact.

    """
    results: dict[str, list[ValidationArtifact]] = {}

    for directory in paths:
        if not directory.exists() or not directory.is_dir():
            continue

        for file_path in directory.iterdir():
            if not file_path.is_file() or file_path.suffix.lower() != ".md":
                continue

            filename = file_path.name
            artifact: ValidationArtifact | None = None

            # Try synthesis pattern first (authoritative)
            match = SYNTHESIS_PATTERN.match(filename)
            if match:
                story_key = f"{match.group('epic')}-{match.group('story')}"
                artifact = ValidationArtifact(
                    path=file_path,
                    story_key=story_key,
                    reviewer=None,
                    is_synthesis=True,
                    timestamp=match.group("timestamp"),
                )
            else:
                # Try new role_id validation pattern (a, b, c...)
                match = NEW_VALIDATION_PATTERN.match(filename)
                if match:
                    story_key = f"{match.group('epic')}-{match.group('story')}"
                    artifact = ValidationArtifact(
                        path=file_path,
                        story_key=story_key,
                        reviewer=match.group("role_id"),  # Single letter: a, b, c...
                        is_synthesis=False,
                        timestamp=match.group("timestamp"),
                    )
                else:
                    # Try legacy pattern
                    match = LEGACY_VALIDATION_PATTERN.match(filename)
                    if match:
                        story_key = f"{match.group('epic')}-{match.group('story')}"
                        artifact = ValidationArtifact(
                            path=file_path,
                            story_key=story_key,
                            reviewer=match.group("reviewer"),
                            is_synthesis=False,
                            timestamp=match.group("timestamp"),
                        )

            if artifact:
                if artifact.story_key not in results:
                    results[artifact.story_key] = []
                results[artifact.story_key].append(artifact)
            else:
                logger.debug("Skipping unrecognized validation file: %s", filename)

    return results


def _scan_retrospectives(paths: list[Path]) -> dict[str, RetrospectiveArtifact]:
    """Scan directories for retrospective files.

    Parses epic ID from filename pattern. Supports both numeric and string
    epic identifiers.

    Args:
        paths: List of directories to scan for retrospective files.

    Returns:
        Dict mapping epic_id (as string) to RetrospectiveArtifact.

    """
    results: dict[str, RetrospectiveArtifact] = {}

    for directory in paths:
        if not directory.exists() or not directory.is_dir():
            continue

        for file_path in directory.iterdir():
            if not file_path.is_file() or file_path.suffix.lower() != ".md":
                continue

            filename = file_path.name
            match = RETRO_PATTERN.match(filename)
            if match:
                epic_id_str = match.group("epic_id")
                epic_id = _parse_epic_id(epic_id_str)
                artifact = RetrospectiveArtifact(
                    path=file_path,
                    epic_id=epic_id,
                    timestamp=match.group("timestamp"),
                )
                # Use string key for dict (allows both int and str epic IDs)
                results[str(epic_id)] = artifact
            else:
                logger.debug("Skipping unrecognized retrospective file: %s", filename)

    return results


# ============================================================================
# ArtifactIndex
# ============================================================================


@dataclass
class ArtifactIndex:
    """Index of all project artifacts for evidence-based status inference.

    Provides a unified interface to query discovered artifacts. The index is
    built by scanning artifact directories and parsing filenames to extract
    story keys, epic IDs, and metadata.

    Attributes:
        story_files: Dict mapping full story key to StoryArtifact.
        code_reviews: Dict mapping short story key to list of CodeReviewArtifact.
        validations: Dict mapping short story key to list of ValidationArtifact.
        retrospectives: Dict mapping epic_id (as string) to RetrospectiveArtifact.
        scan_time: Timestamp when the scan was performed.

    Example:
        >>> index = ArtifactIndex.scan(Path("/project"))
        >>> index.has_master_review("20-1")
        True
        >>> index.get_story_status("20-1-entry-classification")
        'done'

    """

    story_files: dict[str, StoryArtifact] = field(default_factory=dict)
    code_reviews: dict[str, list[CodeReviewArtifact]] = field(default_factory=dict)
    validations: dict[str, list[ValidationArtifact]] = field(default_factory=dict)
    retrospectives: dict[str, RetrospectiveArtifact] = field(default_factory=dict)
    scan_time: datetime = field(default_factory=datetime.now)

    @classmethod
    def scan(cls, project_root: Path) -> ArtifactIndex:
        """Scan project directories and build artifact index.

        Discovers all artifact locations (legacy + new) and scans each for
        relevant files. New location takes precedence (scanned last, overwrites).

        Args:
            project_root: Root path of the project.

        Returns:
            Populated ArtifactIndex with all discovered artifacts.

        Example:
            >>> index = ArtifactIndex.scan(Path("/project"))
            >>> len(index.story_files)
            42

        """
        locations = _get_artifact_locations(project_root)

        story_files = _scan_stories(locations["stories"])
        code_reviews = _scan_code_reviews(locations["code_reviews"])
        validations = _scan_validations(locations["validations"])
        retrospectives = _scan_retrospectives(locations["retrospectives"])

        logger.info(
            "Artifact scan complete: %d stories, %d code_review keys, "
            "%d validation keys, %d retrospectives",
            len(story_files),
            len(code_reviews),
            len(validations),
            len(retrospectives),
        )

        return cls(
            story_files=story_files,
            code_reviews=code_reviews,
            validations=validations,
            retrospectives=retrospectives,
            scan_time=datetime.now(),
        )

    # ========================================================================
    # Query Methods
    # ========================================================================

    def has_story_file(self, story_key: str) -> bool:
        """Check if a story file exists for the given key.

        Accepts both full keys (with slug) and short keys (epic-story).

        Args:
            story_key: Full or short story key.

        Returns:
            True if story file exists in index.

        Example:
            >>> index.has_story_file("20-1-entry-classification")
            True
            >>> index.has_story_file("20-1")
            True

        """
        # Try exact match first (full key)
        if story_key in self.story_files:
            return True

        # Try normalized (short) key - search for any match
        short_key = _normalize_story_key(story_key)
        return any(_normalize_story_key(full_key) == short_key for full_key in self.story_files)

    def get_story_artifact(self, story_key: str) -> StoryArtifact | None:
        """Get StoryArtifact for the given key.

        Accepts both full keys (with slug) and short keys (epic-story).

        Args:
            story_key: Full or short story key.

        Returns:
            StoryArtifact if found, None otherwise.

        Example:
            >>> artifact = index.get_story_artifact("20-1")
            >>> artifact.status
            'done'

        """
        # Try exact match first (full key)
        if story_key in self.story_files:
            return self.story_files[story_key]

        # Try normalized (short) key - search for any match
        short_key = _normalize_story_key(story_key)
        for full_key, artifact in self.story_files.items():
            if _normalize_story_key(full_key) == short_key:
                return artifact

        return None

    def get_story_status(self, story_key: str) -> str | None:
        """Get Status field value from story file.

        Accepts both full keys (with slug) and short keys (epic-story).

        Args:
            story_key: Full or short story key.

        Returns:
            Normalized status value or None if not found.

        Example:
            >>> index.get_story_status("20-1-entry-classification")
            'done'
            >>> index.get_story_status("20-1")
            'done'

        """
        artifact = self.get_story_artifact(story_key)
        return artifact.status if artifact else None

    def has_master_review(self, story_key: str) -> bool:
        """Check if a master code review or synthesis exists.

        Accepts both full keys (with slug) and short keys (epic-story).

        Args:
            story_key: Full or short story key.

        Returns:
            True if master review or synthesis exists.

        Example:
            >>> index.has_master_review("20-1")
            True

        """
        short_key = _normalize_story_key(story_key)
        reviews = self.code_reviews.get(short_key, [])
        return any(r.is_master or r.is_synthesis for r in reviews)

    def has_any_review(self, story_key: str) -> bool:
        """Check if any code review exists (master or validator).

        Accepts both full keys (with slug) and short keys (epic-story).

        Args:
            story_key: Full or short story key.

        Returns:
            True if any code review exists.

        Example:
            >>> index.has_any_review("20-1")
            True

        """
        short_key = _normalize_story_key(story_key)
        return bool(self.code_reviews.get(short_key))

    def get_code_reviews(self, story_key: str) -> list[CodeReviewArtifact]:
        """Get all code review artifacts for the given key.

        Accepts both full keys (with slug) and short keys (epic-story).

        Args:
            story_key: Full or short story key.

        Returns:
            List of CodeReviewArtifact (empty if none).

        Example:
            >>> reviews = index.get_code_reviews("20-1")
            >>> len(reviews)
            5

        """
        short_key = _normalize_story_key(story_key)
        return self.code_reviews.get(short_key, [])

    def has_validation(self, story_key: str) -> bool:
        """Check if any validation report exists.

        Accepts both full keys (with slug) and short keys (epic-story).

        Args:
            story_key: Full or short story key.

        Returns:
            True if validation report exists.

        Example:
            >>> index.has_validation("20-1")
            True

        """
        short_key = _normalize_story_key(story_key)
        return bool(self.validations.get(short_key))

    def get_validations(self, story_key: str) -> list[ValidationArtifact]:
        """Get all validation artifacts for the given key.

        Accepts both full keys (with slug) and short keys (epic-story).

        Args:
            story_key: Full or short story key.

        Returns:
            List of ValidationArtifact (empty if none).

        Example:
            >>> validations = index.get_validations("20-1")
            >>> len(validations)
            5

        """
        short_key = _normalize_story_key(story_key)
        return self.validations.get(short_key, [])

    def has_retrospective(self, epic_id: EpicId) -> bool:
        """Check if a retrospective exists for the given epic.

        Args:
            epic_id: Epic identifier (int or str).

        Returns:
            True if retrospective file exists.

        Example:
            >>> index.has_retrospective(12)
            True
            >>> index.has_retrospective("testarch")
            True

        """
        return str(epic_id) in self.retrospectives

    def get_retrospective(self, epic_id: EpicId) -> RetrospectiveArtifact | None:
        """Get retrospective artifact for the given epic.

        Args:
            epic_id: Epic identifier (int or str).

        Returns:
            RetrospectiveArtifact if found, None otherwise.

        Example:
            >>> retro = index.get_retrospective(12)
            >>> retro.timestamp
            '20260105'

        """
        return self.retrospectives.get(str(epic_id))

    def __repr__(self) -> str:
        """Return debug-friendly representation."""
        return (
            f"ArtifactIndex(stories={len(self.story_files)}, "
            f"code_reviews={len(self.code_reviews)}, "
            f"validations={len(self.validations)}, "
            f"retrospectives={len(self.retrospectives)})"
        )
