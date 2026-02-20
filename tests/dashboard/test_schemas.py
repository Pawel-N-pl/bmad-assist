"""Tests for dashboard SSE event schemas.

Story 22.9: SSE sidebar tree updates - Task 6 (tests).

"""

import pytest
from pydantic import ValidationError

from bmad_assist.core.loop.dashboard_events import generate_run_id
from bmad_assist.dashboard.schemas import (
    StoryStatusData,
    StoryStatusEvent,
    StoryTransitionData,
    StoryTransitionEvent,
    WorkflowStatusData,
    WorkflowStatusEvent,
    create_story_status,
    create_story_transition,
    create_workflow_status,
)


class TestGenerateRunId:
    """Tests for generate_run_id function."""

    def test_generate_run_id_format(self) -> None:
        """Test that generated run_id matches required format."""
        run_id = generate_run_id()
        assert isinstance(run_id, str)

        # Should match pattern: run-YYYYMMDD-HHMMSS-{uuid8}
        import re

        pattern = r"^run-(\d{8})-(\d{6})-([a-z0-9]{8})$"
        match = re.match(pattern, run_id)
        assert match is not None, f"run_id {run_id} doesn't match pattern {pattern}"

    def test_generate_run_id_unique(self) -> None:
        """Test that each generated run_id is unique."""
        run_ids = [generate_run_id() for _ in range(100)]
        assert len(set(run_ids)) == 100, "Generated run_ids are not unique"


class TestWorkflowStatusEvent:
    """Tests for WorkflowStatusEvent schema."""

    def test_valid_workflow_status_event(self) -> None:
        """Test creating a valid workflow_status event."""
        event = WorkflowStatusEvent(
            type="workflow_status",
            timestamp="2026-01-15T08:00:00",
            run_id="run-20260115-080000-a1b2c3d4",
            sequence_id=1,
            data=WorkflowStatusData(
                current_epic=22,
                current_story="22.9",
                current_phase="DEV_STORY",
                phase_status="in-progress",
            ),
        )
        assert event.type == "workflow_status"
        assert event.data.current_epic == 22
        assert event.data.current_phase == "DEV_STORY"

    def test_workflow_status_missing_required_field(self) -> None:
        """Test that missing required fields raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowStatusEvent(
                type="workflow_status",
                timestamp="2026-01-15T08:00:00",
                run_id="run-20260115-080000-a1b2c3d4",
                sequence_id=1,
                # Missing 'data' field
            )  # type: ignore

        errors = exc_info.value.errors()
        assert any(err["loc"][0] == "data" for err in errors)

    def test_workflow_status_invalid_run_id_format(self) -> None:
        """Test that invalid run_id format raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowStatusEvent(
                type="workflow_status",
                timestamp="2026-01-15T08:00:00",
                run_id="invalid-run-id",  # Invalid format
                sequence_id=1,
                data=WorkflowStatusData(
                    current_epic=22,
                    current_story="22.9",
                    current_phase="DEV_STORY",
                    phase_status="in-progress",
                ),
            )

        errors = exc_info.value.errors()
        assert any(err["loc"][0] == "run_id" for err in errors)

    def test_workflow_status_invalid_phase(self) -> None:
        """Test that invalid phase name raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowStatusEvent(
                type="workflow_status",
                timestamp="2026-01-15T08:00:00",
                run_id="run-20260115-080000-a1b2c3d4",
                sequence_id=1,
                data=WorkflowStatusData(
                    current_epic=22,
                    current_story="22.9",
                    current_phase="INVALID_PHASE",  # Invalid phase
                    phase_status="in-progress",
                ),
            )

        errors = exc_info.value.errors()
        # Note: When WorkflowStatusData validates before event creation,
        # the error location is ('current_phase',) not ('data', 'current_phase')
        assert any(
            err["loc"] == ("current_phase",)
            or (err["loc"][0] == "data" and err["loc"][1] == "current_phase")
            for err in errors
        )


class TestStoryStatusEvent:
    """Tests for StoryStatusEvent schema."""

    def test_valid_story_status_event(self) -> None:
        """Test creating a valid story_status event."""
        event = StoryStatusEvent(
            type="story_status",
            timestamp="2026-01-15T08:00:00",
            run_id="run-20260115-080000-a1b2c3d4",
            sequence_id=2,
            data=StoryStatusData(
                epic_num=22,
                story_num=9,
                story_id="22-9-sse-sidebar-tree-updates",
                status="in-progress",
                previous_status="ready-for-dev",
            ),
        )
        assert event.type == "story_status"
        assert event.data.epic_num == 22
        assert event.data.status == "in-progress"

    def test_story_status_invalid_story_id_format(self) -> None:
        """Test that invalid story_id format raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            StoryStatusEvent(
                type="story_status",
                timestamp="2026-01-15T08:00:00",
                run_id="run-20260115-080000-a1b2c3d4",
                sequence_id=2,
                data=StoryStatusData(
                    epic_num=22,
                    story_num=9,
                    story_id="invalid-story-id",  # Invalid format
                    status="in-progress",
                ),
            )

        errors = exc_info.value.errors()
        # Note: When StoryStatusData validates before event creation,
        # the error location is ('story_id',) not ('data', 'story_id')
        assert any(
            err["loc"] == ("story_id",) or (err["loc"][0] == "data" and err["loc"][1] == "story_id")
            for err in errors
        )

    def test_story_status_invalid_status(self) -> None:
        """Test that invalid status raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            StoryStatusEvent(
                type="story_status",
                timestamp="2026-01-15T08:00:00",
                run_id="run-20260115-080000-a1b2c3d4",
                sequence_id=2,
                data=StoryStatusData(
                    epic_num=22,
                    story_num=9,
                    story_id="22-9-sse-sidebar-tree-updates",
                    status="invalid_status",  # Invalid status
                ),
            )

        errors = exc_info.value.errors()
        # Note: When StoryStatusData validates before event creation,
        # the error location is ('status',) not ('data', 'status')
        assert any(
            err["loc"] == ("status",) or (err["loc"][0] == "data" and err["loc"][1] == "status")
            for err in errors
        )


class TestStoryTransitionEvent:
    """Tests for StoryTransitionEvent schema."""

    def test_valid_story_transition_event(self) -> None:
        """Test creating a valid story_transition event."""
        event = StoryTransitionEvent(
            type="story_transition",
            timestamp="2026-01-15T08:00:00",
            run_id="run-20260115-080000-a1b2c3d4",
            sequence_id=3,
            data=StoryTransitionData(
                action="started",
                epic_num=22,
                story_num=9,
                story_id="22-9-sse-sidebar-tree-updates",
                story_title="sse-sidebar-tree-updates",
            ),
        )
        assert event.type == "story_transition"
        assert event.data.action == "started"
        assert event.data.epic_num == 22

    def test_story_transition_invalid_action(self) -> None:
        """Test that invalid action raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            StoryTransitionEvent(
                type="story_transition",
                timestamp="2026-01-15T08:00:00",
                run_id="run-20260115-080000-a1b2c3d4",
                sequence_id=3,
                data=StoryTransitionData(
                    action="invalid_action",  # Invalid action
                    epic_num=22,
                    story_num=9,
                    story_id="22-9-sse-sidebar-tree-updates",
                    story_title="sse-sidebar-tree-updates",
                ),
            )

        errors = exc_info.value.errors()
        # Note: When StoryTransitionData validates before event creation,
        # the error location is ('action',) not ('data', 'action')
        assert any(
            err["loc"] == ("action",) or (err["loc"][0] == "data" and err["loc"][1] == "action")
            for err in errors
        )


