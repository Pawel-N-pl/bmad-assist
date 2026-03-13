"""Context file building for BMAD workflow compilers.

This module provides the ContextBuilder class with a fluent API for
assembling context files with recency-bias ordering. All compilers
should use ContextBuilder instead of duplicating file discovery logic.

Public API:
    ContextBuilder: Fluent builder for context file assembly
    PRIORITY_BACKGROUND: Priority constant (10)
    PRIORITY_PLANNING: Priority constant (20)
    PRIORITY_STORIES: Priority constant (30)
    PRIORITY_VALIDATIONS: Priority constant (40)
    PRIORITY_EPIC: Priority constant (50)
"""

from __future__ import annotations

__all__ = [
    "ContextBuilder",
    "PRIORITY_BACKGROUND",
    "PRIORITY_PLANNING",
    "PRIORITY_STORIES",
    "PRIORITY_VALIDATIONS",
    "PRIORITY_EPIC",
]

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from bmad_assist.bmad.sharding import load_sharded_content, resolve_doc_path
from bmad_assist.bmad.sharding.sorting import DocType
from bmad_assist.compiler.shared_utils import (
    find_project_context_file,
    get_epics_dir,
    get_planning_artifacts_dir,
    get_stories_dir,
    get_validations_dir,
    safe_read_file,
)
from bmad_assist.core.exceptions import ContextError

if TYPE_CHECKING:
    from bmad_assist.compiler.types import CompilerContext

logger = logging.getLogger(__name__)

# Priority constants for recency-bias ordering
# Lower = earlier in context (more general/background)
# Higher = later in context (more specific/relevant)
PRIORITY_BACKGROUND = 10
PRIORITY_PLANNING = 20
PRIORITY_STORIES = 30
PRIORITY_VALIDATIONS = 40
PRIORITY_EPIC = 50


