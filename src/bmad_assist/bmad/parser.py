"""BMAD markdown file parser with YAML frontmatter support.

This module provides deterministic parsing of BMAD markdown files,
extracting YAML frontmatter metadata and markdown content without LLM calls.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter  # Library lacks type stubs

from bmad_assist.core.exceptions import ParserError
from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

# Regex patterns for epic file parsing
# Pattern: ## Story X.Y: Title (2+ hashes - supports ##, ###, ####, etc.)
STORY_HEADER_PATTERN = re.compile(
    r"^#{2,}\s+Story\s+(\d+)\.(\d+):\s+(.+)$",
    re.MULTILINE,
)

# Pattern: **Estimate:** 3 SP or **Story Points:** 3
ESTIMATE_PATTERN = re.compile(
    r"\*\*(?:Estimate|Story Points):\*\*\s*(\d+)",
    re.IGNORECASE,
)

# Pattern: **Status:** done OR **Status:** Ready for Review (captures multi-word)
STATUS_PATTERN = re.compile(
    r"\*\*Status:\*\*\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)

# Pattern: **Priority:** P0 - Foundation (captures priority value)
PRIORITY_PATTERN = re.compile(
    r"\*\*Priority:\*\*\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)

# Pattern: **Dependencies:** Story 3.2, Story 3.4
DEPENDENCIES_PATTERN = re.compile(
    r"\*\*Dependencies:\*\*\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)

# Pattern to extract story numbers from dependencies
STORY_NUMBER_PATTERN = re.compile(r"(\d+\.\d+)")

# Pattern for non-standard dependency codes like PRSP-5-1, REFACTOR-2-1
NON_STANDARD_DEP_PATTERN = re.compile(r"([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)", re.IGNORECASE)

# Patterns for checkbox criteria
CHECKBOX_CHECKED_PATTERN = re.compile(r"-\s*\[x\]", re.IGNORECASE)
CHECKBOX_UNCHECKED_PATTERN = re.compile(r"-\s*\[\s*\]")

# Pattern for multiple epics in a file: # Epic N: Title or ## Epic N: Title
EPIC_HEADER_PATTERN = re.compile(
    r"^#{1,2}\s+Epic\s+\d+:",
    re.MULTILINE,
)

# Pattern to extract epic number and title from header: # Epic 16: Real-time Dashboard
EPIC_TITLE_PATTERN = re.compile(
    r"^#\s+Epic\s+(\d+|[a-zA-Z][\w-]*):\s*(.+)$",
    re.MULTILINE,
)


@dataclass
class BmadDocument:
    """Parsed BMAD document with frontmatter and content.

    Attributes:
        frontmatter: Dictionary of YAML frontmatter metadata.
        content: Markdown content after frontmatter.
        path: Original file path as string.

    """

    frontmatter: dict[str, Any]
    content: str
    path: str

    def __eq__(self, other: object) -> bool:
        """Compare BmadDocument objects based on their path."""
        if not isinstance(other, BmadDocument):
            return NotImplemented
        return self.path == other.path

    def __hash__(self) -> int:
        """Return the hash of the BmadDocument object based on its path."""
        return hash(self.path)


@dataclass
class EpicStory:
    """Represents a story extracted from an epic file.

    Attributes:
        number: Story number in format "X.Y" (e.g., "2.1").
        title: Story title.
        code: Original story code for non-standard formats (e.g., "PRSP-5-1"), None for standard.
        estimate: Story point estimate, or None if not specified.
        status: Story status from explicit **Status:** field, or None.
        dependencies: List of dependent story numbers (e.g., ["3.2", "3.4"]).
        completed_criteria: Count of checked acceptance criteria checkboxes.
        total_criteria: Total count of acceptance criteria checkboxes.

    """

    number: str
    title: str
    code: str | None = None
    estimate: int | None = None
    status: str | None = None
    dependencies: list[str] = field(default_factory=list)
    completed_criteria: int | None = None
    total_criteria: int | None = None


@dataclass
class EpicDocument:
    """Represents a parsed epic file with stories.

    Attributes:
        epic_num: Epic ID from frontmatter (int or str), or None for multi-epic files.
        title: Epic title from frontmatter, or None for multi-epic files.
        status: Epic status from frontmatter, or None for multi-epic files.
        stories: List of stories extracted from the epic file.
        path: Original file path as string.

    """

    epic_num: EpicId | None
    title: str | None
    status: str | None
    stories: list[EpicStory]
    path: str


def parse_bmad_file(path: str | Path) -> BmadDocument:
    """Parse a BMAD markdown file with YAML frontmatter.

    Reads the file, extracts YAML frontmatter metadata, and separates
    the markdown content. Uses python-frontmatter library for robust
    parsing.

    Args:
        path: Path to the BMAD markdown file (string or Path object).

    Returns:
        BmadDocument with frontmatter dict, content string, and path.

    Raises:
        FileNotFoundError: If the file does not exist.
        ParserError: If YAML frontmatter is malformed or parsing fails.

    Examples:
        >>> doc = parse_bmad_file("docs/prd.md")
        >>> doc.frontmatter["status"]
        'complete'
        >>> doc.content[:20]
        '# Product Requirements'

    """
    path = Path(path)

    try:
        post = frontmatter.load(path)
    except FileNotFoundError:
        raise
    except Exception as e:
        raise ParserError(f"Failed to parse {path}: {e}") from e

    return BmadDocument(
        frontmatter=dict(post.metadata),
        content=post.content,
        path=str(path),
    )


def _extract_estimate(section: str) -> int | None:
    """Extract story point estimate from a story section.

    Args:
        section: The markdown content of a story section.

    Returns:
        The story point estimate as an integer, or None if not found.

    """
    match = ESTIMATE_PATTERN.search(section)
    if match:
        return int(match.group(1))
    return None


def _extract_status(section: str) -> str | None:
    """Extract explicit status from a story section.

    Args:
        section: The markdown content of a story section.

    Returns:
        The status string (cleaned), or None if no explicit status is found.

    """
    match = STATUS_PATTERN.search(section)
    if match:
        # Clean up: strip whitespace and trailing asterisks (typos like "done**")
        return match.group(1).strip().rstrip("*").strip()
    return None


def _extract_priority(section: str) -> str | None:
    """Extract priority from a story section.

    Args:
        section: The markdown content of a story section.

    Returns:
        The priority string (cleaned), or None if no explicit priority is found.

    """
    match = PRIORITY_PATTERN.search(section)
    if match:
        return match.group(1).strip()
    return None


def _has_story_anchor(section: str) -> bool:
    """Check if section contains a story anchor (Status or Priority).

    Used by fallback parser to detect story boundaries.

    Args:
        section: The markdown content of a story section.

    Returns:
        True if section contains **Status:** or **Priority:** field.

    """
    return bool(
        STATUS_PATTERN.search(section) or PRIORITY_PATTERN.search(section)
    )


def _extract_dependencies(section: str) -> list[str]:
    """Extract dependency story numbers from a story section.

    Supports both standard (X.Y) and non-standard (PRSP-5-1) formats.

    Args:
        section: The markdown content of a story section.

    Returns:
        List of story numbers that this story depends on.

    """
    deps_match = DEPENDENCIES_PATTERN.search(section)
    if not deps_match:
        return []

    deps_text = deps_match.group(1)

    # Try standard format first (X.Y)
    numbers = STORY_NUMBER_PATTERN.findall(deps_text)
    if numbers:
        return numbers

    # Fallback: try non-standard format (PRSP-5-1, etc.)
    codes = NON_STANDARD_DEP_PATTERN.findall(deps_text)
    return codes


def _count_criteria(section: str) -> tuple[int | None, int | None]:
    """Count checked and total acceptance criteria checkboxes.

    Args:
        section: The markdown content of a story section.

    Returns:
        Tuple of (completed_criteria, total_criteria), or (None, None)
        if no checkboxes are found.

    """
    checked = len(CHECKBOX_CHECKED_PATTERN.findall(section))
    unchecked = len(CHECKBOX_UNCHECKED_PATTERN.findall(section))
    total = checked + unchecked

    if total == 0:
        return None, None

    return checked, total


def _is_multi_epic_file(content: str) -> bool:
    """Check if content contains multiple epic headers.

    Args:
        content: The markdown content to check.

    Returns:
        True if multiple "# Epic N:" headers are found.

    """
    matches = EPIC_HEADER_PATTERN.findall(content)
    return len(matches) > 1


def _find_stories_section(content: str) -> tuple[str, int] | None:
    """Find all Stories sections and return combined (section_content, marker_level).

    Supports multiple Stories sections (e.g., "## Stories - Section A", "## Stories - Section B").
    Returns combined content from all Stories sections.

    Returns None if no Stories section found.
    """
    # Find ALL headers containing "Stories"
    stories_markers = list(
        re.finditer(r"^(#{2,})\s+.*Stories.*$", content, re.MULTILINE | re.IGNORECASE)
    )
    if not stories_markers:
        return None

    # Use the level of the first Stories header as reference
    marker_level = len(stories_markers[0].group(1))

    # Find all same-level headers (Stories and non-Stories)
    same_level_pattern = r"^" + "#" * marker_level + r"(?!#)\s+(.*)$"
    all_headers = list(re.finditer(same_level_pattern, content, re.MULTILINE))

    # Collect content from all Stories sections
    combined_sections: list[str] = []

    for i, header in enumerate(all_headers):
        header_text = header.group(1).lower()
        if "stories" not in header_text:
            continue

        # Get content from this header to the next same-level header
        section_start = header.end()
        if i + 1 < len(all_headers):
            section_end = all_headers[i + 1].start()
        else:
            section_end = len(content)

        combined_sections.append(content[section_start:section_end])

    if not combined_sections:
        return None

    return "\n".join(combined_sections), marker_level


def _parse_fallback_story_sections(
    content: str,
    epic_num: EpicId,
    path: str,
) -> list[EpicStory]:
    """Fallback parser using Status/Priority-anchored detection.

    Finds stories by locating **Status:** or **Priority:** fields and mapping them
    to their nearest preceding header. Numbers sequentially.

    When only Priority is present (no Status), defaults status to "backlog".
    """
    result = _find_stories_section(content)
    if result is None:
        return []

    section, _ = result

    # Find all headers in section
    headers = list(re.finditer(r"^(#{2,})\s+(.+)$", section, re.MULTILINE))
    if not headers:
        # No headers but check if anchor exists - that's malformed
        if _has_story_anchor(section):
            raise ParserError(
                f"Malformed epic file {path}: Found **Status:** or **Priority:** field(s) "
                "but no valid story headers. These fields must appear AFTER a header."
            )
        return []

    stories: list[EpicStory] = []
    for i, header in enumerate(headers):
        # Get this header's "area" (until next header or end)
        area_start = header.end()
        area_end = headers[i + 1].start() if i + 1 < len(headers) else len(section)
        area = section[area_start:area_end]

        # Check if this area has a story anchor (Status or Priority)
        status = _extract_status(area)
        priority = _extract_priority(area)

        if status is None and priority is None:
            continue  # Not a story, skip (e.g., phase header)

        # If no explicit status but has priority, default to "backlog"
        if status is None:
            status = "backlog"

        # Parse header: "CODE: Title" or just "Title"
        header_text = header.group(2).strip()
        if not header_text:
            logger.warning("Empty header in %s, skipping", path)
            continue

        if ":" in header_text:
            parts = header_text.split(":", 1)
            code = parts[0].strip()
            title = parts[1].strip() if len(parts) > 1 and parts[1].strip() else header_text
        else:
            code = None
            title = header_text

        # Validate non-empty title
        if not title:
            logger.warning(
                "Empty title after parsing header '%s' in %s, skipping", header_text, path
            )
            continue

        # Extract other fields, cache criteria count
        criteria = _count_criteria(area)

        stories.append(
            EpicStory(
                number=f"{epic_num}.{len(stories) + 1}",
                title=title,
                code=code,
                status=status,
                estimate=_extract_estimate(area),
                dependencies=_extract_dependencies(area),
                completed_criteria=criteria[0],
                total_criteria=criteria[1],
            )
        )

    if stories:
        # Log fallback usage (INFO level - working as designed)
        first_id = stories[0].code or stories[0].title[:25]
        logger.info(
            "Non-standard story format in %s. Using fallback parser "
            "(sequential numbering): %s -> %s, ... (%d stories total)",
            path,
            first_id,
            stories[0].number,
            len(stories),
        )

    return stories


def _parse_story_sections(
    content: str,
    epic_num: EpicId | None = None,
    path: str = "",
) -> list[EpicStory]:
    """Extract stories from epic content.

    Tries standard pattern first, falls back to Status-anchored detection.

    Args:
        content: The markdown content of an epic file.
        epic_num: Epic ID for fallback numbering (required for fallback).
        path: File path for error/warning messages.

    Returns:
        List of EpicStory objects extracted from the content.

    """
    matches = list(STORY_HEADER_PATTERN.finditer(content))

    if not matches:
        # Fallback: try Status-anchored detection
        if epic_num is not None:
            return _parse_fallback_story_sections(content, epic_num, path)
        return []

    # Detect mixed format - standard found but there might be more non-standard
    stories_section = _find_stories_section(content)
    if stories_section and epic_num is not None:
        section_content, _ = stories_section
        status_count = len(re.findall(r"\*\*Status:\*\*", section_content, re.IGNORECASE))
        if status_count > len(matches):
            logger.info(
                "Mixed story format detected in %s: %d standard, %d total Status fields. "
                "Only standard stories parsed. Consider using consistent format.",
                path,
                len(matches),
                status_count,
            )

    stories = []
    for i, match in enumerate(matches):
        try:
            # Extract section content (from this header to next or end)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            section = content[start:end]

            epic_num_parsed, story_num, title = match.groups()
            number = f"{epic_num_parsed}.{story_num}"

            # Extract details from section
            estimate = _extract_estimate(section)
            status = _extract_status(section)
            dependencies = _extract_dependencies(section)
            completed, total = _count_criteria(section)

            stories.append(
                EpicStory(
                    number=number,
                    title=title.strip(),
                    estimate=estimate,
                    status=status,
                    dependencies=dependencies,
                    completed_criteria=completed,
                    total_criteria=total,
                )
            )
        except Exception:
            # Log warning for malformed headers and continue
            malformed_text = match.group(0) if match else "unknown"
            logger.warning("Skipping malformed story header: %s", malformed_text)
            continue

    return stories


def parse_epic_file(path: str | Path) -> EpicDocument:
    """Parse a BMAD epic file to extract story list.

    Uses parse_bmad_file() for frontmatter/content parsing, then
    applies epic-specific parsing to extract story information.

    Args:
        path: Path to the epic markdown file (string or Path object).

    Returns:
        EpicDocument with epic metadata and list of stories.

    Raises:
        FileNotFoundError: If the file does not exist.
        ParserError: If file parsing fails.

    Examples:
        >>> epic = parse_epic_file("docs/epics.md")
        >>> len(epic.stories)
        60
        >>> epic.stories[0].number
        '1.1'

    """
    doc = parse_bmad_file(path)

    # Check if this is a multi-epic file
    is_multi_epic = _is_multi_epic_file(doc.content)

    if is_multi_epic:
        # For consolidated epics file, metadata is None
        epic_num = None
        title = None
        status = None
    else:
        # Extract epic metadata from frontmatter
        epic_num = doc.frontmatter.get("epic_num")
        title = doc.frontmatter.get("title")
        status = doc.frontmatter.get("status")

        # Fallback: parse from markdown header if frontmatter is empty
        # Handles files like "# Epic 16: Real-time Dashboard"
        if epic_num is None or title is None:
            header_match = EPIC_TITLE_PATTERN.search(doc.content)
            if header_match:
                if epic_num is None:
                    raw_num = header_match.group(1)
                    # Try to convert to int, keep as string if not numeric
                    try:
                        epic_num = int(raw_num)
                    except ValueError:
                        epic_num = raw_num
                if title is None:
                    title = header_match.group(2).strip()

    # Parse story sections from content
    stories = _parse_story_sections(doc.content, epic_num, doc.path)

    return EpicDocument(
        epic_num=epic_num,
        title=title,
        status=status,
        stories=stories,
        path=doc.path,
    )
