"""Epic and story variable resolution for BMAD workflow variables.

This module handles epic/story number and title resolution:
- Computing story_id, story_key, story_title variables
- Extracting story titles from epics markdown files
- Date and timestamp computation

Dependencies flow: epic_story.py imports _extract_story_title from sprint_status.py.
"""

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from bmad_assist.compiler.variables.sprint_status import _extract_story_title

logger = logging.getLogger(__name__)

__all__ = [
    "_compute_story_variables",
    "_extract_story_title_from_epics",
]


def _compute_story_variables(
    epic_num: int | str,
    story_num: int,
    sprint_status_path: Path | None,
    epics_path: Path | None = None,
    story_title_override: str | None = None,
    date_override: str | None = None,
) -> dict[str, Any]:
    """Compute story-related variables.

    Args:
        epic_num: Epic number.
        story_num: Story number within epic.
        sprint_status_path: Optional path to sprint-status.yaml.
        epics_path: Optional path to epic file for title extraction fallback.
        story_title_override: If provided, use this instead of looking up.
        date_override: If provided, use this date (for deterministic builds).

    Returns:
        Dictionary with story_id, story_key, story_title, date.

    """
    result: dict[str, Any] = {}

    # story_id: "10.3" format
    result["story_id"] = f"{epic_num}.{story_num}"

    # story_title: from override, sprint-status lookup, epics file, or fallback
    story_title: str | None = None

    if story_title_override:
        story_title = story_title_override
    elif sprint_status_path:
        story_title = _extract_story_title(sprint_status_path, epic_num, story_num)

    # Fallback: try extracting from epics file
    if not story_title and epics_path:
        story_title = _extract_story_title_from_epics(epics_path, epic_num, story_num)

    # Final fallback
    if not story_title:
        story_title = f"story-{story_num}"
        logger.debug("Using fallback story_title: %s", story_title)

    result["story_title"] = story_title

    # story_key: "10-3-variable-resolution-engine" format
    result["story_key"] = f"{epic_num}-{story_num}-{story_title}"

    # date: YYYY-MM-DD format (override for determinism or current date)
    if date_override:
        result["date"] = date_override
    else:
        result["date"] = date.today().isoformat()

    # timestamp: YYYYMMDD_hhmm format
    now = datetime.now()
    result["timestamp"] = now.strftime("%Y%m%d_%H%M")

    return result


def _extract_story_title_from_epics(
    epics_path: Path,
    epic_num: int | str,
    story_num: int,
) -> str | None:
    r"""Extract story title from epics markdown file.

    Supports multiple formats:
    - ## Story 10.3: Variable Resolution Engine
    - ### Story 1.2: Projects Gallery Section
    - ### Story 1.2: ... followed by **Title:** Actual Title Here

    Args:
        epics_path: Path to epics markdown file.
        epic_num: Epic number to match.
        story_num: Story number to match.

    Returns:
        Extracted story title (kebab-case) or None if not found.

    """
    if not epics_path.exists():
        logger.debug("Epics file not found: %s", epics_path)
        return None

    try:
        content = epics_path.read_text(encoding="utf-8")

        # Pattern 1: ##/### Story X.Y: Title on same line
        # Matches: ## Story 10.3: Variable Resolution Engine
        # Matches: ### Story 1.2: Projects Gallery Section
        # Note: {{2,3}} escapes braces in f-string to produce {2,3} in regex
        header_pattern = re.compile(
            rf"^#{{2,3}}\s+Story\s+{epic_num}\.{story_num}:\s*(.+)$",
            re.MULTILINE | re.IGNORECASE,
        )

        match = header_pattern.search(content)
        if match:
            raw_title = match.group(1).strip()
            # Convert to kebab-case
            kebab_title = re.sub(r"[^a-zA-Z0-9]+", "-", raw_title).strip("-").lower()
            logger.debug("Extracted story_title from header: %s", kebab_title)
            return kebab_title

        # Pattern 2: Look for **Title:** line after story header
        # Matches: ### Story 1.2: ...\n\n**Title:** Implement projects gallery
        title_pattern = re.compile(
            rf"^#{{2,3}}\s+Story\s+{epic_num}\.{story_num}:.*?"
            rf"\*\*Title:\*\*\s*(.+?)$",
            re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )

        match = title_pattern.search(content)
        if match:
            raw_title = match.group(1).strip()
            # Convert to kebab-case
            kebab_title = re.sub(r"[^a-zA-Z0-9]+", "-", raw_title).strip("-").lower()
            logger.debug("Extracted story_title from **Title:** field: %s", kebab_title)
            return kebab_title

        logger.debug(
            "No matching story header found for %s.%s in %s",
            epic_num,
            story_num,
            epics_path,
        )
        return None

    except OSError as e:
        logger.debug("Error reading epics file: %s", e)
        return None
