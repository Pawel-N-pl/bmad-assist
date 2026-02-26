"""Tests for Story 6.6: Loop Interruption Handling.

Tests signal handling infrastructure (SIGINT, SIGTERM) and graceful shutdown
functionality in the main development loop.
"""

import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.loop import (
    LoopExitReason,
    Phase,
    PhaseResult,
    State,
    _get_interrupt_exit_reason,
    _handle_sigint,
    _handle_sigterm,
    get_received_signal,
    register_signal_handlers,
    request_shutdown,
    reset_shutdown,
    run_loop,
    shutdown_requested,
    unregister_signal_handlers,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def clean_shutdown_state():
    """Ensure clean shutdown state before and after each test."""
    reset_shutdown()
    yield
    reset_shutdown()


@pytest.fixture
def mock_config(tmp_path: Path) -> MagicMock:
    """Create a mock Config object."""
    config = MagicMock()
    config.state_path = tmp_path / "state.yaml"
    config.providers.master.provider = "claude"
    config.providers.master.model = "claude-sonnet-4-20250514"
    return config


@pytest.fixture
def basic_epic_list() -> list[int]:
    """Provide a basic epic list for testing."""
    return [1, 2]


@pytest.fixture
def basic_story_loader():
    """Provide a basic story loader for testing."""
    return lambda epic: [f"{epic}.1", f"{epic}.2"]


# =============================================================================
# Shutdown Flag Tests
# =============================================================================


class TestShutdownRequestedFlag:
    """Tests for shutdown_requested(), request_shutdown(), reset_shutdown()."""

    def test_shutdown_requested_initially_false(self):
        """Shutdown flag starts as False after reset."""
        reset_shutdown()
        assert shutdown_requested() is False

    def test_request_shutdown_sets_flag(self):
        """request_shutdown() sets the shutdown flag."""
        reset_shutdown()
        request_shutdown(signal.SIGINT)
        assert shutdown_requested() is True

    def test_reset_shutdown_clears_flag(self):
        """reset_shutdown() clears the shutdown flag."""
        request_shutdown(signal.SIGINT)
        assert shutdown_requested() is True
        reset_shutdown()
        assert shutdown_requested() is False

    def test_request_shutdown_stores_signal_number(self):
        """request_shutdown() stores the signal number for exit code calculation."""
        reset_shutdown()
        request_shutdown(signal.SIGINT)
        assert get_received_signal() == signal.SIGINT

    def test_request_shutdown_with_sigterm(self):
        """request_shutdown() stores SIGTERM signal number."""
        reset_shutdown()
        request_shutdown(signal.SIGTERM)
        assert get_received_signal() == signal.SIGTERM

    def test_reset_shutdown_clears_signal_number(self):
        """reset_shutdown() clears the stored signal number."""
        request_shutdown(signal.SIGINT)
        reset_shutdown()
        assert get_received_signal() is None


# =============================================================================
# Signal Handler Tests
# =============================================================================


class TestSignalHandlers:
    """Tests for signal handler functions.

    Note: Signal handlers now do hard kill (os._exit), so we mock those calls.
    """

    def test_sigint_handler_calls_exit(self):
        """SIGINT handler calls os._exit with code 130."""
        with patch("bmad_assist.core.loop.signals.os._exit") as mock_exit:
            with patch("bmad_assist.core.loop.signals.os.killpg"):
                _handle_sigint(signal.SIGINT, None)
                mock_exit.assert_called_once_with(130)

    def test_sigterm_handler_calls_exit(self):
        """SIGTERM handler calls os._exit with code 143."""
        with patch("bmad_assist.core.loop.signals.os._exit") as mock_exit:
            with patch("bmad_assist.core.loop.signals.os.killpg"):
                _handle_sigterm(signal.SIGTERM, None)
                mock_exit.assert_called_once_with(143)

    def test_sigint_handler_kills_process_group(self):
        """SIGINT handler attempts to kill process group."""
        with patch("bmad_assist.core.loop.signals.os._exit"):
            with patch("bmad_assist.core.loop.signals.os.killpg") as mock_killpg:
                with patch("bmad_assist.core.loop.signals.os.getpid", return_value=1234):
                    with patch("bmad_assist.core.loop.signals.os.getpgid", return_value=1234):
                        _handle_sigint(signal.SIGINT, None)
                        mock_killpg.assert_called_once_with(1234, signal.SIGKILL)

    def test_sigterm_handler_kills_process_group(self):
        """SIGTERM handler attempts to kill process group."""
        with patch("bmad_assist.core.loop.signals.os._exit"):
            with patch("bmad_assist.core.loop.signals.os.killpg") as mock_killpg:
                with patch("bmad_assist.core.loop.signals.os.getpid", return_value=1234):
                    with patch("bmad_assist.core.loop.signals.os.getpgid", return_value=1234):
                        _handle_sigterm(signal.SIGTERM, None)
                        mock_killpg.assert_called_once_with(1234, signal.SIGKILL)

    def test_handler_survives_killpg_failure(self):
        """Handler still exits even if killpg fails."""
        with patch("bmad_assist.core.loop.signals.os._exit") as mock_exit:
            with patch("bmad_assist.core.loop.signals.os.killpg", side_effect=OSError("No such process")):
                _handle_sigint(signal.SIGINT, None)
                # Should still call exit despite killpg failure
                mock_exit.assert_called_once_with(130)


# =============================================================================
# Signal Registration Tests
# =============================================================================


class TestSignalRegistration:
    """Tests for signal handler registration and unregistration."""

    def test_register_from_non_main_thread_raises_state_error(self):
        """register_signal_handlers() raises StateError if not from main thread."""
        import threading

        from bmad_assist.core.exceptions import StateError

        result_box = {"error": None}

        def try_register():
            try:
                register_signal_handlers()
            except StateError as e:
                result_box["error"] = e

        thread = threading.Thread(target=try_register)
        thread.start()
        thread.join()

        assert result_box["error"] is not None
        assert "main thread" in str(result_box["error"])

    def test_register_signal_handlers_installs_handlers(self):
        """register_signal_handlers() installs SIGINT and SIGTERM handlers."""
        with patch("signal.signal") as mock_signal:
            mock_signal.return_value = signal.SIG_DFL
            register_signal_handlers()

            # Should register both SIGINT and SIGTERM
            assert mock_signal.call_count == 2
            calls = [call[0] for call in mock_signal.call_args_list]
            assert (signal.SIGINT, _handle_sigint) in calls
            assert (signal.SIGTERM, _handle_sigterm) in calls

    def test_unregister_signal_handlers_restores_previous(self):
        """unregister_signal_handlers() restores previous handlers."""
        # First register to save previous handlers
        with patch("signal.signal") as mock_signal:
            mock_signal.return_value = signal.SIG_DFL
            register_signal_handlers()

        # Now unregister
        with patch("signal.signal") as mock_signal:
            unregister_signal_handlers()

            # Should restore both handlers
            assert mock_signal.call_count == 2

    def test_register_saves_previous_handlers(self):
        """register_signal_handlers() saves previous handlers for restoration."""
        original_int = signal.getsignal(signal.SIGINT)
        original_term = signal.getsignal(signal.SIGTERM)

        try:
            register_signal_handlers()
            # Verify handlers were installed
            assert signal.getsignal(signal.SIGINT) == _handle_sigint
            assert signal.getsignal(signal.SIGTERM) == _handle_sigterm

            unregister_signal_handlers()
            # Verify original handlers restored
            assert signal.getsignal(signal.SIGINT) == original_int
            assert signal.getsignal(signal.SIGTERM) == original_term
        finally:
            # Ensure cleanup
            signal.signal(signal.SIGINT, original_int)
            signal.signal(signal.SIGTERM, original_term)


# =============================================================================
# Exit Reason Determination Tests
# =============================================================================


class TestGetInterruptExitReason:
    """Tests for _get_interrupt_exit_reason()."""

    def test_sigint_returns_interrupted_sigint(self):
        """SIGINT returns INTERRUPTED_SIGINT exit reason."""
        reset_shutdown()
        request_shutdown(signal.SIGINT)
        assert _get_interrupt_exit_reason() == LoopExitReason.INTERRUPTED_SIGINT

    def test_sigterm_returns_interrupted_sigterm(self):
        """SIGTERM returns INTERRUPTED_SIGTERM exit reason."""
        reset_shutdown()
        request_shutdown(signal.SIGTERM)
        assert _get_interrupt_exit_reason() == LoopExitReason.INTERRUPTED_SIGTERM

    def test_unknown_signal_defaults_to_sigint(self):
        """Unknown signal defaults to INTERRUPTED_SIGINT."""
        reset_shutdown()
        request_shutdown(99)  # Unknown signal
        assert _get_interrupt_exit_reason() == LoopExitReason.INTERRUPTED_SIGINT


# =============================================================================
# LoopExitReason Enum Tests
# =============================================================================


class TestLoopExitReasonEnum:
    """Tests for LoopExitReason enum."""

    def test_enum_values(self):
        """Verify all expected enum values exist."""
        assert LoopExitReason.COMPLETED.value == "completed"
        assert LoopExitReason.INTERRUPTED_SIGINT.value == "interrupted_sigint"
        assert LoopExitReason.INTERRUPTED_SIGTERM.value == "interrupted_sigterm"
        assert LoopExitReason.GUARDIAN_HALT.value == "guardian_halt"

    def test_enum_is_string_subclass(self):
        """LoopExitReason is a str enum for backward compatibility."""
        assert isinstance(LoopExitReason.COMPLETED, str)
        assert LoopExitReason.COMPLETED == "completed"


# =============================================================================
# run_loop Shutdown Integration Tests
# =============================================================================


class TestRunLoopShutdownIntegration:
    """Integration tests for shutdown handling in run_loop()."""

    def test_run_loop_returns_interrupted_sigint_on_shutdown(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        basic_epic_list: list[int],
        basic_story_loader,
    ):
        """run_loop() returns INTERRUPTED_SIGINT when shutdown requested."""
        with patch("bmad_assist.core.loop.runner.load_state") as mock_load:
            mock_load.return_value = State(
                current_epic=1,
                current_story="1.1",
                current_phase=Phase.CREATE_STORY,
            )
            with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:

                def side_effect(state):
                    # Set shutdown after first phase
                    request_shutdown(signal.SIGINT)
                    return PhaseResult.ok()

                mock_exec.side_effect = side_effect

                with patch("bmad_assist.core.loop.runner.save_state"):
                    result = run_loop(mock_config, tmp_path, basic_epic_list, basic_story_loader)

                    assert result == LoopExitReason.INTERRUPTED_SIGINT

    def test_run_loop_returns_interrupted_sigterm_on_shutdown(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        basic_epic_list: list[int],
        basic_story_loader,
    ):
        """run_loop() returns INTERRUPTED_SIGTERM when SIGTERM received."""
        with patch("bmad_assist.core.loop.runner.load_state") as mock_load:
            mock_load.return_value = State(
                current_epic=1,
                current_story="1.1",
                current_phase=Phase.CREATE_STORY,
            )
            with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:

                def side_effect(state):
                    request_shutdown(signal.SIGTERM)
                    return PhaseResult.ok()

                mock_exec.side_effect = side_effect

                with patch("bmad_assist.core.loop.runner.save_state"):
                    result = run_loop(mock_config, tmp_path, basic_epic_list, basic_story_loader)

                    assert result == LoopExitReason.INTERRUPTED_SIGTERM

    def test_run_loop_saves_state_before_shutdown_exit(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        basic_epic_list: list[int],
        basic_story_loader,
    ):
        """State is saved before shutdown exit."""
        with patch("bmad_assist.core.loop.runner.load_state") as mock_load:
            mock_load.return_value = State(
                current_epic=1,
                current_story="1.1",
                current_phase=Phase.CREATE_STORY,
            )
            with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:

                def side_effect(state):
                    request_shutdown(signal.SIGINT)
                    return PhaseResult.ok()

                mock_exec.side_effect = side_effect

                with patch("bmad_assist.core.loop.runner.save_state") as mock_save:
                    run_loop(mock_config, tmp_path, basic_epic_list, basic_story_loader)

                    # Verify save_state was called
                    assert mock_save.called

    def test_run_loop_unregisters_handlers_on_normal_exit(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        basic_epic_list: list[int],
        basic_story_loader,
    ):
        """Signal handlers are unregistered on normal exit."""
        original_int = signal.getsignal(signal.SIGINT)
        original_term = signal.getsignal(signal.SIGTERM)

        try:
            with patch("bmad_assist.core.loop.runner.load_state") as mock_load:
                mock_load.return_value = State(
                    current_epic=1,
                    current_story="1.1",
                    current_phase=Phase.CREATE_STORY,
                )
                with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:
                    mock_exec.side_effect = lambda state: (
                        request_shutdown(signal.SIGINT),
                        PhaseResult.ok(),
                    )[1]

                    with patch("bmad_assist.core.loop.runner.save_state"):
                        run_loop(mock_config, tmp_path, basic_epic_list, basic_story_loader)

            # After run_loop exits, handlers should be restored
            assert signal.getsignal(signal.SIGINT) == original_int
            assert signal.getsignal(signal.SIGTERM) == original_term
        finally:
            signal.signal(signal.SIGINT, original_int)
            signal.signal(signal.SIGTERM, original_term)

    def test_run_loop_unregisters_handlers_on_exception(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        basic_epic_list: list[int],
        basic_story_loader,
    ):
        """Signal handlers are unregistered even when exception occurs."""
        original_int = signal.getsignal(signal.SIGINT)
        original_term = signal.getsignal(signal.SIGTERM)

        try:
            with patch("bmad_assist.core.loop.runner.load_state") as mock_load:
                mock_load.side_effect = RuntimeError("Test error")

                with pytest.raises(RuntimeError, match="Test error"):
                    run_loop(mock_config, tmp_path, basic_epic_list, basic_story_loader)

            # After run_loop exits (even via exception), handlers should be restored
            assert signal.getsignal(signal.SIGINT) == original_int
            assert signal.getsignal(signal.SIGTERM) == original_term
        finally:
            signal.signal(signal.SIGINT, original_int)
            signal.signal(signal.SIGTERM, original_term)

    def test_run_loop_clears_previous_shutdown_state(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        basic_epic_list: list[int],
        basic_story_loader,
    ):
        """run_loop() clears any previous shutdown state at start."""
        # Set shutdown state before calling run_loop
        request_shutdown(signal.SIGINT)
        assert shutdown_requested() is True

        with patch("bmad_assist.core.loop.runner.load_state") as mock_load:
            mock_load.return_value = State(
                current_epic=1,
                current_story="1.1",
                current_phase=Phase.CREATE_STORY,
            )
            with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:
                call_count = [0]

                def side_effect(state):
                    call_count[0] += 1
                    if call_count[0] == 1:
                        # First call - shutdown was cleared so we should continue
                        return PhaseResult.ok()
                    # Second call - set shutdown to exit
                    request_shutdown(signal.SIGINT)
                    return PhaseResult.ok()

                mock_exec.side_effect = side_effect

                with patch("bmad_assist.core.loop.runner.save_state"):
                    run_loop(mock_config, tmp_path, basic_epic_list, basic_story_loader)

                # Loop should have run at least twice (shutdown was cleared initially)
                assert call_count[0] >= 2

    def test_run_loop_returns_guardian_halt(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        basic_epic_list: list[int],
        basic_story_loader,
    ):
        """run_loop() returns GUARDIAN_HALT when guardian halts."""
        from bmad_assist.core.loop import GuardianDecision

        with patch("bmad_assist.core.loop.runner.load_state") as mock_load:
            mock_load.return_value = State(
                current_epic=1,
                current_story="1.1",
                current_phase=Phase.CREATE_STORY,
            )
            with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:
                mock_exec.return_value = PhaseResult.fail("Test failure")

                with patch("bmad_assist.core.loop.runner.guardian_check_anomaly") as mock_guardian:
                    mock_guardian.return_value = GuardianDecision.HALT

                    with patch("bmad_assist.core.loop.runner.save_state"):
                        result = run_loop(
                            mock_config, tmp_path, basic_epic_list, basic_story_loader
                        )

                        assert result == LoopExitReason.GUARDIAN_HALT


# =============================================================================
# Shutdown During Special Transitions Tests
# =============================================================================


class TestShutdownDuringTransitions:
    """Tests for shutdown handling during special phase transitions."""

    def test_shutdown_after_retrospective_transition(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        basic_epic_list: list[int],
    ):
        """Shutdown is checked after RETROSPECTIVE transition save_state."""
        # Loader that returns single-story epic to trigger retrospective
        loader = lambda epic: [f"{epic}.1"]

        with patch("bmad_assist.core.loop.runner.load_state") as mock_load:
            mock_load.return_value = State(
                current_epic=1,
                current_story="1.1",
                current_phase=Phase.CODE_REVIEW_SYNTHESIS,
            )
            with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:
                mock_exec.return_value = PhaseResult.ok()

                save_count = [0]

                def save_side_effect(state, path):
                    save_count[0] += 1
                    # Set shutdown after RETROSPECTIVE transition save
                    if save_count[0] >= 2:
                        request_shutdown(signal.SIGINT)

                with patch("bmad_assist.core.loop.runner.save_state", side_effect=save_side_effect):
                    with patch(
                        "bmad_assist.core.loop.runner.handle_story_completion"
                    ) as mock_handle:
                        # Return is_epic_complete=True to trigger RETROSPECTIVE
                        mock_state = State(
                            current_epic=1,
                            current_story="1.1",
                            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
                            completed_stories=["1.1"],
                        )
                        mock_handle.return_value = (mock_state, True)

                        result = run_loop(mock_config, tmp_path, basic_epic_list, loader)

                        assert result == LoopExitReason.INTERRUPTED_SIGINT


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Edge case tests for signal handling."""

    def test_shutdown_immediately_after_loop_start(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        basic_epic_list: list[int],
        basic_story_loader,
    ):
        """Shutdown right after loop starts still saves state."""
        with patch("bmad_assist.core.loop.runner.load_state") as mock_load:
            mock_load.return_value = State(
                current_epic=1,
                current_story="1.1",
                current_phase=Phase.CREATE_STORY,
            )
            with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:
                # Set shutdown immediately in first phase
                mock_exec.side_effect = lambda state: (
                    request_shutdown(signal.SIGINT),
                    PhaseResult.ok(),
                )[1]

                with patch("bmad_assist.core.loop.runner.save_state") as mock_save:
                    result = run_loop(mock_config, tmp_path, basic_epic_list, basic_story_loader)

                    assert result == LoopExitReason.INTERRUPTED_SIGINT
                    # State should have been saved at least once (initial + after phase)
                    assert mock_save.call_count >= 1

    def test_shutdown_during_failure_path(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        basic_epic_list: list[int],
        basic_story_loader,
    ):
        """Shutdown during failure path is handled correctly."""
        from bmad_assist.core.loop import GuardianDecision

        with patch("bmad_assist.core.loop.runner.load_state") as mock_load:
            mock_load.return_value = State(
                current_epic=1,
                current_story="1.1",
                current_phase=Phase.CREATE_STORY,
            )
            with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:
                mock_exec.return_value = PhaseResult.fail("Test failure")

                with patch("bmad_assist.core.loop.runner.guardian_check_anomaly") as mock_guardian:
                    mock_guardian.return_value = GuardianDecision.CONTINUE

                    save_count = [0]

                    def save_side_effect(state, path):
                        save_count[0] += 1
                        # Set shutdown after failure path save
                        request_shutdown(signal.SIGTERM)

                    with patch(
                        "bmad_assist.core.loop.runner.save_state", side_effect=save_side_effect
                    ):
                        result = run_loop(
                            mock_config, tmp_path, basic_epic_list, basic_story_loader
                        )

                        assert result == LoopExitReason.INTERRUPTED_SIGTERM

    def test_handler_idempotent_multiple_calls(self):
        """Signal handler is idempotent - multiple calls always exit."""
        with patch("bmad_assist.core.loop.signals.os._exit") as mock_exit:
            with patch("bmad_assist.core.loop.signals.os.killpg"):
                # Call multiple times
                for _ in range(10):
                    _handle_sigint(signal.SIGINT, None)

                # Should have called exit 10 times
                assert mock_exit.call_count == 10

    def test_reset_after_register_is_safe(self):
        """Calling reset_shutdown after register_signal_handlers is safe."""
        original_int = signal.getsignal(signal.SIGINT)
        original_term = signal.getsignal(signal.SIGTERM)

        try:
            register_signal_handlers()
            reset_shutdown()  # Should not affect signal handlers

            # Handlers should still be registered
            assert signal.getsignal(signal.SIGINT) == _handle_sigint
            assert signal.getsignal(signal.SIGTERM) == _handle_sigterm

            unregister_signal_handlers()
        finally:
            signal.signal(signal.SIGINT, original_int)
            signal.signal(signal.SIGTERM, original_term)
