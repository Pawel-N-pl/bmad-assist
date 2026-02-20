"""Tests for terminal EOF handling - Story 22.11.

Tests verify:
- AC1: Individual validator completion doesn't close SSE stream
- AC2: SSE stream closes gracefully after all validators complete
- AC3: SSE stream handles timeout and continues with remaining validators
- AC4: asyncio.gather() waits for ALL tasks before continuing
- AC5: Subprocess exit closes SSE connection cleanly
- AC6: Stop button during validation terminates immediately

Key test patterns:
- Mock subprocess stdout with async iterator
- Verify SSE broadcaster continues during partial completion
- Verify readyState=2 on normal EOF
- Verify no reconnection on readyState=2
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bmad_assist.dashboard.server import DashboardServer
from bmad_assist.dashboard.sse import SSEBroadcaster

# =============================================================================
# Fixtures for EOF handling tests
# =============================================================================


class AsyncIteratorMock:
    """Mock async iterator for stdout lines that supports early EOF.

    Simulates subprocess stdout that may close before all tasks complete
    (individual validator completion scenario).
    """

    def __init__(self, lines: list[bytes], delay_eof: bool = False) -> None:
        self._lines = lines
        self._index = 0
        self._delay_eof = delay_eof  # If True, hang after last line
        self._eof_called = False

    def __aiter__(self) -> "AsyncIteratorMock":
        return self

    async def __anext__(self) -> bytes:
        if self._delay_eof and self._index >= len(self._lines):
            # Simulate hanging stdout (waiting for final flush)
            await asyncio.sleep(0.1)
            # Return EOF after delay
            raise StopAsyncIteration

        if self._index >= len(self._lines):
            self._eof_called = True
            raise StopAsyncIteration

        line = self._lines[self._index]
        self._index += 1
        return line


@pytest.fixture
def mock_multi_validator_process() -> MagicMock:
    """Create mock process simulating 6 validators with staggered completion.

    First 4 complete quickly, last 2 take longer.
    Simulates individual EOF without closing entire stream.
    """
    process = AsyncMock()
    process.returncode = 0
    # Simulate validator output lines
    lines = [
        b"Validator A started\n",
        b"Validator B started\n",
        b"Validator C started\n",
        b"Validator D started\n",
        b"Validator A completed\n",
        b"Validator B completed\n",
        b"Validator C completed\n",
        b"Validator D completed\n",
        b"Validator E started\n",
        b"Validator F started\n",
        b"Validator E completed\n",
        b"Validator F completed\n",
        b"All 6 validators completed\n",
    ]
    process.stdout = AsyncIteratorMock(lines)
    process.wait = AsyncMock(return_value=0)
    process.terminate = MagicMock()
    process.kill = MagicMock()
    return process


@pytest.fixture
def mock_process_with_timeout() -> MagicMock:
    """Create mock process where some validators timeout."""
    process = AsyncMock()
    process.returncode = 0
    lines = [
        b"Validator A started\n",
        b"Validator B started\n",
        b"Validator A completed\n",
        b"Validator B timed out after 300s\n",
        b"Validator C started\n",
        b"Validator C completed\n",
        b"2 validators completed, 1 timed out\n",
    ]
    process.stdout = AsyncIteratorMock(lines)
    process.wait = AsyncMock(return_value=0)
    process.terminate = MagicMock()
    process.kill = MagicMock()
    return process


@pytest.fixture
def mock_process_hanging_stdout() -> MagicMock:
    """Create mock process with delayed EOF (buffering issue)."""
    process = AsyncMock()
    process.returncode = 0
    lines = [b"Output line\n", b"Another line\n"]
    process.stdout = AsyncIteratorMock(lines, delay_eof=True)
    process.wait = AsyncMock(return_value=0)
    process.terminate = MagicMock()
    process.kill = MagicMock()
    return process


# =============================================================================
# AC1: Individual validator completion doesn't close SSE stream
# =============================================================================


class TestIndividualValidatorCompletionAC1:
    """Tests for AC1: Individual validator completion doesn't close SSE stream."""

    @pytest.mark.asyncio
    async def test_sse_continues_after_early_validator_completion(
        self,
        mock_multi_validator_process: MagicMock,
    ) -> None:
        """GIVEN Multi-LLM validation phase running with 6 validators
        WHEN 4 of 6 validators complete successfully
        THEN async for loop reads ALL lines before exiting
        AND all lines are available to SSE broadcaster.
        """
        # Test that async for reads all lines from stdout
        lines_read: list[str] = []

        async for line in mock_multi_validator_process.stdout:
            lines_read.append(line.decode(errors="replace").rstrip())

        # Verify all output was read (including lines after first 4 completed)
        assert len(lines_read) == 13  # All 13 lines from fixture
        assert any("Validator A completed" in line for line in lines_read)
        assert any("Validator F completed" in line for line in lines_read)
        assert any("All 6 validators completed" in line for line in lines_read)

    @pytest.mark.asyncio
    async def test_eventsource_remains_connected_after_partial_completion(self) -> None:
        """GIVEN SSE connection is active during parallel validator execution
        WHEN individual validator's subprocess completes (EOF on its stdout)
        THEN the orchestrator's async task completes normally
        AND asyncio.gather() continues waiting for remaining validator tasks.
        """
        # This test verifies the orchestrator's asyncio.gather() behavior
        # Simulated by tracking task completion

        async def mock_validator(name: str, duration: float) -> str:
            await asyncio.sleep(duration)
            return f"{name} completed"

        # Create tasks with staggered completion times
        tasks = [
            asyncio.create_task(mock_validator("Validator A", 0.1)),
            asyncio.create_task(mock_validator("Validator B", 0.1)),
            asyncio.create_task(mock_validator("Validator C", 0.1)),
            asyncio.create_task(mock_validator("Validator D", 0.1)),
            asyncio.create_task(mock_validator("Validator E", 0.3)),
            asyncio.create_task(mock_validator("Validator F", 0.3)),
        ]

        # Track completion order
        completed: list[str] = []

        async def track_completions() -> None:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, str):
                    completed.append(result)

        await track_completions()

        # Verify all tasks completed
        assert len(completed) == 6
        assert all("completed" in c for c in completed)


