"""SSE event schemas for dashboard status updates.

Story 22.9: SSE sidebar tree updates.

This module defines Pydantic schemas for SSE events that update the sidebar
tree in real-time during bmad-assist execution.

Event Types:
- workflow_status: Phase transition updates
- story_status: Story status changes
- story_transition: Story start/completion events

All events include base fields: type, timestamp (ISO 8601), run_id, sequence_id.
"""

import logging
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# =============================================================================
# Base Event Schema
# =============================================================================


class DashboardEvent(BaseModel):
    """Base schema for all dashboard SSE events.

    All events share these common fields for correlation and ordering.

    Attributes:
        type: Event type identifier.
        timestamp: ISO 8601 UTC timestamp.
        run_id: Run identifier (format: run-YYYYMMDD-HHMMSS-{uuid8}).
        sequence_id: Monotonic sequence number for ordering.

    """

    type: str
    timestamp: datetime
    run_id: str = Field(..., pattern=r"^run-\d{8}-\d{6}-[a-z0-9]{8}$")
    sequence_id: int = Field(..., ge=1)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: datetime) -> datetime:
        """Ensure timestamp is in UTC and has no timezone info (naive UTC)."""
        if v.tzinfo is not None:
            # Convert to naive UTC (project convention)
            return v.astimezone(UTC).replace(tzinfo=None)
        return v

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, v: str) -> str:
        """Validate run_id format."""
        pattern = r"^run-(\d{8})-(\d{6})-([a-z0-9]{8})$"
        match = re.match(pattern, v)
        if not match:
            raise ValueError(f"run_id must match format run-YYYYMMDD-HHMMSS-{{uuid8}}, got: {v}")
        return v


# =============================================================================
# Workflow Status Event (Phase Transitions)
# =============================================================================


class WorkflowStatusData(BaseModel):
    """Data payload for workflow_status event.

    Emitted when the main loop transitions between phases.

    Attributes:
        current_epic: Current epic number or string ID (e.g., 22 or "testarch").
        current_story: Current story ID (e.g., "22.9" or "testarch.1").
        current_phase: Current workflow phase.
        phase_status: Status of current phase (pending, in-progress, completed, failed).

    """

    current_epic: int | str = Field(...)
    current_story: str = Field(..., pattern=r"^[\w-]+\.[\w]+(?:-[\w]+)*$")
    current_phase: Literal[
        "CREATE_STORY",
        "VALIDATE_STORY",
        "VALIDATE_STORY_SYNTHESIS",
        "ATDD",
        "DEV_STORY",
        "CODE_REVIEW",
        "CODE_REVIEW_SYNTHESIS",
        "TEST_REVIEW",
        "TEA_FRAMEWORK",
        "TEA_CI",
        "TEA_TEST_DESIGN",
        "TEA_AUTOMATE",
        "TRACE",
        "TEA_NFR_ASSESS",
        "RETROSPECTIVE",
        "QA_PLAN_GENERATE",
        "QA_PLAN_EXECUTE",
        "QA_REMEDIATE",
    ]
    phase_status: Literal["pending", "in-progress", "completed", "failed"]


class WorkflowStatusEvent(DashboardEvent):
    """Event emitted on phase transitions.

    AC1: Emitted when main loop transitions between phases with current_phase,
    current_story, sequence_id, timestamp, run_id fields.

    Example:
        {
            "type": "workflow_status",
            "timestamp": "2026-01-15T08:00:00Z",
            "run_id": "run-20260115-080000-a1b2c3d4",
            "sequence_id": 1,
            "data": {
                "current_epic": 22,
                "current_story": "22.9",
                "current_phase": "DEV_STORY",
                "phase_status": "in_progress"
            }
        }

    """

    type: Literal["workflow_status"] = "workflow_status"
    data: WorkflowStatusData


# =============================================================================
# Story Status Event (Story Status Changes)
# =============================================================================


class StoryStatusData(BaseModel):
    """Data payload for story_status event.

    Emitted when a story's status changes.

    Attributes:
        epic_num: Epic number or string ID (e.g., 22 or "testarch").
        story_num: Story number (just the number part).
        story_id: Full story ID (e.g., "22-9-sse-sidebar-tree-updates" or "testarch-1-config").
        status: New story status.
        previous_status: Previous story status (optional).

    """

    epic_num: int | str = Field(...)
    story_num: int | str = Field(...)
    story_id: str = Field(..., pattern=r"^[\w-]+-\d+-[\w-]+$")
    status: Literal["backlog", "ready-for-dev", "in-progress", "review", "done"]
    previous_status: Literal["backlog", "ready-for-dev", "in-progress", "review", "done"] | None = (
        None
    )


