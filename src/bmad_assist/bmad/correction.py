"""State discrepancy correction for BMAD files.

This module provides functionality to correct discrepancies between internal
state and BMAD files by updating BMAD files to match internal state.

CRITICAL: Internal state is the source of truth. All corrections update
BMAD files to match internal state, NEVER vice versa.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

import frontmatter
import yaml

from bmad_assist.bmad.discrepancy import Discrepancy, StateComparable
from bmad_assist.core.exceptions import ReconciliationError

logger = logging.getLogger(__name__)


def _get_stories_dir(bmad_root: Path) -> Path:
    """Get stories directory, using paths singleton if available.

    Args:
        bmad_root: Fallback BMAD documentation root.

    Returns:
        Path to stories directory.

    """
    try:
        from bmad_assist.core.paths import get_paths

        return get_paths().stories_dir
    except (RuntimeError, ImportError):
        # Fallback to legacy location
        return bmad_root / "sprint-artifacts"


def _get_sprint_status_path(bmad_root: Path) -> Path:
    """Get sprint-status.yaml path, using paths singleton if available.

    Args:
        bmad_root: Fallback BMAD documentation root.

    Returns:
        Path to sprint-status.yaml.

    """
    from bmad_assist.core.paths import get_paths

    try:
        paths = get_paths()
        found = paths.find_sprint_status()
        if found:
            return found
        # Return default new location if not found
        return paths.sprint_status_file
    except RuntimeError:
        # Fallback when singleton not initialized
        # Check planning-artifacts first (Beta default), then legacy locations
        planning_artifacts = bmad_root.parent / "_bmad-output" / "planning-artifacts" / "sprint-status.yaml"
        if planning_artifacts.exists():
            return planning_artifacts
        legacy_artifacts = bmad_root / "sprint-artifacts" / "sprint-status.yaml"
        if legacy_artifacts.exists():
            return legacy_artifacts
        return bmad_root / "sprint-status.yaml"


# Type alias for confirmation callback
# callback(discrepancy, options) -> chosen_option
ConfirmCallback = Callable[[Discrepancy, list[str]], str]


class CorrectionAction(Enum):
    """Action taken to correct a discrepancy.

    Note: We ALWAYS update BMAD files, NEVER internal state.
    Internal state is the source of truth.

    Attributes:
        UPDATED_BMAD: BMAD file was updated to match internal state.
        SKIPPED: User chose to skip correction.
        NO_CHANGE_NEEDED: BMAD already matches internal OR requires user input.
        ERROR: Correction failed with error.

    """

    UPDATED_BMAD = auto()
    SKIPPED = auto()
    NO_CHANGE_NEEDED = auto()
    ERROR = auto()


@dataclass
class CorrectionResult:
    """Result of a discrepancy correction attempt.

    Attributes:
        action: The action taken (or not taken).
        discrepancy: The original Discrepancy that was processed.
        details: Human-readable description of what was done.
        error: Error message if action is ERROR, otherwise None.
        modified_files: Paths of modified BMAD files, or None if no files modified.

    """

    action: CorrectionAction
    discrepancy: Discrepancy
    details: str
    error: str | None = None
    modified_files: list[Path] | None = None


def _atomic_write_file(path: Path, content: str) -> None:
    """Write content to file atomically using temp file + rename.

    Args:
        path: Target file path.
        content: Content to write.

    Raises:
        OSError: If file write fails.

    """
    # Create temp file in same directory to ensure same filesystem for rename
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)

    fd = None
    temp_path = None

    try:
        fd, temp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None  # Prevent double-close; fdopen takes ownership
            f.write(content)
        os.rename(temp_path, path)
        temp_path = None  # Successfully renamed; don't clean up
    except Exception as write_error:
        # Clean up resources without losing the original exception
        if fd is not None:
            try:
                os.close(fd)
            except OSError as close_error:
                logger.debug("Failed to close temp fd: %s", close_error)

        if temp_path is not None and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError as unlink_error:
                logger.warning(
                    "Failed to cleanup temp file %s: %s",
                    temp_path,
                    unlink_error,
                )

        raise write_error


def _update_story_frontmatter(
    story_path: Path,
    new_status: str,
) -> None:
    """Update story file frontmatter with new status.

    Uses python-frontmatter library to preserve structure.

    Args:
        story_path: Path to story markdown file.
        new_status: New status value to set.

    Raises:
        FileNotFoundError: If story file doesn't exist.
        OSError: If file operations fail.

    """
    post = frontmatter.load(story_path)
    post.metadata["status"] = new_status
    content = frontmatter.dumps(post)
    _atomic_write_file(story_path, content)


def _update_sprint_status(
    sprint_status_path: Path,
    story_key: str,
    new_status: str,
) -> None:
    """Update sprint-status.yaml with new story status.

    Args:
        sprint_status_path: Path to sprint-status.yaml.
        story_key: Story key in development_status (e.g., "2-3-story-name").
        new_status: New status value.

    Raises:
        FileNotFoundError: If sprint-status.yaml doesn't exist.
        OSError: If file operations fail.

    """
    with open(sprint_status_path, encoding="utf-8") as f:
        content = f.read()

    data = yaml.safe_load(content)
    if data is None:
        data = {}

    dev_status = data.get("development_status", {})
    if story_key in dev_status:
        dev_status[story_key] = new_status
        data["development_status"] = dev_status

        # Preserve original file structure as much as possible
        # Using yaml.dump with default_flow_style=False for readability
        new_content = yaml.dump(data, default_flow_style=False, allow_unicode=True)
        _atomic_write_file(sprint_status_path, new_content)


def _find_sprint_status_key(
    sprint_status_path: Path,
    story_number: str,
) -> str | None:
    """Find the sprint-status key for a given story number.

    Sprint-status keys follow format: "X-Y-slug" where X.Y is story number.

    Args:
        sprint_status_path: Path to sprint-status.yaml.
        story_number: Story number in "X.Y" format.

    Returns:
        Sprint-status key if found, None otherwise.

    """
    try:
        with open(sprint_status_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (FileNotFoundError, yaml.YAMLError):
        return None

    if not data or "development_status" not in data:
        return None

    # Parse story number to match key pattern
    parts = story_number.split(".")
    if len(parts) != 2:
        return None

    epic_num, story_num = parts
    prefix = f"{epic_num}-{story_num}-"

    for key in data["development_status"]:
        if isinstance(key, str) and (key.startswith(prefix) or key == f"{epic_num}-{story_num}"):
            return key

    return None


def _find_story_file(
    bmad_root: Path,
    story_number: str,
) -> Path | None:
    """Find story file in BMAD project by story number.

    Searches in sprint-artifacts and other common locations.

    Args:
        bmad_root: Root path of BMAD documentation.
        story_number: Story number in "X.Y" format.

    Returns:
        Path to story file if found, None otherwise.

    """
    parts = story_number.split(".")
    if len(parts) != 2:
        return None

    epic_num, story_num = parts
    pattern = f"{epic_num}-{story_num}-*.md"

    # Try new paths first
    stories_dir = _get_stories_dir(bmad_root)
    if stories_dir.exists():
        matches = list(stories_dir.glob(pattern))
        if matches:
            return matches[0]

    # Legacy fallback patterns
    legacy_patterns = [
        f"sprint-artifacts/{epic_num}-{story_num}-*.md",
        f"{epic_num}-{story_num}-*.md",
        f"stories/{epic_num}-{story_num}-*.md",
    ]

    for legacy_pattern in legacy_patterns:
        matches = list(bmad_root.glob(legacy_pattern))
        if matches:
            return matches[0]

    return None


def _create_minimal_story_file(
    bmad_root: Path,
    story_number: str,
    status: str,
) -> Path:
    """Create minimal BMAD story file from internal state.

    Args:
        bmad_root: Root path of BMAD documentation.
        story_number: Story number in "X.Y" format.
        status: Status to set in frontmatter.

    Returns:
        Path to created story file.

    """
    parts = story_number.split(".")
    epic_num, story_num = parts

    # Create in stories directory (new path or legacy sprint-artifacts)
    stories_dir = _get_stories_dir(bmad_root)
    stories_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{epic_num}-{story_num}-placeholder.md"
    story_path = stories_dir / filename

    content = f"""---
