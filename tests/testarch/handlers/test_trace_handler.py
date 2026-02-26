"""Tests for TraceHandler (testarch-7).

These tests verify:
- AC #1: TraceHandler class creation
- AC #2: Trace mode configuration (off/auto/on)
- AC #3: Trace workflow invocation (placeholder)
- AC #4: Gate decision extraction
- AC #5: Traceability matrix output (placeholder)
- AC #6: Integration with retrospective phase
- AC #7: RetrospectiveHandler modification
- AC #8: PhaseResult structure
- AC #9: Error handling
- AC #10: Logging
- AC #11: Config model (trace_on_epic_complete)
- AC #12: Unit tests (this file)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import Phase, State

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock Config with testarch settings."""
    config = MagicMock()
    config.testarch = MagicMock()
    config.testarch.engagement_model = "auto"  # Allow workflows to run
    config.testarch.trace_on_epic_complete = "auto"
    config.benchmarking = MagicMock()
    config.benchmarking.enabled = False

    config.providers = MagicMock()
    config.providers.master = MagicMock()
    config.providers.master.provider = "claude"
    config.providers.master.model = "opus"
    config.timeout = 30
    return config


@pytest.fixture
def handler(mock_config: MagicMock, tmp_path: Path) -> "TraceHandler":
    """Create TraceHandler instance with mock config."""
    from bmad_assist.testarch.handlers import TraceHandler

    return TraceHandler(mock_config, tmp_path)


@pytest.fixture
def state_with_atdd_ran() -> State:
    """State with atdd_ran_in_epic=True."""
    return State(
        current_epic="testarch",
        current_story="testarch.7",
        current_phase=Phase.RETROSPECTIVE,
        atdd_ran_in_epic=True,
    )


@pytest.fixture
def state_without_atdd_ran() -> State:
    """State with atdd_ran_in_epic=False."""
    return State(
        current_epic="testarch",
        current_story="testarch.7",
        current_phase=Phase.RETROSPECTIVE,
        atdd_ran_in_epic=False,
    )


# =============================================================================
# AC #1: TraceHandler class creation
# =============================================================================


