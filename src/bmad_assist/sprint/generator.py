"""Epic and module generator for sprint-status entries.

This module provides functionality to scan epic files and module directories,
extract story definitions, and generate SprintStatusEntry objects with
appropriate keys, statuses, and classifications.

The generator scans in priority order:
1. docs/epics/ (primary - first occurrence wins)
2. _bmad-output/planning-artifacts/epics/ (new artifacts)
3. docs/modules/*/ (module epics)

Public API:
    - GeneratedEntries: Result container with entries and metadata
    - generate_from_epics: Main entry point for generation
    - generate_story_slug: Convert story title to kebab-case slug
    - generate_story_key: Generate sprint-status key from epic and story
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from bmad_assist.bmad.parser import EpicDocument, EpicStory, parse_epic_file
from bmad_assist.bmad.sharding import load_sharded_epics, resolve_doc_path
from bmad_assist.core.exceptions import ParserError
from bmad_assist.core.types import EpicId
from bmad_assist.sprint.classifier import EntryType
from bmad_assist.sprint.models import SprintStatusEntry, ValidStatus

logger = logging.getLogger(__name__)

__all__ = [
    "GeneratedEntries",
    "detect_legacy_epics",
    "generate_from_epics",
    "generate_story_slug",
    "generate_story_key",
]


def detect_legacy_epics(project_root: Path) -> set[int]:
    """Auto-detect epic numbers tracked in legacy location.

    Scans docs/sprint-artifacts/ for evidence of legacy epic tracking:
    1. sprint-status.yaml file (if exists, parse keys)
    2. Story files matching pattern: {epic}-{story}-*.md
    3. Retrospective files matching pattern: epic-{epic}-retro*.md

    These epic numbers should be excluded from new sprint-status generation
    to avoid duplicates when legacy tracking coexists with new tracking.

    Args:
        project_root: Root path of the project.

    Returns:
        Set of epic numbers found in legacy tracking location.
        Returns empty set if no legacy artifacts found.

    Examples:
        >>> legacy = detect_legacy_epics(Path("/project"))
        >>> legacy
        {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14}

    """
    try:
        from bmad_assist.core.paths import get_paths

        legacy_dir = get_paths().legacy_sprint_artifacts
    except RuntimeError:
        # Paths not initialized (e.g., in tests) - use project_root defaults
        legacy_dir = project_root / "docs" / "sprint-artifacts"
    if not legacy_dir.exists() or not legacy_dir.is_dir():
        return set()

    epic_nums: set[int] = set()

    # Method 1: Parse sprint-status.yaml if exists
    legacy_status = legacy_dir / "sprint-status.yaml"
    if legacy_status.exists():
        try:
            import yaml

            with open(legacy_status, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data and "development_status" in data:
                epic_pattern = re.compile(r"^(?:epic-)?(\d+)(?:-|$)")
                for key in data["development_status"]:
                    match = epic_pattern.match(str(key))
                    if match:
                        epic_nums.add(int(match.group(1)))
        except Exception as e:
            logger.warning("Failed to parse legacy sprint-status: %s", e)

    # Method 2: Scan for story files (e.g., 1-1-project-init.md, 14-3-loop.md)
    story_pattern = re.compile(r"^(\d+)-\d+-.*\.md$")
    for file in legacy_dir.glob("*.md"):
        match = story_pattern.match(file.name)
        if match:
            epic_nums.add(int(match.group(1)))

    # Method 3: Scan for retrospective files (e.g., epic-1-retrospective.md)
    retro_pattern = re.compile(r"^epic-(\d+)-retro.*\.md$")
    for file in legacy_dir.glob("epic-*-retro*.md"):
        match = retro_pattern.match(file.name)
        if match:
            epic_nums.add(int(match.group(1)))

    if epic_nums:
        logger.info(
            "Auto-detected %d legacy epics in %s: %s",
            len(epic_nums),
            legacy_dir,
            sorted(epic_nums),
        )

    return epic_nums


@dataclass
class GeneratedEntries:
    """Result of generating sprint-status entries from epic files.

    Tracks metadata about the generation process for logging/reporting.

    Attributes:
        entries: List of SprintStatusEntry objects generated.
        duplicates_skipped: Count of duplicate keys that were skipped.
        files_processed: Count of epic files successfully processed.
        files_failed: Count of epic files that failed to parse.

    Example:
        >>> result = generate_from_epics(Path("/project"))
        >>> len(result.entries)
        42
        >>> result.duplicates_skipped
        0

    """

    entries: list[SprintStatusEntry] = field(default_factory=list)
    duplicates_skipped: int = 0
    files_processed: int = 0
    files_failed: int = 0


def generate_story_slug(title: str, max_length: int = 50) -> str:
    """Convert story title to kebab-case slug.

    Normalizes unicode characters, removes special characters, and truncates
    at word boundaries if necessary.

    Args:
        title: Story title to convert.
        max_length: Maximum slug length (truncates at word boundary).

    Returns:
        Kebab-case slug suitable for sprint-status key.

    Examples:
        >>> generate_story_slug("Entry Classification System")
        'entry-classification-system'
        >>> generate_story_slug("ATDD Eligibility Prompt")
        'atdd-eligibility-prompt'
        >>> generate_story_slug("CLI `serve` Command (with options)")
        'cli-serve-command-with-options'
        >>> generate_story_slug("")
        'untitled'

    """
    if not title or not title.strip():
        return "untitled"

    # Normalize unicode (é → e)
    slug = unicodedata.normalize("NFKD", title)
    slug = slug.encode("ascii", "ignore").decode("ascii")

    # Convert to lowercase
    slug = slug.lower()

    # Replace special characters and whitespace with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", slug)

    # Remove leading/trailing hyphens
    slug = slug.strip("-")

    # Truncate if too long (at word boundary)
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]

    return slug or "untitled"


def generate_story_key(epic_id: EpicId, story: EpicStory) -> str | None:
    """Generate sprint-status key from epic and story.

    Pattern: {epic_id}-{story_num}-{slug}

    The story_num is extracted from EpicStory.number format "X.Y" (uses Y component).
    Falls back to full number if no dot separator is present.

    Args:
        epic_id: Epic identifier (int or str, e.g., 12 or "testarch").
        story: EpicStory object with number and title.

    Returns:
        Sprint-status key string, or None if story number is invalid.

    Examples:
        >>> story = EpicStory(number="12.3", title="Variables Cleanup")
        >>> generate_story_key(12, story)
        '12-3-variables-cleanup'
        >>> story = EpicStory(number="T.1", title="Config Schema")
        >>> generate_story_key("testarch", story)
        'testarch-1-config-schema'

    """
    # Validate story number
    if not story.number or not story.number.strip():
        logger.warning(
            "Empty story number in epic %s, skipping story: %s",
            epic_id,
            story.title,
        )
        return None

    # Extract story number from "X.Y" format
    # EpicStory.number is "12.3" or "T.1"
    parts = story.number.split(".")
    # Take last segment: "3" for "12.3", "1" for "T.1", or fallback to full number
    story_num = parts[-1] if len(parts) >= 2 else story.number

    # Validate extracted story_num is not empty
    if not story_num or not story_num.strip():
        logger.warning(
            "Invalid story number format '%s' in epic %s, skipping story: %s",
            story.number,
            epic_id,
            story.title,
        )
        return None

    slug = generate_story_slug(story.title)

    # epic_id can be int (12) or str ("testarch")
    return f"{epic_id}-{story_num}-{slug}"


def _normalize_status(status: str | None) -> ValidStatus:
    """Normalize status string to ValidStatus value.

    Handles common variations and defaults to 'backlog' if not recognized.

    Args:
        status: Raw status string from epic file.

    Returns:
        ValidStatus literal value.

    """
    if not status:
        return "backlog"

    status_lower = status.lower().strip()

    # Map common variations to valid statuses
    status_map: dict[str, ValidStatus] = {
        "backlog": "backlog",
        "ready-for-dev": "ready-for-dev",
        "ready for dev": "ready-for-dev",
        "in-progress": "in-progress",
        "in progress": "in-progress",
        "review": "review",
        "done": "done",
        "complete": "done",
        "completed": "done",
        "blocked": "blocked",
        "deferred": "deferred",
    }

    return status_map.get(status_lower, "backlog")


def _parse_multi_epic_file(path: Path) -> list[EpicDocument]:
    """Parse multi-epic file (docs/epics.md) into individual EpicDocuments.

    Splits content by epic headers and parses each section separately.

    Args:
        path: Path to multi-epic markdown file.

    Returns:
        List of EpicDocument objects extracted from the file.

    """
    from bmad_assist.bmad.parser import (
        EPIC_TITLE_PATTERN,
        _parse_story_sections,
    )

    content = path.read_text(encoding="utf-8")

    # Find all epic header positions
    matches = list(EPIC_TITLE_PATTERN.finditer(content))

    if not matches:
        logger.warning("No epic headers found in %s", path)
        return []

    epics: list[EpicDocument] = []

    for i, match in enumerate(matches):
        # Extract epic content (from this header to next or end)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        epic_content = content[start:end]

        # Create a temporary EpicDocument by parsing the epic section
        # We need to extract epic_num and title from the header match
        raw_num = match.group(1)
        title = match.group(2).strip()

        # Try to convert epic_num to int
        epic_num: int | str
        try:
            epic_num = int(raw_num)
        except ValueError:
            epic_num = raw_num

        # Parse stories from epic content
        stories = _parse_story_sections(epic_content, epic_num, str(path))

        epics.append(
            EpicDocument(
                epic_num=epic_num,
                title=title,
                status=None,  # Status not in epic header
                stories=stories,
                path=str(path),
            )
        )

    return epics


def _scan_epic_files(
    paths: list[Path],
    base_path: Path,
) -> tuple[list[EpicDocument], int]:
    """Scan multiple epic locations for epic files.

    Args:
        paths: List of paths to scan (directories or files).
        base_path: Base path for sharding detection.

    Returns:
        Tuple of (list of EpicDocuments, count of failed files).

    """
    epics: list[EpicDocument] = []
    failed_count = 0

    for path in paths:
        if not path.exists():
            logger.debug("Path does not exist, skipping: %s", path)
            continue

        if path.is_dir():
            # Use resolve_doc_path for sharded detection
            resolved_path, is_sharded = resolve_doc_path(path.parent, path.name)

            if is_sharded and resolved_path.is_dir():
                # Sharded epics directory
                try:
                    sharded_epics = load_sharded_epics(resolved_path, base_path)
                    epics.extend(sharded_epics)
                    logger.debug(
                        "Loaded %d epics from sharded dir: %s",
                        len(sharded_epics),
                        resolved_path,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to load sharded epics from %s: %s",
                        resolved_path,
                        e,
                    )
                    failed_count += 1
            elif not is_sharded and resolved_path.is_file():
                # Single-file multi-epic format (docs/epics.md)
                try:
                    multi_epics = _parse_multi_epic_file(resolved_path)
                    epics.extend(multi_epics)
                    logger.debug(
                        "Loaded %d epics from single file: %s",
                        len(multi_epics),
                        resolved_path,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to load multi-epic file %s: %s",
                        resolved_path,
                        e,
                    )
                    failed_count += 1
            else:
                # Scan individual files in directory
                for epic_file in sorted(path.glob("epic-*.md")):
                    try:
                        epic = parse_epic_file(epic_file)
                        epics.append(epic)
                    except ParserError as e:
                        logger.warning(
                            "Failed to parse epic file %s: %s",
                            epic_file,
                            e,
                        )
                        failed_count += 1
        elif path.is_file() and path.suffix == ".md":
            # Single epic file or multi-epic file
            try:
                from bmad_assist.bmad.parser import _is_multi_epic_file

                content = path.read_text(encoding="utf-8")

                if _is_multi_epic_file(content):
                    # Multi-epic file (docs/epics.md)
                    multi_epics = _parse_multi_epic_file(path)
                    epics.extend(multi_epics)
                    logger.debug(
                        "Loaded %d epics from multi-epic file: %s",
                        len(multi_epics),
                        path,
                    )
                else:
                    # Single epic file
                    epic = parse_epic_file(path)
                    epics.append(epic)
            except ParserError as e:
                logger.warning("Failed to parse epic file %s: %s", path, e)
                failed_count += 1

    return epics, failed_count


def _scan_module_epics(
    modules_dir: Path,
) -> tuple[list[tuple[str, EpicDocument]], int]:
    """Scan module directories for epic definitions.

    Args:
        modules_dir: Path to docs/modules/ directory.

    Returns:
        Tuple of (list of (module_name, EpicDocument) tuples, count of failed files).

    """
    results: list[tuple[str, EpicDocument]] = []
    failed_count = 0

    if not modules_dir.exists() or not modules_dir.is_dir():
        logger.debug("Modules directory does not exist: %s", modules_dir)
        return results, failed_count

    # Scan each subdirectory in docs/modules/
    for module_dir in sorted(modules_dir.iterdir()):
        if not module_dir.is_dir():
            continue

        module_name = module_dir.name

        # Look for epic-*.md files in the module directory
        for epic_file in sorted(module_dir.glob("epic-*.md")):
            try:
                epic = parse_epic_file(epic_file)
                results.append((module_name, epic))
                logger.debug(
                    "Loaded module epic %s from %s",
                    module_name,
                    epic_file,
                )
            except ParserError as e:
                logger.warning(
                    "Failed to parse module epic %s: %s",
                    epic_file,
                    e,
                )
                failed_count += 1

    return results, failed_count


def _generate_entries_from_epic(
    epic: EpicDocument,
    is_module: bool = False,
) -> list[SprintStatusEntry]:
    """Generate SprintStatusEntry objects from an EpicDocument.

    Generates:
    1. Epic meta entry (epic-{id}) with EPIC_META type
    2. Story entries for each story in the epic

    Args:
        epic: Parsed EpicDocument with stories.
        is_module: True if this is a module epic (affects entry_type).

    Returns:
        List of SprintStatusEntry objects (epic meta + all stories).

    """
    entries: list[SprintStatusEntry] = []

    if epic.epic_num is None:
        logger.warning("Epic has no epic_num, skipping: %s", epic.path)
        return entries

    # Add epic meta entry first (AC8)
    epic_key = f"epic-{epic.epic_num}"
    entries.append(
        SprintStatusEntry(
            key=epic_key,
            status="backlog",
            entry_type=EntryType.EPIC_META,
            source="epic",
            comment=None,
        )
    )

    # Add story entries
    for story in epic.stories:
        story_key = generate_story_key(epic.epic_num, story)

        # Skip invalid story numbers (AC4 edge case handling)
        if story_key is None:
            continue

        # Use explicit status from epic if present, otherwise backlog (AC5)
        status = _normalize_status(story.status)

        entries.append(
            SprintStatusEntry(
                key=story_key,
                status=status,
                entry_type=EntryType.MODULE_STORY if is_module else EntryType.EPIC_STORY,
                source="epic",
                comment=None,
            )
        )

    # Add retrospective entry at the end of each epic
    retro_key = f"epic-{epic.epic_num}-retrospective"
    entries.append(
        SprintStatusEntry(
            key=retro_key,
            status="backlog",
            entry_type=EntryType.RETROSPECTIVE,
            source="epic",
            comment=None,
        )
    )

    return entries


def generate_from_epics(
    project_root: Path,
    module_prefixes: list[str] | None = None,
    exclude_epics: set[int] | None = None,
    auto_exclude_legacy: bool = True,
) -> GeneratedEntries:
    """Generate sprint-status entries from epic files.

    Scans all epic locations in priority order:
    1. docs/epics/ (primary - first occurrence wins)
    2. _bmad-output/planning-artifacts/epics/ (new artifacts)
    3. docs/modules/*/ (module epics)

    Automatically excludes:
    - Epics in archive/ or archived/ directories
    - Epics tracked in legacy file (docs/sprint-artifacts/sprint-status.yaml)
      when auto_exclude_legacy=True

    Handles duplicate detection by keeping first occurrence by scan order.
    Parse failures are logged but don't stop processing.

    Args:
        project_root: Root path of the project.
        module_prefixes: Optional list of module prefixes for classification.
            Not used directly in generation but reserved for future config.
        exclude_epics: Optional set of epic numbers to explicitly exclude.
            If provided, takes precedence over auto-detection.
        auto_exclude_legacy: If True (default), auto-detect and exclude epics
            tracked in docs/sprint-artifacts/sprint-status.yaml. Set to False
            to include all epics regardless of legacy tracking.

    Returns:
        GeneratedEntries with all entries and generation metadata.

    Examples:
        >>> result = generate_from_epics(Path("/project"))
        >>> len(result.entries)
        42
        >>> result.files_processed
        5
        >>> # Legacy epics auto-excluded, explicit override:
        >>> result = generate_from_epics(Path("/project"), exclude_epics=set())

    """
    result = GeneratedEntries()
    seen_keys: set[str] = set()

    # Get paths with fallback for when singleton not initialized
    try:
        from bmad_assist.core.paths import get_paths

        paths = get_paths()
        epics_dir = paths.epics_dir
        project_knowledge = paths.project_knowledge
        planning_artifacts = paths.planning_artifacts
        modules_dir = paths.modules_dir
    except RuntimeError:
        # Paths not initialized (e.g., in tests) - use project_root defaults
        epics_dir = project_root / "docs" / "epics"
        project_knowledge = project_root / "docs"
        planning_artifacts = project_root / "_bmad-output" / "planning-artifacts"
        modules_dir = project_root / "docs" / "modules"

    # Determine excluded epics: explicit or auto-detected
    effective_exclude: set[int] = set()
    if exclude_epics is not None:
        # Explicit exclusion takes precedence
        effective_exclude = exclude_epics
    elif auto_exclude_legacy:
        # Auto-detect from legacy tracking file
        effective_exclude = detect_legacy_epics(project_root)

    # Define epic scan locations in priority order
    epic_locations: list[Path] = [
        planning_artifacts / "epics",  # planning-artifacts/epics (prioritize Story 0 / generated planning)
        epics_dir,  # docs/epics (sharded)
        project_knowledge / "epics.md",  # Single-file multi-epic
    ]

    # Scan epic files from primary locations
    all_epics: list[tuple[EpicDocument, bool]] = []  # (epic, is_module)
    total_failed = 0

    for epic_path in epic_locations:
        epics, failed = _scan_epic_files([epic_path], project_root)
        total_failed += failed
        for epic in epics:
            all_epics.append((epic, False))

    # Scan module epics
    module_epics, module_failed = _scan_module_epics(modules_dir)
    total_failed += module_failed
    for _module_name, epic in module_epics:
        all_epics.append((epic, True))

    # Generate entries from all epics (with optional exclusion)
    for epic, is_module in all_epics:
        # Skip epics in archive/ directories
        epic_path = Path(epic.path) if isinstance(epic.path, str) else epic.path
        if epic_path and any(part in ("archive", "archived") for part in epic_path.parts):
            logger.debug("Skipping archived epic: %s", epic_path)
            continue

        # Filter out excluded epics by number
        if effective_exclude and epic.epic_num is not None:
            try:
                epic_num_int = int(epic.epic_num)
                if epic_num_int in effective_exclude:
                    logger.debug(
                        "Skipping excluded epic %d: %s",
                        epic_num_int,
                        epic.path,
                    )
                    continue
            except (ValueError, TypeError):
                pass  # Non-numeric epic_num, don't filter

        entries = _generate_entries_from_epic(epic, is_module=is_module)
        result.files_processed += 1

        # Count story entries (exclude epic meta and retrospective entries)
        story_entries = [e for e in entries if e.entry_type == EntryType.EPIC_STORY]
        if story_entries:
            logger.debug(
                "Epic %s: found %d stories (%s)",
                epic.epic_num,
                len(story_entries),
                epic.path,
            )

        for entry in entries:
            if entry.key in seen_keys:
                logger.warning(
                    "Duplicate story key '%s' from %s, skipping",
                    entry.key,
                    epic.path,
                )
                result.duplicates_skipped += 1
                continue

            seen_keys.add(entry.key)
            result.entries.append(entry)

    result.files_failed = total_failed

    logger.info(
        "Generated %d entries from %d files (%d duplicates skipped, %d failed)",
        len(result.entries),
        result.files_processed,
        result.duplicates_skipped,
        result.files_failed,
    )

    return result
