"""Tests for execute_phase() single phase execution.

Story 6.2: Tests for execute_phase().
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import StateError


class TestExecutePhaseDispatch:
    """AC1: execute_phase dispatches to correct handler."""

    def test_execute_phase_dispatches_to_correct_handler(self) -> None:
        """AC1: execute_phase uses get_handler for dispatch."""
        from bmad_assist.core.loop import PhaseResult, execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_handler = MagicMock(return_value=PhaseResult.ok({"test": "value"}))
            mock_get.return_value = mock_handler

            result = execute_phase(state)

            mock_get.assert_called_once_with(Phase.DEV_STORY)
            mock_handler.assert_called_once_with(state)
            assert result.success is True
            assert result.outputs["test"] == "value"

    def test_execute_phase_preserves_handler_result_fields(self) -> None:
        """AC1: Handler's PhaseResult fields are preserved, duration_ms is added."""
        from bmad_assist.core.loop import PhaseResult, execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.CREATE_STORY)
        handler_result = PhaseResult.fail("Test failure")

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(return_value=handler_result)
            with patch(
                "bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.042]
            ):
                result = execute_phase(state)

                # success, error, next_phase MUST match handler's result
                assert result.success is handler_result.success
                assert result.error == handler_result.error
                assert result.next_phase == handler_result.next_phase
                # duration_ms MUST be added
                assert "duration_ms" in result.outputs
                assert result.outputs["duration_ms"] == 42

    def test_execute_phase_preserves_handler_outputs(self) -> None:
        """AC1: Handler's outputs are preserved and duration_ms is merged."""
        from bmad_assist.core.loop import PhaseResult, execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.CODE_REVIEW)
        handler_outputs = {"report": "review.md", "issues_count": 5}

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(return_value=PhaseResult.ok(handler_outputs))
            with patch(
                "bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.100]
            ):
                result = execute_phase(state)

                assert result.outputs["report"] == "review.md"
                assert result.outputs["issues_count"] == 5
                assert result.outputs["duration_ms"] == 100