class TestTraceHandlerCreation:
    """Test TraceHandler class creation (AC #1)."""

    def test_handler_created_successfully(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """TraceHandler can be instantiated."""
        from bmad_assist.testarch.handlers import TraceHandler

        handler = TraceHandler(mock_config, tmp_path)
        assert handler is not None
        assert handler.config is mock_config
        assert handler.project_path == tmp_path

    def test_handler_phase_name(self, handler: "TraceHandler") -> None:
        """TraceHandler.phase_name returns 'trace'."""
        assert handler.phase_name == "trace"


# =============================================================================
# AC #2: Trace mode configuration
# =============================================================================


class TestTraceModeOff:
    """Test trace skipped when mode=off (AC #2)."""

    def test_run_skips_when_mode_off(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_with_atdd_ran: State
    ) -> None:
        """run() skips with mode=off."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch.trace_on_epic_complete = "off"
        handler = TraceHandler(mock_config, tmp_path)

        result = handler.run(state_with_atdd_ran)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("trace_mode") == "off"
        assert result.outputs.get("reason") == "trace_on_epic_complete=off"


class TestTraceModeNotConfigured:
    """Test trace skipped when testarch not configured (AC #9)."""

    def test_run_skips_when_not_configured(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_with_atdd_ran: State
    ) -> None:
        """run() skips when testarch is None."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch = None
        handler = TraceHandler(mock_config, tmp_path)

        result = handler.run(state_with_atdd_ran)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("trace_mode") == "not_configured"
        assert result.outputs.get("reason") == "testarch not configured"


class TestTraceModeOn:
    """Test trace always runs when mode=on (AC #2)."""

    def test_run_executes_when_mode_on(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_without_atdd_ran: State
    ) -> None:
        """run() executes trace when mode=on, regardless of atdd_ran_in_epic."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch.trace_on_epic_complete = "on"
        handler = TraceHandler(mock_config, tmp_path)

        with patch.object(handler, "_invoke_trace_workflow") as mock_invoke:
            mock_invoke.return_value = PhaseResult.ok(
                {
                    "response": "Gate Decision: PASS",
                    "gate_decision": "PASS",
                    "trace_file": None,
                    "placeholder": True,
                }
            )

            result = handler.run(state_without_atdd_ran)

        assert result.success is True
        assert result.outputs.get("skipped") is None or result.outputs.get("skipped") is False
        mock_invoke.assert_called_once()


class TestTraceModeAuto:
    """Test trace in auto mode checks atdd_ran_in_epic (AC #2)."""

    def test_run_executes_when_auto_and_atdd_ran(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_with_atdd_ran: State
    ) -> None:
        """run() executes when mode=auto and atdd_ran_in_epic=True."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch.trace_on_epic_complete = "auto"
        handler = TraceHandler(mock_config, tmp_path)

        with patch.object(handler, "_invoke_trace_workflow") as mock_invoke:
            mock_invoke.return_value = PhaseResult.ok(
                {
                    "response": "Gate Decision: PASS",
                    "gate_decision": "PASS",
                    "trace_file": None,
                }
            )

            result = handler.run(state_with_atdd_ran)

        assert result.success is True
        mock_invoke.assert_called_once()

    def test_run_skips_when_auto_and_no_atdd(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_without_atdd_ran: State
    ) -> None:
        """run() skips when mode=auto and atdd_ran_in_epic=False."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch.trace_on_epic_complete = "auto"
        handler = TraceHandler(mock_config, tmp_path)

        result = handler.run(state_without_atdd_ran)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("trace_mode") == "auto"
        assert result.outputs.get("reason") == "no ATDD ran in epic"


# =============================================================================
# AC #4: Gate decision extraction
# =============================================================================


class TestGateDecisionExtraction:
    """Test _extract_gate_decision helper (AC #4)."""

    def test_extract_pass(self, handler: "TraceHandler") -> None:
        """Extracts PASS from output."""
        output = "Analysis complete. Gate Decision: PASS\n\nMatrix generated."
        assert handler._extract_gate_decision(output) == "PASS"

    def test_extract_fail(self, handler: "TraceHandler") -> None:
        """Extracts FAIL from output."""
        output = "Requirements missing. Gate Decision: FAIL"
        assert handler._extract_gate_decision(output) == "FAIL"

    def test_extract_concerns(self, handler: "TraceHandler") -> None:
        """Extracts CONCERNS from output."""
        output = "Some issues found. Gate Decision: CONCERNS"
        assert handler._extract_gate_decision(output) == "CONCERNS"

    def test_extract_waived(self, handler: "TraceHandler") -> None:
        """Extracts WAIVED from output."""
        output = "Manual override. Gate Decision: WAIVED"
        assert handler._extract_gate_decision(output) == "WAIVED"

    def test_extract_case_insensitive(self, handler: "TraceHandler") -> None:
        """Extracts decisions case-insensitively."""
        assert handler._extract_gate_decision("gate: pass") == "PASS"
        assert handler._extract_gate_decision("gate: Pass") == "PASS"
        assert handler._extract_gate_decision("gate: PASS") == "PASS"

    def test_extract_avoids_partial_matches(self, handler: "TraceHandler") -> None:
        """Avoids partial matches like PASSED, FAILING."""
        # "PASSED" should not match "PASS" - requires word boundary
        output = "Tests PASSED successfully"
        # PASS should not be extracted from PASSED
        assert handler._extract_gate_decision(output) is None

    def test_extract_priority_fail_over_pass(self, handler: "TraceHandler") -> None:
        """FAIL has priority over PASS if both present."""
        output = "Result: PASS on module A, FAIL on module B"
        assert handler._extract_gate_decision(output) == "FAIL"

    def test_extract_none_when_not_found(self, handler: "TraceHandler") -> None:
        """Returns None when no decision found."""
        output = "No decision in this output"
        assert handler._extract_gate_decision(output) is None


# =============================================================================
# AC #3: Trace workflow invocation (implemented in testarch-8)
# =============================================================================


class TestTraceWorkflowInvocation:
    """Test _invoke_trace_workflow (now implemented with compiler integration)."""

    def test_invoke_returns_error_when_paths_not_initialized(
        self,
        handler: "TraceHandler",
        state_with_atdd_ran: State
    ) -> None:
        """Returns error PhaseResult when paths singleton not initialized.

        Note: Full integration tests are in test_trace_integration.py which
        properly mocks get_paths().
        """
        result = handler._invoke_trace_workflow(state_with_atdd_ran)

        # Without paths initialized, the handler fails gracefully
        assert result.success is False
        assert "Paths not initialized" in result.error


# =============================================================================
# AC #8: PhaseResult structure
# =============================================================================


class TestPhaseResultStructure:
    """Test PhaseResult outputs structure (AC #8)."""

    def test_success_result_structure(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_with_atdd_ran: State
    ) -> None:
        """Success result contains required outputs when workflow fails gracefully.

        Note: Without paths initialized, the workflow fails gracefully.
        Full success tests are in test_trace_integration.py.
        """
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch.trace_on_epic_complete = "on"
        handler = TraceHandler(mock_config, tmp_path)

        result = handler.run(state_with_atdd_ran)

        # Handler fails gracefully when paths not initialized
        assert result.success is False
        assert "error" in result.error.lower() or "Paths not initialized" in result.error

    def test_skip_result_structure(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_with_atdd_ran: State
    ) -> None:
        """Skip result contains required outputs."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch.trace_on_epic_complete = "off"
        handler = TraceHandler(mock_config, tmp_path)

        result = handler.run(state_with_atdd_ran)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "reason" in result.outputs
        assert "trace_mode" in result.outputs


# =============================================================================
# AC #9: Error handling
# =============================================================================


class TestErrorHandling:
    """Test error handling (AC #9)."""

    def test_workflow_error_returns_fail(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_with_atdd_ran: State
    ) -> None:
        """Workflow invocation error returns PhaseResult.fail()."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch.trace_on_epic_complete = "on"
        handler = TraceHandler(mock_config, tmp_path)

        with patch.object(
            handler,
            "_invoke_trace_workflow",
            side_effect=RuntimeError("Provider failed")
        ):
            result = handler.run(state_with_atdd_ran)

        assert result.success is False
        assert "Provider failed" in (result.error or "")


# =============================================================================
# AC #3: Check trace mode logic
# =============================================================================


class TestCheckTraceModeLogic:
    """Test _check_mode with trace config."""

    def test_check_trace_mode_off(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('off', False) for mode=off."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch.trace_on_epic_complete = "off"
        handler = TraceHandler(mock_config, tmp_path)
        state = State(current_epic="testarch", atdd_ran_in_epic=True)

        mode, should_run = handler._check_mode(state, "trace_on_epic_complete")

        assert mode == "off"
        assert should_run is False

    def test_check_trace_mode_on(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('on', True) for mode=on."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch.trace_on_epic_complete = "on"
        handler = TraceHandler(mock_config, tmp_path)
        state = State(current_epic="testarch", atdd_ran_in_epic=False)

        mode, should_run = handler._check_mode(state, "trace_on_epic_complete")

        assert mode == "on"
        assert should_run is True

    def test_check_trace_mode_auto_with_atdd(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('auto', True) when mode=auto and atdd_ran_in_epic=True."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch.trace_on_epic_complete = "auto"
        handler = TraceHandler(mock_config, tmp_path)
        state = State(current_epic="testarch", atdd_ran_in_epic=True)

        mode, should_run = handler._check_mode(state, "trace_on_epic_complete", "atdd_ran_in_epic")

        assert mode == "auto"
        assert should_run is True

    def test_check_trace_mode_auto_without_atdd(
        self,
        mock_config: MagicMock,
        tmp_path: Path
    ) -> None:
        """Returns ('auto', False) when mode=auto and atdd_ran_in_epic=False."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch.trace_on_epic_complete = "auto"
        handler = TraceHandler(mock_config, tmp_path)
        state = State(current_epic="testarch", atdd_ran_in_epic=False)

        mode, should_run = handler._check_mode(state, "trace_on_epic_complete", "atdd_ran_in_epic")

        assert mode == "auto"
        assert should_run is False

    def test_check_trace_mode_not_configured(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('not_configured', False) when testarch is None."""
        from bmad_assist.testarch.handlers import TraceHandler

        mock_config.testarch = None
        handler = TraceHandler(mock_config, tmp_path)
        state = State(current_epic="testarch", atdd_ran_in_epic=True)

        mode, should_run = handler._check_mode(state, "trace_on_epic_complete")

        assert mode == "not_configured"
        assert should_run is False


# =============================================================================
# Note: RetrospectiveHandler integration tests removed (Story 25.8 AC9)
#
# Trace is now a separate Phase (Phase.TRACE) and can be configured in
# loop.epic_teardown to run before retrospective. The trace invocation
# has been removed from RetrospectiveHandler to decouple core from testarch.
# =============================================================================