class TestEventFactoryFunctions:
    """Tests for event factory functions."""

    def test_create_workflow_status(self) -> None:
        """Test create_workflow_status factory function."""
        event = create_workflow_status(
            run_id="run-20260115-080000-a1b2c3d4",
            sequence_id=1,
            epic_num=22,
            story_id="22.9",
            phase="DEV_STORY",
            phase_status="in-progress",
        )
        assert isinstance(event, WorkflowStatusEvent)
        assert event.run_id == "run-20260115-080000-a1b2c3d4"
        assert event.sequence_id == 1
        assert event.data.current_epic == 22

    def test_create_story_status(self) -> None:
        """Test create_story_status factory function."""
        event = create_story_status(
            run_id="run-20260115-080000-a1b2c3d4",
            sequence_id=2,
            epic_num=22,
            story_num=9,
            story_id="22-9-sse-sidebar-tree-updates",
            status="in-progress",
            previous_status="ready-for-dev",
        )
        assert isinstance(event, StoryStatusEvent)
        assert event.data.epic_num == 22
        assert event.data.status == "in-progress"

    def test_create_story_transition(self) -> None:
        """Test create_story_transition factory function."""
        event = create_story_transition(
            run_id="run-20260115-080000-a1b2c3d4",
            sequence_id=3,
            action="started",
            epic_num=22,
            story_num=9,
            story_id="22-9-sse-sidebar-tree-updates",
            story_title="sse-sidebar-tree-updates",
        )
        assert isinstance(event, StoryTransitionEvent)
        assert event.data.action == "started"
        assert event.data.epic_num == 22