class ContextBuilder:
    """Fluent builder for context file assembly with recency-bias ordering.

    Assembles context files from various sources (project context, planning docs,
    previous stories, validations, epics) with automatic ordering based on priority.
    Files are ordered from general (early) to specific (late) in the final output.

    Usage:
        builder = ContextBuilder(context)
        context_files = (
            builder
            .add_project_context()
            .add_planning_docs(prd=True, architecture=True)
            .add_previous_stories(count=3)
            .add_epic_files(epic_num=12)
            .build()
        )

    The build() method returns an ordered dict where keys are absolute path strings
    and values are file contents. Python 3.7+ guarantees dict insertion order.

    """

    def __init__(self, context: CompilerContext) -> None:
        """Initialize ContextBuilder with compilation context.

        Args:
            context: CompilerContext with project_root and output_folder.

        """
        self._context = context
        # Store entries as (priority, path, content) for sorting
        self._entries: list[tuple[int, str, str]] = []
        # Track added paths to prevent duplicates
        self._seen_paths: set[str] = set()

    def add_project_context(self, required: bool = True) -> ContextBuilder:
        """Add project_context.md to the context.

        Args:
            required: If True, raises ContextError when file is missing.
                     If False, logs warning and continues.

        Returns:
            Self for method chaining.

        Raises:
            ContextError: If required=True and file is not found.

        """
        path = find_project_context_file(self._context)

        if path is None:
            if required:
                raise ContextError(
                    "Required context file not found: project_context.md\n"
                    "  Searched in: output_folder, project_root/docs, project_root\n"
                    "  Suggestion: Run 'generate-project-context' workflow"
                )
            logger.warning("project_context.md not found, skipping")
            return self

        self._add_file(path, PRIORITY_BACKGROUND, required=required)
        return self

    def add_planning_docs(
        self,
        prd: bool = True,
        architecture: bool = True,
        ux: bool = True,
        required: bool = False,
    ) -> ContextBuilder:
        """Add planning documents (PRD, architecture, UX) to the context.

        Handles both single-file and sharded document formats. Sharded documents
        are loaded using FULL_LOAD strategy (all files concatenated).

        Args:
            prd: If True, include PRD document.
            architecture: If True, include architecture document.
            ux: If True, include UX design document.
            required: If True, raises ContextError when any requested file is missing.

        Returns:
            Self for method chaining.

        Raises:
            ContextError: If required=True and a requested file is not found.

        """
        planning_dir = get_planning_artifacts_dir(self._context)

        if prd:
            self._add_planning_doc("prd", planning_dir, required)

        if architecture:
            self._add_planning_doc("architecture", planning_dir, required)

        if ux:
            self._add_planning_doc("ux", planning_dir, required)

        return self

    def _add_planning_doc(
        self,
        doc_name: DocType,
        planning_dir: Path,
        required: bool,
    ) -> None:
        """Add a single planning document (handles sharded/whole).

        Searches in two locations with priority:
        1. planning_artifacts (specific to current work)
        2. project_knowledge (general project docs, brownfield fallback)

        Args:
            doc_name: Document type name (prd, architecture, ux).
            planning_dir: Planning artifacts directory (from config).
            required: If True, raises ContextError when not found.

        """
        resolved_path: Path | None = None
        is_sharded = False

        # Try to resolve as sharded or whole in planning_dir
        path, sharded = resolve_doc_path(planning_dir, doc_name)
        # Check if file/dir actually exists (resolve_doc_path returns path even when not found)
        if path.exists():
            resolved_path = path
            is_sharded = sharded

        if resolved_path is None:
            # Try glob pattern fallback in planning_dir
            pattern = f"*{doc_name}*.md"
            matches = sorted(planning_dir.glob(pattern))
            if matches:
                resolved_path = matches[0]
                is_sharded = False

        # Fallback to project_knowledge (brownfield projects)
        if resolved_path is None:
            try:
                from bmad_assist.core.paths import get_paths

                project_knowledge = get_paths().project_knowledge
                if project_knowledge != planning_dir:
                    path, sharded = resolve_doc_path(project_knowledge, doc_name)
                    if path.exists():
                        resolved_path = path
                        is_sharded = sharded
                    if resolved_path is None:
                        pattern = f"*{doc_name}*.md"
                        matches = sorted(project_knowledge.glob(pattern))
                        if matches:
                            resolved_path = matches[0]
                            is_sharded = False
            except RuntimeError:
                # Paths not initialized, try project_root/docs
                fallback = self._context.project_root / "docs"
                if fallback.exists() and fallback != planning_dir:
                    pattern = f"*{doc_name}*.md"
                    matches = sorted(fallback.glob(pattern))
                    if matches:
                        resolved_path = matches[0]
                        is_sharded = False

        if resolved_path is None:
            if required:
                raise ContextError(
                    f"Required context file not found: {doc_name}.md\n"
                    f"  Searched in: {planning_dir}\n"
                    f"  Suggestion: Create the {doc_name} document"
                )
            logger.debug("%s document not found, skipping", doc_name)
            return

        if is_sharded:
            # Load all files from sharded directory
            result = load_sharded_content(resolved_path, doc_name, base_path=planning_dir)
            if result.content:
                # Use directory path as key for sharded content
                path_str = str(resolved_path.resolve())
                if path_str not in self._seen_paths:
                    self._entries.append((PRIORITY_PLANNING, path_str, result.content))
                    self._seen_paths.add(path_str)
                    logger.debug(
                        "Added sharded %s (%d files)",
                        doc_name,
                        len(result.files_loaded),
                    )
        else:
            self._add_file(resolved_path, PRIORITY_PLANNING, required=required)

    def add_previous_stories(self, count: int = 3) -> ContextBuilder:
        """Add N most recent previous stories from the same epic.

        Stories are added in chronological order (oldest first) for recency-bias
        context. This means the most recent story appears last, closest to the
        instructions.

        Args:
            count: Maximum number of previous stories to include.

        Returns:
            Self for method chaining.

        """
        epic_num = self._context.resolved_variables.get("epic_num")
        story_num = self._context.resolved_variables.get("story_num")

        # Type-safe conversion
        try:
            story_num_int = int(story_num) if story_num is not None else 0
        except (TypeError, ValueError):
            logger.debug("Invalid story_num '%s', skipping previous stories", story_num)
            return self

        if story_num_int <= 1:
            return self

        stories_dir = get_stories_dir(self._context)
        if not stories_dir.exists():
            logger.debug("Stories directory not found: %s", stories_dir)
            return self

        found_stories: list[Path] = []

        # Search backwards from current story
        for prev_num in range(story_num_int - 1, 0, -1):
            if len(found_stories) >= count:
                break

            pattern = f"{epic_num}-{prev_num}-*.md"
            matches = sorted(stories_dir.glob(pattern))
            if matches:
                found_stories.append(matches[0])

        # Reverse to get chronological order (oldest first)
        found_stories.reverse()

        # Add each story with PRIORITY_STORIES
        for story_path in found_stories:
            self._add_file(story_path, PRIORITY_STORIES)

        if found_stories:
            logger.debug(
                "Added %d previous stories for story %s.%s (chronological)",
                len(found_stories),
                epic_num,
                story_num,
            )

        return self

    def add_epic_files(self, epic_num: int | str) -> ContextBuilder:
        """Add current epic file + index.md for sharded epics.

        For sharded epics (directory with multiple epic-*.md files):
        - index.md (epic overview/navigation)
        - The specific epic-{num}-*.md file for current epic
        - No other support files (summary.md, etc.) - they waste tokens

        For single-file epic:
        - The entire epic file

        Args:
            epic_num: Epic number (int or str like "testarch").

        Returns:
            Self for method chaining.

        """
        epics_dir = get_epics_dir(self._context)

        if epics_dir.exists() and epics_dir.is_dir():
            # Sharded epics - include index.md + current epic file
            found_files: list[Path] = []

            # Always include index.md if present (epic overview)
            index_file = epics_dir / "index.md"
            if index_file.exists():
                found_files.append(index_file)
                logger.debug("Found epic index file: %s", index_file)

            # Find current epic file: epic-19-*.md, epic-testarch-*.md
            pattern = f"epic-{epic_num}-*.md"
            matches = sorted(epics_dir.glob(pattern))
            if matches:
                found_files.append(matches[0])
                logger.debug("Found current epic file: %s", matches[0])

            if found_files:
                for f in found_files:
                    self._add_file(f, PRIORITY_EPIC)
                logger.debug("Added %d epic files for epic %s", len(found_files), epic_num)
                return self

        # Single-file epic fallback
        single_epic_file = self._find_single_epic_file(epic_num)
        if single_epic_file:
            self._add_file(single_epic_file, PRIORITY_EPIC)
            logger.debug("Added single epic file: %s", single_epic_file)
        else:
            logger.debug("No epic files found for epic %s (epics may be loaded from sharded loader)", epic_num)

        return self

    def _find_single_epic_file(self, epic_num: int | str) -> Path | None:
        """Find single-file epic (not sharded).

        Searches in multiple locations:
        1. output_folder (implementation_artifacts) for epic-{num}-*.md
        2. output_folder for generic epics.md
        3. project_knowledge (docs) for epic-{num}-*.md
        4. project_knowledge for generic epics.md

        Args:
            epic_num: Epic number to find.

        Returns:
            Path to epic file or None.

        """
        from bmad_assist.core.paths import get_paths

        output_folder = self._context.output_folder
        pattern = f"*epic*{epic_num}*.md"

        # Check output_folder directly for epic-{num}-*.md
        matches = sorted(output_folder.glob(pattern))
        if matches:
            return matches[0]

        # Fallback: generic epics.md file in output_folder
        generic_epics = output_folder / "epics.md"
        if generic_epics.exists():
            return generic_epics

        # Fallback to project_knowledge (docs/) if paths are initialized
        try:
            paths = get_paths()
            project_knowledge = paths.project_knowledge

            # Check project_knowledge for epic-{num}-*.md
            matches = sorted(project_knowledge.glob(pattern))
            if matches:
                return matches[0]

            # Fallback: generic epics.md in project_knowledge
            generic_epics = project_knowledge / "epics.md"
            if generic_epics.exists():
                return generic_epics
        except RuntimeError:
            # Paths not initialized - skip this fallback
            pass

        return None

    def add_validations(
        self,
        story_key: str,
        session_id: str | None = None,
    ) -> ContextBuilder:
        """Add validation reports for synthesis workflows.

        Finds validation files matching the story and optional session.
        Pattern: validation-{story_key}-{role_id}-{timestamp}.md
        where role_id is a single letter (a, b, c...)

        Args:
            story_key: Story identifier (e.g., "12-2").
            session_id: Optional timestamp prefix to filter validations.

        Returns:
            Self for method chaining.

        """
        validations_dir = get_validations_dir(self._context)
        if not validations_dir.exists():
            logger.debug("Validations directory not found: %s", validations_dir)
            return self

        if session_id:
            # Find validations for specific session/timestamp
            # Pattern: validation-{story_key}-{role_id}-{session_id}*.md
            pattern = f"validation-{story_key}-?-{session_id}*.md"
        else:
            # Find all validations for this story
            # Pattern: validation-{story_key}-{role_id}-*.md
            pattern = f"validation-{story_key}-?-*.md"

        matches = sorted(validations_dir.glob(pattern))

        for validation_path in matches:
            self._add_file(validation_path, PRIORITY_VALIDATIONS)

        if matches:
            logger.debug(
                "Added %d validation files for story %s",
                len(matches),
                story_key,
            )

        return self

    def _add_file(self, path: Path, priority: int, required: bool = False) -> None:
        """Add a file to the context with given priority.

        Args:
            path: Path to the file.
            priority: Priority for ordering (lower = earlier).
            required: If True, raises ContextError on read failure.

        Raises:
            ContextError: If required=True and file cannot be read.

        """
        path_str = str(path.resolve())

        # Prevent duplicates
        if path_str in self._seen_paths:
            return

        content = safe_read_file(path, self._context.project_root)

        if not content:
            if required:
                raise ContextError(
                    f"Required context file not found: {path}\n"
                    f"  Suggestion: Ensure the file exists and is readable"
                )
            logger.warning("Could not read file, skipping: %s", path)
            return

        self._entries.append((priority, path_str, content))
        self._seen_paths.add(path_str)
        logger.debug("Added context file: %s (priority=%d)", path, priority)

    def build(self) -> dict[str, str]:
        """Build the final context files dictionary.

        Files are sorted by priority (ascending), then by path for determinism.
        Returns an ordered dict where keys are absolute path strings and values
        are file contents.

        Returns:
            Ordered dictionary mapping file paths to contents.

        """
        # Sort by priority, then by path for determinism (NFR11)
        sorted_entries = sorted(self._entries, key=lambda e: (e[0], e[1]))

        result: dict[str, str] = {}
        for _priority, path, content in sorted_entries:
            result[path] = content

        logger.debug("Built context with %d files", len(result))
        return result
