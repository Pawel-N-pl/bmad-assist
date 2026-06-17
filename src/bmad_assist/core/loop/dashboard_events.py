"""Dashboard event broadcasting for main loop.

Story 22.9: SSE sidebar tree updates.
Story 22.10: Pause/resume events.

This module provides functions for emitting dashboard events from the main loop
via stdout markers. The dashboard server parses these markers and broadcasts
SSE events to connected clients.

IPC Protocol:
- Main loop (subprocess) prints DASHBOARD_EVENT:{json_payload} to stdout
- Dashboard server parses stdout for DASHBOARD_EVENT markers
- Validated events are broadcast via SSE broadcaster

Events:
- workflow_status: Phase transitions
- story_status: Story status changes
- story_transition: Story start/completion
- LOOP_PAUSED: Pause entered (Story 22.10)
- LOOP_RESUMED: Pause exited (Story 22.10)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from typing import Literal

from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

# Dashboard event marker prefix
DASHBOARD_EVENT_MARKER = "DASHBOARD_EVENT:"

# =============================================================================
# Event Emission Functions (Main Loop / Subprocess)
# =============================================================================


def _emit_dashboard_event(event_data: dict[str, object]) -> None:
    """Emit a dashboard event via stdout marker.

    This function prints a DASHBOARD_EVENT marker to stdout with JSON payload.
    The dashboard server parses stdout for these markers and broadcasts via SSE.

    Events are only emitted when BMAD_DASHBOARD_MODE=1 environment variable is set.
    This prevents noise in CLI output when running without the dashboard.

    Args:
        event_data: Event data dictionary (will be JSON serialized).

    """
    # Only emit events when running as dashboard subprocess
    if os.environ.get("BMAD_DASHBOARD_MODE") != "1":
        return

    try:
        json_payload = json.dumps(event_data)
        print(f"{DASHBOARD_EVENT_MARKER}{json_payload}")
        sys.stdout.flush()  # Ensure immediate output
    except Exception as e:
        logger.debug("Failed to emit dashboard event (ignored): %s", e)


def emit_workflow_status(
    run_id: str,
    sequence_id: int,
    epic_num: EpicId,
    story_id: str,
    phase: str,
    phase_status: Literal["pending", "in-progress", "completed", "failed"],
) -> None:
    """Emit workflow_status event on phase transitions.

    AC1: SSE event emitted when main loop transitions between phases with
    current_phase, current_story, sequence_id, timestamp, run_id fields.

    Args:
        run_id: Run identifier.
        sequence_id: Monotonic sequence number.
        epic_num: Current epic number (supports string epics like "testarch").
        story_id: Current story ID (e.g., "22.9").
        phase: Current phase name (e.g., "DEV_STORY").
        phase_status: Phase status.

    Example output:
        DASHBOARD_EVENT:{"type":"workflow_status","timestamp":"2026-01-15T08:00:00Z",...}

    """
    now = datetime.now(UTC)
    data: dict[str, object] = {
        "current_epic": epic_num,
        "current_story": story_id,
        "current_phase": phase,
        "phase_status": phase_status,
    }
    # Include phase_started_at for in-progress phases (dashboard elapsed time display)
    if phase_status == "in-progress":
        data["phase_started_at"] = now.isoformat()

    event_data = {
        "type": "workflow_status",
        "timestamp": now.isoformat(),
        "run_id": run_id,
        "sequence_id": sequence_id,
        "data": data,
    }
    _emit_dashboard_event(event_data)


def emit_story_status(
    run_id: str,
    sequence_id: int,
    epic_num: EpicId,
    story_num: int | str,
    story_id: str,
    status: Literal["backlog", "ready-for-dev", "in-progress", "review", "done"],
    previous_status: (
        Literal["backlog", "ready-for-dev", "in-progress", "review", "done"] | None
    ) = None,
) -> None:
    """Emit story_status event on story status changes.

    AC2: SSE event emitted when story status changes with story_id, epic_num,
    story_num, status, sequence_id, timestamp, run_id fields.

    Args:
        run_id: Run identifier.
        sequence_id: Monotonic sequence number.
        epic_num: Epic number (supports string epics like "testarch").
        story_num: Story number.
        story_id: Full story ID (e.g., "22-9-sse-sidebar-tree-updates").
        status: New story status.
        previous_status: Previous story status (optional).

    """
    event_data = {
        "type": "story_status",
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "sequence_id": sequence_id,
        "data": {
            "epic_num": epic_num,
            "story_num": story_num,
            "story_id": story_id,
            "status": status,
            "previous_status": previous_status,
        },
    }
    _emit_dashboard_event(event_data)


def emit_story_transition(
    run_id: str,
    sequence_id: int,
    action: Literal["started", "completed"],
    epic_num: EpicId,
    story_num: int | str,
    story_id: str,
    story_title: str,
) -> None:
    """Emit story_transition event on story start/completion.

    AC3: SSE event emitted when new story starts or current story completes
    with epic_num, story_num, story_id, story_title, action, sequence_id,
    timestamp, run_id fields.

    Args:
        run_id: Run identifier.
        sequence_id: Monotonic sequence number.
        action: Either "started" or "completed".
        epic_num: Epic number (supports string epics like "testarch").
        story_num: Story number.
        story_id: Full story ID (e.g., "22-9-sse-sidebar-tree-updates").
        story_title: Story title (slug).

    """
    event_data = {
        "type": "story_transition",
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "sequence_id": sequence_id,
        "data": {
            "action": action,
            "epic_num": epic_num,
            "story_num": story_num,
            "story_id": story_id,
            "story_title": story_title,
        },
    }
    _emit_dashboard_event(event_data)


# =============================================================================
# Run ID Generation
# =============================================================================


def generate_run_id() -> str:
    """Generate a unique run_id.

    Format: run-YYYYMMDD-HHMMSS-{uuid8}

    Returns:
        Run ID string.

    """
    import uuid

    now = datetime.now(UTC)
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    uuid_suffix = str(uuid.uuid4())[:8]
    return f"run-{timestamp}-{uuid_suffix}"


# =============================================================================
# Story ID Parsing Helpers
# =============================================================================


def parse_story_id(story_id: str) -> tuple[EpicId, int]:
    """Parse story ID into epic_num and story_num.

    Supports both numeric and string epic IDs (e.g., "22.9" or "testarch.1").

    Args:
        story_id: Story ID in format "epic.story" (e.g., "22.9" or "testarch.1").

    Returns:
        Tuple of (epic_num, story_num) where epic_num can be int or str.

    Raises:
        ValueError: If story_id format is invalid.

    Examples:
        >>> parse_story_id("22.9")
        (22, 9)
        >>> parse_story_id("testarch.1")
        ('testarch', 1)

    """
    parts = story_id.split(".")
    if len(parts) != 2:
        raise ValueError(f"Invalid story_id format: {story_id} (expected 'epic.story')")

    # Parse story_num (must be numeric)
    try:
        story_num = int(parts[1])
    except ValueError as e:
        raise ValueError(f"Invalid story_id format: {story_id} (story_num must be numeric)") from e

    # Parse epic_num (can be int or str)
    epic_num: EpicId
    try:
        epic_num = int(parts[0])
    except ValueError:
        # String epic ID (e.g., "testarch")
        epic_num = parts[0]

    return epic_num, story_num


def story_id_from_parts(epic_num: EpicId, story_num: int, title: str) -> str:
    """Generate story_id from epic_num, story_num, and title.

    Args:
        epic_num: Epic number or string ID (e.g., 22 or "testarch").
        story_num: Story number.
        title: Story title (will be slugified).

    Returns:
        Story ID in format "epic-story-title-slug".

    Examples:
        >>> story_id_from_parts(22, 9, "SSE Sidebar Tree Updates")
        '22-9-sse-sidebar-tree-updates'
        >>> story_id_from_parts("testarch", 1, "Config Schema")
        'testarch-1-config-schema'

    """
    # Slugify title: lowercase, replace spaces/hyphens with single hyphen
    slug = title.lower().strip()
    # Replace spaces and underscores with hyphens
    slug = re.sub(r"[\s_]+", "-", slug)
    # Remove non-alphanumeric characters (except hyphens)
    slug = re.sub(r"[^a-z0-9-]+", "", slug)
    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)
    # Strip leading/trailing hyphens
    slug = slug.strip("-")

    return f"{epic_num}-{story_num}-{slug}"


# =============================================================================
# Story 22.10: Pause/Resume events
# =============================================================================


def emit_loop_paused(
    run_id: str,
    sequence_id: int,
    current_phase: str | None,
) -> None:
    """Emit LOOP_PAUSED event when main loop enters pause wait loop (Story 22.10).

    This event signals to the dashboard that the loop is now paused and waiting
    for resume. The frontend will display the "Paused" status and show the
    Resume button.

    Args:
        run_id: Run identifier.
        sequence_id: Monotonic sequence number.
        current_phase: Current phase name (e.g., "DEV_STORY") when paused.

    Example output:
        DASHBOARD_EVENT:{"type":"LOOP_PAUSED","timestamp":"2026-01-15T08:00:00Z",...}

    """
    event_data = {
        "type": "LOOP_PAUSED",
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "sequence_id": sequence_id,
        "data": {
            "current_phase": current_phase,
        },
    }
    _emit_dashboard_event(event_data)


def emit_loop_resumed(
    run_id: str,
    sequence_id: int,
) -> None:
    """Emit LOOP_RESUMED event when main loop exits pause wait loop (Story 22.10).

    This event signals to the dashboard that the loop has resumed from pause.
    The frontend will hide the "Paused" status and Resume button, and show the
    Pause button again.

    Args:
        run_id: Run identifier.
        sequence_id: Monotonic sequence number.

    Example output:
        DASHBOARD_EVENT:{"type":"LOOP_RESUMED","timestamp":"2026-01-15T08:00:00Z",...}

    """
    event_data = {
        "type": "LOOP_RESUMED",
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "sequence_id": sequence_id,
        "data": {},
    }
    _emit_dashboard_event(event_data)


# =============================================================================
# Story 22.11: Validator progress and phase complete events
# =============================================================================


def emit_validator_progress(
    run_id: str,
    sequence_id: int,
    validator_id: str,
    status: Literal["completed", "timeout", "failed"],
    duration_ms: int | None = None,
) -> None:
    """Emit validator_progress event when individual validator completes (Story 22.11).

    This event is emitted during Multi-LLM validation to track individual
    validator completion without closing the SSE stream. The frontend can use
    this to update a progress indicator.

    Args:
        run_id: Run identifier.
        sequence_id: Monotonic sequence number.
        validator_id: Identifier for the validator (e.g., "validator-a", "claude-haiku").
        status: Completion status (completed, timeout, failed).
        duration_ms: Time taken in milliseconds (optional).

    Example output:
        DASHBOARD_EVENT:{"type":"validator_progress","timestamp":"2026-01-15T08:00:00Z",...}

    """
    event_data = {
        "type": "validator_progress",
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "sequence_id": sequence_id,
        "data": {
            "validator_id": validator_id,
            "status": status,
            "duration_ms": duration_ms,
        },
    }
    _emit_dashboard_event(event_data)


def emit_phase_complete(
    run_id: str,
    sequence_id: int,
    phase_name: str,
    success: bool,
    validator_count: int,
    failed_count: int,
) -> None:
    """Emit phase_complete event when workflow phase completes (Story 22.11).

    This event is emitted after all validators complete to signal phase
    completion with summary statistics. The frontend can use this to update
    the terminal status and phase status in the sidebar.

    Args:
        run_id: Run identifier.
        sequence_id: Monotonic sequence number.
        phase_name: Name of the completed phase (e.g., "VALIDATE_STORY").
        success: Whether the phase completed successfully.
        validator_count: Total number of validators that ran.
        failed_count: Number of validators that failed or timed out.

    Example output:
        DASHBOARD_EVENT:{"type":"phase_complete","timestamp":"2026-01-15T08:00:00Z",...}

    """
    event_data = {
        "type": "phase_complete",
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "sequence_id": sequence_id,
        "data": {
            "phase_name": phase_name,
            "success": success,
            "validator_count": validator_count,
            "failed_count": failed_count,
        },
    }
    _emit_dashboard_event(event_data)


# =============================================================================
# Security Review Agent Events
# =============================================================================


def emit_security_review_started(
    run_id: str,
    sequence_id: int,
) -> None:
    """Emit security_review_started when security agent task is created.

    Args:
        run_id: Run identifier.
        sequence_id: Monotonic sequence number.

    """
    event_data = {
        "type": "security_review_started",
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "sequence_id": sequence_id,
        "data": {},
    }
    _emit_dashboard_event(event_data)


def emit_security_review_completed(
    run_id: str,
    sequence_id: int,
    finding_count: int,
    severity_summary: dict[str, int],
    timed_out: bool = False,
) -> None:
    """Emit security_review_completed when security agent finishes.

    Args:
        run_id: Run identifier.
        sequence_id: Monotonic sequence number.
        finding_count: Total number of findings.
        severity_summary: Counts by severity (e.g., {"HIGH": 2, "MEDIUM": 3}).
        timed_out: Whether the review timed out (partial results).

    """
    event_data = {
        "type": "security_review_completed",
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "sequence_id": sequence_id,
        "data": {
            "finding_count": finding_count,
            "severity_summary": severity_summary,
            "timed_out": timed_out,
        },
    }
    _emit_dashboard_event(event_data)


def emit_security_review_failed(
    run_id: str,
    sequence_id: int,
    error: str,
) -> None:
    """Emit security_review_failed when security agent errors out.

    Args:
        run_id: Run identifier.
        sequence_id: Monotonic sequence number.
        error: Error description.

    """
    event_data = {
        "type": "security_review_failed",
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "sequence_id": sequence_id,
        "data": {
            "error": error,
        },
    }
    _emit_dashboard_event(event_data)


# =============================================================================
# Model Invocation Tracking
# =============================================================================

# Model started marker - separate from DASHBOARD_EVENT for cleaner parsing
MODEL_STARTED_MARKER = "MODEL_STARTED:"

# Counter for generating unique tab IDs per model
_model_invocation_counters: dict[str, int] = {}


def emit_model_started(
    model: str,
    role: str | None = None,
    provider: str | None = None,
) -> str | None:
    """Emit model_started event when a model invocation begins.

    This creates a new tab in the dashboard terminal for this model invocation.
    The tab ID is returned so it can be associated with output.

    Args:
        model: Model identifier (e.g., "opus", "glm-4.7", "gemini-2.5-flash-lite").
        role: Optional role descriptor (e.g., "master", "helper", "validator-1").
        provider: Optional provider name (e.g., "claude", "gemini", "glm").

    Returns:
        Tab ID string (e.g., "opus-1", "glm-4.7-2") or None if not in dashboard mode.

    Example output:
        MODEL_STARTED:{"model":"opus","role":"master","tab_id":"opus-1","provider":"claude"}

    """
    # Only emit when running as dashboard subprocess
    if os.environ.get("BMAD_DASHBOARD_MODE") != "1":
        return None

    # Generate unique tab ID for this model
    global _model_invocation_counters
    if model not in _model_invocation_counters:
        _model_invocation_counters[model] = 0
    _model_invocation_counters[model] += 1
    count = _model_invocation_counters[model]
    tab_id = f"{model}-{count}"

    try:
        payload = {
            "model": model,
            "tab_id": tab_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if role:
            payload["role"] = role
        if provider:
            payload["provider"] = provider

        json_payload = json.dumps(payload)
        print(f"{MODEL_STARTED_MARKER}{json_payload}")
        sys.stdout.flush()

        logger.debug("Emitted model_started: model=%s, tab_id=%s, role=%s", model, tab_id, role)
        return tab_id

    except Exception as e:
        logger.debug("Failed to emit model_started (ignored): %s", e)
        return None


def reset_model_counters() -> None:
    """Reset model invocation counters (called at loop start)."""
    global _model_invocation_counters
    _model_invocation_counters = {}


# =============================================================================
# Re-export for convenience
# =============================================================================


__all__ = [
    # Marker constants
    "DASHBOARD_EVENT_MARKER",
    "MODEL_STARTED_MARKER",
    # Run ID generation
    "generate_run_id",
    # Story ID parsing
    "parse_story_id",
    "story_id_from_parts",
    # Event emission
    "emit_workflow_status",
    "emit_story_status",
    "emit_story_transition",
    # Story 22.10: Pause/resume events
    "emit_loop_paused",
    "emit_loop_resumed",
    # Story 22.11: Validator progress and phase complete events
    "emit_validator_progress",
    "emit_phase_complete",
    # Security review agent events
    "emit_security_review_started",
    "emit_security_review_completed",
    "emit_security_review_failed",
    # Model invocation tracking
    "emit_model_started",
    "reset_model_counters",
]
