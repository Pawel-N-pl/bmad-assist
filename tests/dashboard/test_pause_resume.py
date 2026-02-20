"""Tests for dashboard pause/resume functionality (Story 22.10).

Tests cover:
- Resume endpoint behavior
- Main loop pause detection via file-based IPC
- State consistency during pause/resume
- Stale flag cleanup on startup
- Stop while paused
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from bmad_assist.core.state import Phase, State
from bmad_assist.dashboard.server import DashboardServer

# =============================================================================
# Task 2 Tests: Resume functionality backend
# =============================================================================


class TestResumeEndpoint:
    """Tests for POST /api/loop/resume endpoint."""

    @pytest.mark.asyncio
    async def test_resume_clears_pause_flag(self, tmp_path: Path) -> None:
        """Test that resume_loop() clears pause_requested flag."""
        server = DashboardServer(project_root=tmp_path)

        # Setup: loop is running and paused
        server._loop_running = True
        server._pause_requested = True

        # Create pause flag file
        pause_flag = tmp_path / ".bmad-assist" / "pause.flag"
        pause_flag.parent.mkdir(parents=True, exist_ok=True)
        pause_flag.touch()

        # Execute resume
        result = await server.resume_loop()

        # Verify: flag cleared and file removed
        assert server._pause_requested is False
        assert not pause_flag.exists()
        assert result["status"] == "resumed"

    @pytest.mark.asyncio
    async def test_resume_when_not_running_returns_error(self, tmp_path: Path) -> None:
        """Test that resume when loop not running returns error."""
        server = DashboardServer(project_root=tmp_path)

        # Setup: loop not running
        server._loop_running = False
        server._pause_requested = True

        # Execute resume
        result = await server.resume_loop()

        # Verify: error returned
        assert result["status"] == "not_running"
        assert "not running" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_resume_when_not_paused_returns_error(self, tmp_path: Path) -> None:
        """Test that resume when not paused returns error."""
        server = DashboardServer(project_root=tmp_path)

        # Setup: loop running but not paused
        server._loop_running = True
        server._pause_requested = False

        # Execute resume
        result = await server.resume_loop()

        # Verify: error returned
        assert result["status"] == "not_paused"
        assert "not paused" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_resume_broadcasts_output_message(self, tmp_path: Path) -> None:
        """Test that resume broadcasts output message (SSE event is emitted by subprocess)."""
        server = DashboardServer(project_root=tmp_path)

        # Setup: loop running and paused
        server._loop_running = True
        server._pause_requested = True
        server._run_id = "test-run-123"

        # Mock SSE broadcaster
        server.sse_broadcaster.broadcast_output = AsyncMock()  # type: ignore[method-assign]

        # Execute resume
        await server.resume_loop()

        # Verify: Output message broadcast (LOOP_RESUMED event is emitted by subprocess, not server)
        server.sse_broadcaster.broadcast_output.assert_called_once()
        call_args = server.sse_broadcaster.broadcast_output.call_args
        assert "Resumed" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_stop_while_paused_cleans_pause_flag(self, tmp_path: Path) -> None:
        """Test that stop_loop() cleans pause.flag when stopping while paused (AC #6)."""
        server = DashboardServer(project_root=tmp_path)

        # Setup: loop running and paused
        server._loop_running = True
        server._pause_requested = True

        # Create pause flag (stop_flag will be created by stop_loop)
        pause_flag = tmp_path / ".bmad-assist" / "pause.flag"
        pause_flag.parent.mkdir(parents=True, exist_ok=True)
        pause_flag.touch()

        # Mock cancel_process to avoid actual process termination
        server._cancel_process = AsyncMock()  # type: ignore[method-assign]

        # Execute stop
        result = await server.stop_loop()

        # Verify: pause flag cleaned, stop flag created (for subprocess)
        assert not pause_flag.exists()
        stop_flag = tmp_path / ".bmad-assist" / "stop.flag"
        # Note: stop_loop creates stop.flag for subprocess detection
        # We don't verify it's gone because that's for the subprocess to clean
        assert result["status"] == "stopped"


# =============================================================================
# Task 3 Tests: Main loop pause detection
# =============================================================================


class TestPauseFlagDetection:
    """Tests for file-based pause flag detection in main loop."""

    def test_check_pause_flag_exists(self, tmp_path: Path) -> None:
        """Test that _check_pause_flag returns True when flag exists."""
        from bmad_assist.core.loop.pause import check_pause_flag

        # Create pause flag
        pause_flag = tmp_path / ".bmad-assist" / "pause.flag"
        pause_flag.parent.mkdir(parents=True, exist_ok=True)
        pause_flag.touch()

        # Check
        assert check_pause_flag(tmp_path) is True

    def test_check_pause_flag_not_exists(self, tmp_path: Path) -> None:
        """Test that _check_pause_flag returns False when flag doesn't exist."""
        from bmad_assist.core.loop.pause import check_pause_flag

        # Don't create flag
        assert check_pause_flag(tmp_path) is False

    def test_cleanup_stale_flags_on_startup(self, tmp_path: Path) -> None:
        """Test that stale pause.flag is removed on startup (AC #7)."""
        from bmad_assist.core.loop.pause import cleanup_stale_pause_flags

        # Create stale pause flag (from crashed session)
        pause_flag = tmp_path / ".bmad-assist" / "pause.flag"
        pause_flag.parent.mkdir(parents=True, exist_ok=True)
        pause_flag.touch()

        # Verify flag exists
        assert pause_flag.exists()

        # Cleanup (no exception raised, just warning log)
        cleanup_stale_pause_flags(tmp_path)

        # Verify: flag removed
        assert not pause_flag.exists()

    def test_cleanup_stale_stop_flag_on_startup(self, tmp_path: Path) -> None:
        """Test that stale stop.flag is also removed on startup (AC #6)."""
        from bmad_assist.core.loop.pause import cleanup_stale_pause_flags

        # Create stale stop flag (from crashed session during stop)
        stop_flag = tmp_path / ".bmad-assist" / "stop.flag"
        stop_flag.parent.mkdir(parents=True, exist_ok=True)
        stop_flag.touch()

        # Verify flag exists
        assert stop_flag.exists()

        # Cleanup (no exception raised, just warning log)
        cleanup_stale_pause_flags(tmp_path)

        # Verify: flag removed
        assert not stop_flag.exists()


class TestWaitForResume:
    """Tests for _wait_for_resume function."""

    def test_wait_for_resume_resumes_when_flag_cleared(self, tmp_path: Path) -> None:
        """Test that _wait_for_resume returns True when pause flag is cleared."""
        from bmad_assist.core.loop.pause import wait_for_resume

        # Create pause flag
        pause_flag = tmp_path / ".bmad-assist" / "pause.flag"
        pause_flag.parent.mkdir(parents=True, exist_ok=True)
        pause_flag.touch()

        # Start wait in background
        import threading

        result = [None]
        stop_event = threading.Event()

        def wait_thread():
            result[0] = wait_for_resume(tmp_path, stop_event, pause_timeout_minutes=0)

        thread = threading.Thread(target=wait_thread)
        thread.start()

        # Wait a bit, then clear flag
        import time

        time.sleep(0.2)
        pause_flag.unlink()

        # Wait for thread to complete
        thread.join(timeout=2)

        # Verify: resumed successfully
        assert result[0] is True

    def test_wait_for_resume_stops_when_stop_flag_detected(self, tmp_path: Path) -> None:
        """Test that _wait_for_resume returns False when stop flag is detected (AC #6)."""
        from bmad_assist.core.loop.pause import wait_for_resume

        # Create pause flag
        pause_flag = tmp_path / ".bmad-assist" / "pause.flag"
        pause_flag.parent.mkdir(parents=True, exist_ok=True)
        pause_flag.touch()

        # Start wait in background
        import threading

        result = [None]
        stop_event = threading.Event()

        def wait_thread():
            result[0] = wait_for_resume(tmp_path, stop_event, pause_timeout_minutes=0)

        thread = threading.Thread(target=wait_thread)
        thread.start()

        # Wait a bit, then create stop flag
        import time

        time.sleep(0.2)
        stop_flag = tmp_path / ".bmad-assist" / "stop.flag"
        stop_flag.touch()

        # Wait for thread to complete
        thread.join(timeout=2)

        # Verify: stopped (not resumed)
        assert result[0] is False
        # Verify: stop flag cleaned up
        assert not stop_flag.exists()

    def test_wait_for_resume_timeout(self, tmp_path: Path) -> None:
        """Test that _wait_for_resume auto-resumes after timeout."""
        from bmad_assist.core.loop.pause import wait_for_resume

        # Create pause flag
        pause_flag = tmp_path / ".bmad-assist" / "pause.flag"
        pause_flag.parent.mkdir(parents=True, exist_ok=True)
        pause_flag.touch()

        # Wait with 1 second timeout (should auto-resume)
        import threading

        result = [None]
        stop_event = threading.Event()

        def wait_thread():
            # Set timeout to 1 second for fast test
            result[0] = wait_for_resume(tmp_path, stop_event, pause_timeout_minutes=1 / 60)

        thread = threading.Thread(target=wait_thread)
        thread.start()

        # Wait for thread to complete
        thread.join(timeout=5)

        # Verify: auto-resumed after timeout
        assert result[0] is True
        # Verify: flag cleaned up by timeout
        assert not pause_flag.exists()


# =============================================================================
# Task 6 Tests: State consistency verification
# =============================================================================


class TestStateConsistency:
    """Tests for state consistency during pause/resume (AC #3)."""

    def test_state_validation_before_pause(self, tmp_path: Path) -> None:
        """Test that state is validated before entering pause wait loop (AC #3)."""
        from bmad_assist.core.loop.pause import validate_state_for_pause

        # Create valid state
        state = State(
            current_epic=22,
            current_story="22.10",
            current_phase=Phase.DEV_STORY,
        )
        state_path = tmp_path / ".bmad-assist" / "state.yaml"
        state_path.parent.mkdir(parents=True, exist_ok=True)

        from bmad_assist.core.state import save_state

        save_state(state, state_path)

        # Validate - should pass
        assert validate_state_for_pause(state_path) is True

    def test_state_validation_detects_corruption(self, tmp_path: Path) -> None:
        """Test that state validation catches corrupted YAML (AC #6)."""
        from bmad_assist.core.loop.pause import validate_state_for_pause

        # Create corrupted state file
        state_path = tmp_path / ".bmad-assist" / "state.yaml"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("invalid: yaml: content: [")

        # Validate - should fail
        assert validate_state_for_pause(state_path) is False

    def test_state_validation_detects_missing_fields(self, tmp_path: Path) -> None:
        """Test that state validation detects missing required fields (AC #6)."""
        import yaml

        from bmad_assist.core.loop.pause import validate_state_for_pause

        # Create state with missing fields
        state_path = tmp_path / ".bmad-assist" / "state.yaml"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(yaml.dump({"current_epic": 22}))  # Missing story and phase

        # Validate - should fail
        assert validate_state_for_pause(state_path) is False


# =============================================================================
# Integration Tests
# =============================================================================


class TestPauseResumeIntegration:
    """Integration tests for full pause/resume cycle."""

    @pytest.mark.asyncio
    async def test_full_pause_resume_cycle(self, tmp_path: Path) -> None:
        """Test full pause/resume cycle: pause → wait → resume (AC #1, #2)."""
        server = DashboardServer(project_root=tmp_path)

        # Start loop (mocked)
        server._loop_running = True
        server._run_id = "test-run-123"

        # Mock subprocess creation to avoid actual process spawn
        with patch.object(server, "_run_workflow_loop", new=AsyncMock()):
            server._loop_task = asyncio.create_task(server._run_workflow_loop())

        # Pause
        pause_result = await server.pause_loop()
        assert pause_result["status"] == "pause_requested"
        assert server._pause_requested is True

        # Verify pause flag file created by pause_loop()
        pause_flag = tmp_path / ".bmad-assist" / "pause.flag"
        # Note: pause_loop() in server.py creates pause.flag directly via touch()
        # (see server.py:293-295). The subprocess detects this flag.
        assert pause_flag.exists()

        # Resume
        resume_result = await server.resume_loop()
        assert resume_result["status"] == "resumed"
        assert server._pause_requested is False

    @pytest.mark.asyncio
    async def test_multiple_pause_resume_cycles(self, tmp_path: Path) -> None:
        """Test multiple pause/resume cycles in single run (AC #7.12)."""
        server = DashboardServer(project_root=tmp_path)

        # Setup
        server._loop_running = True
        server._run_id = "test-run-123"

        # First pause/resume
        await server.pause_loop()
        assert server._pause_requested is True
        await server.resume_loop()
        assert server._pause_requested is False

        # Second pause/resume
        await server.pause_loop()
        assert server._pause_requested is True
        await server.resume_loop()
        assert server._pause_requested is False

        # Third pause/resume
        await server.pause_loop()
        assert server._pause_requested is True
        await server.resume_loop()
        assert server._pause_requested is False


# =============================================================================
# Task 5 Tests: SSE events
# =============================================================================


class TestSSEPauseResumeEvents:
    """Tests for SSE pause/resume event broadcasting.

    Note: LOOP_PAUSED and LOOP_RESUMED events are emitted by the subprocess
    (runner.py:1084, runner.py:1105), not by the dashboard server. The server
    receives these events via stdout parsing and broadcasts them to clients.
    """

    @pytest.mark.asyncio
    async def test_dashboard_broadcasts_received_loop_paused_event(self, tmp_path: Path) -> None:
        """Test that dashboard broadcasts LOOP_PAUSED event received from subprocess (AC #2)."""
        server = DashboardServer(project_root=tmp_path)
        server._run_id = "test-run-123"

        # Mock SSE broadcaster
        server.sse_broadcaster.broadcast_event = AsyncMock()  # type: ignore[method-assign]

        # Simulate subprocess emitting LOOP_PAUSED via stdout marker
        import json

        from bmad_assist.core.loop.dashboard_events import DASHBOARD_EVENT_MARKER

        event_data = {
            "type": "LOOP_PAUSED",
            "timestamp": "2026-01-19T03:00:00Z",
            "run_id": "test-run-123",
            "sequence_id": 1,
            "data": {"current_phase": "DEV_STORY"},
        }
        marker_line = f"{DASHBOARD_EVENT_MARKER}{json.dumps(event_data)}"

        # Handle the event (simulates stdout parsing in _run_workflow_loop)
        await server._handle_dashboard_event(marker_line)

        # Verify: event was broadcast
        server.sse_broadcaster.broadcast_event.assert_called_once()
        call_args = server.sse_broadcaster.broadcast_event.call_args
        assert call_args[0][0] == "LOOP_PAUSED"
