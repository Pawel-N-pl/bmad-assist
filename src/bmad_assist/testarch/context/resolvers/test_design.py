"""Test design artifact resolver.

Resolves test-design.md and epic-{N}-test-plan.md artifacts.
Epic-specific test plans have higher priority than system-level designs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bmad_assist.testarch.context.resolvers.base import BaseResolver
from bmad_assist.testarch.paths import get_artifact_patterns

if TYPE_CHECKING:
    from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)


class TestDesignResolver(BaseResolver):
    """Resolver for test design artifacts.

    Loads test-design.md or epic-{N}-test-plan.md files.
    Priority: epic-specific > system-level.

    """

    @property
    def artifact_type(self) -> str:
        """Return artifact type identifier."""
        return "test-design"

    def resolve(
        self,
        epic_id: EpicId,
        story_id: str | None = None,
    ) -> dict[str, str]:
        """Resolve test design artifact.

        Args:
            epic_id: Epic identifier (int or str).
            story_id: Not used for test-design (epic-level artifact).

        Returns:
            Dict with single entry {path: content} or empty dict.

        """
        result: dict[str, str] = {}

        # Get patterns in priority order (epic-specific first)
        patterns = get_artifact_patterns(self.artifact_type, epic_id)
        subdir = self._get_artifact_dir()

        for pattern in patterns:
            matches = self._find_matching_files(pattern, subdir)
            if not matches:
                continue

            # Take first match for this pattern
            path = matches[0]
            content = self._safe_read(path)
            if content is None:
                continue

            # Apply token truncation
            truncated = self._truncate_content(content, self._max_tokens)
            result[str(path)] = truncated

            logger.info(
                "TEA context: loaded %s (%s)",
                self.artifact_type,
                path.name,
            )
            # Return first found (priority order)
            return result

        # Also check for system-level test-design files at root
        from bmad_assist.testarch.paths import ARTIFACT_CONFIGS

        system_config = ARTIFACT_CONFIGS.get("test-design-system")
        if system_config:
            system_subdir, system_patterns = system_config
            for pattern in system_patterns:
                matches = self._find_matching_files(pattern, system_subdir)
                if not matches:
                    continue

                path = matches[0]
                content = self._safe_read(path)
                if content is None:
                    continue

                truncated = self._truncate_content(content, self._max_tokens)
                result[str(path)] = truncated

                logger.info(
                    "TEA context: loaded system test-design (%s)",
                    path.name,
                )
                return result

        logger.info(
            "TEA artifact not found: %s (skipping)",
            self.artifact_type,
        )
        return result