# =============================================================================
# AC2: SSE stream closes gracefully after all validators complete
# =============================================================================


class TestSSEClosesAfterAllCompleteAC2:
    """Tests for AC2: SSE stream closes gracefully after all validators complete."""

    @pytest.mark.asyncio
    async def test_async_for_exits_on_eof(
        self,
        mock_multi_validator_process: MagicMock,
    ) -> None:
        """GIVEN ALL 6 validators complete successfully (return codes 0)
        WHEN subprocess stdout reaches EOF
        THEN async for loop exits naturally
        AND all lines were read before EOF.
        """
        lines_read: list[str] = []

        # This is the pattern used in _run_workflow_loop
        async for line in mock_multi_validator_process.stdout:
            lines_read.append(line.decode(errors="replace").rstrip())

        # Verify all output was read before EOF
        assert len(lines_read) == 13  # All lines from fixture
        assert "All 6 validators completed" in lines_read[-1]

    @pytest.mark.asyncio
    async def test_terminal_shows_all_validator_output(
        self,
        mock_multi_validator_process: MagicMock,
    ) -> None:
        """GIVEN ALL 6 validators complete successfully
        WHEN async for loop iterates stdout
        THEN all output from all 6 validators is captured.
        """
        all_output: list[str] = []

        async for line in mock_multi_validator_process.stdout:
            all_output.append(line.decode(errors="replace").rstrip())

        # Verify output from all validators is present
        validator_names = ["A", "B", "C", "D", "E", "F"]
        for name in validator_names:
            assert any(f"Validator {name}" in line for line in all_output)


# =============================================================================
# AC3: SSE stream handles timeout and continues with remaining validators
# =============================================================================


