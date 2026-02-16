"""Tests for ProjectContext class.

Tests state machine, log buffer, and summary generation.
"""

from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from subprocess import Popen
from unittest.mock import MagicMock

import pytest

from bmad_assist.dashboard.manager.project_context import (
    DEFAULT_LOG_BUFFER_SIZE,
    LoopState,
    ProjectContext,
)


class TestLoopState:
    """Tests for LoopState enum."""

    def test_state_values(self):
        """Verify all state enum values."""
        assert LoopState.IDLE.value == "idle"
        assert LoopState.STARTING.value == "starting"
        assert LoopState.RUNNING.value == "running"
        assert LoopState.PAUSE_REQUESTED.value == "pause_requested"
        assert LoopState.PAUSED.value == "paused"
        assert LoopState.QUEUED.value == "queued"
        assert LoopState.ERROR.value == "error"


class TestProjectContextCreate:
    """Tests for ProjectContext.create() factory method."""

    def test_create_with_path(self, tmp_path: Path):
        """Create context with minimal arguments."""
        context = ProjectContext.create(tmp_path)

        assert context.project_root == tmp_path.resolve()
        assert context.display_name == tmp_path.name
        assert context.state == LoopState.IDLE
        assert context.project_uuid is not None
        assert len(context.project_uuid) == 36  # UUID format

    def test_create_with_display_name(self, tmp_path: Path):
        """Create context with custom display name."""
        context = ProjectContext.create(tmp_path, display_name="My Project")

        assert context.display_name == "My Project"

    def test_create_with_custom_buffer_size(self, tmp_path: Path):
        """Create context with custom log buffer size."""
        context = ProjectContext.create(tmp_path, log_buffer_size=100)

        assert context.log_buffer.maxlen == 100

    def test_create_nonexistent_path_raises(self):
        """Create with nonexistent path raises ValueError."""
        with pytest.raises(ValueError, match="does not exist"):
            ProjectContext.create(Path("/nonexistent/path"))

    def test_create_generates_unique_uuids(self, tmp_path: Path):
        """Each create call generates unique UUID."""
        context1 = ProjectContext.create(tmp_path)
        context2 = ProjectContext.create(tmp_path)

        assert context1.project_uuid != context2.project_uuid


class TestProjectContextLogBuffer:
    """Tests for log ring buffer functionality."""

    def test_add_log_stores_line(self, tmp_path: Path):
        """add_log() stores line in buffer."""
        context = ProjectContext.create(tmp_path)

        context.add_log("Test line 1")
        context.add_log("Test line 2")

        assert list(context.log_buffer) == ["Test line 1", "Test line 2"]

    def test_add_log_updates_last_seen(self, tmp_path: Path):
        """add_log() updates last_seen timestamp."""
        context = ProjectContext.create(tmp_path)
        old_seen = context.last_seen

        context.add_log("New line")

        assert context.last_seen >= old_seen

    def test_get_logs_returns_all(self, tmp_path: Path):
        """get_logs() returns all logs."""
        context = ProjectContext.create(tmp_path)
        context.add_log("Line 1")
        context.add_log("Line 2")

        logs = context.get_logs()

        assert logs == ["Line 1", "Line 2"]

    def test_get_logs_with_count(self, tmp_path: Path):
        """get_logs(count) returns last N logs."""
        context = ProjectContext.create(tmp_path)
        for i in range(10):
            context.add_log(f"Line {i}")

        logs = context.get_logs(count=3)

        assert logs == ["Line 7", "Line 8", "Line 9"]

    def test_ring_buffer_drops_oldest(self, tmp_path: Path):
        """Ring buffer drops oldest when full."""
        context = ProjectContext.create(tmp_path, log_buffer_size=3)

        context.add_log("First")
        context.add_log("Second")
        context.add_log("Third")
        context.add_log("Fourth")

        assert list(context.log_buffer) == ["Second", "Third", "Fourth"]

    def test_clear_logs(self, tmp_path: Path):
        """clear_logs() empties buffer."""
        context = ProjectContext.create(tmp_path)
        context.add_log("Test")
        context.add_log("Lines")

        context.clear_logs()

        assert len(context.log_buffer) == 0


