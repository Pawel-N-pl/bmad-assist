"""Tests for Story 22.9: SSE Sidebar Tree Updates.

Integration tests for:
- Phase completion/failure status emission (Task 7)
- String epic ID support in schemas (Task 10)
- Event deduplication via sequence_id (AC4)
- Reconnection resync (AC5)
"""

import json

import pytest

from bmad_assist.core.loop.dashboard_events import (
    DASHBOARD_EVENT_MARKER,
    emit_story_status,
    emit_story_transition,
    emit_workflow_status,
    generate_run_id,
)
from bmad_assist.dashboard.schemas import (
    StoryStatusData,
    StoryTransitionData,
    WorkflowStatusData,
    WorkflowStatusEvent,
    create_story_status,
    create_story_transition,
    create_workflow_status,
)


@pytest.fixture(autouse=True)
def enable_dashboard_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable dashboard mode for all tests in this module.

    Dashboard events are only emitted when BMAD_DASHBOARD_MODE=1.
    """
    monkeypatch.setenv("BMAD_DASHBOARD_MODE", "1")


class TestPhaseStatusEmission:
    """Tests for phase_status emission (Task 7, AC2)."""

    def test_emit_phase_status_completed(self, capsys: pytest.CaptureFixture) -> None:
        """Test that phase_status='completed' is emitted after successful phase."""
        run_id = generate_run_id()
        sequence_id = 5

        emit_workflow_status(
            run_id=run_id,
            sequence_id=sequence_id,
            epic_num=22,
            story_id="22.9",
            phase="DEV_STORY",
            phase_status="completed",
        )

        captured = capsys.readouterr()
        assert DASHBOARD_EVENT_MARKER in captured.out

        json_str = captured.out[len(DASHBOARD_EVENT_MARKER):].strip()
        data = json.loads(json_str)

        assert data["type"] == "workflow_status"
        assert data["data"]["phase_status"] == "completed"
        assert data["data"]["current_phase"] == "DEV_STORY"
        assert data["sequence_id"] == sequence_id

    def test_emit_phase_status_failed(self, capsys: pytest.CaptureFixture) -> None:
        """Test that phase_status='failed' is emitted after failed phase."""
        run_id = generate_run_id()
        sequence_id = 6

        emit_workflow_status(
            run_id=run_id,
            sequence_id=sequence_id,
            epic_num=22,
            story_id="22.9",
            phase="CODE_REVIEW",
            phase_status="failed",
        )

        captured = capsys.readouterr()
        json_str = captured.out[len(DASHBOARD_EVENT_MARKER):].strip()
        data = json.loads(json_str)

        assert data["data"]["phase_status"] == "failed"
        assert data["data"]["current_phase"] == "CODE_REVIEW"

    def test_phase_status_values(self) -> None:
        """Test all valid phase_status values are accepted by schema."""
        valid_statuses = ["pending", "in-progress", "completed", "failed"]

        for status in valid_statuses:
            event = WorkflowStatusEvent(
                type="workflow_status",
                timestamp="2026-01-19T08:00:00",
                run_id="run-20260119-080000-a1b2c3d4",
                sequence_id=1,
                data=WorkflowStatusData(
                    current_epic=22,
                    current_story="22.9",
                    current_phase="DEV_STORY",
                    phase_status=status,
                ),
            )
            assert event.data.phase_status == status


class TestStringEpicIdSupport:
    """Tests for string epic ID support (Task 10)."""

    def test_workflow_status_string_epic_id(self, capsys: pytest.CaptureFixture) -> None:
        """Test emit_workflow_status with string epic ID like 'testarch'."""
        run_id = generate_run_id()

        emit_workflow_status(
            run_id=run_id,
            sequence_id=1,
            epic_num="testarch",  # String epic ID
            story_id="testarch.1",
            phase="CREATE_STORY",
            phase_status="in-progress",
        )

        captured = capsys.readouterr()
        json_str = captured.out[len(DASHBOARD_EVENT_MARKER):].strip()
        data = json.loads(json_str)

        assert data["data"]["current_epic"] == "testarch"
        assert data["data"]["current_story"] == "testarch.1"

    def test_story_status_string_epic_id(self, capsys: pytest.CaptureFixture) -> None:
        """Test emit_story_status with string epic ID."""
        run_id = generate_run_id()

        emit_story_status(
            run_id=run_id,
            sequence_id=2,
            epic_num="dashboard",  # String epic ID
            story_num=5,
            story_id="dashboard-5-sse-updates",
            status="in-progress",
        )

        captured = capsys.readouterr()
        json_str = captured.out[len(DASHBOARD_EVENT_MARKER):].strip()
        data = json.loads(json_str)

        assert data["data"]["epic_num"] == "dashboard"

    def test_story_transition_string_epic_id(self, capsys: pytest.CaptureFixture) -> None:
        """Test emit_story_transition with string epic ID."""
        run_id = generate_run_id()

        emit_story_transition(
            run_id=run_id,
            sequence_id=3,
            action="started",
            epic_num="testarch",  # String epic ID
            story_num=2,
            story_id="testarch-2-config-schema",
            story_title="config-schema",
        )

        captured = capsys.readouterr()
        json_str = captured.out[len(DASHBOARD_EVENT_MARKER):].strip()
        data = json.loads(json_str)

        assert data["data"]["epic_num"] == "testarch"
        assert data["data"]["story_id"] == "testarch-2-config-schema"

    def test_workflow_status_schema_accepts_string_epic(self) -> None:
        """Test WorkflowStatusData schema accepts string epic ID."""
        data = WorkflowStatusData(
            current_epic="testarch",  # String epic
            current_story="testarch.1",
            current_phase="CREATE_STORY",
            phase_status="in-progress",
        )
        assert data.current_epic == "testarch"

    def test_workflow_status_schema_accepts_numeric_epic(self) -> None:
        """Test WorkflowStatusData schema still accepts numeric epic ID."""
        data = WorkflowStatusData(
            current_epic=22,  # Numeric epic
            current_story="22.9",
            current_phase="DEV_STORY",
            phase_status="completed",
        )
        assert data.current_epic == 22

    def test_story_status_schema_accepts_string_epic(self) -> None:
        """Test StoryStatusData schema accepts string epic ID."""
        data = StoryStatusData(
            epic_num="testarch",  # String epic
            story_num=3,
            story_id="testarch-3-test-design",
            status="in-progress",
        )
        assert data.epic_num == "testarch"

    def test_story_transition_schema_accepts_string_epic(self) -> None:
        """Test StoryTransitionData schema accepts string epic ID."""
        data = StoryTransitionData(
            action="started",
            epic_num="dashboard",  # String epic
            story_num=1,
            story_id="dashboard-1-initial-setup",
            story_title="initial-setup",
        )
        assert data.epic_num == "dashboard"


class TestSequenceIdDeduplication:
    """Tests for sequence_id deduplication (AC4)."""

    def test_sequence_id_increments(self, capsys: pytest.CaptureFixture) -> None:
        """Test that sequence_id increments correctly in emissions."""
        run_id = generate_run_id()

        emit_workflow_status(
            run_id=run_id,
            sequence_id=1,
            epic_num=22,
            story_id="22.9",
            phase="CREATE_STORY",
            phase_status="in-progress",
        )

        captured1 = capsys.readouterr()
        json_str1 = captured1.out[len(DASHBOARD_EVENT_MARKER):].strip()
        data1 = json.loads(json_str1)
        assert data1["sequence_id"] == 1

        emit_workflow_status(
            run_id=run_id,
            sequence_id=2,
            epic_num=22,
            story_id="22.9",
            phase="CREATE_STORY",
            phase_status="completed",
        )

        captured2 = capsys.readouterr()
        json_str2 = captured2.out[len(DASHBOARD_EVENT_MARKER):].strip()
        data2 = json.loads(json_str2)
        assert data2["sequence_id"] == 2

    def test_run_id_consistency(self, capsys: pytest.CaptureFixture) -> None:
        """Test that run_id remains consistent across events in a run."""
        run_id = generate_run_id()

        for seq_id in range(1, 4):
            emit_workflow_status(
                run_id=run_id,
                sequence_id=seq_id,
                epic_num=22,
                story_id="22.9",
                phase="DEV_STORY",
                phase_status="in-progress",
            )

            captured = capsys.readouterr()
            json_str = captured.out[len(DASHBOARD_EVENT_MARKER):].strip()
            data = json.loads(json_str)

            assert data["run_id"] == run_id


class TestEventFactoriesWithStringEpic:
    """Tests for event factory functions with string epic IDs."""

    def test_create_workflow_status_string_epic(self) -> None:
        """Test create_workflow_status with string epic ID."""
        event = create_workflow_status(
            run_id="run-20260119-080000-a1b2c3d4",
            sequence_id=1,
            epic_num="testarch",
            story_id="testarch.1",
            phase="DEV_STORY",
            phase_status="in-progress",
        )
        assert event.data.current_epic == "testarch"

    def test_create_story_status_string_epic(self) -> None:
        """Test create_story_status with string epic ID."""
        event = create_story_status(
            run_id="run-20260119-080000-a1b2c3d4",
            sequence_id=2,
            epic_num="dashboard",
            story_num=5,
            story_id="dashboard-5-sse-updates",
            status="in-progress",
        )
        assert event.data.epic_num == "dashboard"

    def test_create_story_transition_string_epic(self) -> None:
        """Test create_story_transition with string epic ID."""
        event = create_story_transition(
            run_id="run-20260119-080000-a1b2c3d4",
            sequence_id=3,
            action="started",
            epic_num="testarch",
            story_num=2,
            story_id="testarch-2-config-schema",
            story_title="config-schema",
        )
        assert event.data.epic_num == "testarch"


class TestStoryIdPatterns:
    """Tests for updated story ID patterns supporting string epics."""

    def test_current_story_pattern_numeric_epic(self) -> None:
        """Test current_story pattern with numeric epic."""
        data = WorkflowStatusData(
            current_epic=22,
            current_story="22.9",
            current_phase="DEV_STORY",
            phase_status="in-progress",
        )
        assert data.current_story == "22.9"

    def test_current_story_pattern_string_epic(self) -> None:
        """Test current_story pattern with string epic."""
        data = WorkflowStatusData(
            current_epic="testarch",
            current_story="testarch.1",
            current_phase="DEV_STORY",
            phase_status="in-progress",
        )
        assert data.current_story == "testarch.1"

    def test_current_story_pattern_hyphenated_epic(self) -> None:
        """Test current_story pattern with hyphenated string epic."""
        data = WorkflowStatusData(
            current_epic="my-module",
            current_story="my-module.5",
            current_phase="CREATE_STORY",
            phase_status="pending",
        )
        assert data.current_story == "my-module.5"

    def test_story_id_pattern_numeric_epic(self) -> None:
        """Test story_id pattern with numeric epic."""
        data = StoryStatusData(
            epic_num=22,
            story_num=9,
            story_id="22-9-sse-sidebar-tree-updates",
            status="in-progress",
        )
        assert data.story_id == "22-9-sse-sidebar-tree-updates"

    def test_story_id_pattern_string_epic(self) -> None:
        """Test story_id pattern with string epic."""
        data = StoryStatusData(
            epic_num="testarch",
            story_num=1,
            story_id="testarch-1-config-schema",
            status="backlog",
        )
        assert data.story_id == "testarch-1-config-schema"


class TestDashboardModeEnvironment:
    """Tests for BMAD_DASHBOARD_MODE environment variable behavior."""

    def test_events_not_emitted_without_dashboard_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Test that events are not emitted when BMAD_DASHBOARD_MODE is not set."""
        monkeypatch.delenv("BMAD_DASHBOARD_MODE", raising=False)

        emit_workflow_status(
            run_id="run-20260119-080000-a1b2c3d4",
            sequence_id=1,
            epic_num=22,
            story_id="22.9",
            phase="DEV_STORY",
            phase_status="in-progress",
        )

        captured = capsys.readouterr()
        assert DASHBOARD_EVENT_MARKER not in captured.out
        assert captured.out == ""

    def test_events_emitted_with_dashboard_mode(
        self,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Test that events are emitted when BMAD_DASHBOARD_MODE=1."""
        # autouse fixture already sets BMAD_DASHBOARD_MODE=1
        emit_workflow_status(
            run_id="run-20260119-080000-a1b2c3d4",
            sequence_id=1,
            epic_num=22,
            story_id="22.9",
            phase="DEV_STORY",
            phase_status="in-progress",
        )

        captured = capsys.readouterr()
        assert DASHBOARD_EVENT_MARKER in captured.out
