"""Project state reader for BMAD files.

This module provides functionality to read and aggregate project state
from BMAD files, including epic discovery, story compilation, and current
position determination.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from bmad_assist.bmad.parser import EpicDocument, EpicStory, parse_epic_file
from bmad_assist.bmad.sharding import (
    DuplicateEpicError,
    load_sharded_epics,
    resolve_doc_path,
)
from bmad_assist.core.exceptions import ParserError
from bmad_assist.core.types import EpicId, parse_epic_id

logger = logging.getLogger(__name__)


def _get_sprint_status_candidates(bmad_path: Path) -> list[Path]:
    """Get candidate paths for sprint-status.yaml.

    Uses paths singleton if available (handles external paths correctly),
    plus legacy fallback locations for fixtures/legacy projects.

    Args:
        bmad_path: BMAD documentation root (used for legacy fallbacks only).

    Returns:
        List of possible sprint-status.yaml paths to try.

    Note: When external paths are configured, bmad_path could point anywhere.
    The paths singleton handles external paths correctly. Legacy fallbacks
    use bmad_path directly (not bmad_path.parent) since bmad_path IS the
    docs folder where sprint-artifacts/ would be located.

    """
    from bmad_assist.core.paths import get_paths

    try:
        paths = get_paths()
        # Use singleton's configured paths (handles external paths correctly)
        return paths.get_sprint_status_search_locations()
    except RuntimeError:
        # Singleton not yet initialized - use explicit fallback
        # NOTE: When singleton is not initialized, we assume default config where
        # bmad_path = project_root / "docs". For external paths, singleton MUST be initialized.
        # We derive project_root from bmad_path.parent (valid for default config only).
        project_root = bmad_path.parent
        return [
            # New location
            project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml",
            bmad_path / "sprint-artifacts" / "sprint-status.yaml",  # Legacy
            bmad_path / "sprint-status.yaml",  # Legacy (direct)
        ]


@dataclass
class ProjectState:
    """Complete project state from BMAD files.

    Attributes:
        epics: List of parsed EpicDocument objects.
        all_stories: Flattened list of all stories, sorted by number.
        completed_stories: List of story numbers with status "done".
        current_epic: Current epic ID (first with non-done stories).
        current_story: Number of the current story (first non-done).
        bmad_path: Path to BMAD documentation directory.

    """

    epics: list[EpicDocument]
    all_stories: list[EpicStory]
    completed_stories: list[str]
    current_epic: EpicId | None
    current_story: str | None
    bmad_path: str


def _discover_epic_files(bmad_path: Path) -> list[Path]:
    """Discover epic files in BMAD directory (single-file pattern).

    Searches for epic files using glob patterns and returns them
    sorted for consistent ordering. Used when epics are not sharded.

    Args:
        bmad_path: Path to BMAD documentation directory.

    Returns:
        List of discovered epic file paths, sorted alphabetically.

    """
    epic_files = list(bmad_path.glob("*epic*.md"))

    # Filter out retrospectives and other non-epic files
    epic_files = [f for f in epic_files if "retrospective" not in f.name.lower() and f.is_file()]

    return sorted(epic_files)


def _load_epics(bmad_path: Path) -> list[EpicDocument]:
    """Load epics from BMAD directory, handling sharded and single-file patterns.

    Implements the precedence rule: single file takes priority over directory.
    Supports both:
    - Single file: docs/epics.md (consolidated epics)
    - Sharded directory: docs/epics/ (separate file per epic)

    Falls back to paths.epics_dir when bmad_path has no epics (e.g., empty
    planning-artifacts/ with epics in docs/).

    Args:
        bmad_path: Path to BMAD documentation directory.

    Returns:
        List of parsed EpicDocument objects.

    """
    result = _load_epics_from(bmad_path)
    if result:
        return result

    # Fallback: try paths.epics_dir which has full resolution chain
    # (project_knowledge → docs/ → auto-discovery)
    try:
        from bmad_assist.core.paths import get_paths

        epics_dir = get_paths().epics_dir
        if epics_dir.exists() and epics_dir.resolve() != (bmad_path / "epics").resolve():
            logger.info("Falling back to epics_dir: %s", epics_dir)
            return _load_epics_from(epics_dir.parent)
    except RuntimeError:
        pass  # Paths singleton not initialized

    return []


def _load_epics_from(bmad_path: Path) -> list[EpicDocument]:
    """Load epics from a specific BMAD directory path."""
    # Detect sharded vs single-file pattern using sharding module
    epics_path, is_sharded = resolve_doc_path(bmad_path, "epics")

    if is_sharded:
        # Sharded pattern: use dedicated loader
        logger.info("Loading epics from sharded directory: %s", epics_path)
        try:
            return load_sharded_epics(epics_path, base_path=bmad_path)
        except DuplicateEpicError:
            # Re-raise to let caller handle
            raise
    else:
        # Single-file or glob pattern: use existing discovery
        epic_files = _discover_epic_files(bmad_path)

        if not epic_files:
            logger.debug("No epic files found in %s", bmad_path)
            return []

        epics: list[EpicDocument] = []
        for epic_file in epic_files:
            try:
                epic_doc = parse_epic_file(epic_file)
                epics.append(epic_doc)
            except ParserError as e:
                logger.warning("Skipping malformed epic file %s: %s", epic_file, e)
                continue
            except OSError as e:
                logger.warning("Failed to read epic file %s: %s", epic_file, e)
                continue

        return epics


def _story_sort_key(story: EpicStory) -> tuple[int, int | str, int]:
    """Generate sort key for story ordering.

    Numeric epic IDs sort before string IDs.

    Args:
        story: The EpicStory to generate a sort key for.

    Returns:
        Tuple of (type_order, epic_id, story_num) for sorting.
        type_order: 0 for numeric epics, 1 for string epics.
        Returns (0, 0, 0) for malformed story numbers.

    """
    parts = story.number.split(".")
    if len(parts) != 2:
        logger.warning("Invalid story number format (expected X.Y): %s", story.number)
        return (0, 0, 0)

    try:
        story_num = int(parts[1])
    except ValueError as e:
        logger.warning("Non-numeric story number in %s: %s", story.number, e)
        return (0, 0, 0)

    epic_part = parts[0]
    try:
        # Numeric epic ID - sort first (type_order=0)
        epic_num = int(epic_part)
        return (0, epic_num, story_num)
    except ValueError:
        # String epic ID - sort after numeric (type_order=1)
        return (1, epic_part, story_num)


def _flatten_stories(epics: list[EpicDocument]) -> list[EpicStory]:
    """Flatten stories from all epics into a single sorted list.

    Args:
        epics: List of parsed EpicDocument objects.

    Returns:
        Sorted list of all stories by (epic_num, story_num).

    """
    all_stories: list[EpicStory] = []
    seen_numbers: set[str] = set()

    for epic in epics:
        for story in epic.stories:
            # Deduplicate by story number (AC12)
            if story.number in seen_numbers:
                logger.warning(
                    "Duplicate story %s found in %s, keeping first occurrence",
                    story.number,
                    epic.path,
                )
                continue
            all_stories.append(story)
            seen_numbers.add(story.number)

    return sorted(all_stories, key=_story_sort_key)


def _normalize_status(status: str | None) -> str:
    """Normalize story status to lowercase.

    Args:
        status: Raw status string or None.

    Returns:
        Normalized lowercase status, or "backlog" if None.

    """
    if status is None:
        return "backlog"
    return status.lower().strip()


def _apply_default_status(stories: list[EpicStory]) -> list[EpicStory]:
    """Apply default 'backlog' status to stories without explicit status.

    Creates new EpicStory instances with status set to 'backlog' for
    any story that has status=None.

    Args:
        stories: List of stories to process.

    Returns:
        List of stories with default status applied.

    """
    return [
        replace(story, status="backlog") if story.status is None else story for story in stories
    ]


def _determine_current_position(
    stories: list[EpicStory],
) -> tuple[EpicId | None, str | None]:
    """Determine current epic and story from story list.

    Finds the first story that is not "done" to determine the current
    position in the development workflow.

    Args:
        stories: List of stories sorted by number.

    Returns:
        Tuple of (current_epic, current_story) or (None, None) if all done.

    """
    for story in stories:
        status = _normalize_status(story.status)
        if status != "done":
            epic_num = parse_epic_id(story.number.split(".")[0])
            return (epic_num, story.number)

    # All stories done
    return (None, None)


def _parse_sprint_status_key(key: str) -> str | None:
    """Parse story number from sprint-status.yaml key.

    Sprint-status keys follow format:
    - Numeric: "X-Y-slug" (e.g., "2-1-markdown-parser") -> "2.1"
    - Module: "module-Y-slug" (e.g., "testarch-1-config") -> "testarch.1"

    Args:
        key: Sprint status key (e.g., "2-1-markdown-parser" or "testarch-1-config").

    Returns:
        Story number in "X.Y" format, or None if key is not a story key.

    """
    # Skip epic keys (epic-N, module-X) and retrospective keys
    if key.startswith("epic-") or key.startswith("module-") or "retrospective" in key.lower():
        return None

    parts = key.split("-")
    if len(parts) >= 2:
        # Try parsing story_num (second part must be numeric)
        try:
            story_num = int(parts[1])
        except ValueError:
            return None

        # Epic part can be numeric or string (module name)
        epic_part = parts[0]
        return f"{epic_part}.{story_num}"

    return None


def _create_epics_from_stories(stories: list[EpicStory]) -> list[EpicDocument]:
    """Create synthetic EpicDocument objects from a list of stories.

    Groups stories by epic number and creates EpicDocument objects
    for compatibility with code expecting epic structures.

    Args:
        stories: List of EpicStory objects.

    Returns:
        List of EpicDocument objects, one per unique epic.

    """
    from collections import defaultdict

    epic_stories: dict[EpicId, list[EpicStory]] = defaultdict(list)
    for story in stories:
        epic_id = (
            int(story.number.split(".")[0])
            if story.number.split(".")[0].isdigit()
            else story.number.split(".")[0]
        )
        epic_stories[epic_id].append(story)

    epics: list[EpicDocument] = []
    for epic_id, stories_list in epic_stories.items():
        epics.append(
            EpicDocument(
                epic_num=epic_id,
                title=f"Epic {epic_id}",
                status=None,
                stories=stories_list,
                path=f"<sprint-status:{epic_id}>",
            )
        )

    return epics


def _load_sprint_status_stories(bmad_path: Path) -> list[EpicStory] | None:
    """Load stories directly from sprint-status.yaml.

    Parses sprint-status.yaml and converts entries to EpicStory objects.
    This is different from _load_sprint_status() which returns a simplified
    dict mapping. This function preserves story titles.

    Args:
        bmad_path: Path to BMAD documentation directory.

    Returns:
        List of EpicStory objects, or None if sprint-status unavailable.

    """
    import yaml

    possible_paths = _get_sprint_status_candidates(bmad_path)

    for status_path in possible_paths:
        try:
            with open(status_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data is None:
                continue

            dev_status = data.get("development_status")
            if dev_status is None or not isinstance(dev_status, dict):
                continue

            stories: list[EpicStory] = []
            for key, status in dev_status.items():
                # Skip epic-level entries (e.g., "epic-1: done")
                if key.startswith("epic-") or key.endswith("-retrospective"):
                    continue

                # Parse story key (e.g., "1-2-project-name" or "22-3-title")
                # Format: epic-story-title (all hyphens)
                parts = key.split("-", 2)  # ["1", "2", "project-name"] or max 3 parts

                if len(parts) < 3:
                    continue  # Invalid format, skip

                epic_part = parts[0]
                story_part = parts[1]
                title_part = parts[2] if len(parts) > 2 else key

                story_number = f"{epic_part}.{story_part}"
                title = title_part.replace("-", " ")  # Convert hyphens to spaces for title

                if not isinstance(status, str):
                    continue

                stories.append(
                    EpicStory(
                        number=story_number,
                        title=title,
                        status=status,
                    )
                )

            if stories:
                return stories

        except (FileNotFoundError, OSError, yaml.YAMLError):
            continue

    return None


def _load_sprint_status(bmad_path: Path) -> dict[str, str] | None:
    """Load story statuses from sprint-status.yaml if available.

    Searches for sprint-status.yaml in common locations and parses
    the development_status section. Uses EAFP pattern to avoid
    TOCTOU race conditions.

    Args:
        bmad_path: Path to BMAD documentation directory.

    Returns:
        Dict mapping story numbers to statuses, or None if file doesn't exist
        or is invalid.

    """
    possible_paths = _get_sprint_status_candidates(bmad_path)

    for status_path in possible_paths:
        try:
            with open(status_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data is None:
                logger.warning("sprint-status.yaml is empty: %s", status_path)
                continue

            dev_status = data.get("development_status")

            # AC14: Validate development_status exists and is a dict
            if dev_status is None:
                logger.warning(
                    "Missing development_status section in %s, falling back to embedded statuses",
                    status_path,
                )
                return None

            if not isinstance(dev_status, dict):
                logger.warning("development_status is not a dict in %s", status_path)
                return None

            # Parse keys to story numbers
            result: dict[str, str] = {}
            for key, status in dev_status.items():
                story_num = _parse_sprint_status_key(key)
                if story_num is not None and isinstance(status, str):
                    result[story_num] = status

            return result

        except FileNotFoundError:
            continue  # Try next path (EAFP pattern)
        except yaml.YAMLError as e:
            logger.warning("Failed to parse sprint-status.yaml %s: %s", status_path, e)
            return None
        except OSError as e:
            logger.warning("Failed to read sprint-status.yaml %s: %s", status_path, e)
            return None

    return None


def _apply_sprint_statuses(
    stories: list[EpicStory], sprint_statuses: dict[str, str]
) -> list[EpicStory]:
    """Apply sprint-status.yaml statuses to stories.

    Creates new EpicStory instances with statuses from sprint-status.yaml,
    taking precedence over embedded story statuses.

    Args:
        stories: List of stories to update.
        sprint_statuses: Dict mapping story numbers to statuses.

    Returns:
        List of stories with sprint statuses applied.

    """
    return [
        replace(story, status=sprint_statuses[story.number])
        if story.number in sprint_statuses
        else story
        for story in stories
    ]


def _sync_epic_stories(
    epics: list[EpicDocument], all_stories: list[EpicStory]
) -> list[EpicDocument]:
    """Sync story statuses from all_stories back to epic.stories.

    After applying sprint statuses to all_stories, the stories within
    each EpicDocument still have their original embedded statuses.
    This function updates them to match.

    Args:
        epics: List of EpicDocument objects with original stories.
        all_stories: List of stories with updated statuses.

    Returns:
        List of EpicDocument objects with synced story statuses.

    """
    # Build lookup from story number to updated story
    story_lookup = {s.number: s for s in all_stories}

    updated_epics = []
    for epic in epics:
        # Replace stories with updated versions from all_stories
        updated_stories = [story_lookup.get(s.number, s) for s in epic.stories]
        updated_epics.append(replace(epic, stories=updated_stories))

    return updated_epics


def read_project_state(
    bmad_path: str | Path,
    use_sprint_status: bool = False,
) -> ProjectState:
    """Read current project state from BMAD files.

    Discovers and parses all epic files in the BMAD project, compiling
    a unified view of project progress including completed stories and
    current position.

    Args:
        bmad_path: Path to BMAD documentation directory (e.g., "docs").
        use_sprint_status: If True, use sprint-status.yaml for story statuses.
            Disabled by default as this is an optional extension beyond
            core Epic 2 scope.

    Returns:
        ProjectState with all epics, stories, and current position.

    Raises:
        FileNotFoundError: If bmad_path does not exist.

    Examples:
        >>> state = read_project_state("docs")
        >>> len(state.all_stories)
        60
        >>> state.current_epic
        2
        >>> state.current_story
        '2.3'

    """
    bmad_path = Path(bmad_path)

    # AC9: Handle invalid BMAD path
    if not bmad_path.exists():
        raise FileNotFoundError(f"BMAD path does not exist: {bmad_path}")

    # Step 1: Always load epics from BMAD files (supports both sharded and single-file patterns)
    epics = _load_epics(bmad_path)

    # AC8: Handle missing epic files gracefully
    if not epics:
        return ProjectState(
            epics=[],
            all_stories=[],
            completed_stories=[],
            current_epic=None,
            current_story=None,
            bmad_path=str(bmad_path),
        )

    # Step 2: Flatten and sort all stories from epic files (AC6, AC7, AC12)
    all_stories = _flatten_stories(epics)

    # Step 3: Apply default status to stories without status (AC11)
    all_stories = _apply_default_status(all_stories)

    # Step 4: Load sprint-status.yaml if enabled and merge (AC13, AC14)
    # Sprint-status takes precedence for status values, but new stories
    # from epic files (not in sprint-status) are preserved
    if use_sprint_status:
        sprint_statuses = _load_sprint_status(bmad_path)
        if sprint_statuses:
            all_stories = _apply_sprint_statuses(all_stories, sprint_statuses)
            # Also update stories within epics to keep them in sync
            epics = _sync_epic_stories(epics, all_stories)

        # Merge NEW stories from sprint-status that aren't in epics.md
        # This handles hardening stories (Story X.0) added by the handler
        sprint_stories = _load_sprint_status_stories(bmad_path)
        if sprint_stories:
            existing_numbers = {s.number for s in all_stories}
            new_stories = [s for s in sprint_stories if s.number not in existing_numbers]
            if new_stories:
                all_stories.extend(new_stories)
                all_stories = sorted(all_stories, key=_story_sort_key)
                # Create synthetic epics for the new stories and merge
                new_epics = _create_epics_from_stories(new_stories)
                for new_epic in new_epics:
                    # Merge into existing epic or append
                    merged = False
                    for i, existing in enumerate(epics):
                        if existing.epic_num == new_epic.epic_num:
                            merged_stories = list(existing.stories) + list(new_epic.stories)
                            merged_stories.sort(key=_story_sort_key)
                            epics[i] = replace(existing, stories=merged_stories)
                            merged = True
                            break
                    if not merged:
                        epics.append(new_epic)
                logger.info(
                    "Merged %d new stories from sprint-status (not in epics.md)",
                    len(new_stories),
                )

    # Step 5: Compile completed stories (AC3)
    completed_stories = [s.number for s in all_stories if _normalize_status(s.status) == "done"]

    # Step 6: Determine current position (AC4, AC5)
    current_epic, current_story = _determine_current_position(all_stories)

    # AC15: Enforce field invariants
    # If current_epic is None, current_story must be None
    # If current_story is set, current_epic must match
    # These invariants are naturally satisfied by _determine_current_position

    return ProjectState(
        epics=epics,
        all_stories=all_stories,
        completed_stories=completed_stories,
        current_epic=current_epic,
        current_story=current_story,
        bmad_path=str(bmad_path),
    )
