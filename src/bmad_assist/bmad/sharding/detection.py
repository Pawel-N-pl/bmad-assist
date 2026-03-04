"""Detection utilities for sharded vs single-file documentation.

This module provides functions to detect whether documentation exists as
a single file or sharded directory, with proper precedence handling.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def is_sharded_path(path: Path) -> bool:
    """Check if path is a sharded documentation directory.

    A path is considered sharded if it is an existing directory.

    Args:
        path: Path to check.

    Returns:
        True if path is a directory, False otherwise.

    Examples:
        >>> is_sharded_path(Path("docs/epics"))  # directory
        True
        >>> is_sharded_path(Path("docs/epics.md"))  # file
        False

    """
    return path.is_dir()


def resolve_doc_path(base_path: Path, doc_name: str) -> tuple[Path, bool]:
    """Resolve documentation path, detecting sharded vs single-file.

    Implements PRECEDENCE RULE: If both sharded directory AND single file exist,
    sharded directory takes priority. This supports modern projects with
    sharded docs while allowing single-file stubs/redirects to coexist.

    Args:
        base_path: Project docs directory.
        doc_name: Document name without extension (e.g., "epics", "prd").

    Returns:
        Tuple of (resolved_path, is_sharded).
        - If sharded directory exists: (path_to_dir, True)
        - If only single file exists: (path_to_file, False)
        - If neither exists: (path_to_file, False) as default pattern

    Examples:
        >>> resolve_doc_path(Path("docs"), "epics")
        (PosixPath('docs/epics'), True)  # if docs/epics/ exists
        >>> resolve_doc_path(Path("docs"), "epics")
        (PosixPath('docs/epics.md'), False)  # if only docs/epics.md exists

    """
    single_file = base_path / f"{doc_name}.md"
    sharded_dir = base_path / doc_name

    # PRECEDENCE: Sharded directory vs single file
    if sharded_dir.is_dir():
        has_shards = any(sharded_dir.glob("*.md"))
        has_index = (sharded_dir / "index.md").exists()

        if has_shards:
            if single_file.exists() and not has_index:
                # Directory has .md files but no index.md — it's a supplemental
                # directory (e.g., ADRs), not a properly sharded doc.
                # Single file is the main document.
                logger.debug(
                    "Both %s/ and %s exist but dir has no index.md; "
                    "using single file as main document",
                    sharded_dir,
                    single_file,
                )
                return single_file, False

            # Properly sharded (has index.md) or no single file → dir wins
            if single_file.exists():
                logger.debug(
                    "Both %s/ and %s exist; using sharded directory (has index.md)",
                    sharded_dir,
                    single_file,
                )
            return sharded_dir, True

        # If directory is empty, it only wins if no single file exists
        if not single_file.exists():
            return sharded_dir, True

        # Empty directory + existing file -> file wins
        logger.debug(
            "Sharded directory %s is empty; falling back to single file: %s",
            sharded_dir,
            single_file,
        )
        return single_file, False

    if single_file.exists():
        logger.debug("Using single file: %s", single_file)
        return single_file, False
    else:
        # Default to single-file pattern when neither exists
        logger.debug(
            "Neither %s/ nor %s exist; defaulting to single-file pattern",
            sharded_dir,
            single_file,
        )
        return single_file, False
