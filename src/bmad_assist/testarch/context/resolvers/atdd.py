"""ATDD checklist artifact resolver.

Resolves *atdd-checklist*{story}*.md artifacts.
Supports multiple files per story with configurable limit.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from bmad_assist.compiler.shared_utils import estimate_tokens
from bmad_assist.testarch.context.resolvers.base import BaseResolver
from bmad_assist.testarch.paths import get_artifact_patterns

if TYPE_CHECKING:
    from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

# Default max files for ATDD (can be overridden by config)
DEFAULT_MAX_FILES = 10


class ATDDResolver(BaseResolver):
    """Resolver for ATDD checklist artifacts.

    Loads *atdd-checklist*{story}*.md files.
    Supports multiple files per story, capped at max_files.

    Attributes:
        _max_files: Maximum number of ATDD files to load.

    """

    def __init__(
        self,
        base_path: Path,
        max_tokens: int,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        """Initialize ATDD resolver.

        Args:
            base_path: Base directory for artifact search.
            max_tokens: Maximum tokens budget for this resolver.
            max_files: Maximum number of ATDD files to load.

        """
        super().__init__(base_path, max_tokens)
        self._max_files = max_files

    @property
    def artifact_type(self) -> str:
        """Return artifact type identifier."""
        return "atdd"

    def resolve(
        self,
        epic_id: EpicId,
        story_id: str | None = None,
    ) -> dict[str, str]:
        """Resolve ATDD checklist artifacts.

        Args:
            epic_id: Epic identifier (int or str).
            story_id: Story identifier (required for ATDD).

        Returns:
            Dict with entries {path: content} or empty dict.

        """
        result: dict[str, str] = {}

        if not story_id:
            logger.debug("ATDD resolver requires story_id, skipping")
            return result

        # Get patterns for both dot and hyphen formats
        patterns = get_artifact_patterns(self.artifact_type, epic_id, story_id)
        subdir = self._get_artifact_dir()

        # Collect all matches across all patterns
        all_matches: list[Path] = []
        seen_paths: set[Path] = set()

        for pattern in patterns:
            matches = self._find_matching_files(pattern, subdir)
            for match in matches:
                resolved = match.resolve()
                if resolved not in seen_paths:
                    seen_paths.add(resolved)
                    all_matches.append(match)

        if not all_matches:
            logger.info(
                "TEA artifact not found: %s for story %s (skipping)",
                self.artifact_type,
                story_id,
            )
            return result

        # Sort by modification time (most recent first)
        all_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        # Cap at max_files
        files_to_load = all_matches[: self._max_files]

        # Load files with token budget tracking
        remaining_budget = self._max_tokens

        for path in files_to_load:
            if remaining_budget <= 0:
                logger.info(
                    "ATDD resolver: budget exhausted after %d files",
                    len(result),
                )
                break

            content = self._safe_read(path)
            if content is None:
                continue

            # Truncate if needed
            truncated = self._truncate_content(content, remaining_budget)
            tokens_used = estimate_tokens(truncated)

            result[str(path)] = truncated
            remaining_budget -= tokens_used

        if result:
            logger.info(
                "TEA context: loaded %d ATDD checklist(s) for story %s",
                len(result),
                story_id,
            )

        return result
