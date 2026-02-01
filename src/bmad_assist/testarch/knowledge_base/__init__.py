"""Bundled TEA knowledge base for bmad-assist.

This module provides fallback knowledge fragments when no project-level
_bmad/tea/testarch/ or _bmad/bmm/testarch/ directory exists.

Usage:
    from bmad_assist.testarch.knowledge_base import get_bundled_knowledge_dir

    bundled_dir = get_bundled_knowledge_dir()
    if bundled_dir:
        index_path = bundled_dir / "tea-index.csv"
"""

import sys
from importlib.resources import files
from pathlib import Path

# Python 3.14+ moved Traversable to importlib.resources.abc
if sys.version_info >= (3, 14):
    from importlib.resources.abc import Traversable
else:
    from importlib.abc import Traversable


def get_bundled_knowledge_dir() -> Path | None:
    """Get path to bundled knowledge base directory.

    Returns:
        Path to knowledge_base directory containing tea-index.csv,
        or None if not available.

    """
    try:
        package_path: Traversable = files("bmad_assist.testarch.knowledge_base")

        # Validate tea-index.csv exists
        index_file: Traversable = package_path / "tea-index.csv"
        if not index_file.is_file():
            return None

        return Path(str(package_path))
    except Exception:
        return None


def get_bundled_index_path() -> Path | None:
    """Get path to bundled tea-index.csv.

    Returns:
        Path to tea-index.csv, or None if not available.

    """
    bundled_dir = get_bundled_knowledge_dir()
    if bundled_dir is None:
        return None

    index_path = bundled_dir / "tea-index.csv"
    if index_path.exists():
        return index_path
    return None