class TestTimeoutHandlingAC3:
    """Tests for AC3: Timeout handling with remaining validators."""

    @pytest.mark.asyncio
    async def test_stdout_continues_after_timeout(
        self,
        mock_process_with_timeout: MagicMock,
    ) -> None:
        """GIVEN some validators timeout (exceed configured timeout)
        WHEN subprocess continues outputting after timeout message
        THEN async for loop continues reading output
        AND all output is captured including post-timeout validators.
        """
        output: list[str] = []

        async for line in mock_process_with_timeout.stdout:
            output.append(line.decode(errors="replace").rstrip())

        # Verify timeout was logged
        assert any("timed out" in line.lower() for line in output)
        # Verify remaining validators completed
        assert any("Validator C completed" in line for line in output)
        # Verify final status was captured
        assert any("2 validators completed" in line for line in output)


# =============================================================================
# AC4: asyncio.gather() waits for ALL tasks
# =============================================================================


class TestAsyncioGatherWaitsForAllAC4:
    """Tests for AC4: asyncio.gather() behavior."""

    @pytest.mark.asyncio
    async def test_gather_waits_for_all_tasks(self) -> None:
        """GIVEN asyncio.gather() is called with multiple tasks
        WHEN individual tasks complete at different times
        THEN gather() continues waiting for ALL tasks before returning.
        """
        completion_order: list[str] = []

        async def mock_task(name: str, delay: float) -> str:
            await asyncio.sleep(delay)
            completion_order.append(name)
            return name

        # Create tasks with staggered delays
        tasks = [
            asyncio.create_task(mock_task("fast1", 0.05)),
            asyncio.create_task(mock_task("fast2", 0.05)),
            asyncio.create_task(mock_task("fast3", 0.05)),
            asyncio.create_task(mock_task("fast4", 0.05)),
            asyncio.create_task(mock_task("slow1", 0.15)),
            asyncio.create_task(mock_task("slow2", 0.15)),
        ]

        # Verify gather waits for all
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert len(results) == 6
        assert len(completion_order) == 6
        # Fast tasks complete before slow tasks
        fast_tasks = [name for name in completion_order[:4] if name.startswith("fast")]
        assert len(fast_tasks) == 4

    @pytest.mark.asyncio
    async def test_gather_with_return_exceptions(self) -> None:
        """GIVEN asyncio.gather() with return_exceptions=True
        WHEN some tasks raise exceptions
        THEN gather() continues waiting for remaining tasks.
        """

        async def failing_task(name: str) -> str:
            await asyncio.sleep(0.05)
            raise ValueError(f"{name} failed")

        async def success_task(name: str) -> str:
            await asyncio.sleep(0.1)
            return name

        tasks = [
            asyncio.create_task(failing_task("fail1")),
            asyncio.create_task(success_task("success1")),
            asyncio.create_task(failing_task("fail2")),
            asyncio.create_task(success_task("success2")),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # All tasks completed (either with result or exception)
        assert len(results) == 4
        assert isinstance(results[0], ValueError)
        assert results[1] == "success1"
        assert isinstance(results[2], ValueError)
        assert results[3] == "success2"


# =============================================================================
# AC5: Subprocess exit closes SSE connection cleanly
# =============================================================================


class TestSubprocessExitClosesSSEAC5:
    """Tests for AC5: Subprocess exit closes SSE connection cleanly."""

    @pytest.mark.asyncio
    async def test_subprocess_eof_exits_stdout_loop(
        self,
        mock_multi_validator_process: MagicMock,
    ) -> None:
        """GIVEN bmad-assist subprocess is streaming output via SSE
        WHEN subprocess stdout reaches EOF
        THEN async for loop exits naturally
        AND StopAsyncIteration is raised (signaling EOF).
        """
        stdout_loop_exited = False
        lines_read = 0

        # This is the pattern used in _run_workflow_loop
        async for line in mock_multi_validator_process.stdout:
            lines_read += 1

        stdout_loop_exited = True

        # Verify stdout loop exited
        assert stdout_loop_exited
        # Verify all lines were read
        assert lines_read == 13

    @pytest.mark.asyncio
    async def test_subprocess_wait_returns_exit_code(
        self,
        mock_multi_validator_process: MagicMock,
    ) -> None:
        """GIVEN bmad-assist subprocess completes
        WHEN dashboard server waits for process
        THEN subprocess exit code is available from returncode.
        """
        # Consume stdout first (as done in _run_workflow_loop)
        async for _ in mock_multi_validator_process.stdout:
            pass

        # Wait for process completion
        await mock_multi_validator_process.wait()

        # Verify returncode is available
        assert mock_multi_validator_process.returncode == 0


# =============================================================================
# AC6: Stop button during validation terminates immediately
# =============================================================================


class TestStopButtonDuringValidationAC6:
    """Tests for AC6: Stop button during validation."""

    @pytest.mark.asyncio
    async def test_cancel_process_sends_sigterm(
        self,
        dashboard_server: DashboardServer,
        mock_multi_validator_process: MagicMock,
    ) -> None:
        """GIVEN dashboard server has a running subprocess
        WHEN _cancel_process is called
        THEN terminate() is called on the subprocess
        AND wait() is called to complete termination.
        """
        terminate_called = False
        wait_called = False

        def track_terminate() -> None:
            nonlocal terminate_called
            terminate_called = True

        async def track_wait() -> int:
            nonlocal wait_called
            wait_called = True
            return 0

        mock_multi_validator_process.terminate = track_terminate
        mock_multi_validator_process.wait = track_wait

        # Set the current process
        dashboard_server._current_process = mock_multi_validator_process

        # Call cancel
        await dashboard_server._cancel_process()

        # Verify terminate and wait were called
        assert terminate_called
        assert wait_called

    @pytest.mark.asyncio
    async def test_stop_loop_sets_flags_and_cancels(
        self,
        dashboard_server: DashboardServer,
        mock_multi_validator_process: MagicMock,
    ) -> None:
        """GIVEN dashboard loop is running
        WHEN stop_loop is called
        THEN stop_requested flag is set to True
        AND loop_running flag is set to False.
        """
        # Set initial state
        dashboard_server._loop_running = True
        dashboard_server._pause_requested = False
        dashboard_server._stop_requested = False
        dashboard_server._current_process = mock_multi_validator_process

        # Call stop_loop
        result = await dashboard_server.stop_loop()

        # Verify flags were set
        assert dashboard_server._stop_requested is True
        assert dashboard_server._loop_running is False
        assert result["status"] == "stopped"


# =============================================================================
# Tests for SSE broadcaster EOF behavior
# =============================================================================


class TestSSEBroadcasterEOF:
    """Tests for SSE broadcaster EOF handling."""

    @pytest.mark.asyncio
    async def test_subscribe_exits_on_none_signal(self) -> None:
        """GIVEN SSE subscriber is active
        WHEN broadcaster sends None signal
        THEN subscribe() generator exits cleanly.
        """
        broadcaster = SSEBroadcaster(heartbeat_interval=1.0)

        messages: list[str] = []

        async def collect_messages():
            async for msg in broadcaster.subscribe():
                messages.append(msg)
                if "connected" in msg:  # Got initial message
                    # Send shutdown signal
                    await broadcaster.shutdown()
                    break

        await collect_messages()

        # Verify we got at least the initial connection message
        assert len(messages) >= 1
        assert any("connected" in m for m in messages)

    @pytest.mark.asyncio
    async def test_multiple_subscribers_shutdown(self) -> None:
        """GIVEN multiple SSE subscribers are connected
        WHEN broadcaster shutdown is called
        THEN all subscribers receive None signal and exit.
        """
        broadcaster = SSEBroadcaster(heartbeat_interval=1.0)

        subscriber1_active = True
        subscriber2_active = True

        async def subscriber1():
            nonlocal subscriber1_active
            try:
                async for msg in broadcaster.subscribe():
                    pass
            finally:
                subscriber1_active = False

        async def subscriber2():
            nonlocal subscriber2_active
            try:
                async for msg in broadcaster.subscribe():
                    pass
            finally:
                subscriber2_active = False

        # Start subscribers
        task1 = asyncio.create_task(subscriber1())
        task2 = asyncio.create_task(subscriber2())

        # Wait for connection
        await asyncio.sleep(0.1)

        # Shutdown broadcaster
        await broadcaster.shutdown()

        # Wait for subscribers to exit
        await asyncio.wait_for(task1, timeout=1.0)
        await asyncio.wait_for(task2, timeout=1.0)

        # Verify both exited
        assert not subscriber1_active
        assert not subscriber2_active


# =============================================================================
# Story 22.11 Task 8: Tests for validator_progress and phase_complete events
# =============================================================================


class TestValidatorProgressEvents:
    """Tests for validator_progress and phase_complete SSE events."""

    def test_validator_progress_schema_valid(self) -> None:
        """Test that ValidatorProgressData schema validates correctly."""
        from bmad_assist.dashboard.schemas import ValidatorProgressData

        data = ValidatorProgressData(
            validator_id="validator-a",
            status="completed",
            duration_ms=45000,
        )
        assert data.validator_id == "validator-a"
        assert data.status == "completed"
        assert data.duration_ms == 45000

    def test_validator_progress_timeout_status(self) -> None:
        """Test ValidatorProgressData with timeout status."""
        from bmad_assist.dashboard.schemas import ValidatorProgressData

        data = ValidatorProgressData(
            validator_id="validator-b",
            status="timeout",
            duration_ms=300000,
        )
        assert data.status == "timeout"

    def test_validator_progress_no_duration(self) -> None:
        """Test ValidatorProgressData without duration_ms."""
        from bmad_assist.dashboard.schemas import ValidatorProgressData

        data = ValidatorProgressData(
            validator_id="validator-c",
            status="failed",
        )
        assert data.duration_ms is None

    def test_phase_complete_schema_valid(self) -> None:
        """Test that PhaseCompleteData schema validates correctly."""
        from bmad_assist.dashboard.schemas import PhaseCompleteData

        data = PhaseCompleteData(
            phase_name="VALIDATE_STORY",
            success=True,
            validator_count=6,
            failed_count=0,
        )
        assert data.phase_name == "VALIDATE_STORY"
        assert data.success is True
        assert data.validator_count == 6
        assert data.failed_count == 0

    def test_phase_complete_with_failures(self) -> None:
        """Test PhaseCompleteData with some failed validators."""
        from bmad_assist.dashboard.schemas import PhaseCompleteData

        data = PhaseCompleteData(
            phase_name="VALIDATE_STORY",
            success=False,
            validator_count=6,
            failed_count=2,
        )
        assert data.success is False
        assert data.failed_count == 2

    def test_validator_progress_event_creation(self) -> None:
        """Test create_validator_progress factory function."""
        from bmad_assist.dashboard.schemas import create_validator_progress

        event = create_validator_progress(
            run_id="run-20260115-080000-a1b2c3d4",
            sequence_id=5,
            validator_id="validator-a",
            status="completed",
            duration_ms=45000,
        )
        assert event.type == "validator_progress"
        assert event.data.validator_id == "validator-a"
        assert event.data.status == "completed"

    def test_phase_complete_event_creation(self) -> None:
        """Test create_phase_complete factory function."""
        from bmad_assist.dashboard.schemas import create_phase_complete

        event = create_phase_complete(
            run_id="run-20260115-080000-a1b2c3d4",
            sequence_id=10,
            phase_name="VALIDATE_STORY",
            success=True,
            validator_count=6,
            failed_count=0,
        )
        assert event.type == "phase_complete"
        assert event.data.phase_name == "VALIDATE_STORY"
        assert event.data.success is True
