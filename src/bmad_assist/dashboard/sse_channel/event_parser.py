"""DASHBOARD_EVENT parser for subprocess output.

Parses structured events from subprocess stdout that begin with
DASHBOARD_EVENT: prefix and broadcasts them via SSE.

Based on design document: docs/server.md Section 5.3
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Marker prefix for structured events
DASHBOARD_EVENT_PREFIX = "DASHBOARD_EVENT:"

# Pattern to detect log level from line prefix
LOG_LEVEL_PATTERN = re.compile(r"^\[(\w+)\]")


@dataclass
class ParsedEvent:
    """Represents a parsed event from subprocess output.

    Attributes:
        event_type: Type of event (output, phase_changed, etc.).
        data: Event payload dictionary.
        raw_line: Original raw line from stdout.
        is_structured: True if parsed from DASHBOARD_EVENT marker.

    """

    event_type: str
    data: dict[str, Any]
    raw_line: str
    is_structured: bool = False


def parse_log_level(line: str) -> str:
    """Extract log level from line prefix.

    Args:
        line: Log line potentially starting with [LEVEL].

    Returns:
        Log level string (info, warn, error) or "info" as default.

    """
    match = LOG_LEVEL_PATTERN.match(line)
    if match:
        level = match.group(1).lower()
        if level in ("error", "err"):
            return "error"
        if level in ("warning", "warn"):
            return "warn"
        if level == "debug":
            return "debug"
    return "info"


def parse_line(line: str) -> ParsedEvent:
    """Parse a subprocess stdout line into an event.

    Handles two types of lines:
    1. Structured: DASHBOARD_EVENT:{json} → parsed event
    2. Raw output: [LEVEL] message → output event with level

    Args:
        line: Raw line from subprocess stdout.

    Returns:
        ParsedEvent with type and data.

    """
    # Check for structured DASHBOARD_EVENT
    if DASHBOARD_EVENT_PREFIX in line:
        try:
            # Extract JSON after prefix
            idx = line.index(DASHBOARD_EVENT_PREFIX)
            json_str = line[idx + len(DASHBOARD_EVENT_PREFIX) :].strip()
            event_data = json.loads(json_str)

            event_type = event_data.pop("type", "unknown")
            return ParsedEvent(
                event_type=event_type,
                data=event_data,
                raw_line=line,
                is_structured=True,
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse DASHBOARD_EVENT: %s - %s", line[:100], e)
            # Fall through to treat as raw output

    # Parse as raw output line
    level = parse_log_level(line)
    return ParsedEvent(
        event_type="output",
        data={
            "line": line,
            "level": level,
        },
        raw_line=line,
        is_structured=False,
    )


def parse_lines(lines: list[str]) -> list[ParsedEvent]:
    """Parse multiple stdout lines.

    Args:
        lines: List of raw stdout lines.

    Returns:
        List of ParsedEvent instances.

    """
    return [parse_line(line) for line in lines]
