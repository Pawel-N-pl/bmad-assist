"""Sprint status resolution for BMAD workflow variables.

This module handles sprint-status.yaml resolution:
- Finding sprint-status.yaml in docs/ or docs/sprint-artifacts/
- Extracting story titles from sprint-status.yaml

Dependencies flow: sprint_status.py imports from shared_utils (outside variables/).
"""

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from bmad_assist.compiler.types import CompilerContext

logger = logging.getLogger(__name__)

__all__ = [
    "_resolve_sprint_status",
    "_extract_story_title",
]


def _resolve_sprint_status(
    resolved: dict[str, Any],
    context: CompilerContext,
) -> dict[str, Any]:
    """Resolve sprint_status variable to sprint-status.yaml path.

    Uses paths singleton when available, with legacy fallback.

    Rules:
    - If not found: set sprint_status to "none"
    - If found: use that path

    Args:
        resolved: Dict of resolved variables.
        context: Compiler context with project_root.

    Returns:
        Dict with sprint_status resolved.

    """
    # Try paths singleton first (preferred)
    try:
        from bmad_assist.core.paths import get_paths

        paths = get_paths()
        sprint_path = paths.find_sprint_status()
        if sprint_path and sprint_path.exists():
            resolved["sprint_status"] = str(sprint_path)
            logger.debug("Resolved sprint_status via paths singleton: %s", sprint_path)
            return resolved
    except RuntimeError:
        # Fallback when singleton not initialized
        pass

    # Legacy fallback for compiler-only usage (check multiple locations)
    fallback_locations = [
        context.project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml",
        context.project_root / "_bmad-output" / "planning-artifacts" / "sprint-status.yaml",  # Beta default
        context.project_root / "docs" / "sprint-status.yaml",
        context.project_root / "docs" / "sprint-artifacts" / "sprint-status.yaml",
    ]

    for fallback_path in fallback_locations:
        if fallback_path.exists():
            resolved["sprint_status"] = str(fallback_path)
            logger.debug("Resolved sprint_status via legacy fallback: %s", fallback_path)
            return resolved

    resolved["sprint_status"] = "none"
    logger.debug("No sprint-status.yaml found, set sprint_status to 'none'")
    return resolved


def _extract_story_title(
    sprint_status_path: Path,
    epic_num: int,
    story_num: int,
) -> str | None:
    """Extract story title from sprint-status.yaml.

    Looks for key matching pattern: {epic_num}-{story_num}-{title}
    in the development_status section.

    Args:
        sprint_status_path: Path to sprint-status.yaml.
        epic_num: Epic number to match.
        story_num: Story number to match.

    Returns:
        Extracted story title (kebab-case) or None if not found.

    """
    if not sprint_status_path.exists():
        logger.debug("Sprint status file not found: %s", sprint_status_path)
        return None

    try:
        content = sprint_status_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        if not isinstance(data, dict):
            logger.debug("Sprint status file is not a dict")
            return None

        development_status = data.get("development_status", {})
        if not isinstance(development_status, dict):
            logger.debug("development_status is not a dict")
            return None

        # Pattern: epic_num-story_num-title
        pattern = re.compile(rf"^{epic_num}-{story_num}-(.+)$")

        for key in development_status:
            match = pattern.match(str(key))
            if match:
                title = match.group(1)
                logger.debug("Extracted story_title from sprint-status: %s", title)
                return title

        logger.debug("No matching story key found for %s-%s", epic_num, story_num)
        return None

    except (OSError, yaml.YAMLError) as e:
        logger.debug("Error reading sprint-status.yaml: %s", e)
        return None
