"""Retrospective report extraction and persistence module.

Bug Fix: Retrospective Report Persistence

This module provides:
- extract_retrospective_report(): Extract report from LLM output using markers
- save_retrospective_report(): Save retrospective report to file
- extract_hardening_plan(): Extract hardening plan XML from LLM output
- create_hardening_story(): Create Story 0 for the next epic

Extraction Strategy (via shared core/extraction.py):
1. Primary: Extract content between <!-- RETROSPECTIVE_REPORT_START --> and
   <!-- RETROSPECTIVE_REPORT_END --> markers
2. Fallback: Look for "# Epic" header pattern and extract from there
3. Last resort: Return raw output stripped

"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bmad_assist.core.extraction import HARDENING_PLAN_MARKERS, RETROSPECTIVE_MARKERS, extract_report
from bmad_assist.core.io import atomic_write
from bmad_assist.core.paths import get_paths
from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

__all__ = [
    "extract_retrospective_report",
    "save_retrospective_report",
    "extract_hardening_plan",
    "create_hardening_story",
    "get_latest_retrospective_report",
]


def extract_retrospective_report(raw_output: str) -> str:
    r"""Extract retrospective report content from LLM output.

    Uses shared extraction logic from core/extraction.py:
    1. Primary: Extract between <!-- RETROSPECTIVE_REPORT_START/END --> markers
    2. Fallback: Look for "# Epic N Retrospective" or "RETROSPECTIVE COMPLETE"
    3. Last resort: Return entire output stripped

    Args:
        raw_output: Raw LLM output (stdout from provider).

    Returns:
        Extracted report content. Never returns empty string.

    Example:
        >>> output = '''Bob (Scrum Master): "Starting retro..."
        ... <!-- RETROSPECTIVE_REPORT_START -->
        ... # Epic 21 Retrospective: Notification Format Enhancement
        ... ...report content...
        ... <!-- RETROSPECTIVE_REPORT_END -->
        ... Bob: "Meeting adjourned!"'''
        >>> extract_retrospective_report(output)
        '# Epic 21 Retrospective: Notification Format Enhancement\n...report content...'

    """
    return extract_report(raw_output, RETROSPECTIVE_MARKERS)


def extract_hardening_plan(raw_output: str) -> dict[str, Any] | None:
    """Extract hardening plan from LLM output.

    Looks for <!-- HARDENING_PLAN_START --> block containing XML.

    Args:
        raw_output: Raw LLM output.

    Returns:
        Dict with keys 'next_epic_id' and 'action_items' (list of strings),
        or None if no valid plan found.

    """
    content = extract_report(raw_output, HARDENING_PLAN_MARKERS)
    # extract_report returns original content if markers missing, so check if it looks like XML
    if not content or "<hardening_plan>" not in content:
        return None

    try:
        # If extraction returned a block with tags, it might still have surrounding text
        # if fallback regex was used. Ensure we have the XML part.
        match = re.search(r"<hardening_plan>.*?</hardening_plan>", content, re.DOTALL)
        if match:
            xml_content = match.group(0)
            root = ET.fromstring(xml_content)
            
            next_epic_id = root.findtext("next_epic_id")
            action_items_tags = root.findall(".//item")
            action_items = [item.text.strip() for item in action_items_tags if item.text and item.text.strip()]

            if next_epic_id and action_items:
                return {
                    "next_epic_id": next_epic_id.strip(),
                    "action_items": action_items,
                }
    except ET.ParseError as e:
        logger.warning("Failed to parse hardening plan XML: %s", e)

    return None


def create_hardening_story(plan: dict[str, Any]) -> Path | None:
    """Create a hardening story (Story 0) for the next epic.

    Location: _bmad-output/planning-artifacts/epics/epic-{id}-0-hardening.md

    Args:
        plan: Plan dict from extract_hardening_plan.

    Returns:
        Path to created story file, or None if failed.

    """
    next_epic_id = plan["next_epic_id"]
    action_items = plan["action_items"]

    paths = get_paths()
    # Prefer planning artifacts for new generated content
    target_dir = paths.planning_artifacts / "epics"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("Failed to create target directory %s: %s", target_dir, e)
        return None

    filename = f"epic-{next_epic_id}-0-hardening.md"
    file_path = target_dir / filename

    # Format action items as checkboxes
    items_md = "\n".join(f"- [ ] {item}" for item in action_items)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    content = f"""# Epic {next_epic_id}: Retrospective Hardening

## Stories

### Story {next_epic_id}.0: Retrospective Hardening

**As a** team member,
**I want** to implement critical retrospective action items,
**So that** the next epic starts on a solid foundation.

**Status:** backlog

#### Acceptance Criteria
{items_md}

#### Description
This story was automatically generated from the retrospective of the previous epic.
It contains critical "Must-Do" action items that should be addressed before starting new feature work.

#### Development Notes
- Created on {now}
"""

    if file_path.exists():
        logger.warning("Overwriting existing hardening story: %s", file_path)

    try:
        atomic_write(file_path, content.strip())
        logger.info("Created hardening story: %s", file_path)
        return file_path
    except OSError as e:
        logger.error("Failed to write hardening story to %s: %s", file_path, e)
        return None


def save_retrospective_report(
    content: str,
    epic_id: EpicId,
    retrospectives_dir: Path,
    timestamp: datetime | None = None,
) -> Path:
    """Save a retrospective report to file.

    File path pattern:
    {retrospectives_dir}/epic-{epic_id}-retro-{YYYYMMDD}.md

    Args:
        content: Extracted retrospective report content.
        epic_id: Epic identifier (int or string like "testarch").
        retrospectives_dir: Path to retrospectives directory.
        timestamp: Optional timestamp for filename. If None, uses now().

    Returns:
        Path to saved report file.

    Raises:
        OSError: If write fails.

    """
    if timestamp is None:
        timestamp = datetime.now(UTC)

    # Format date for filename (YYYYMMDD)
    date_str = timestamp.strftime("%Y%m%d")

    # Build filename
    filename = f"epic-{epic_id}-retro-{date_str}.md"
    file_path = retrospectives_dir / filename

    # Check for existing file (overwrite with warning)
    if file_path.exists():
        logger.warning("Overwriting existing retrospective report: %s", file_path)

    atomic_write(file_path, content)

    logger.info("Saved retrospective report: %s", file_path)
    return file_path


def get_latest_retrospective_report(epic_id: EpicId) -> tuple[Path | None, str | None]:
    """Find and read the latest retrospective report for an epic.

    Args:
        epic_id: The epic ID to find report for.

    Returns:
        Tuple of (file_path, content). Both None if not found.

    """
    paths = get_paths()
    retro_dir = paths.retrospectives_dir
    if not retro_dir.exists():
        return None, None

    # Glob for reports: epic-{id}-retro-*.md
    pattern = f"epic-{epic_id}-retro-*.md"
    matches = sorted(retro_dir.glob(pattern), reverse=True)  # Newest first

    if not matches:
        return None, None

    latest_file = matches[0]
    try:
        content = latest_file.read_text(encoding="utf-8")
        return latest_file, content
    except OSError as e:
        logger.error("Failed to read retrospective report %s: %s", latest_file, e)
        return None, None
