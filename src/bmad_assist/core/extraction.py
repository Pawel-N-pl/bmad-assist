"""Shared report extraction utilities.

This module provides unified report extraction logic used by:
- validation/reports.py (story validation)
- code_review/orchestrator.py (code review)
- retrospective/reports.py (epic retrospective)

Extraction Strategy (Priority Order):
1. HTML Markers: Extract between <!-- START --> and <!-- END --> markers
2. Fallback Patterns: Look for report header patterns (regex)
3. Last Resort: Return entire output stripped

The markers are the PRIMARY mechanism - LLMs are instructed to use them.
Fallback patterns exist for when LLMs ignore marker instructions.
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = [
    "ReportMarkers",
    "extract_report",
    "strip_code_block",
    "VALIDATION_MARKERS",
    "CODE_REVIEW_MARKERS",
    "RETROSPECTIVE_MARKERS",
    "SYNTHESIS_MARKERS",
    "CODE_REVIEW_SYNTHESIS_MARKERS",
    "HARDENING_PLAN_MARKERS",
]


@dataclass(frozen=True)
class ReportMarkers:
    """Configuration for report extraction markers and fallbacks.

    Attributes:
        start_marker: HTML comment start marker (e.g., <!-- REPORT_START -->)
        end_marker: HTML comment end marker (e.g., <!-- REPORT_END -->)
        fallback_patterns: List of regex patterns to try if markers not found.
            Patterns are tried in order; first match wins.
            Each pattern should match the START of the report content.
        name: Human-readable name for logging (e.g., "validation", "code-review")

    """

    start_marker: str
    end_marker: str
    fallback_patterns: list[str]
    name: str


# Pre-configured markers for each report type

VALIDATION_MARKERS = ReportMarkers(
    start_marker="<!-- VALIDATION_REPORT_START -->",
    end_marker="<!-- VALIDATION_REPORT_END -->",
    fallback_patterns=[
        # Most specific first - with emoji
        r"^#\s*🎯\s*Story\s+(Context\s+)?Validation\s+Report",
        # Without emoji, with "Context"
        r"^#\s*Story\s+Context\s+Validation\s+Report",
        # Without emoji, without "Context"
        r"^#\s*Story\s+Validation\s+Report",
        # Generic validation report header
        r"^#\s*Validation\s+Report",
        # Executive Summary as last resort (many reports start with this)
        r"^##\s*Executive\s+Summary",
    ],
    name="validation",
)

CODE_REVIEW_MARKERS = ReportMarkers(
    start_marker="<!-- CODE_REVIEW_REPORT_START -->",
    end_marker="<!-- CODE_REVIEW_REPORT_END -->",
    fallback_patterns=[
        # Adversarial review header (with emoji)
        r"^\*{0,2}🔥\s*ADVERSARIAL\s+CODE\s+REVIEW",
        # Review Summary table
        r"^##\s*📊?\s*Review\s+Summary",
        # Generic code review header
        r"^#\s+(Code\s+)?Review",
        # Story header (common in reviews)
        r"^\*{0,2}Story\s*:",
        # Final Score (appears in adversarial reviews)
        r"^\*{0,2}Final\s+Score\s*:",
    ],
    name="code-review",
)

RETROSPECTIVE_MARKERS = ReportMarkers(
    start_marker="<!-- RETROSPECTIVE_REPORT_START -->",
    end_marker="<!-- RETROSPECTIVE_REPORT_END -->",
    fallback_patterns=[
        # Epic N Retrospective header
        r"^#\s*Epic\s+\d+\s+Retrospective",
        # Retrospective complete section
        r"^[═✅]+\s*RETROSPECTIVE\s+COMPLETE",
        # Generic retrospective header
        r"^#\s*Retrospective",
    ],
    name="retrospective",
)

SYNTHESIS_MARKERS = ReportMarkers(
    start_marker="<!-- VALIDATION_SYNTHESIS_START -->",
    end_marker="<!-- VALIDATION_SYNTHESIS_END -->",
    fallback_patterns=[
        # Summary header (case insensitive handled by regex flags)
        r"^##\s+\w+\s+Summary",
        # Synthesis header
        r"^#\s*Synthesis",
        # Final verdict
        r"^##\s*Final\s+Verdict",
    ],
    name="validation-synthesis",
)

CODE_REVIEW_SYNTHESIS_MARKERS = ReportMarkers(
    start_marker="<!-- CODE_REVIEW_SYNTHESIS_START -->",
    end_marker="<!-- CODE_REVIEW_SYNTHESIS_END -->",
    fallback_patterns=[
        # Summary header
        r"^##\s+\w+\s+Summary",
        # Synthesis header
        r"^#\s*Synthesis",
        # Changes Applied section
        r"^##\s*Changes\s+Applied",
    ],
    name="code-review-synthesis",
)

HARDENING_PLAN_MARKERS = ReportMarkers(
    start_marker="<!-- HARDENING_PLAN_START -->",
    end_marker="<!-- HARDENING_PLAN_END -->",
    fallback_patterns=[
        # XML start tag
        r"<hardening_plan>",
    ],
    name="hardening-plan",
)


def extract_report(
    raw_output: str,
    markers: ReportMarkers,
    *,
    stop_at_markers: list[str] | None = None,
) -> str:
    r"""Extract report content from LLM output.

    Uses a three-stage extraction strategy:
    1. Primary: Extract content between HTML markers (START/END comments)
    2. Fallback: Try each fallback pattern in order; extract from match to end
       (or to stop_at_markers if provided)
    3. Last Resort: Return entire output stripped

    Args:
        raw_output: Raw LLM output (stdout from provider).
        markers: ReportMarkers configuration with start/end markers and fallbacks.
        stop_at_markers: Optional list of markers that indicate end of report
            content when using fallback extraction. Useful for stopping before
            METRICS_JSON blocks or other trailing content.

    Returns:
        Extracted report content. Never returns empty string - always returns
        at least the stripped original output.

    Example:
        >>> output = '''Thinking...
        ... <!-- VALIDATION_REPORT_START -->
        ... # Story Validation Report
        ... Content here...
        ... <!-- VALIDATION_REPORT_END -->
        ... More thinking...'''
        >>> extract_report(output, VALIDATION_MARKERS)
        '# Story Validation Report\\nContent here...'

    """
    # Stage 1: Try marker-based extraction (PRIMARY - this should work!)
    content = _extract_by_markers(raw_output, markers)
    if content is not None:
        logger.debug(
            "Extracted %s report using markers (%d chars)",
            markers.name,
            len(content),
        )
        return content

    # Stage 2: Fallback to pattern-based extraction
    logger.debug(
        "Markers not found for %s report, trying fallback patterns",
        markers.name,
    )
    content = _extract_by_patterns(raw_output, markers, stop_at_markers)
    if content is not None:
        logger.debug(
            "Extracted %s report using fallback pattern (%d chars)",
            markers.name,
            len(content),
        )
        return content

    # Stage 3: Last resort - return stripped original
    logger.warning(
        "Could not extract structured %s report, using raw content (%d chars)",
        markers.name,
        len(raw_output.strip()),
    )
    return raw_output.strip()


def _extract_by_markers(
    output: str,
    markers: ReportMarkers,
) -> str | None:
    """Extract content between HTML markers.

    Handles edge cases:
    - LLM echoing markers (duplicate start markers)
    - Missing end marker (extract to end)
    - Code block wrappers around content

    Args:
        output: Raw LLM output.
        markers: Marker configuration.

    Returns:
        Extracted content, or None if start marker not found.

    """
    start_idx = output.find(markers.start_marker)
    if start_idx == -1:
        return None

    # Move past the marker and any following newline
    content_start = start_idx + len(markers.start_marker)
    if content_start < len(output) and output[content_start] == "\n":
        content_start += 1

    end_idx = output.find(markers.end_marker, content_start)
    if end_idx == -1:
        # Start marker found but no end marker - extract to end
        logger.warning(
            "%s: Start marker found but end marker missing",
            markers.name,
        )
        content = output[content_start:].strip()
    else:
        # Normal case: extract between markers
        content = output[content_start:end_idx].strip()

    # Remove code block wrappers if present
    content = strip_code_block(content)

    # Handle LLM echoing the start marker (duplicate markers)
    while content.startswith(markers.start_marker):
        content = content[len(markers.start_marker) :].lstrip()

    return content


def _extract_by_patterns(
    output: str,
    markers: ReportMarkers,
    stop_at_markers: list[str] | None = None,
) -> str | None:
    """Extract content using fallback regex patterns.

    Tries each pattern in order. First match wins.
    Extracts from match position to:
    - First stop_at_marker found (if provided)
    - End of output (if no stop markers)

    Args:
        output: Raw LLM output.
        markers: Marker configuration with fallback_patterns.
        stop_at_markers: Optional markers to stop extraction at.

    Returns:
        Extracted content, or None if no pattern matched.

    """
    # Remove code block wrappers before pattern matching
    cleaned = strip_code_block(output)

    for pattern in markers.fallback_patterns:
        match = re.search(pattern, cleaned, re.MULTILINE | re.IGNORECASE)
        if match:
            # Found a match - extract from here
            content = cleaned[match.start() :]

            # Check for stop markers
            if stop_at_markers:
                earliest_stop = len(content)
                for stop_marker in stop_at_markers:
                    stop_idx = content.find(stop_marker)
                    if stop_idx != -1 and stop_idx < earliest_stop:
                        earliest_stop = stop_idx
                content = content[:earliest_stop]

            return content.strip()

    return None


def strip_code_block(text: str) -> str:
    r"""Strip markdown code block wrappers if present.

    Handles:
    - ```markdown\\n...\\n```
    - ```\\n...\\n```
    - Leading/trailing whitespace

    Args:
        text: Text that may be wrapped in code blocks.

    Returns:
        Text with code block wrappers removed.

    """
    stripped = text.strip()

    # Check for code block start
    if stripped.startswith("```"):
        # Find end of first line (language specifier line)
        first_newline = stripped.find("\n")
        if first_newline != -1:
            # Check for closing ```
            if stripped.endswith("```"):
                # Remove opening line and closing ```
                stripped = stripped[first_newline + 1 : -3].strip()
            else:
                # Only opening, no closing - just remove opening line
                stripped = stripped[first_newline + 1 :].strip()

    return stripped
