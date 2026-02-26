"""Notification message formatter for compact, information-dense messages.

This module provides the central formatting logic for notifications,
converting event types and payloads into the Epic 21 format specification.

Format specification:
    Success: "{icon} {label} ✓ {story} {story_time}/{total_time}"
    Failure: "{icon} {label} {story} {story_time}/{total_time}"
             "→ {error_message}"

Example:
    >>> from bmad_assist.notifications.formatter import format_notification
    >>> from bmad_assist.notifications.events import EventType, StoryCompletedPayload
    >>> payload = StoryCompletedPayload(
    ...     project="bmad-assist", epic=12, story="Status codes",
    ...     duration_ms=180_000, outcome="success"
    ... )
    >>> format_notification(EventType.STORY_COMPLETED, payload)
    '📝 Create ✓ 12.Status codes 3m'

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .events import (
    AnomalyDetectedPayload,
    CLICrashedPayload,
    ErrorOccurredPayload,
    EventPayload,
    EventType,
    FatalErrorPayload,
    QueueBlockedPayload,
    StoryCompletedPayload,
    TimeoutWarningPayload,
    get_signal_name,
    is_high_priority,
)
from .time_format import format_duration
from .workflow_labels import get_workflow_icon, get_workflow_label

if TYPE_CHECKING:
    from bmad_assist.core.state import Phase

logger = logging.getLogger(__name__)

__all__ = ["format_notification"]

# Maximum length for error message line (excluding "→ " prefix)
MAX_ERROR_LENGTH = 80

# Status icons for different outcomes
STATUS_ICONS: dict[str, str] = {
    "success": "✓",
    "failed": "❌",
    "review_issues": "⚠️",
    # Infrastructure icons (Story 21.4)
    "timeout_warning": "⚡",
    "cli_recovered": "🔄",
    "cli_crashed": "💀",
    "fatal": "☠️",
    # Completion icons (Story standalone-03)
    "epic_completed": "🎉",
    "project_completed": "🏆",
}

# Default icon for high-priority events
HIGH_PRIORITY_ICON = "❌"

# Success checkmark
SUCCESS_ICON = "✓"

# Epic setup and teardown phases that show ONLY epic number, no story
EPIC_LEVEL_PHASES = frozenset({
    "tea_framework",
    "tea_ci",
    "tea_test_design",
    "tea_automate",
    "trace",
    "tea_nfr_assess",
    "retrospective",
    "hardening",
    "qa_plan_generate",
    "qa_plan_execute",
    "qa_remediate",
})



def _truncate_message(text: str, max_len: int = MAX_ERROR_LENGTH) -> str:
    """Truncate message to max length, preserving Unicode.

    Args:
        text: Message to truncate.
        max_len: Maximum length (default 80).

    Returns:
        Truncated message with "..." if over limit.

    Examples:
        >>> _truncate_message("short message")
        'short message'
        >>> _truncate_message("a" * 100)
        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa...'
        >>> _truncate_message("exact 80" + "x" * 72)  # exactly 80 chars
        'exact 80xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx...'

    """
    if len(text) <= max_len:
        return text
    # Leave room for "..." suffix (3 chars)
    return text[: max_len - 3] + "..."


def _sanitize_error_message(message: str) -> str:
    """Sanitize error message for notification display.

    Replace newlines with " | " to maintain single-line format.

    Args:
        message: Raw error message (may contain newlines).

    Returns:
        Sanitized message with newlines replaced.

    """
    return message.replace("\n", " | ").replace("\r", "").strip()


def _phase_to_workflow_name(phase: str | Phase) -> str:
    """Convert Phase enum value to workflow name.

    Args:
        phase: Phase value or enum (e.g., Phase.CREATE_STORY or "create_story").

    Returns:
        Workflow name (kebab-case, e.g., "create-story").

    Examples:
        >>> _phase_to_workflow_name("CREATE_STORY")
        'create-story'
        >>> _phase_to_workflow_name("validate_story")
        'validate-story'

    """
    # Handle Phase enum
    if hasattr(phase, "value"):
        phase = phase.value
    return str(phase).lower().replace("_", "-")


def _get_status_icon(event: EventType, payload: EventPayload) -> str:
    """Determine status icon based on event and payload.

    Args:
        event: Event type being processed.
        payload: Event payload with outcome details.

    Returns:
        Status icon string (emoji or checkmark).

    """
    if event == EventType.STORY_COMPLETED:
        if isinstance(payload, StoryCompletedPayload):
            outcome = payload.outcome
            # Check for review issues format (pipe-delimited)
            if "|" in outcome:
                parts = outcome.split("|")
                if parts[0] == "review_issues":
                    return STATUS_ICONS.get("review_issues", "⚠️")
            return STATUS_ICONS.get(outcome, HIGH_PRIORITY_ICON)
    # Completion events (Story standalone-03 AC6/AC7)
    elif event == EventType.EPIC_COMPLETED:
        return STATUS_ICONS["epic_completed"]
    elif event == EventType.PROJECT_COMPLETED:
        return STATUS_ICONS["project_completed"]
    # Infrastructure events (Story 21.4)
    elif event == EventType.TIMEOUT_WARNING:
        return STATUS_ICONS["timeout_warning"]
    elif event == EventType.CLI_CRASHED:
        if isinstance(payload, CLICrashedPayload):
            return (
                STATUS_ICONS["cli_recovered"] if payload.recovered else STATUS_ICONS["cli_crashed"]
            )
        return STATUS_ICONS["cli_crashed"]
    elif event == EventType.CLI_RECOVERED:
        return STATUS_ICONS["cli_recovered"]
    elif event == EventType.FATAL_ERROR:
        return STATUS_ICONS["fatal"]
    elif is_high_priority(event):
        return HIGH_PRIORITY_ICON
    elif event == EventType.PHASE_COMPLETED:
        return SUCCESS_ICON
    # STORY_STARTED has no status icon (no checkmark - story just beginning)
    return ""


def _parse_story_title(story_key: str) -> str | None:
    """Extract human-readable title from story key.

    Story keys can be in formats like:
    - "3" (just story number)
    - "19.3" (epic.story)
    - "19-3-add-cool-feature" (epic-story-title with dashes)
    - "testarch-1-setup-framework" (string epic with dashes)

    Args:
        story_key: Story identifier string.

    Returns:
        Extracted title with spaces, or None if no title found.

    """
    if not story_key:
        return None

    # Try to parse story key format: "19-3-add-cool-feature"
    # or "testarch-1-setup-framework"
    parts = story_key.split("-")
    if len(parts) > 2:
        # Skip prefix parts that look like epic-story (numeric or known patterns)
        # Find first non-numeric, non-single-char part as title start
        title_start = 0
        for i, part in enumerate(parts):
            # Skip numeric parts and short alphanumeric parts (likely epic/story IDs)
            if part.isdigit() or (len(part) <= 2 and part.isalnum()):
                title_start = i + 1
                continue
            # If this part looks like an ID (all lowercase, short), skip
            if i < 2 and len(part) <= 10 and part.isalnum():
                title_start = i + 1
                continue
            break

        if title_start < len(parts):
            title_parts = parts[title_start:]
            if title_parts:
                return " ".join(title_parts)

    return None


def _extract_story_id(payload: EventPayload) -> str:
    """Extract story ID string from payload.

    Handles various story key formats and both numeric and string epic IDs:
    - epic=19, story="3" -> "19.3"
    - epic=19, story="19.3" -> "19.3" (no duplication)
    - epic=19, story="19-3-add-feature" -> "19.3 add feature"
    - epic="testarch", story="testarch-1-setup" -> "testarch.1 setup"

    Args:
        payload: Event payload containing epic and story info.

    Returns:
        Formatted story ID (e.g., "12.4" or "testarch.1 setup").

    Note:
        Epic ID of 0 is valid - we use explicit None checks.
        Epic ID can be int or str (e.g., "testarch").

    """
    epic = getattr(payload, "epic", None)
    story = getattr(payload, "story", None)

    if not story:
        if epic is not None and epic != "":
            return str(epic)
        return "Unknown"

    story_str = str(story)
    epic_str = str(epic) if epic is not None and epic != "" else ""

    # Determine story number portion
    story_num = story_str
    if epic_str:
        # Handle "19.3" or "testarch.1" format - already has epic with dot
        if story_str.startswith(f"{epic_str}."):
            story_num = story_str
        # Handle "19-3-title" or "testarch-1-title" format
        elif story_str.startswith(f"{epic_str}-"):
            rest = story_str[len(epic_str) + 1 :]  # "3-add-feature" or "1-setup"
            parts = rest.split("-", 1)
            # First part after epic is the story number
            story_num = f"{epic_str}.{parts[0]}"
        # Check if story is just the story number (no epic prefix)
        elif not story_str.startswith(epic_str):
            story_num = f"{epic_str}.{story_str}"
        else:
            # Story starts with epic but no separator - ambiguous, use as-is
            story_num = f"{epic_str}.{story_str}"

    # Try to extract title from story key
    title = _parse_story_title(story_str)
    if title:
        return f"{story_num} {title}"

    return story_num


def _format_header(event: EventType, payload: EventPayload) -> str:
    """Format the header line of the notification.

    Args:
        event: Event type being processed.
        payload: Event payload with details.

    Returns:
        Formatted header line (first line of notification).

    """
    if payload is None:
        logger.warning("format_notification called with None payload")
        return "⚠️ Unknown Unknown"

    # Handle completion events specially (Story standalone-03 AC6/AC7)
    if event == EventType.EPIC_COMPLETED:
        return _format_epic_completed_header(payload)
    if event == EventType.PROJECT_COMPLETED:
        return _format_project_completed_header(payload)

    # Determine workflow name from phase
    phase = getattr(payload, "phase", None)
    # Fallback for events without phase: use event type as workflow hint
    workflow_name = _phase_to_workflow_name(phase) if phase else event.value.replace("_", "-")

    # Get icon and label from workflow labels system
    icon = get_workflow_icon(workflow_name)
    label = get_workflow_label(workflow_name)

    # Get status icon
    status = _get_status_icon(event, payload)

    # Story standalone-03 AC5: Epic-level phases show ONLY epic number, no story
    # Check if this is an epic setup or teardown phase
    phase_str = str(phase).lower() if phase else ""
    if phase_str in EPIC_LEVEL_PHASES or workflow_name in EPIC_LEVEL_PHASES:
        epic = getattr(payload, "epic", "Unknown")
        story_id = str(epic)  # Epic only, no story number
    else:
        # Get story ID (normal case)
        story_id = _extract_story_id(payload)

    # Get timing
    duration_ms = getattr(payload, "duration_ms", None)
    time_str = ""
    if duration_ms is not None:
        time_str = f" ({format_duration(duration_ms)})"

    # Build header: "{story} {icon} {label} {status} ({duration})"
    # Example: "22.7 ✏️ Create ✓ (2m 14s)"
    if status == SUCCESS_ICON:
        header = f"{story_id} {icon} {label} {status}{time_str}"
    elif status:
        # For failures, status icon after label
        header = f"{story_id} {icon} {label} {status}{time_str}"
    else:
        header = f"{story_id} {icon} {label}{time_str}"

    # STORY_STARTED: add story title on second line
    if event == EventType.STORY_STARTED:
        story_title = getattr(payload, "story_title", None)
        if story_title:
            header = f"{header}\n{story_title}"

    return header


def _format_epic_completed_header(payload: EventPayload) -> str:
    """Format header for EPIC_COMPLETED event (Story standalone-03 AC6).

    Format: "🎉 Epic {epic_id} Complete ({stories} stories, {duration})"

    Args:
        payload: EpicCompletedPayload with epic details.

    Returns:
        Formatted epic completion header.

    """
    epic = getattr(payload, "epic", "Unknown")
    duration_ms = getattr(payload, "duration_ms", 0)
    stories_completed = getattr(payload, "stories_completed", 0)

    time_str = format_duration(duration_ms) if duration_ms else "0s"
    stories_word = "story" if stories_completed == 1 else "stories"

    return f"🎉 Epic {epic} Complete ({stories_completed} {stories_word}, {time_str})"


def _format_project_completed_header(payload: EventPayload) -> str:
    """Format header for PROJECT_COMPLETED event (Story standalone-03 AC7).

    Format: "🏆 Project Complete ({epics} epics, {stories} stories, {duration})"

    Args:
        payload: ProjectCompletedPayload with project details.

    Returns:
        Formatted project completion header.

    """
    duration_ms = getattr(payload, "duration_ms", 0)
    epics_completed = getattr(payload, "epics_completed", 0)
    stories_completed = getattr(payload, "stories_completed", 0)

    time_str = format_duration(duration_ms) if duration_ms else "0s"
    epics_word = "epic" if epics_completed == 1 else "epics"
    stories_word = "story" if stories_completed == 1 else "stories"

    return (
        f"🏆 Project Complete "
        f"({epics_completed} {epics_word}, {stories_completed} {stories_word}, {time_str})"
    )


def _extract_error_message(event: EventType, payload: EventPayload) -> str | None:
    """Extract error message from payload based on event type.

    Args:
        event: Event type being processed.
        payload: Event payload.

    Returns:
        Error message string, or None if no error.

    """
    if isinstance(payload, StoryCompletedPayload):
        outcome = payload.outcome
        if outcome == "success":
            return None
        # Check for review issues format
        if "|" in outcome:
            parts = outcome.split("|")
            if parts[0] == "review_issues" and len(parts) > 1:
                # Filter out empty strings from issues list
                issues = [p.strip() for p in parts[1:] if p.strip()]
                count = len(issues)
                if count == 0:
                    return None  # No actual issues
                # Singular/plural grammar
                issue_word = "issue" if count == 1 else "issues"
                # Limit display to 5 issues
                if count > 5:
                    displayed = issues[:5]
                    issue_list = ", ".join(displayed)
                    return f"{count} {issue_word}: {issue_list} (+{count - 5} more)"
                else:
                    issue_list = ", ".join(issues)
                    return f"{count} {issue_word}: {issue_list}"
        # Plain failure - return outcome as error message
        return outcome if outcome != "failed" else None

    if isinstance(payload, ErrorOccurredPayload):
        return payload.message

    if isinstance(payload, AnomalyDetectedPayload):
        return payload.context

    if isinstance(payload, QueueBlockedPayload):
        return payload.reason

    # Infrastructure event payloads (Story 21.4)
    if isinstance(payload, TimeoutWarningPayload):
        remaining = format_duration(payload.remaining_ms)
        limit = format_duration(payload.limit_ms)
        return f"{payload.tool_name}: {remaining} until timeout (limit: {limit})"

    if isinstance(payload, CLICrashedPayload):
        if payload.recovered:
            return (
                f"{payload.tool_name} crashed, resumed ({payload.attempt}/{payload.max_attempts})"
            )
        else:
            # Determine failure reason: signal name, exit code, or unknown
            if payload.signal is not None:
                reason = get_signal_name(payload.signal) or f"signal {payload.signal}"
            elif payload.exit_code is not None:
                reason = f"exit {payload.exit_code}"
            else:
                reason = "unknown"
            return (
                f"{payload.tool_name}: {payload.attempt}/{payload.max_attempts} failed ({reason})"
            )

    if isinstance(payload, FatalErrorPayload):
        return f"bmad-assist: {payload.exception_type} in {payload.location}"

    # Check for generic message attribute
    message = getattr(payload, "message", None)
    if message:
        return str(message)

    return None


def _format_error_line(event: EventType, payload: EventPayload) -> str | None:
    """Format the error line of the notification (second line).

    Args:
        event: Event type being processed.
        payload: Event payload.

    Returns:
        Formatted error line with "→ " prefix, or None if no error.

    """
    error_msg = _extract_error_message(event, payload)
    if not error_msg:
        return None

    # Sanitize (replace newlines)
    sanitized = _sanitize_error_message(error_msg)

    # Truncate if needed
    truncated = _truncate_message(sanitized, MAX_ERROR_LENGTH)

    return f"→ {truncated}"


def format_notification(event: EventType, payload: EventPayload) -> str:
    """Format notification message according to Epic 21 spec.

    Formats notifications with compact, information-dense messages showing
    workflow icon, label, status, story ID, and timing.

    Format specification:
        Success: "{icon} {label} ✓ {story} {story_time}"
        Failure: "{icon} {label} {story} {story_time}"
                 "→ {error_message}"

    Args:
        event: Event type being sent.
        payload: Event payload with details.

    Returns:
        Formatted notification string (may be multi-line for failures).

    Examples:
        >>> # Success case
        >>> payload = StoryCompletedPayload(
        ...     project="proj", epic=12, story="Status codes",
        ...     duration_ms=180_000, outcome="success"
        ... )
        >>> format_notification(EventType.STORY_COMPLETED, payload)
        '📝 ... ✓ 12.Status codes 3m'

        >>> # Failure case
        >>> payload = StoryCompletedPayload(
        ...     project="proj", epic=12, story="Status codes",
        ...     duration_ms=180_000, outcome="Missing tests"
        ... )
        >>> result = format_notification(EventType.STORY_COMPLETED, payload)
        >>> '→' in result
        True

    """
    # Build header line
    header = _format_header(event, payload)

    # Build error line (if applicable)
    error_line = _format_error_line(event, payload)

    # Combine
    if error_line:
        return f"{header}\n{error_line}"
    return header