class TestProjectContextStateTransitions:
    """Tests for state transition methods."""

    def test_set_running(self, tmp_path: Path):
        """set_running() transitions to RUNNING with process."""
        context = ProjectContext.create(tmp_path)
        mock_process = MagicMock(spec=Popen)

        context.set_running(mock_process)

        assert context.state == LoopState.RUNNING
        assert context.current_process == mock_process
        assert context.phase_start_time is not None
        assert context.error_message is None

    def test_set_paused(self, tmp_path: Path):
        """set_paused() transitions to PAUSED."""
        context = ProjectContext.create(tmp_path)
        context.state = LoopState.RUNNING

        context.set_paused()

        assert context.state == LoopState.PAUSED

    def test_set_error(self, tmp_path: Path):
        """set_error() transitions to ERROR with message."""
        context = ProjectContext.create(tmp_path)
        context.state = LoopState.RUNNING

        context.set_error("Something went wrong")

        assert context.state == LoopState.ERROR
        assert context.error_message == "Something went wrong"
        assert context.last_status == "FAILED"
        assert context.current_process is None

    def test_set_idle_success(self, tmp_path: Path):
        """set_idle(success=True) clears state."""
        context = ProjectContext.create(tmp_path)
        context.state = LoopState.RUNNING
        context.current_epic = 1
        context.current_story = "1.1"

        context.set_idle(success=True)

        assert context.state == LoopState.IDLE
        assert context.current_epic is None
        assert context.current_story is None
        assert context.last_status == "SUCCESS"

    def test_set_idle_failure(self, tmp_path: Path):
        """set_idle(success=False) sets FAILED status."""
        context = ProjectContext.create(tmp_path)
        context.state = LoopState.ERROR

        context.set_idle(success=False)

        assert context.state == LoopState.IDLE
        assert context.last_status == "FAILED"

    def test_set_queued(self, tmp_path: Path):
        """set_queued() transitions to QUEUED with position."""
        context = ProjectContext.create(tmp_path)

        context.set_queued(position=3)

        assert context.state == LoopState.QUEUED
        assert context.queue_position == 3


class TestProjectContextUpdatePosition:
    """Tests for position update functionality."""

    def test_update_epic(self, tmp_path: Path):
        """update_position() sets epic."""
        context = ProjectContext.create(tmp_path)

        context.update_position(epic=5)

        assert context.current_epic == 5

    def test_update_story(self, tmp_path: Path):
        """update_position() sets story."""
        context = ProjectContext.create(tmp_path)

        context.update_position(story="5.2")

        assert context.current_story == "5.2"

    def test_update_phase(self, tmp_path: Path):
        """update_position() sets phase and resets timer."""
        context = ProjectContext.create(tmp_path)
        old_time = context.phase_start_time

        context.update_position(phase="dev_story")

        assert context.current_phase == "dev_story"
        assert context.phase_start_time is not None
        assert context.phase_start_time != old_time

    def test_update_multiple(self, tmp_path: Path):
        """update_position() can set multiple values."""
        context = ProjectContext.create(tmp_path)

        context.update_position(epic=1, story="1.1", phase="create_story")

        assert context.current_epic == 1
        assert context.current_story == "1.1"
        assert context.current_phase == "create_story"


class TestProjectContextPhaseDuration:
    """Tests for phase duration tracking."""

    def test_get_phase_duration_when_none(self, tmp_path: Path):
        """get_phase_duration_seconds() returns None when no phase."""
        context = ProjectContext.create(tmp_path)

        assert context.get_phase_duration_seconds() is None

    def test_get_phase_duration_returns_positive(self, tmp_path: Path):
        """get_phase_duration_seconds() returns positive value."""
        context = ProjectContext.create(tmp_path)
        context.update_position(phase="dev_story")

        duration = context.get_phase_duration_seconds()

        assert duration is not None
        assert duration >= 0


class TestProjectContextSummary:
    """Tests for summary generation."""

    def test_to_summary_includes_required_fields(self, tmp_path: Path):
        """to_summary() includes all required fields."""
        context = ProjectContext.create(tmp_path, display_name="Test Project")
        context.update_position(epic=1, story="1.1", phase="dev_story")

        summary = context.to_summary()

        assert summary["uuid"] == context.project_uuid
        assert summary["path"] == str(tmp_path.resolve())
        assert summary["display_name"] == "Test Project"
        assert summary["state"] == "idle"
        assert summary["current_epic"] == 1
        assert summary["current_story"] == "1.1"
        assert summary["current_phase"] == "dev_story"
        assert "last_seen" in summary
        assert "last_status" in summary


class TestProjectContextIsActive:
    """Tests for is_active() method."""

    def test_idle_not_active(self, tmp_path: Path):
        """IDLE state is not active."""
        context = ProjectContext.create(tmp_path)
        context.state = LoopState.IDLE

        assert context.is_active() is False

    def test_running_is_active(self, tmp_path: Path):
        """RUNNING state is active."""
        context = ProjectContext.create(tmp_path)
        context.state = LoopState.RUNNING

        assert context.is_active() is True

    def test_paused_is_active(self, tmp_path: Path):
        """PAUSED state is active."""
        context = ProjectContext.create(tmp_path)
        context.state = LoopState.PAUSED

        assert context.is_active() is True

    def test_queued_is_active(self, tmp_path: Path):
        """QUEUED state is active."""
        context = ProjectContext.create(tmp_path)
        context.state = LoopState.QUEUED

        assert context.is_active() is True

    def test_error_not_active(self, tmp_path: Path):
        """ERROR state is not active."""
        context = ProjectContext.create(tmp_path)
        context.state = LoopState.ERROR

        assert context.is_active() is False