class StoryStatusEvent(DashboardEvent):
    """Event emitted when story status changes.

    AC2: Emitted when story transitions from one status to another with story_id,
    epic_num, story_num, status, sequence_id, timestamp, run_id fields.

    Example:
        {
            "type": "story_status",
            "timestamp": "2026-01-15T08:00:00Z",
            "run_id": "run-20260115-080000-a1b2c3d4",
            "sequence_id": 2,
            "data": {
                "epic_num": 22,
                "story_num": 9,
                "story_id": "22-9-sse-sidebar-tree-updates",
                "status": "in-progress",
                "previous_status": "ready-for-dev"
            }
        }

    """

    type: Literal["story_status"] = "story_status"
    data: StoryStatusData


# =============================================================================
# Story Transition Event (Story Start/Completion)
# =============================================================================


class StoryTransitionData(BaseModel):
    """Data payload for story_transition event.

    Emitted when a new story is started or the current story completes.

    Attributes:
        action: Either "started" or "completed".
        epic_num: Epic number or string ID (e.g., 22 or "testarch").
        story_num: Story number (just the number part).
        story_id: Full story ID (e.g., "22-9-sse-sidebar-tree-updates" or "testarch-1-config").
        story_title: Story title (slug).

    """

    action: Literal["started", "completed"]
    epic_num: int | str = Field(...)
    story_num: int | str = Field(...)
    story_id: str = Field(..., pattern=r"^[\w-]+-\d+-[\w-]+$")
    story_title: str = Field(..., min_length=1)


class StoryTransitionEvent(DashboardEvent):
    """Event emitted on story transitions.

    AC3: Emitted when new story starts or current story completes with epic_num,
    story_num, story_id, story_title, action, sequence_id, timestamp, run_id fields.

    Example (started):
        {
            "type": "story_transition",
            "timestamp": "2026-01-15T08:00:00Z",
            "run_id": "run-20260115-080000-a1b2c3d4",
            "sequence_id": 3,
            "data": {
                "action": "started",
                "epic_num": 22,
                "story_num": 9,
                "story_id": "22-9-sse-sidebar-tree-updates",
                "story_title": "sse-sidebar-tree-updates"
            }
        }
    """

    type: Literal["story_transition"] = "story_transition"
    data: StoryTransitionData


# =============================================================================
# Validator Progress Event (Story 22.11)
# =============================================================================


class ValidatorProgressData(BaseModel):
    """Data payload for validator_progress event.

    Emitted when an individual validator completes during Multi-LLM validation.

    Attributes:
        validator_id: Identifier for the validator (e.g., "validator-a", "claude-haiku").
        status: Completion status of the validator.
        duration_ms: Time taken in milliseconds (optional).

    """

    validator_id: str = Field(..., min_length=1)
    status: Literal["completed", "timeout", "failed"]
    duration_ms: int | None = Field(default=None, ge=0)


class ValidatorProgressEvent(DashboardEvent):
    """Event emitted when individual validator completes.

    Story 22.11: Emitted during Multi-LLM validation to track individual
    validator completion without closing the SSE stream.

    Example:
        {
            "type": "validator_progress",
            "timestamp": "2026-01-15T08:00:00Z",
            "run_id": "run-20260115-080000-a1b2c3d4",
            "sequence_id": 5,
            "data": {
                "validator_id": "validator-a",
                "status": "completed",
                "duration_ms": 45000
            }
        }

    """

    type: Literal["validator_progress"] = "validator_progress"
    data: ValidatorProgressData


# =============================================================================
# Phase Complete Event (Story 22.11)
# =============================================================================


class PhaseCompleteData(BaseModel):
    """Data payload for phase_complete event.

    Emitted when a workflow phase completes (e.g., all validators done).

    Attributes:
        phase_name: Name of the completed phase.
        success: Whether the phase completed successfully.
        validator_count: Total number of validators that ran.
        failed_count: Number of validators that failed or timed out.

    """

    phase_name: str = Field(..., min_length=1)
    success: bool
    validator_count: int = Field(..., ge=0)
    failed_count: int = Field(..., ge=0)


class PhaseCompleteEvent(DashboardEvent):
    """Event emitted when workflow phase completes.

    Story 22.11: Emitted after all validators complete to signal
    phase completion with summary statistics.

    Example:
        {
            "type": "phase_complete",
            "timestamp": "2026-01-15T08:00:00Z",
            "run_id": "run-20260115-080000-a1b2c3d4",
            "sequence_id": 10,
            "data": {
                "phase_name": "VALIDATE_STORY",
                "success": true,
                "validator_count": 6,
                "failed_count": 0
            }
        }

    """

    type: Literal["phase_complete"] = "phase_complete"
    data: PhaseCompleteData


# =============================================================================
# Event Factory
# =============================================================================


