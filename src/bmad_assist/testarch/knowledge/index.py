"""CSV index parsing for TEA Knowledge Base.

This module provides parsing of tea-index.csv into KnowledgeFragment objects
with validation and security checks.

Usage:
    from bmad_assist.testarch.knowledge.index import parse_index

    fragments = parse_index(Path("_bmad/tea/testarch/tea-index.csv"))
"""

import csv
import logging
from pathlib import Path

from bmad_assist.core.exceptions import ParserError
from bmad_assist.testarch.knowledge.models import KnowledgeFragment

logger = logging.getLogger(__name__)

# Required CSV columns per AC2
REQUIRED_COLUMNS = frozenset({"id", "name", "description", "tags", "fragment_file"})


def _validate_path_security(fragment_file: str, row_num: int) -> bool:
    """Validate fragment file path for security.

    Args:
        fragment_file: Relative path to fragment file.
        row_num: Row number for error messages.

    Returns:
        True if path is safe, False otherwise.

    """
    # Reject absolute paths
    if Path(fragment_file).is_absolute():
        logger.warning(
            "Row %d: Absolute fragment path rejected: %s (security)",
            row_num,
            fragment_file,
        )
        return False

    # Reject path traversal
    if ".." in fragment_file:
        logger.warning(
            "Row %d: Fragment path with traversal rejected: %s (security)",
            row_num,
            fragment_file,
        )
        return False

    return True


def _parse_tags(tags_str: str) -> tuple[str, ...]:
    """Parse comma-separated tags string into tuple.

    Args:
        tags_str: Comma-separated tags (may be empty).

    Returns:
        Tuple of stripped, non-empty tags.

    """
    if not tags_str or not tags_str.strip():
        return ()

    return tuple(tag.strip() for tag in tags_str.split(",") if tag.strip())


def parse_index(index_path: Path) -> list[KnowledgeFragment]:
    """Parse tea-index.csv into list of KnowledgeFragment objects.

    Parses CSV with columns: id, name, description, tags, fragment_file.
    Handles quoted fields with embedded commas using Python csv module.

    Args:
        index_path: Path to tea-index.csv file.

    Returns:
        List of KnowledgeFragment objects in CSV order.
        Returns empty list if file is missing or empty (with warning).

    Raises:
        ParserError: If CSV is malformed (missing required columns).

    """
    # Handle missing file gracefully (AC2)
    if not index_path.exists():
        logger.warning("Knowledge index not found: %s (returning empty list)", index_path)
        return []

    try:
        with open(index_path, encoding="utf-8", newline="") as f:
            content = f.read()
    except OSError as e:
        logger.warning("Failed to read knowledge index: %s (returning empty list)", e)
        return []

    # Handle empty file
    if not content.strip():
        logger.warning("Knowledge index is empty: %s (returning empty list)", index_path)
        return []

    # Parse CSV
    try:
        reader = csv.DictReader(content.splitlines())

        # Validate required columns exist (AC2)
        if reader.fieldnames is None:
            raise ParserError(f"Knowledge index has no header row: {index_path}")

        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing_columns:
            raise ParserError(
                f"Knowledge index missing required columns: {sorted(missing_columns)}. "
                f"Required: {sorted(REQUIRED_COLUMNS)}"
            )

        fragments: list[KnowledgeFragment] = []
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
            # Get required fields
            fragment_id = row.get("id", "").strip()
            name = row.get("name", "").strip()
            description = row.get("description", "").strip()
            tags_str = row.get("tags", "").strip()
            fragment_file = row.get("fragment_file", "").strip()

            # Skip rows with missing required fields
            if not fragment_id:
                logger.warning("Row %d: Missing required field 'id', skipping", row_num)
                continue

            if not fragment_file:
                logger.warning(
                    "Row %d: Missing required field 'fragment_file', skipping",
                    row_num,
                )
                continue

            # Security validation
            if not _validate_path_security(fragment_file, row_num):
                continue

            # Parse tags
            tags = _parse_tags(tags_str)

            # Create fragment
            try:
                fragment = KnowledgeFragment(
                    id=fragment_id,
                    name=name,
                    description=description,
                    tags=tags,
                    fragment_file=fragment_file,
                )
                fragments.append(fragment)
            except ValueError as e:
                logger.warning("Row %d: Invalid fragment data: %s, skipping", row_num, e)
                continue

        logger.debug("Parsed %d fragments from %s", len(fragments), index_path)
        return fragments

    except csv.Error as e:
        raise ParserError(f"Failed to parse knowledge index CSV: {e}") from e
