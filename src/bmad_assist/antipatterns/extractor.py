"""Antipatterns extraction from synthesis reports.

This module extracts verified issues from synthesis reports using regex patterns,
then appends them to epic-scoped antipatterns files for use by subsequent workflows.

Public API:
    extract_antipatterns: Extract issues list from synthesis content
    append_to_antipatterns_file: Append issues to antipatterns file
    extract_and_append_antipatterns: Combined convenience function
"""

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from bmad_assist.core.io import atomic_write
from bmad_assist.core.paths import get_paths

if TYPE_CHECKING:
    from bmad_assist.core.config import Config
    from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

# Regex patterns for extraction
ISSUES_SECTION_PATTERN = re.compile(r"## Issues Verified.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
SEVERITY_HEADER_PATTERN = re.compile(
    r"^###\s+(Critical|High|Medium|Low)", re.IGNORECASE | re.MULTILINE
)

# --- Single-line pipe-delimited format ---
# Format A: - **Issue desc** | ... | **Fix**: action
# Format B: - **Issue**: desc | ... | **Fix**: action
# Format C: 1. **Issue desc** | ... | **Fix**: action (numbered variant)
ISSUE_WITH_FIX_PATTERN = re.compile(
    r"^\s*(?:-|\d+\.)\s+\*\*([^|]+?)\s*\|.*?\*\*Fix\*\*:\s*(.+?)$", re.MULTILINE
)

# --- Dismissed findings format (from synthesis "Issues Dismissed" section) ---
# Matches "## Issues Dismissed" section up to next ## header or end of content
DISMISSED_SECTION_PATTERN = re.compile(
    r"## Issues Dismissed\s*\n(.*?)(?=\n## |\Z)",
    re.DOTALL,
)
# Matches: - **Claimed Issue**: desc | **Raised by**: reviewers | **Dismissal Reason**: reason
DISMISSED_ITEM_PATTERN = re.compile(
    r"-\s*\*\*Claimed Issue\*\*:\s*(.+?)\s*\|\s*\*\*Raised by\*\*:\s*(.+?)\s*\|\s*\*\*Dismissal Reason\*\*:\s*(.+?)(?=\n-\s*\*\*Claimed Issue\*\*|\Z)",
    re.DOTALL,
)

# --- Multi-line block format patterns ---
# Issue block start: numbered item or bold-numbered item
# Matches: "1. **Title**" or "**1. Title**" or "- **Title**"
# The "- **" alternative excludes field labels like "- **Issue**:", "- **Fix Applied**:"
BLOCK_START_PATTERN = re.compile(
    r"^(?:\d+\.\s+\*\*|\*\*\d+\.\s+|-\s+\*\*(?!\w+(?:\s+\w+)?\*\*\s*:))(.+?)$", re.MULTILINE
)
# Fix line within a block (indented or not)
# Matches: "- **Fix**: ...", "- **Fix Applied**: ...", "  - **Fix**: ..."
BLOCK_FIX_PATTERN = re.compile(
    r"^\s*-\s+\*\*Fix(?:\s+Applied)?\*\*:\s*(.+?)$", re.MULTILINE
)
# Issue description line within a validation synthesis block
# Matches: "- **Issue**: description"
BLOCK_ISSUE_PATTERN = re.compile(
    r"^\s*-\s+\*\*Issue\*\*:\s*(.+?)$", re.MULTILINE
)


# Warning header for antipatterns files
STORY_ANTIPATTERNS_HEADER = """# Epic {epic_id} - Story Antipatterns

> **WARNING: ANTI-PATTERNS**
> The issues below were MISTAKES found during validation of previous stories.
> DO NOT repeat these patterns. Learn from them and avoid similar errors.
> These represent story-writing mistakes (unclear AC, missing Notes, unrealistic scope).

"""

CODE_ANTIPATTERNS_HEADER = """# Epic {epic_id} - Code Antipatterns

> **WARNING: ANTI-PATTERNS**
> The issues below were MISTAKES found during code review of previous stories.
> DO NOT repeat these patterns. Learn from them and avoid similar errors.
> These represent implementation mistakes (race conditions, missing tests, weak assertions, etc.)

"""


def _clean_issue_desc(desc: str) -> str:
    """Clean up issue description from various synthesis formats."""
    # Remove trailing ** (bold markers)
    desc = desc.rstrip("*").strip()
    # Remove leading "Issue**:" or "Issue:" prefix only when it's a field label
    # (has colon after "Issue"), not when "Issue" is part of the title
    if re.match(r"^Issue\*{0,2}:", desc):
        desc = re.sub(r"^Issue\*{0,2}:\s*", "", desc)
    # Remove trailing parenthetical source refs like "(Validator B + ...)"
    desc = re.sub(r"\s*\([^)]*(?:Validator|Reviewer|Deep Verify)[^)]*\)\s*$", "", desc)
    # Remove bold markers wrapping the whole description
    desc = desc.strip("*").strip()
    return desc


def _clean_fix_desc(desc: str) -> str:
    """Clean up fix description, removing status markers."""
    # Remove status emoji prefixes like "✅ **APPLIED** — " or "⏭️ **DEFERRED** — "
    desc = re.sub(r"^[✅⏭️🔄❌\s]*\*\*(?:APPLIED|DEFERRED|PARTIAL)\*\*\s*[—–-]?\s*", "", desc)
    return desc.strip()


def extract_antipatterns(
    synthesis_content: str,
    epic_id: "EpicId",
    story_id: str,
    config: "Config",
) -> list[dict[str, str]]:
    """Extract verified issues from synthesis content using regex patterns.

    Args:
        synthesis_content: Raw synthesis report content.
        epic_id: Epic identifier (numeric or string like "testarch").
        story_id: Story identifier (e.g., "24-11").
        config: Application configuration with antipatterns settings.

    Returns:
        List of issue dictionaries with keys: severity, issue, fix.
        Returns empty list on any failure (best-effort, non-blocking).

    """
    logger.info("Starting antipatterns extraction for story %s", story_id)

    # Check config
    try:
        if not config.antipatterns.enabled:
            logger.debug("Antipatterns extraction disabled in config")
            return []
    except AttributeError:
        pass  # Config doesn't have antipatterns yet, proceed with default enabled

    # Input validation - early exit
    if not synthesis_content or not synthesis_content.strip():
        logger.debug("Empty synthesis content, skipping antipatterns extraction")
        return []

    issues: list[dict[str, str]] = []

    # Find Issues Verified section
    section_match = ISSUES_SECTION_PATTERN.search(synthesis_content)
    if not section_match:
        logger.debug("No 'Issues Verified' section found")
    else:
        section_content = section_match.group(0)

        # Split by severity headers and extract issues
        current_severity = "unknown"
        lines = section_content.split("\n")

        # Track multi-line block state
        current_block_issue: str | None = None
        current_block_fix: str | None = None

        def _flush_block() -> None:
            """Flush accumulated block into issues list."""
            nonlocal current_block_issue, current_block_fix
            if current_block_issue and current_block_fix:
                # Skip DEFERRED items
                fix_upper = current_block_fix.upper()
                if "DEFERRED" not in fix_upper or "APPLIED" in fix_upper:
                    issues.append(
                        {
                            "severity": current_severity,
                            "issue": _clean_issue_desc(current_block_issue),
                            "fix": _clean_fix_desc(current_block_fix),
                        }
                    )
            current_block_issue = None
            current_block_fix = None

        for line in lines:
            # Check for severity header
            header_match = SEVERITY_HEADER_PATTERN.match(line)
            if header_match:
                _flush_block()
                current_severity = header_match.group(1).lower()
                continue

            # --- Legacy single-line pipe-delimited format ---
            issue_match = ISSUE_WITH_FIX_PATTERN.match(line)
            if issue_match:
                _flush_block()
                issue_desc = issue_match.group(1).strip()
                fix_desc = issue_match.group(2).strip()
                issues.append(
                    {
                        "severity": current_severity,
                        "issue": _clean_issue_desc(issue_desc),
                        "fix": _clean_fix_desc(fix_desc),
                    }
                )
                continue

            # --- Multi-line block format ---
            # Check for block start (numbered or bold-numbered item)
            block_start = BLOCK_START_PATTERN.match(line)
            if block_start:
                _flush_block()
                current_block_issue = block_start.group(1).strip()
                continue

            # Inside a block: check for explicit issue description line
            if current_block_issue is not None:
                issue_line = BLOCK_ISSUE_PATTERN.match(line)
                if issue_line:
                    # Override block title with explicit issue description
                    current_block_issue = issue_line.group(1).strip()
                    continue

                # Check for fix line
                fix_line = BLOCK_FIX_PATTERN.match(line)
                if fix_line:
                    current_block_fix = fix_line.group(1).strip()
                    continue

        # Flush any remaining block
        _flush_block()

    # --- Also extract dismissed findings (false positives) as severity="dismissed" ---
    # Idea credit: @derron1 (GitHub PR #39)
    dismissed_section = DISMISSED_SECTION_PATTERN.search(synthesis_content)
    if dismissed_section:
        section_text = dismissed_section.group(1)
        # Skip if section says "no false positives" or similar
        if not re.search(
            r"no false positives|none identified|no issues dismissed",
            section_text,
            re.IGNORECASE,
        ):
            for match in DISMISSED_ITEM_PATTERN.finditer(section_text):
                claimed = re.sub(r"\s+", " ", match.group(1)).strip()
                reason = re.sub(r"\s+", " ", match.group(3)).strip()
                if claimed and reason:
                    issues.append(
                        {
                            "severity": "dismissed",
                            "issue": claimed,
                            "fix": f"FALSE POSITIVE: {reason}",
                        }
                    )

    logger.info(
        "Extracted %d antipatterns from story %s (epic %s)",
        len(issues),
        story_id,
        epic_id,
    )
    return issues


def append_to_antipatterns_file(
    issues: list[dict[str, str]],
    epic_id: "EpicId",
    story_id: str,
    antipattern_type: Literal["story", "code"],
    project_path: Path,
) -> None:
    """Append extracted issues to antipatterns file.

    Creates file with warning header if it doesn't exist.
    Appends story section with issues table in markdown format.

    Args:
        issues: List of issue dictionaries to append.
        epic_id: Epic identifier (numeric or string).
        story_id: Story identifier (e.g., "24-11").
        antipattern_type: Either "story" (for validation) or "code" (for code review).
        project_path: Project root path for path resolution.

    """
    if not issues:
        logger.debug("No issues to append, skipping file write")
        return

    try:
        paths = get_paths()
        impl_artifacts = paths.implementation_artifacts
    except RuntimeError:
        # Paths not initialized - use fallback
        impl_artifacts = project_path / "_bmad-output" / "implementation-artifacts"

    # Create antipatterns subdirectory
    antipatterns_dir = impl_artifacts / "antipatterns"
    antipatterns_dir.mkdir(parents=True, exist_ok=True)
    antipatterns_path = antipatterns_dir / f"epic-{epic_id}-{antipattern_type}-antipatterns.md"

    # Determine header based on type
    if antipattern_type == "story":
        header = STORY_ANTIPATTERNS_HEADER.format(epic_id=epic_id)
    else:
        header = CODE_ANTIPATTERNS_HEADER.format(epic_id=epic_id)

    # Read existing content or start with header
    if antipatterns_path.exists():
        existing_content = antipatterns_path.read_text(encoding="utf-8")
    else:
        existing_content = header

    # Build story section with 3-column table (no file column)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    story_section = f"\n## Story {story_id} ({date_str})\n\n"
    story_section += "| Severity | Issue | Fix |\n"
    story_section += "|----------|-------|-----|\n"

    for issue in issues:
        severity = issue.get("severity", "unknown")
        issue_desc = issue.get("issue", "").replace("|", "\\|").replace("\n", " ")
        fix_desc = issue.get("fix", "-").replace("|", "\\|").replace("\n", " ")
        story_section += f"| {severity} | {issue_desc} | {fix_desc} |\n"

    # Append to content
    full_content = existing_content.rstrip() + "\n" + story_section

    # Atomic write
    atomic_write(antipatterns_path, full_content)
    logger.info("Appended %d antipatterns to %s", len(issues), antipatterns_path)


def extract_and_append_antipatterns(
    synthesis_content: str,
    epic_id: "EpicId",
    story_id: str,
    antipattern_type: Literal["story", "code"],
    project_path: Path,
    config: "Config",
) -> None:
    """Extract antipatterns and append to file (convenience function).

    Combines extract_antipatterns() and append_to_antipatterns_file() into
    a single call. Handles all errors gracefully (best-effort, non-blocking).

    Args:
        synthesis_content: Raw synthesis report content.
        epic_id: Epic identifier (numeric or string).
        story_id: Story identifier (e.g., "24-11").
        antipattern_type: Either "story" (for validation) or "code" (for code review).
        project_path: Project root path for path resolution.
        config: Application configuration with helper provider settings.

    """
    issues = extract_antipatterns(synthesis_content, epic_id, story_id, config)
    if issues:
        append_to_antipatterns_file(issues, epic_id, story_id, antipattern_type, project_path)