def create_workflow_status(
    run_id: str,
    sequence_id: int,
    epic_num: int | str,
    story_id: str,
    phase: str,
    phase_status: str,
) -> WorkflowStatusEvent:
    """Create a workflow_status event.

    Args:
        run_id: Run identifier.
        sequence_id: Sequence number.
        epic_num: Current epic number or string ID.
        story_id: Current story ID (e.g., "22.9" or "testarch.1").
        phase: Current phase name.
        phase_status: Phase status.

    Returns:
        WorkflowStatusEvent instance.

    """
    return WorkflowStatusEvent(
        type="workflow_status",
        timestamp=datetime.now(UTC),
        run_id=run_id,
        sequence_id=sequence_id,
        data=WorkflowStatusData(
            current_epic=epic_num,
            current_story=story_id,
            current_phase=phase,  # type: ignore[arg-type]
            phase_status=phase_status,  # type: ignore[arg-type]
        ),
    )


def create_story_status(
    run_id: str,
    sequence_id: int,
    epic_num: int | str,
    story_num: int | str,
    story_id: str,
    status: str,
    previous_status: str | None = None,
) -> StoryStatusEvent:
    """Create a story_status event.

    Args:
        run_id: Run identifier.
        sequence_id: Sequence number.
        epic_num: Epic number or string ID.
        story_num: Story number.
        story_id: Full story ID (e.g., "22-9-sse-sidebar-tree-updates" or "testarch-1-config").
        status: New story status.
        previous_status: Previous story status (optional).

    Returns:
        StoryStatusEvent instance.

    """
    return StoryStatusEvent(
        type="story_status",
        timestamp=datetime.now(UTC),
        run_id=run_id,
        sequence_id=sequence_id,
        data=StoryStatusData(
            epic_num=epic_num,
            story_num=story_num,
            story_id=story_id,
            status=status,  # type: ignore[arg-type]
            previous_status=previous_status,  # type: ignore[arg-type]
        ),
    )


def create_story_transition(
    run_id: str,
    sequence_id: int,
    action: str,
    epic_num: int | str,
    story_num: int | str,
    story_id: str,
    story_title: str,
) -> StoryTransitionEvent:
    """Create a story_transition event.

    Args:
        run_id: Run identifier.
        sequence_id: Sequence number.
        action: Either "started" or "completed".
        epic_num: Epic number or string ID.
        story_num: Story number.
        story_id: Full story ID (e.g., "22-9-sse-sidebar-tree-updates" or "testarch-1-config").
        story_title: Story title.

    Returns:
        StoryTransitionEvent instance.

    """
    return StoryTransitionEvent(
        type="story_transition",
        timestamp=datetime.now(UTC),
        run_id=run_id,
        sequence_id=sequence_id,
        data=StoryTransitionData(
            action=action,  # type: ignore[arg-type]
            epic_num=epic_num,
            story_num=story_num,
            story_id=story_id,
            story_title=story_title,
        ),
    )


def create_validator_progress(
    run_id: str,
    sequence_id: int,
    validator_id: str,
    status: str,
    duration_ms: int | None = None,
) -> ValidatorProgressEvent:
    """Create a validator_progress event.

    Story 22.11: Emitted when individual validator completes during Multi-LLM validation.

    Args:
        run_id: Run identifier.
        sequence_id: Sequence number.
        validator_id: Identifier for the validator.
        status: Completion status (completed, timeout, failed).
        duration_ms: Time taken in milliseconds (optional).

    Returns:
        ValidatorProgressEvent instance.

    """
    return ValidatorProgressEvent(
        type="validator_progress",
        timestamp=datetime.now(UTC),
        run_id=run_id,
        sequence_id=sequence_id,
        data=ValidatorProgressData(
            validator_id=validator_id,
            status=status,  # type: ignore[arg-type]
            duration_ms=duration_ms,
        ),
    )


def create_phase_complete(
    run_id: str,
    sequence_id: int,
    phase_name: str,
    success: bool,
    validator_count: int,
    failed_count: int,
) -> PhaseCompleteEvent:
    """Create a phase_complete event.

    Story 22.11: Emitted when workflow phase completes with summary statistics.

    Args:
        run_id: Run identifier.
        sequence_id: Sequence number.
        phase_name: Name of the completed phase.
        success: Whether the phase completed successfully.
        validator_count: Total number of validators that ran.
        failed_count: Number of validators that failed or timed out.

    Returns:
        PhaseCompleteEvent instance.

    """
    return PhaseCompleteEvent(
        type="phase_complete",
        timestamp=datetime.now(UTC),
        run_id=run_id,
        sequence_id=sequence_id,
        data=PhaseCompleteData(
            phase_name=phase_name,
            success=success,
            validator_count=validator_count,
            failed_count=failed_count,
        ),
    )
