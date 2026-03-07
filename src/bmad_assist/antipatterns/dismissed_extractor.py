"""Dismissed findings extraction from synthesis reports.

This module extracts dismissed findings (false positives, intentional design decisions)
from synthesis reports and persists them for injection into subsequent code review prompts.
This prevents reviewers from re-flagging issues that have already been investigated and dismissed.

Public API:
    extract_dismissed_findings: Extract dismissed findings from synthesis content
    append_to_dismissed_findings_file: Append findings to epic-scoped file
    extract_and_append_dismissed_findings: Combined convenience function
"""

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from bmad_assist.core.io import atomic_write
from bmad_assist.core.paths import get_paths

if TYPE_CHECKING:
    from bmad_assist.core.config import Config
    from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

# Regex patterns for dismissed findings format
# Matches "## Issues Dismissed" section up to next ## header or end of content
DISMISSED_SECTION_PATTERN = re.compile(
    r"## Issues Dismissed\s*\n(.*?)(?=\n## |\Z)",
    re.DOTALL,
)

# Matches individual dismissed items in pipe-delimited format:
# - **Claimed Issue**: desc | **Raised by**: reviewers | **Dismissal Reason**: reason
DISMISSED_ITEM_PATTERN = re.compile(
    r"-\s*\*\*Claimed Issue\*\*:\s*(.+?)\s*\|\s*\*\*Raised by\*\*:\s*(.+?)\s*\|\s*\*\*Dismissal Reason\*\*:\s*(.+?)(?=\n-\s*\*\*Claimed Issue\*\*|\Z)",
    re.DOTALL,
)

DISMISSED_FINDINGS_HEADER = """# Epic {epic_id} - Dismissed Findings

> CONTEXT FOR REVIEWERS: These findings were previously investigated during
> code review synthesis and dismissed with documented reasoning. Do NOT
> re-flag these issues unless you have substantial NEW evidence that
> contradicts the dismissal reason.

"""


def _clean_text(text: str) -> str:
    """Clean up extracted text, collapsing whitespace and stripping."""
    return re.sub(r"\s+", " ", text).strip()


def extract_dismissed_findings(
    synthesis_content: str,
    epic_id: "EpicId",
    story_id: str,
    config: "Config",
) -> list[dict[str, str]]:
    """Extract dismissed findings from synthesis content.

    Args:
        synthesis_content: Raw synthesis report content.
        epic_id: Epic identifier.
        story_id: Story identifier (e.g., "5-1").
        config: Application configuration.

    Returns:
        List of dicts with keys: claimed_issue, raised_by, dismissal_reason.
        Returns empty list on any failure (best-effort, non-blocking).

    """
    logger.info("Starting dismissed findings extraction for story %s", story_id)

    # Check config (reuse antipatterns.enabled flag)
    try:
        if not config.antipatterns.enabled:
            logger.debug("Antipatterns/dismissed extraction disabled in config")
            return []
    except AttributeError:
        pass  # Config doesn't have antipatterns yet, proceed with default enabled

    if not synthesis_content or not synthesis_content.strip():
        logger.debug("Empty synthesis content, skipping dismissed findings extraction")
        return []

    # Find Issues Dismissed section
    section_match = DISMISSED_SECTION_PATTERN.search(synthesis_content)
    if not section_match:
        logger.debug("No 'Issues Dismissed' section found, skipping extraction")
        return []

    section_content = section_match.group(1)

    # Skip if section says "No false positives identified" or similar
    if re.search(r"no false positives|none identified|no issues dismissed", section_content, re.IGNORECASE):
        logger.debug("Issues Dismissed section indicates no dismissals")
        return []

    findings: list[dict[str, str]] = []

    for match in DISMISSED_ITEM_PATTERN.finditer(section_content):
        claimed_issue = _clean_text(match.group(1))
        raised_by = _clean_text(match.group(2))
        dismissal_reason = _clean_text(match.group(3))

        if claimed_issue and dismissal_reason:
            findings.append(
                {
                    "claimed_issue": claimed_issue,
                    "raised_by": raised_by,
                    "dismissal_reason": dismissal_reason,
                }
            )

    logger.info(
        "Extracted %d dismissed findings from story %s (epic %s)",
        len(findings),
        story_id,
        epic_id,
    )
    return findings


def append_to_dismissed_findings_file(
    findings: list[dict[str, str]],
    epic_id: "EpicId",
    story_id: str,
    project_path: Path,
) -> None:
    """Append dismissed findings to epic-scoped file.

    Creates file with header if it doesn't exist.
    Appends story section with findings table in markdown format.

    File: impl_artifacts/dismissed-findings/epic-{N}-dismissed-findings.md

    Args:
        findings: List of finding dicts to append.
        epic_id: Epic identifier.
        story_id: Story identifier (e.g., "5-1").
        project_path: Project root path for path resolution.

    """
    if not findings:
        logger.debug("No dismissed findings to append, skipping file write")
        return

    try:
        paths = get_paths()
        impl_artifacts = paths.implementation_artifacts
    except RuntimeError:
        impl_artifacts = project_path / "_bmad-output" / "implementation-artifacts"

    # Create dismissed-findings subdirectory
    dismissed_dir = impl_artifacts / "dismissed-findings"
    dismissed_dir.mkdir(parents=True, exist_ok=True)
    dismissed_path = dismissed_dir / f"epic-{epic_id}-dismissed-findings.md"

    # Read existing content or start with header
    if dismissed_path.exists():
        existing_content = dismissed_path.read_text(encoding="utf-8")
    else:
        existing_content = DISMISSED_FINDINGS_HEADER.format(epic_id=epic_id)

    # Build story section with findings table
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    story_section = f"\n## Story {story_id} ({date_str})\n\n"
    story_section += "| Finding | Raised By | Dismissal Reason |\n"
    story_section += "|---------|-----------|------------------|\n"

    for finding in findings:
        claimed = finding.get("claimed_issue", "").replace("|", "\\|").replace("\n", " ")
        raised = finding.get("raised_by", "").replace("|", "\\|").replace("\n", " ")
        reason = finding.get("dismissal_reason", "").replace("|", "\\|").replace("\n", " ")
        story_section += f"| {claimed} | {raised} | {reason} |\n"

    full_content = existing_content.rstrip() + "\n" + story_section

    atomic_write(dismissed_path, full_content)
    logger.info("Appended %d dismissed findings to %s", len(findings), dismissed_path)


def extract_and_append_dismissed_findings(
    synthesis_content: str,
    epic_id: "EpicId",
    story_id: str,
    project_path: Path,
    config: "Config",
) -> None:
    """Extract dismissed findings and append to file (convenience function).

    Combines extract_dismissed_findings() and append_to_dismissed_findings_file()
    into a single call. Handles all errors gracefully (best-effort, non-blocking).

    Args:
        synthesis_content: Raw synthesis report content.
        epic_id: Epic identifier.
        story_id: Story identifier (e.g., "5-1").
        project_path: Project root path for path resolution.
        config: Application configuration.

    """
    findings = extract_dismissed_findings(synthesis_content, epic_id, story_id, config)
    if findings:
        append_to_dismissed_findings_file(findings, epic_id, story_id, project_path)
