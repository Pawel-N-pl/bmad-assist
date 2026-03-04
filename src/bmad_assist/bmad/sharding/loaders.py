"""Loaders for sharded documentation directories.

This module provides the main loading functions for sharded documentation,
handling both index-guided and alphabetic/numeric sorted loading strategies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from bmad_assist.bmad.parser import EpicDocument, parse_epic_file
from bmad_assist.core.exceptions import ParserError
from bmad_assist.core.types import EpicId

from .index_parser import parse_index_references
from .security import DuplicateEpicError, SecurityError, validate_sharded_path
from .sorting import DocType, get_sort_key

logger = logging.getLogger(__name__)


@dataclass
class ShardedContent:
    """Result of loading sharded content documentation.

    Attributes:
        content: Concatenated content from all sharded files.
        files_loaded: List of file paths that were loaded.
        files_skipped: List of file paths that were skipped (missing, invalid).

    """

    content: str
    files_loaded: list[str]
    files_skipped: list[str]


def _get_sorted_files(
    sharded_dir: Path,
    doc_type: DocType,
    base_path: Path,
) -> list[Path]:
    """Get sorted list of .md files from sharded directory.

    If index.md exists, uses index-guided order. Otherwise falls back
    to doc_type-specific sorting (numeric for epics, alphabetic otherwise).

    Args:
        sharded_dir: Path to sharded documentation directory.
        doc_type: Document type for sorting strategy.
        base_path: Base path for security validation.

    Returns:
        Sorted list of file paths to load.

    """
    index_path = sharded_dir / "index.md"

    if index_path.exists():
        # INDEX-GUIDED: Parse index.md for order
        # Note: index.md itself is NOT loaded as content - only used for ordering
        order = parse_index_references(index_path)
        files: list[Path] = []

        for ref in order:
            file_path = sharded_dir / ref
            if file_path.exists():
                try:
                    validate_sharded_path(base_path, file_path)
                    files.append(file_path)
                except SecurityError:
                    logger.warning("Skipping path traversal attempt: %s", ref)
            else:
                logger.warning("Index references non-existent file: %s", ref)

        # Deduplicate preserving first-seen order (index.md may link same file multiple times)
        files = list(dict.fromkeys(files))

        # Add orphan files (in directory but not in index)
        all_md_files = set(sharded_dir.glob("*.md")) - {index_path}
        indexed_files = set(files)
        orphan_candidates = sorted(
            all_md_files - indexed_files,
            key=lambda f: get_sort_key(doc_type, f.name),
        )

        # Validate orphan files for security (symlinks, traversal)
        orphan_files: list[Path] = []
        for orphan in orphan_candidates:
            try:
                validate_sharded_path(base_path, orphan)
                orphan_files.append(orphan)
            except SecurityError:
                logger.warning("Skipping invalid orphan path: %s", orphan)

        if orphan_files:
            logger.info(
                "Found %d files not in index.md, appending sorted: %s",
                len(orphan_files),
                [f.name for f in orphan_files],
            )
            files.extend(orphan_files)

        return files
    else:
        # FALLBACK: Sort by doc_type rules
        # Exclude index.md from content loading
        all_files = [f for f in sharded_dir.glob("*.md") if f.name != "index.md"]
        sorted_files = sorted(
            all_files,
            key=lambda f: get_sort_key(doc_type, f.name),
        )

        # Validate all paths
        valid_files: list[Path] = []
        for file_path in sorted_files:
            try:
                validate_sharded_path(base_path, file_path)
                valid_files.append(file_path)
            except SecurityError:
                logger.warning("Skipping invalid path: %s", file_path)

        return valid_files


def load_sharded_content(
    sharded_dir: Path,
    doc_type: DocType,
    base_path: Path | None = None,
) -> ShardedContent:
    """Load all docs from sharded directory with type-specific sorting.

    For architecture, prd, and ux document types, loads all .md files
    and concatenates their content. Uses index.md for ordering if present,
    otherwise sorts alphabetically.

    Args:
        sharded_dir: Path to sharded documentation directory.
        doc_type: One of 'architecture', 'prd', 'ux' (or 'epics' but
            prefer load_sharded_epics for that).
        base_path: Base path for security validation. Defaults to sharded_dir.

    Returns:
        ShardedContent with concatenated content and load metadata.

    Examples:
        >>> result = load_sharded_content(Path("docs/architecture"), "architecture")
        >>> len(result.files_loaded)
        4

    """
    if base_path is None:
        base_path = sharded_dir

    files = _get_sorted_files(sharded_dir, doc_type, base_path)

    if not files:
        logger.warning("No .md files found in sharded directory: %s", sharded_dir)
        return ShardedContent(content="", files_loaded=[], files_skipped=[])

    content_parts: list[str] = []
    files_loaded: list[str] = []
    files_skipped: list[str] = []

    for file_path in files:
        try:
            file_content = file_path.read_text(encoding="utf-8")
            content_parts.append(file_content)
            files_loaded.append(str(file_path))
            logger.debug("Loaded sharded file: %s", file_path)
        except OSError as e:
            logger.warning("Failed to read sharded file %s: %s", file_path, e)
            files_skipped.append(str(file_path))

    logger.info(
        "Loaded %d files from %s (%d skipped)",
        len(files_loaded),
        sharded_dir,
        len(files_skipped),
    )

    return ShardedContent(
        content="\n\n".join(content_parts),
        files_loaded=files_loaded,
        files_skipped=files_skipped,
    )


def load_sharded_epics(
    sharded_dir: Path,
    base_path: Path | None = None,
) -> list[EpicDocument]:
    """Load epics from sharded directory with duplicate detection.

    Specialized loader for epic files that:
    - Parses each file as an EpicDocument
    - Detects duplicate epic_id across files
    - Uses numeric sorting (epic-1.md before epic-2.md before epic-10.md)
    - Validates paths for security

    Args:
        sharded_dir: Path to sharded epics directory.
        base_path: Base path for security validation. Defaults to sharded_dir.

    Returns:
        List of parsed EpicDocument objects.

    Raises:
        DuplicateEpicError: If multiple files have the same epic_id.
        SecurityError: If path traversal is detected.

    Examples:
        >>> epics = load_sharded_epics(Path("docs/epics"))
        >>> [e.epic_num for e in epics]
        [1, 2, 10]

    """
    if base_path is None:
        base_path = sharded_dir

    files = _get_sorted_files(sharded_dir, "epics", base_path)

    if not files:
        logger.warning("No epic files found in sharded directory: %s", sharded_dir)
        return []

    epics: list[EpicDocument] = []
    seen_epic_ids: dict[EpicId, str] = {}  # epic_id -> file_path

    for file_path in files:
        try:
            epic_doc = parse_epic_file(file_path)

            # Check for duplicate epic_id
            if epic_doc.epic_num is not None:
                if epic_doc.epic_num in seen_epic_ids:
                    raise DuplicateEpicError(
                        f"Duplicate epic_id {epic_doc.epic_num} found in "
                        f"{file_path} and {seen_epic_ids[epic_doc.epic_num]}"
                    )
                seen_epic_ids[epic_doc.epic_num] = str(file_path)

            epics.append(epic_doc)
            logger.debug("Loaded sharded epic: %s (epic_num=%s)", file_path, epic_doc.epic_num)

        except ParserError as e:
            logger.warning("Skipping malformed epic file %s: %s", file_path, e)
            continue
        except OSError as e:
            logger.warning("Failed to read epic file %s: %s", file_path, e)
            continue

    logger.info("Loaded %d epics from %s", len(epics), sharded_dir)
    return epics
