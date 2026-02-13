"""Shared types for the project_tree module."""

from collections.abc import Generator
from pathlib import Path
from typing import NamedTuple, Protocol


class TreeEntry(NamedTuple):
    """Represents a single entry in the project tree.

    Attributes:
        path: Full path to the file or directory
        name: Name of the file or directory
        is_dir: True if this is a directory, False if it's a file
        mtime: Modification time as Unix timestamp
        depth: Depth in the tree (0 = project root)

    """

    path: Path
    name: str
    is_dir: bool
    mtime: float
    depth: int


class FilesystemInterface(Protocol):
    """Protocol for filesystem operations to enable dependency injection."""

    def scandir(self, path: Path) -> Generator[Path, None, None]:
        """Scan directory and yield entry paths.

        Args:
            path: Directory path to scan

        Yields:
            Path objects for each entry in the directory

        """
        ...

    def lstat(self, path: Path) -> float:
        """Get modification time without following symlinks.

        Args:
            path: Path to get mtime for

        Returns:
            Modification time as Unix timestamp

        """
        ...
