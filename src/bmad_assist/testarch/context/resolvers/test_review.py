"""Test review artifact resolver.

Resolves test-review-{story}.md artifacts.
Used in code_review_synthesis to include test quality findings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bmad_assist.testarch.context.resolvers.base import BaseResolver
from bmad_assist.testarch.paths import get_artifact_patterns

if TYPE_CHECKING:
    from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)


class TestReviewResolver(BaseResolver):
    """Resolver for test review artifacts.

    Loads test-review-{story}.md files.
    Tries both dot and hyphen formats for story ID.

    """

    @property
    def artifact_type(self) -> str:
        """Return artifact type identifier."""
        return "test-review"

    def resolve(
        self,
        epic_id: EpicId,
        story_id: str | None = None,
    ) -> dict[str, str]:
        """Resolve test review artifact.

        Args:
            epic_id: Epic identifier (int or str).
            story_id: Story identifier (required for test-review).

        Returns:
            Dict with single entry {path: content} or empty dict.

        """
        result: dict[str, str] = {}

        if not story_id:
            logger.debug("Test review resolver requires story_id, skipping")
            return result

        # Get patterns for both dot and hyphen formats
        patterns = get_artifact_patterns(self.artifact_type, epic_id, story_id)
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
                "TEA context: loaded %s for story %s (%s)",
                self.artifact_type,
                story_id,
                path.name,
            )
            # Return first found
            return result

        logger.info(
            "TEA artifact not found: %s for story %s (skipping)",
            self.artifact_type,
            story_id,
        )
        return result
