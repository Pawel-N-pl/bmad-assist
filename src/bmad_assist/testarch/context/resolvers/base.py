"""Base resolver ABC for TEA artifact loading.

This module provides the abstract base class for all TEA context resolvers.
Each resolver handles a specific artifact type and implements pattern
matching and content loading.

Addresses:
- F3 Fix: Explicit estimate_tokens import from compiler/shared_utils.py
- F10 Fix: Shared _truncate_content() implementation
- F15 Fix: Exception handling with _safe_read()
- F17 Fix: Path traversal prevention via validate_artifact_path()
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from bmad_assist.compiler.shared_utils import estimate_tokens
from bmad_assist.testarch.paths import get_artifact_dir, validate_artifact_path

if TYPE_CHECKING:
    from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)


class BaseResolver(ABC):
    """Abstract base class for TEA artifact resolvers.

    Each resolver handles a specific type of TEA artifact (test-design,
    atdd, test-review, trace) and implements pattern matching and
    content loading with token budget management.

    Attributes:
        _base_path: Base directory for artifact search.
        _max_tokens: Maximum tokens for this resolver's artifacts.

    """

    def __init__(self, base_path: Path, max_tokens: int) -> None:
        """Initialize resolver.

        Args:
            base_path: Base directory for artifact search (usually testarch/).
            max_tokens: Maximum tokens budget for this resolver.

        """
        self._base_path = base_path
        self._max_tokens = max_tokens

    @property
    @abstractmethod
    def artifact_type(self) -> str:
        """Return artifact type identifier.

        Returns:
            Artifact type string (e.g., 'test-design', 'atdd').

        """
        ...

    @abstractmethod
    def resolve(
        self,
        epic_id: EpicId,
        story_id: str | None = None,
    ) -> dict[str, str]:
        """Resolve artifacts for the given context.

        Args:
            epic_id: Epic identifier (int or str).
            story_id: Optional story identifier.

        Returns:
            Dict mapping file paths to content.
            Empty dict if no artifacts found.

        """
        ...

    def _truncate_content(self, content: str, max_tokens: int) -> str:
        """Truncate content at markdown boundaries.

        Finds a sensible truncation point near the token limit,
        preferring to break at headers or blank lines.

        Args:
            content: Content to potentially truncate.
            max_tokens: Maximum allowed tokens.

        Returns:
            Content truncated if needed, with marker appended.

        """
        tokens = estimate_tokens(content)
        if tokens <= max_tokens:
            return content

        # Find truncation point at markdown boundary
        lines = content.split("\n")
        truncated_lines: list[str] = []
        current_tokens = 0

        for line in lines:
            line_tokens = estimate_tokens(line + "\n")
            if current_tokens + line_tokens > max_tokens:
                # Try to end at a sensible boundary
                break
            truncated_lines.append(line)
            current_tokens += line_tokens

        result = "\n".join(truncated_lines)
        result += "\n\n<!-- truncated: exceeded token budget -->"
        return result

    def _safe_read(self, path: Path) -> str | None:
        """Read file with path validation and exception handling.

        Args:
            path: File path to read.

        Returns:
            File content or None if read failed.

        Note:
            - Validates path is within base_path (F17 Fix)
            - Handles FileNotFoundError, PermissionError, UnicodeDecodeError (F15 Fix)
            - Skips empty files with warning

        """
        # F17: Path traversal protection
        if not validate_artifact_path(path, self._base_path):
            logger.warning(
                "Path traversal attempt blocked: %s (outside %s)",
                path,
                self._base_path,
            )
            return None

        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                logger.warning("Empty artifact file: %s", path)
                return None
            return content
        except FileNotFoundError:
            logger.debug("Artifact not found: %s", path)
            return None
        except PermissionError as e:
            logger.error("Permission denied reading artifact: %s - %s", path, e)
            return None
        except UnicodeDecodeError as e:
            logger.error("Encoding error reading artifact: %s - %s", path, e)
            return None

    def _find_matching_files(self, pattern: str, subdir: str = "") -> list[Path]:
        """Find files matching glob pattern.

        Args:
            pattern: Glob pattern to match.
            subdir: Optional subdirectory within base_path to search in.

        Returns:
            List of matching paths, sorted by name.

        """
        search_path = self._base_path / subdir if subdir else self._base_path
        if not search_path.exists():
            logger.debug("Search path does not exist: %s", search_path)
            return []

        matches = sorted(search_path.glob(pattern))
        return matches

    def _get_artifact_dir(self) -> str:
        """Get subdirectory for this artifact type.

        Returns:
            Subdirectory relative to base_path.

        """
        return get_artifact_dir(self.artifact_type)
