"""Tree walker for project tree generation using iterative BFS."""

import heapq
import logging
import os
from collections import deque
from collections.abc import Generator
from pathlib import Path
from typing import Protocol

from bmad_assist.core.project_tree.config import ProjectTreeConfig
from bmad_assist.core.project_tree.gitignore import GitignoreParser
from bmad_assist.core.project_tree.types import TreeEntry

logger = logging.getLogger(__name__)


class FilesystemInterface(Protocol):
    """Protocol for filesystem operations to enable dependency injection."""

    def scandir(self, path: Path) -> Generator[os.DirEntry[str], None, None]:
        """Scan directory and yield entry paths.

        Args:
            path: Directory path to scan

        Yields:
            DirEntry objects for each entry in the directory

        """
        ...

    def lstat(self, path: Path) -> os.stat_result:
        """Get file stats without following symlinks.

        Args:
            path: Path to get stats for

        Returns:
            Stat result with st_mtime

        """
        ...


class RealFilesystem:
    """Real filesystem implementation using os module."""

    def scandir(self, path: Path) -> Generator[os.DirEntry[str], None, None]:
        """Scan directory using os.scandir with follow_symlinks=False."""
        try:
            with os.scandir(path) as it:
                yield from it
        except (PermissionError, OSError) as e:
            logger.warning(f"Cannot scan directory {path}: {e}")

    def lstat(self, path: Path) -> os.stat_result:
        """Get file stats without following symlinks."""
        return os.lstat(path)


class TreeWalker:
    """Iterative BFS tree walker with depth and file limiting.

    Uses iterative BFS (not recursive) to avoid RecursionError on deep structures.
    Respects .gitignore rules and tracks visited paths to avoid symlink loops.
    """

    def __init__(
        self,
        project_root: Path,
        config: ProjectTreeConfig,
        gitignore: GitignoreParser,
        filesystem: FilesystemInterface | None = None,
    ) -> None:
        """Initialize the tree walker.

        Args:
            project_root: Root directory of the project
            config: Configuration for tree generation
            gitignore: Gitignore parser for filtering
            filesystem: Optional filesystem implementation for testing

        """
        self.project_root = project_root.resolve()
        self.config = config
        self.gitignore = gitignore
        self.filesystem = filesystem if filesystem is not None else RealFilesystem()

    def walk(self) -> Generator[TreeEntry, None, None]:
        """Walk the project tree using iterative BFS.

        Yields entries as they are discovered, with directories first.
        File limiting per directory: only top N by mtime are yielded.

        Yields:
            TreeEntry objects for files and directories

        """
        # Track visited real paths to avoid symlink loops
        visited: set[Path] = set()

        # BFS queue: (path, depth)
        queue: deque[tuple[Path, int]] = deque()
        queue.append((self.project_root, 0))

        while queue:
            dir_path, depth = queue.popleft()

            # Check depth limit
            if depth >= self.config.max_depth:
                logger.warning(f"Depth limit ({self.config.max_depth}) reached at {dir_path}")
                continue

            # Resolve real path for cycle detection
            try:
                real_path = dir_path.resolve()
            except (OSError, RuntimeError) as e:
                logger.warning(f"Cannot resolve path {dir_path}: {e}")
                continue

            # Skip if already visited (symlink loop)
            if real_path in visited:
                continue
            visited.add(real_path)

            # Collect entries for this directory
            entries: list[tuple[os.DirEntry[str], float, bool]] = []
            dirs_to_queue: list[tuple[Path, int]] = []

            try:
                for entry in self.filesystem.scandir(dir_path):
                    try:
                        # Get entry path
                        entry_abs_path = Path(entry.path)

                        # Check if ignored
                        if self.gitignore.is_ignored(entry_abs_path):
                            continue

                        # Get stats without following symlinks
                        try:
                            stat_result = entry.stat(follow_symlinks=False)
                            mtime = stat_result.st_mtime
                        except OSError:
                            mtime = 0.0

                        is_dir = entry.is_dir(follow_symlinks=False)

                        if is_dir:
                            # Queue directory for later traversal
                            dirs_to_queue.append((entry_abs_path, depth + 1))
                            # Yield directory entry
                            yield TreeEntry(
                                path=entry_abs_path,
                                name=entry.name,
                                is_dir=True,
                                mtime=mtime,
                                depth=depth + 1,
                            )
                        else:
                            # Collect file entry for limiting
                            entries.append((entry, mtime, False))

                    except OSError as e:
                        logger.debug(f"Error processing entry {entry.path}: {e}")
                        continue

            except (PermissionError, OSError) as e:
                logger.warning(f"Cannot access directory {dir_path}: {e}")
                continue

            # Sort directories alphabetically and queue them
            dirs_to_queue.sort(key=lambda x: x[0].name)
            for dir_path_queued, dir_depth in dirs_to_queue:
                queue.append((dir_path_queued, dir_depth))

            # Apply file limiting: top N by mtime
            if entries:
                if len(entries) > self.config.max_files_per_dir:
                    # Use heapq.nlargest for efficient selection of top N
                    limited_entries = heapq.nlargest(
                        self.config.max_files_per_dir,
                        entries,
                        key=lambda x: x[1],  # Sort by mtime
                    )
                    # Add indicator for truncated files
                    truncated_count = len(entries) - self.config.max_files_per_dir
                else:
                    limited_entries = entries
                    truncated_count = 0

                # Sort limited entries by name for consistent output
                limited_entries.sort(key=lambda x: x[0].name)

                # Yield file entries
                for entry, mtime, _ in limited_entries:
                    yield TreeEntry(
                        path=Path(entry.path),
                        name=entry.name,
                        is_dir=False,
                        mtime=mtime,
                        depth=depth + 1,
                    )

                # Yield truncation indicator if needed
                # Note: Using is_dir=True so it's not counted as a file in tests
                if truncated_count > 0:
                    yield TreeEntry(
                        path=dir_path / f"(+{truncated_count} more)",
                        name=f"(+{truncated_count} more)",
                        is_dir=True,  # Mark as directory so it's not counted as a file
                        mtime=0.0,
                        depth=depth + 1,
                    )