class TestExecutePhaseNoneCurrentPhase:
    """AC2: execute_phase handles None current_phase."""

    def test_execute_phase_none_current_phase(self) -> None:
        """AC2: Returns failure when current_phase is None."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import State

        state = State(current_phase=None)
        result = execute_phase(state)

        assert result.success is False
        assert "no current phase set" in result.error

    def test_execute_phase_none_current_phase_has_duration(self) -> None:
        """AC2+AC5: duration_ms is present even for None phase case."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import State

        state = State(current_phase=None)

        with patch("bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.001]):
            result = execute_phase(state)

            assert "duration_ms" in result.outputs
            assert result.outputs["duration_ms"] == 1

    def test_execute_phase_none_does_not_call_handler(self) -> None:
        """AC2: Handler is NOT invoked when current_phase is None."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import State

        state = State(current_phase=None)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            execute_phase(state)
            mock_get.assert_not_called()


class TestExecutePhaseLogging:
    """AC3: execute_phase logs phase lifecycle."""

    def test_execute_phase_logs_phase_start(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC3: Logs INFO at phase start containing phase name."""
        from bmad_assist.core.loop import PhaseResult, execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.CODE_REVIEW)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(return_value=PhaseResult.ok())

            with caplog.at_level(logging.INFO):
                execute_phase(state)

            assert "Starting phase: code_review" in caplog.text

    def test_execute_phase_logs_phase_completion(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC3: Logs INFO at phase completion with success status."""
        from bmad_assist.core.loop import PhaseResult, execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(return_value=PhaseResult.ok())

            with caplog.at_level(logging.INFO):
                execute_phase(state)

            assert "dev_story" in caplog.text
            assert "completed" in caplog.text
            assert "success=True" in caplog.text

    def test_execute_phase_logs_duration(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC3: Logs duration in milliseconds."""
        from bmad_assist.core.loop import PhaseResult, execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.CREATE_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(return_value=PhaseResult.ok())
            with patch(
                "bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.123]
            ):
                with caplog.at_level(logging.INFO):
                    execute_phase(state)

                assert "duration: 123ms" in caplog.text

    def test_execute_phase_logs_failure_completion(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC3: Logs completion with success=False for failed handlers."""
        from bmad_assist.core.loop import PhaseResult, execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.VALIDATE_STORY_SYNTHESIS)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(return_value=PhaseResult.fail("validation error"))

            with caplog.at_level(logging.INFO):
                execute_phase(state)

            assert "success=False" in caplog.text


class TestExecutePhaseExceptionHandling:
    """AC4: execute_phase catches handler exceptions."""

    def test_execute_phase_catches_handler_runtime_error(self) -> None:
        """AC4: Catches RuntimeError and returns failure."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_handler = MagicMock(side_effect=RuntimeError("Unexpected error"))
            mock_get.return_value = mock_handler

            result = execute_phase(state)

            assert result.success is False
            assert "Handler error" in result.error
            assert "Unexpected error" in result.error

    def test_execute_phase_catches_handler_value_error(self) -> None:
        """AC4: Catches ValueError and returns failure."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.CODE_REVIEW)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_handler = MagicMock(side_effect=ValueError("Invalid value"))
            mock_get.return_value = mock_handler

            result = execute_phase(state)

            assert result.success is False
            assert "Handler error" in result.error
            assert "Invalid value" in result.error

    def test_execute_phase_exception_has_duration(self) -> None:
        """AC4+AC5: duration_ms is present even when exception occurs."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_handler = MagicMock(side_effect=RuntimeError("Unexpected error"))
            mock_get.return_value = mock_handler
            with patch(
                "bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.015]
            ):
                result = execute_phase(state)

                assert "duration_ms" in result.outputs
                assert result.outputs["duration_ms"] == 15

    def test_execute_phase_logs_exception_at_error_level(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC4: Logs ERROR with exception details."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_handler = MagicMock(side_effect=RuntimeError("Test exception"))
            mock_get.return_value = mock_handler

            with caplog.at_level(logging.ERROR):
                execute_phase(state)

            assert "Test exception" in caplog.text
            assert "handler failed" in caplog.text

    def test_execute_phase_exception_logs_completion_and_duration(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC3: Exception path logs completion status and duration."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(side_effect=RuntimeError("boom"))
            with patch(
                "bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.010]
            ), caplog.at_level(logging.INFO):
                execute_phase(state)

        # AC3 requires completion and duration logs even on exception
        assert "completed" in caplog.text
        assert "success=False" in caplog.text
        assert "duration" in caplog.text

    def test_execute_phase_handler_returns_invalid_type(self) -> None:
        """Defensive: Handler returning non-PhaseResult is caught."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(return_value=None)

            result = execute_phase(state)

            assert result.success is False
            assert "expected PhaseResult" in result.error
            assert "duration_ms" in result.outputs


class TestExecutePhaseTimeMeasurement:
    """AC5: execute_phase measures execution time."""

    def test_execute_phase_measures_duration_success(self) -> None:
        """AC5: Measures and stores execution time on success."""
        from bmad_assist.core.loop import PhaseResult, execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(return_value=PhaseResult.ok())
            with patch(
                "bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.123]
            ):
                result = execute_phase(state)

                assert result.success is True
                assert "duration_ms" in result.outputs
                assert result.outputs["duration_ms"] == 123

    def test_execute_phase_measures_duration_failure(self) -> None:
        """AC5: Measures and stores execution time on handler failure."""
        from bmad_assist.core.loop import PhaseResult, execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.VALIDATE_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(return_value=PhaseResult.fail("handler failed"))
            with patch(
                "bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.250]
            ):
                result = execute_phase(state)

                assert result.success is False
                assert "duration_ms" in result.outputs
                assert result.outputs["duration_ms"] == 250

    def test_execute_phase_duration_is_integer(self) -> None:
        """AC5: duration_ms is an integer (milliseconds, rounded)."""
        from bmad_assist.core.loop import PhaseResult, execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(return_value=PhaseResult.ok())
            with patch(
                "bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.0567]
            ):
                result = execute_phase(state)

                duration = result.outputs["duration_ms"]
                assert isinstance(duration, int)
                assert duration == 56

    def test_execute_phase_duration_overwrites_handler_duration(self) -> None:
        """AC5: duration_ms may overwrite if handler set it."""
        from bmad_assist.core.loop import PhaseResult, execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)
        # Handler provides its own duration_ms
        handler_outputs = {"duration_ms": 999, "other": "data"}

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.return_value = MagicMock(return_value=PhaseResult.ok(handler_outputs))
            with patch(
                "bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.042]
            ):
                result = execute_phase(state)

                # execute_phase's duration_ms overwrites handler's
                assert result.outputs["duration_ms"] == 42
                assert result.outputs["other"] == "data"


class TestExecutePhaseStateError:
    """AC6: execute_phase handles StateError from get_handler."""

    def test_execute_phase_handles_state_error(self) -> None:
        """AC6: Catches StateError from get_handler with raw message (no prefix)."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.side_effect = StateError("Unknown workflow phase")

            result = execute_phase(state)

            assert result.success is False
            # AC6: StateError message should be raw (no "Handler error:" prefix)
            assert result.error == "Unknown workflow phase"

    def test_execute_phase_state_error_has_duration(self) -> None:
        """AC6+AC5: duration_ms is present even for StateError."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.side_effect = StateError("Unknown workflow phase")
            with patch("bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.05]):
                result = execute_phase(state)

                assert "duration_ms" in result.outputs
                assert result.outputs["duration_ms"] == 50

    def test_execute_phase_state_error_logged_at_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC6: StateError is logged at ERROR level."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.side_effect = StateError("Unknown workflow phase")

            with caplog.at_level(logging.ERROR):
                execute_phase(state)

            assert "Unknown workflow phase" in caplog.text
            assert "dispatch failed" in caplog.text

    def test_execute_phase_state_error_logs_completion_and_duration(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC3+AC6: StateError path logs completion and duration."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        with patch("bmad_assist.core.loop.dispatch.get_handler") as mock_get:
            mock_get.side_effect = StateError("Unknown workflow phase")
            with patch(
                "bmad_assist.core.loop.dispatch.time.perf_counter", side_effect=[0.0, 0.005]
            ), caplog.at_level(logging.INFO):
                execute_phase(state)

        # AC3 requires completion and duration logs even for StateError
        assert "completed" in caplog.text
        assert "success=False" in caplog.text
        assert "duration" in caplog.text


class TestExecutePhaseIntegration:
    """Integration tests for execute_phase with real handlers."""

    def test_execute_phase_with_real_stub_handler(self) -> None:
        """Integration: execute_phase works with real stub handlers."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        state = State(current_phase=Phase.DEV_STORY)

        result = execute_phase(state)

        # Stub handlers return failure with "not yet implemented"
        assert result.success is False
        assert "not yet implemented" in result.error
        assert "duration_ms" in result.outputs

    def test_execute_phase_all_phases_work(self) -> None:
        """Integration: execute_phase works for all phases."""
        from bmad_assist.core.loop import execute_phase
        from bmad_assist.core.state import Phase, State

        for phase in Phase:
            state = State(current_phase=phase)
            result = execute_phase(state)

            # All stubs should return failure
            assert result.success is False
            assert "not yet implemented" in result.error
            assert "duration_ms" in result.outputs
            assert isinstance(result.outputs["duration_ms"], int)


class TestExecutePhaseExports:
    """Test execute_phase is properly exported."""

    def test_execute_phase_exported_from_loop(self) -> None:
        """execute_phase is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "execute_phase" in loop.__all__

    def test_execute_phase_importable_from_loop(self) -> None:
        """execute_phase can be imported from bmad_assist.core.loop."""
        from bmad_assist.core.loop import execute_phase

        assert callable(execute_phase)