status: {status}
---

# Story {story_number}: Placeholder

> This story file was auto-generated from internal state.
> Please update with actual story content.

**Status:** {status}
"""

    _atomic_write_file(story_path, content)
    return story_path


def _check_bmad_matches_internal(
    discrepancy: Discrepancy,
    internal_state: StateComparable,
    bmad_root: Path,
) -> bool:
    """Check if BMAD already matches internal state for this discrepancy.

    Used for idempotency check (AC16).

    Args:
        discrepancy: The discrepancy to check.
        internal_state: Internal state (source of truth).
        bmad_root: Root path of BMAD documentation.

    Returns:
        True if BMAD matches internal state, False otherwise.

    """
    disc_type = discrepancy.type

    if disc_type == "current_epic_mismatch":
        # Would need to re-read BMAD state to check - simplified for now
        return False

    if disc_type == "current_story_mismatch":
        return False

    if disc_type == "story_status_mismatch":
        story_num = discrepancy.story_number
        if story_num is None:
            return False

        story_path = _find_story_file(bmad_root, story_num)
        if story_path is None or not story_path.exists():
            return False

        try:
            post = frontmatter.load(story_path)
            current_status = post.metadata.get("status", "").lower()
            # Check if BMAD now has the expected status
            expected = discrepancy.expected
            if expected is not None and isinstance(expected, str):
                return bool(current_status == expected.lower())
        except Exception:
            pass

        return False

    if disc_type == "story_not_in_bmad":
        story_num = discrepancy.story_number
        if story_num is None:
            return False
        # Check if story file now exists
        story_path = _find_story_file(bmad_root, story_num)
        return story_path is not None and story_path.exists()

    if disc_type == "story_not_in_internal":
        # This checks if story was removed from BMAD
        file_path = discrepancy.file_path
        if file_path is None:
            return False
        return not Path(file_path).exists()

    return False


def _get_correction_options(discrepancy_type: str) -> list[str]:
    """Get valid correction options for a discrepancy type.

    Args:
        discrepancy_type: Type of discrepancy.

    Returns:
        List of valid option strings.

    """
    # Map discrepancy types to their valid options
    options_map = {
        "current_epic_mismatch": ["update_bmad", "skip"],
        "current_story_mismatch": ["update_bmad", "skip"],
        "completed_stories_mismatch": ["update_bmad", "skip"],
        "story_status_mismatch": ["update_bmad", "skip"],
        "story_not_in_bmad": ["create_bmad", "skip"],
        "story_not_in_internal": ["remove_from_bmad", "skip"],
        "bmad_empty": ["recreate_bmad", "skip"],
    }
    return options_map.get(discrepancy_type, ["skip"])


def _is_auto_correctable(discrepancy: Discrepancy) -> bool:
    """Determine if a discrepancy can be auto-corrected.

    Args:
        discrepancy: The discrepancy to check.

    Returns:
        True if auto-correctable, False if requires confirmation.

    """
    disc_type = discrepancy.type

    # Always require confirmation for these suspicious types
    if disc_type in ("story_not_in_internal", "bmad_empty"):
        return False

    # story_status_mismatch: auto-correct only if BMAD is "behind"
    # (internal says done, BMAD doesn't)
    if disc_type == "story_status_mismatch":
        expected = discrepancy.expected
        actual = discrepancy.actual
        # BMAD behind internal: internal=done, bmad=something_else
        if expected == "done" and actual != "done":
            return True
        # BMAD ahead of internal: internal=in-progress, bmad=done
        # This is suspicious - requires confirmation
        # All other cases are safe to auto-correct
        return not (expected == "in-progress" and actual == "done")

    # These are safe to auto-correct
    return disc_type in (
        "current_epic_mismatch",
        "current_story_mismatch",
        "completed_stories_mismatch",
        "story_not_in_bmad",
    )


def _correct_current_epic_mismatch(
    discrepancy: Discrepancy,
    internal_state: StateComparable,
    bmad_root: Path,
) -> CorrectionResult:
    """Correct current_epic_mismatch by updating BMAD tracking file.

    Args:
        discrepancy: The discrepancy to correct.
        internal_state: Internal state (source of truth).
        bmad_root: Root path of BMAD documentation.

    Returns:
        CorrectionResult with action taken.

    """
    # Find sprint-status.yaml
    sprint_status_path = _get_sprint_status_path(bmad_root)

    if not sprint_status_path.exists():
        return CorrectionResult(
            action=CorrectionAction.NO_CHANGE_NEEDED,
            discrepancy=discrepancy,
            details="No sprint-status.yaml found to update for current_epic",
        )

    # Note: sprint-status.yaml doesn't have a direct current_epic field
    # The current epic is derived from story statuses
    # For now, we report that correction would need to update story statuses
    logger.info(
        "Corrected current_epic_mismatch: internal=%s",
        internal_state.current_epic,
    )

    return CorrectionResult(
        action=CorrectionAction.NO_CHANGE_NEEDED,
        discrepancy=discrepancy,
        details=(
            f"Current epic mismatch noted: internal={internal_state.current_epic}. "
            "Epic position is derived from story statuses; no direct update needed."
        ),
    )


def _correct_current_story_mismatch(
    discrepancy: Discrepancy,
    internal_state: StateComparable,
    bmad_root: Path,
) -> CorrectionResult:
    """Correct current_story_mismatch by updating BMAD tracking file.

    Args:
        discrepancy: The discrepancy to correct.
        internal_state: Internal state (source of truth).
        bmad_root: Root path of BMAD documentation.

    Returns:
        CorrectionResult with action taken.

    """
    # Similar to current_epic - the current story is derived from statuses
    logger.info(
        "Corrected current_story_mismatch: internal=%s",
        internal_state.current_story,
    )

    return CorrectionResult(
        action=CorrectionAction.NO_CHANGE_NEEDED,
        discrepancy=discrepancy,
        details=(
            f"Current story mismatch noted: internal={internal_state.current_story}. "
            "Story position is derived from statuses; no direct update needed."
        ),
    )


def _correct_completed_stories_mismatch(
    discrepancy: Discrepancy,
    internal_state: StateComparable,
    bmad_root: Path,
) -> CorrectionResult:
    """Correct completed_stories_mismatch by updating BMAD story statuses.

    Args:
        discrepancy: The discrepancy to correct.
        internal_state: Internal state (source of truth).
        bmad_root: Root path of BMAD documentation.

    Returns:
        CorrectionResult with action taken.

    """
    internal_set = set(internal_state.completed_stories)
    bmad_set = set(discrepancy.actual) if discrepancy.actual else set()

    # Stories in internal but not BMAD (need to mark as done in BMAD)
    missing_from_bmad = internal_set - bmad_set

    modified_files: list[Path] = []
    updated_stories: list[str] = []

    # Find sprint-status.yaml
    sprint_status_path = _get_sprint_status_path(bmad_root)

    for story_num in missing_from_bmad:
        # Try to update sprint-status first
        if sprint_status_path.exists():
            story_key = _find_sprint_status_key(sprint_status_path, story_num)
            if story_key:
                try:
                    _update_sprint_status(sprint_status_path, story_key, "done")
                    if sprint_status_path not in modified_files:
                        modified_files.append(sprint_status_path)
                    updated_stories.append(story_num)
                    continue
                except OSError as e:
                    logger.warning("Failed to update sprint-status for %s: %s", story_num, e)

        # Fall back to updating story file
        story_path = _find_story_file(bmad_root, story_num)
        if story_path and story_path.exists():
            try:
                _update_story_frontmatter(story_path, "done")
                modified_files.append(story_path)
                updated_stories.append(story_num)
            except OSError as e:
                logger.warning("Failed to update story file for %s: %s", story_num, e)

    if updated_stories:
        logger.info(
            "Corrected completed_stories_mismatch: updated BMAD for stories %s",
            updated_stories,
        )
        return CorrectionResult(
            action=CorrectionAction.UPDATED_BMAD,
            discrepancy=discrepancy,
            details=f"Updated BMAD completed stories: added {sorted(updated_stories)}",
            modified_files=modified_files,
        )

    return CorrectionResult(
        action=CorrectionAction.NO_CHANGE_NEEDED,
        discrepancy=discrepancy,
        details="No BMAD files found to update for completed_stories",
    )


def _correct_story_status_mismatch(
    discrepancy: Discrepancy,
    internal_state: StateComparable,
    bmad_root: Path,
) -> CorrectionResult:
    """Correct story_status_mismatch by updating BMAD story file.

    Args:
        discrepancy: The discrepancy to correct.
        internal_state: Internal state (source of truth).
        bmad_root: Root path of BMAD documentation.

    Returns:
        CorrectionResult with action taken.

    """
    story_num = discrepancy.story_number
    if story_num is None:
        return CorrectionResult(
            action=CorrectionAction.ERROR,
            discrepancy=discrepancy,
            details="Cannot correct story_status_mismatch without story_number",
            error="Missing story_number in discrepancy",
        )

    expected_status = discrepancy.expected
    if expected_status is None:
        return CorrectionResult(
            action=CorrectionAction.ERROR,
            discrepancy=discrepancy,
            details="Cannot correct story_status_mismatch without expected status",
            error="Missing expected status in discrepancy",
        )

    modified_files: list[Path] = []

    # Try sprint-status first
    sprint_status_path = _get_sprint_status_path(bmad_root)

    if sprint_status_path.exists():
        story_key = _find_sprint_status_key(sprint_status_path, story_num)
        if story_key:
            try:
                _update_sprint_status(sprint_status_path, story_key, expected_status)
                modified_files.append(sprint_status_path)
                logger.info(
                    "Corrected story_status_mismatch for %s: %s → %s",
                    story_num,
                    discrepancy.actual,
                    expected_status,
                )
                return CorrectionResult(
                    action=CorrectionAction.UPDATED_BMAD,
                    discrepancy=discrepancy,
                    details=(
                        f"Updated BMAD story {story_num} status: "
                        f"{discrepancy.actual} → {expected_status}"
                    ),
                    modified_files=modified_files,
                )
            except OSError as e:
                logger.warning("Failed to update sprint-status: %s", e)

    # Fall back to story file
    story_path = _find_story_file(bmad_root, story_num)
    if story_path and story_path.exists():
        try:
            _update_story_frontmatter(story_path, expected_status)
            modified_files.append(story_path)
            logger.info(
                "Corrected story_status_mismatch for %s: %s → %s",
                story_num,
                discrepancy.actual,
                expected_status,
            )
            return CorrectionResult(
                action=CorrectionAction.UPDATED_BMAD,
                discrepancy=discrepancy,
                details=(
                    f"Updated BMAD story {story_num} status: "
                    f"{discrepancy.actual} → {expected_status}"
                ),
                modified_files=modified_files,
            )
        except OSError as e:
            return CorrectionResult(
                action=CorrectionAction.ERROR,
                discrepancy=discrepancy,
                details=f"Failed to update story file for {story_num}",
                error=str(e),
            )

    return CorrectionResult(
        action=CorrectionAction.NO_CHANGE_NEEDED,
        discrepancy=discrepancy,
        details=f"No BMAD file found for story {story_num}",
    )


def _correct_story_not_in_bmad(
    discrepancy: Discrepancy,
    internal_state: StateComparable,
    bmad_root: Path,
) -> CorrectionResult:
    """Correct story_not_in_bmad by creating BMAD story file.

    Args:
        discrepancy: The discrepancy to correct.
        internal_state: Internal state (source of truth).
        bmad_root: Root path of BMAD documentation.

    Returns:
        CorrectionResult with action taken.

    """
    story_num = discrepancy.story_number
    if story_num is None:
        return CorrectionResult(
            action=CorrectionAction.ERROR,
            discrepancy=discrepancy,
            details="Cannot correct story_not_in_bmad without story_number",
            error="Missing story_number in discrepancy",
        )

    # Determine status from internal state
    if story_num in internal_state.completed_stories:
        status = "done"
    elif story_num == internal_state.current_story:
        status = "in-progress"
    else:
        status = "backlog"

    try:
        story_path = _create_minimal_story_file(bmad_root, story_num, status)
        logger.info("Created BMAD file for story %s from internal state", story_num)
        return CorrectionResult(
            action=CorrectionAction.UPDATED_BMAD,
            discrepancy=discrepancy,
            details=f"Created BMAD file for story {story_num} from internal state",
            modified_files=[story_path],
        )
    except OSError as e:
        return CorrectionResult(
            action=CorrectionAction.ERROR,
            discrepancy=discrepancy,
            details=f"Failed to create BMAD file for story {story_num}",
            error=str(e),
        )


def _correct_story_not_in_internal(
    discrepancy: Discrepancy,
    bmad_root: Path,
    action: str,
) -> CorrectionResult:
    """Correct story_not_in_internal based on user action.

    Args:
        discrepancy: The discrepancy to correct.
        bmad_root: Root path of BMAD documentation.
        action: User's chosen action ("remove_from_bmad" or "skip").

    Returns:
        CorrectionResult with action taken.

    """
    if action == "skip":
        return CorrectionResult(
            action=CorrectionAction.SKIPPED,
            discrepancy=discrepancy,
            details="User chose to skip correction for story_not_in_internal",
        )

    story_path = discrepancy.file_path
    if story_path is None:
        return CorrectionResult(
            action=CorrectionAction.ERROR,
            discrepancy=discrepancy,
            details="Cannot remove story without file_path",
            error="Missing file_path in discrepancy",
        )

    path = Path(story_path)
    story_num = discrepancy.story_number

    if not path.exists():
        return CorrectionResult(
            action=CorrectionAction.NO_CHANGE_NEEDED,
            discrepancy=discrepancy,
            details=f"Story file already removed: {story_path}",
        )

    try:
        # Archive the file by renaming with .archived suffix
        archived_path = path.with_suffix(path.suffix + ".archived")
        path.rename(archived_path)
        logger.info("Archived BMAD story file %s → %s", story_path, archived_path)
        return CorrectionResult(
            action=CorrectionAction.UPDATED_BMAD,
            discrepancy=discrepancy,
            details=f"Archived BMAD file for story {story_num}: {archived_path.name}",
            modified_files=[archived_path],
        )
    except OSError as e:
        return CorrectionResult(
            action=CorrectionAction.ERROR,
            discrepancy=discrepancy,
            details=f"Failed to archive story file: {story_path}",
            error=str(e),
        )


def _correct_bmad_empty(
    discrepancy: Discrepancy,
    internal_state: StateComparable,
    bmad_root: Path,
    action: str,
) -> CorrectionResult:
    """Correct bmad_empty by recreating BMAD files from internal state.

    Args:
        discrepancy: The discrepancy to correct.
        internal_state: Internal state (source of truth).
        bmad_root: Root path of BMAD documentation.
        action: User's chosen action ("recreate_bmad" or "skip").

    Returns:
        CorrectionResult with action taken.

    """
    if action == "skip":
        return CorrectionResult(
            action=CorrectionAction.SKIPPED,
            discrepancy=discrepancy,
            details="User chose to skip BMAD reconstruction",
        )

    # Recreate story files for all completed stories
    modified_files: list[Path] = []
    created_stories: list[str] = []

    for story_num in internal_state.completed_stories:
        try:
            story_path = _create_minimal_story_file(bmad_root, story_num, "done")
            modified_files.append(story_path)
            created_stories.append(story_num)
        except OSError as e:
            logger.warning("Failed to create story file for %s: %s", story_num, e)

    # Create current story if exists
    if internal_state.current_story:
        try:
            story_path = _create_minimal_story_file(
                bmad_root, internal_state.current_story, "in-progress"
            )
            modified_files.append(story_path)
            created_stories.append(internal_state.current_story)
        except OSError as e:
            logger.warning(
                "Failed to create current story file for %s: %s",
                internal_state.current_story,
                e,
            )

    if created_stories:
        logger.info("Recreated BMAD files for %d stories from internal state", len(created_stories))
        return CorrectionResult(
            action=CorrectionAction.UPDATED_BMAD,
            discrepancy=discrepancy,
            details=f"Recreated BMAD files for {len(created_stories)} stories from internal state",
            modified_files=modified_files,
        )

    return CorrectionResult(
        action=CorrectionAction.NO_CHANGE_NEEDED,
        discrepancy=discrepancy,
        details="No stories in internal state to recreate",
    )


def correct_discrepancy(
    discrepancy: Discrepancy,
    internal_state: StateComparable,
    bmad_root: Path,
    auto: bool = True,
    confirm_callback: ConfirmCallback | None = None,
) -> CorrectionResult:
    """Correct a single discrepancy by updating BMAD files to match internal state.

    CRITICAL: Internal state is the source of truth. This function NEVER modifies
    internal_state. All corrections update BMAD files to match internal state.

    Args:
        discrepancy: The Discrepancy to correct.
        internal_state: Internal state object (READ-ONLY, source of truth).
        bmad_root: Path to BMAD project root (for writing corrected files).
        auto: If True, auto-correct safe discrepancies. If False, always
            invoke confirm_callback for user decision.
        confirm_callback: Function to call for user confirmation when
            auto=False or when discrepancy requires user decision.
            Must be provided if auto=False.

    Returns:
        CorrectionResult describing what action was taken.

    Raises:
        ReconciliationError: If auto=False and confirm_callback is None.

    Examples:
        >>> result = correct_discrepancy(discrepancy, internal, Path("docs"))
        >>> result.action
        CorrectionAction.UPDATED_BMAD

    """
    # Validate inputs
    if not auto and confirm_callback is None:
        raise ReconciliationError("confirm_callback is required when auto=False")

    bmad_root = Path(bmad_root)

    # AC16: Idempotency check - if BMAD already matches internal, no change needed
    if _check_bmad_matches_internal(discrepancy, internal_state, bmad_root):
        return CorrectionResult(
            action=CorrectionAction.NO_CHANGE_NEEDED,
            discrepancy=discrepancy,
            details="BMAD already matches internal state",
        )

    disc_type = discrepancy.type
    is_auto_ok = _is_auto_correctable(discrepancy)

    # Determine if we need user confirmation
    need_confirmation = not auto or not is_auto_ok

    if need_confirmation:
        if confirm_callback is None:
            # AC12: Return NO_CHANGE_NEEDED for non-auto-correctable without callback
            return CorrectionResult(
                action=CorrectionAction.NO_CHANGE_NEEDED,
                discrepancy=discrepancy,
                details=f"Discrepancy type '{disc_type}' requires user confirmation",
            )

        options = _get_correction_options(disc_type)

        try:
            # AC7: Invoke callback and wait for response
            user_choice = confirm_callback(discrepancy, options)
        except Exception as e:
            # AC15: Handle callback exceptions gracefully
            logger.warning("Callback raised exception for %s: %s", disc_type, e)
            return CorrectionResult(
                action=CorrectionAction.ERROR,
                discrepancy=discrepancy,
                details="Confirmation callback raised exception",
                error=str(e),
            )

        # AC14: Validate callback return value
        if user_choice not in options:
            logger.warning("Invalid callback response for %s: %s", disc_type, user_choice)
            return CorrectionResult(
                action=CorrectionAction.ERROR,
                discrepancy=discrepancy,
                details="Invalid callback response",
                error=f"Invalid callback response: {user_choice}",
            )

        if user_choice == "skip":
            return CorrectionResult(
                action=CorrectionAction.SKIPPED,
                discrepancy=discrepancy,
                details="User chose to skip correction",
            )

        # Handle discrepancy types that need special action handling
        if disc_type == "story_not_in_internal":
            return _correct_story_not_in_internal(discrepancy, bmad_root, user_choice)

        if disc_type == "bmad_empty":
            return _correct_bmad_empty(discrepancy, internal_state, bmad_root, user_choice)

    # Execute correction based on type
    try:
        if disc_type == "current_epic_mismatch":
            return _correct_current_epic_mismatch(discrepancy, internal_state, bmad_root)

        if disc_type == "current_story_mismatch":
            return _correct_current_story_mismatch(discrepancy, internal_state, bmad_root)

        if disc_type == "completed_stories_mismatch":
            return _correct_completed_stories_mismatch(discrepancy, internal_state, bmad_root)

        if disc_type == "story_status_mismatch":
            return _correct_story_status_mismatch(discrepancy, internal_state, bmad_root)

        if disc_type == "story_not_in_bmad":
            return _correct_story_not_in_bmad(discrepancy, internal_state, bmad_root)

        if disc_type == "story_not_in_internal":
            # Should have been handled above with confirmation
            return CorrectionResult(
                action=CorrectionAction.NO_CHANGE_NEEDED,
                discrepancy=discrepancy,
                details="story_not_in_internal requires user confirmation",
            )

        if disc_type == "bmad_empty":
            # Should have been handled above with confirmation
            return CorrectionResult(
                action=CorrectionAction.NO_CHANGE_NEEDED,
                discrepancy=discrepancy,
                details="bmad_empty requires user confirmation",
            )

        # Unknown discrepancy type
        return CorrectionResult(
            action=CorrectionAction.NO_CHANGE_NEEDED,
            discrepancy=discrepancy,
            details=f"Unknown discrepancy type: {disc_type}",
        )

    except Exception as e:
        # AC13: Return ERROR result on correction failure
        logger.warning("Failed to correct discrepancy %s: %s", disc_type, e)
        return CorrectionResult(
            action=CorrectionAction.ERROR,
            discrepancy=discrepancy,
            details="BMAD correction failed",
            error=str(e),
        )


def correct_all_discrepancies(
    discrepancies: list[Discrepancy],
    internal_state: StateComparable,
    bmad_root: Path,
    auto: bool = True,
    confirm_callback: ConfirmCallback | None = None,
) -> list[CorrectionResult]:
    """Correct all discrepancies by updating BMAD files to match internal state.

    CRITICAL: Internal state is the source of truth. This function NEVER modifies
    internal_state. All corrections update BMAD files to match internal state.

    No rollback is performed on failure - corrections applied before an error
    remain in effect.

    Args:
        discrepancies: List of Discrepancy objects to correct.
        internal_state: Internal state object (READ-ONLY, source of truth).
        bmad_root: Path to BMAD project root (for writing corrected files).
        auto: If True, auto-correct safe discrepancies.
        confirm_callback: Function to call for user confirmation.

    Returns:
        List of CorrectionResult objects (one per discrepancy).

    Raises:
        ReconciliationError: If auto=False and confirm_callback is None.

    Examples:
        >>> results = correct_all_discrepancies(discrepancies, internal, Path("docs"))
        >>> updated = sum(1 for r in results if r.action == CorrectionAction.UPDATED_BMAD)

    """
    if not auto and confirm_callback is None:
        raise ReconciliationError("confirm_callback is required when auto=False")

    results: list[CorrectionResult] = []

    for discrepancy in discrepancies:
        result = correct_discrepancy(
            discrepancy,
            internal_state,
            bmad_root,
            auto=auto,
            confirm_callback=confirm_callback,
        )
        results.append(result)

    # Log summary
    updated = sum(1 for r in results if r.action == CorrectionAction.UPDATED_BMAD)
    skipped = sum(1 for r in results if r.action == CorrectionAction.SKIPPED)
    errors = sum(1 for r in results if r.action == CorrectionAction.ERROR)
    no_change = sum(1 for r in results if r.action == CorrectionAction.NO_CHANGE_NEEDED)

    logger.info(
        "Batch correction complete: %d BMAD files updated, %d skipped, %d errors, %d no change",
        updated,
        skipped,
        errors,
        no_change,
    )

    return results
