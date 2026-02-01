"""Tests for ATDDHandler (testarch-6).

These tests verify:
- AC #1: Phase.ATDD in state machine (covered by test_state_model.py)
- AC #2: ATDDHandler class creation
- AC #3: Eligibility check logic
- AC #4: Preflight integration
- AC #5: ATDD workflow invocation (placeholder until testarch-8)
- AC #6: atdd_ran_for_story tracking
- AC #7: atdd_ran_in_epic tracking
- AC #8: Handler registered in dispatch
- AC #9: Skip when mode=off
- AC #10: Skip when not eligible (auto mode)
- AC #11: Run when mode=on
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
    config.testarch.atdd_mode = "auto"
    config.testarch.preflight = None
    config.testarch.eligibility = None
    config.benchmarking = MagicMock()
    config.benchmarking.enabled = False
    
    # Provider config
    config.providers = MagicMock()
    config.providers.master = MagicMock()
    config.providers.master.provider = "mock-provider"
    config.providers.master.model = "mock-model"
    config.timeout = 30
    return config


@pytest.fixture
def handler(mock_config: MagicMock, tmp_path: Path) -> "ATDDHandler":
    """Create ATDDHandler instance with mock config."""
    from bmad_assist.testarch.handlers import ATDDHandler

    return ATDDHandler(mock_config, tmp_path)


@pytest.fixture
def state_story_1_1() -> State:
    """State at story 1.1."""
    return State(
        current_epic=1,
        current_story="1.1",
        current_phase=Phase.ATDD,
    )


@pytest.fixture
def state_story_1_2() -> State:
    """State at story 1.2."""
    return State(
        current_epic=1,
        current_story="1.2",
        current_phase=Phase.ATDD,
    )


# =============================================================================
# AC #2: ATDDHandler class creation
# =============================================================================


class TestATDDHandlerCreation:
    """Test ATDDHandler class creation."""

    def test_handler_created_successfully(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """ATDDHandler can be instantiated."""
        from bmad_assist.testarch.handlers import ATDDHandler

        handler = ATDDHandler(mock_config, tmp_path)
        assert handler is not None
        assert handler.config is mock_config
        assert handler.project_path == tmp_path

    def test_handler_phase_name(self, handler: "ATDDHandler") -> None:
        """ATDDHandler.phase_name returns 'atdd'."""
        assert handler.phase_name == "atdd"


# =============================================================================
# AC #8: Handler registered in dispatch
# =============================================================================


class TestHandlerRegistration:
    """Test ATDDHandler registered in dispatch."""

    def test_atdd_phase_in_workflow_handlers(self) -> None:
        """Phase.ATDD has handler in WORKFLOW_HANDLERS."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        assert Phase.ATDD in WORKFLOW_HANDLERS

    def test_atdd_stub_handler_is_callable(self) -> None:
        """ATDD stub handler is callable."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        handler = WORKFLOW_HANDLERS[Phase.ATDD]
        assert callable(handler)


# =============================================================================
# AC #9: Skip when mode=off
# =============================================================================


class TestModeOff:
    """Test ATDD skipped when mode=off."""

    def test_execute_skips_when_mode_off(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_1: State
    ) -> None:
        """execute() skips with mode=off."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "off"
        handler = ATDDHandler(mock_config, tmp_path)

        result = handler.execute(state_story_1_1)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("atdd_mode") == "off"
        assert result.outputs.get("reason") == "atdd_mode=off"


class TestModeNotConfigured:
    """Test ATDD skipped when testarch not configured."""

    def test_execute_skips_when_not_configured(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_1: State
    ) -> None:
        """execute() skips when testarch is None."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch = None
        handler = ATDDHandler(mock_config, tmp_path)

        result = handler.execute(state_story_1_1)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("atdd_mode") == "not_configured"


# =============================================================================
# AC #10: Skip when not eligible (auto mode)
# =============================================================================


class TestModeAuto:
    """Test ATDD eligibility check in auto mode."""

    def test_execute_checks_eligibility_in_auto_mode(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_1: State
    ) -> None:
        """execute() checks eligibility when mode=auto."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "auto"
        handler = ATDDHandler(mock_config, tmp_path)

        # Mock eligibility detector to return not eligible
        with patch.object(handler, "_check_eligibility") as mock_check:
            mock_result = MagicMock()
            mock_result.eligible = False
            mock_result.reasoning = "No testable patterns found"
            mock_check.return_value = mock_result

            # Mock _check_mode to behave correctly or let it run
            # It will return ("auto", True) if we don't mock it, which is correct
            
            result = handler.execute(state_story_1_1)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("eligible") is False
        assert "No testable patterns found" in result.outputs.get("reason", "")

    def test_execute_runs_workflow_when_eligible(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_1: State
    ) -> None:
        """execute() runs workflow when story is eligible."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "auto"
        handler = ATDDHandler(mock_config, tmp_path)

        # Mock eligibility to return eligible
        with patch.object(handler, "_check_eligibility") as mock_check:
            mock_result = MagicMock()
            mock_result.eligible = True
            mock_result.final_score = 0.8
            mock_check.return_value = mock_result

            # Mock workflow invocation
            with patch.object(handler, "_invoke_atdd_workflow") as mock_invoke:
                mock_invoke.return_value = PhaseResult.ok(
                    {
                        "response": "Tests generated",
                        "tests_generated": True,
                    }
                )

                result = handler.execute(state_story_1_1)

        assert result.success is True
        assert result.outputs.get("skipped") is None or result.outputs.get("skipped") is False
        assert result.outputs.get("eligible") is True


# =============================================================================
# AC #11: Run when mode=on
# =============================================================================


class TestModeOn:
    """Test ATDD always runs in mode=on."""

    def test_execute_skips_eligibility_check_when_mode_on(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_1: State
    ) -> None:
        """execute() skips eligibility check when mode=on."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "on"
        handler = ATDDHandler(mock_config, tmp_path)

        with patch.object(handler, "_check_eligibility") as mock_check:
            with patch.object(handler, "_invoke_atdd_workflow") as mock_invoke:
                mock_invoke.return_value = PhaseResult.ok({"response": "ok"})

                result = handler.execute(state_story_1_1)

        # Eligibility should NOT be called in mode=on
        mock_check.assert_not_called()
        assert result.success is True


# =============================================================================
# AC #6: atdd_ran_for_story tracking
# =============================================================================


class TestStoryTracking:
    """Test atdd_ran_for_story state tracking."""

    def test_atdd_ran_for_story_reset_at_start(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """atdd_ran_for_story is reset at handler start."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "off"
        handler = ATDDHandler(mock_config, tmp_path)

        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.ATDD,
            atdd_ran_for_story=True,  # Pre-set to True
        )

        handler.execute(state)

        # Should be reset to False at start (even though we skip)
        assert state.atdd_ran_for_story is False

    def test_atdd_ran_for_story_set_on_success(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_1: State
    ) -> None:
        """atdd_ran_for_story is set to True on successful workflow."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "on"
        handler = ATDDHandler(mock_config, tmp_path)

        with patch.object(handler, "_invoke_atdd_workflow") as mock_invoke:
            mock_invoke.return_value = PhaseResult.ok({"response": "ok"})

            handler.execute(state_story_1_1)

        assert state_story_1_1.atdd_ran_for_story is True


# =============================================================================
# AC #7: atdd_ran_in_epic tracking
# =============================================================================


class TestEpicTracking:
    """Test atdd_ran_in_epic state tracking."""

    def test_atdd_ran_in_epic_set_on_success(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_1: State
    ) -> None:
        """atdd_ran_in_epic is set to True on successful workflow."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "on"
        handler = ATDDHandler(mock_config, tmp_path)

        assert state_story_1_1.atdd_ran_in_epic is False

        with patch.object(handler, "_invoke_atdd_workflow") as mock_invoke:
            mock_invoke.return_value = PhaseResult.ok({"response": "ok"})

            handler.execute(state_story_1_1)

        assert state_story_1_1.atdd_ran_in_epic is True

    def test_atdd_ran_in_epic_not_set_on_skip(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_1: State
    ) -> None:
        """atdd_ran_in_epic is NOT set when ATDD is skipped."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "off"
        handler = ATDDHandler(mock_config, tmp_path)

        handler.execute(state_story_1_1)

        assert state_story_1_1.atdd_ran_in_epic is False


# =============================================================================
# AC #4: Preflight integration
# =============================================================================


class TestPreflightIntegration:
    """Test preflight check integration."""

    def test_preflight_runs_on_first_story(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_1: State
    ) -> None:
        """Preflight runs on first story of epic (story X.1)."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "on"
        handler = ATDDHandler(mock_config, tmp_path)

        with patch.object(handler, "_run_preflight_if_needed") as mock_preflight:
            with patch.object(handler, "_invoke_atdd_workflow") as mock_invoke:
                mock_invoke.return_value = PhaseResult.ok({})

                handler.execute(state_story_1_1)

        mock_preflight.assert_called_once_with(state_story_1_1)

    def test_preflight_called_for_non_first_story(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_2: State
    ) -> None:
        """Preflight method is called for all stories (checks internally)."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "on"
        handler = ATDDHandler(mock_config, tmp_path)

        with patch.object(handler, "_run_preflight_if_needed") as mock_preflight:
            with patch.object(handler, "_invoke_atdd_workflow") as mock_invoke:
                mock_invoke.return_value = PhaseResult.ok({})

                handler.execute(state_story_1_2)

        # Method is called, but it checks internally if first story
        mock_preflight.assert_called_once_with(state_story_1_2)


class TestPreflightAdvisory:
    """Test that preflight warnings don't block ATDD (AC #4)."""

    def test_preflight_advisory_warnings_continue(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_1: State
    ) -> None:
        """Preflight warnings don't block ATDD (AC #12.19)."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "on"
        handler = ATDDHandler(mock_config, tmp_path)

        # Mock PreflightChecker to return warnings
        with (
            patch("bmad_assist.testarch.PreflightChecker") as MockChecker,
            patch.object(handler, "_invoke_atdd_workflow") as mock_invoke,
            patch("bmad_assist.testarch.handlers.atdd.save_state"),
            patch("bmad_assist.testarch.handlers.atdd.get_state_path"),
        ):
            # Setup preflight mock
            mock_checker_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.all_passed = False
            mock_result.warnings = ["Missing test framework", "No CI config"]
            mock_checker_instance.check.return_value = mock_result
            MockChecker.return_value = mock_checker_instance
            MockChecker.should_run.return_value = True

            # Workflow should still run
            mock_invoke.return_value = PhaseResult.ok({"response": "ok"})

            result = handler.execute(state_story_1_1)

        # ATDD should succeed despite preflight warnings
        assert result.success is True
        assert result.outputs.get("skipped") is None or result.outputs.get("skipped") is False

    def test_preflight_exception_continues(
        self, mock_config: MagicMock, tmp_path: Path, state_story_1_1: State
    ) -> None:
        """Preflight exceptions are caught and ATDD continues."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "on"
        handler = ATDDHandler(mock_config, tmp_path)

        # Mock _run_preflight_if_needed to raise exception
        with (
            patch.object(
                handler, "_run_preflight_if_needed", side_effect=RuntimeError("Preflight failed")
            ),
            patch.object(handler, "_invoke_atdd_workflow") as mock_invoke,
        ):
            mock_invoke.return_value = PhaseResult.ok({"response": "ok"})

            result = handler.execute(state_story_1_1)

        # Should continue despite preflight exception
        assert result.success is True
        mock_invoke.assert_called_once()


class TestFirstStoryDetection:
    """Test _is_first_story_in_epic helper."""

    def test_is_first_story_returns_true_for_story_1(self, handler: "ATDDHandler") -> None:
        """Returns True for story ending in .1"""
        state = State(current_epic=1, current_story="1.1")
        assert handler._is_first_story_in_epic(state) is True

        state = State(current_epic="testarch", current_story="testarch.1")
        assert handler._is_first_story_in_epic(state) is True

    def test_is_first_story_returns_false_for_other_stories(self, handler: "ATDDHandler") -> None:
        """Returns False for non-first stories."""
        state = State(current_epic=1, current_story="1.2")
        assert handler._is_first_story_in_epic(state) is False

        state = State(current_epic=1, current_story="1.10")
        assert handler._is_first_story_in_epic(state) is False

    def test_is_first_story_returns_false_for_none_story(self, handler: "ATDDHandler") -> None:
        """Returns False when no story is set."""
        state = State(current_epic=1, current_story=None)
        assert handler._is_first_story_in_epic(state) is False


# =============================================================================
# AC #3: Eligibility check logic
# =============================================================================


class TestEligibilityCheckLogic:
    """Test _check_mode helper with atdd_mode."""

    def test_check_atdd_mode_off(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('off', False) for mode=off."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "off"
        handler = ATDDHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "atdd_mode")
        assert mode == "off"
        assert should_check is False

    def test_check_atdd_mode_on(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('on', True) for mode=on."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "on"
        handler = ATDDHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "atdd_mode")
        assert mode == "on"
        assert should_check is True

    def test_check_atdd_mode_auto(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('auto', True) for mode=auto."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch.atdd_mode = "auto"
        handler = ATDDHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "atdd_mode")
        assert mode == "auto"
        assert should_check is True

    def test_check_atdd_mode_not_configured(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('not_configured', False) when testarch is None."""
        from bmad_assist.testarch.handlers import ATDDHandler

        mock_config.testarch = None
        handler = ATDDHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "atdd_mode")
        assert mode == "not_configured"
        assert should_check is False


# =============================================================================
# AC #5: ATDD workflow invocation (implemented in testarch-8)
# =============================================================================


class TestWorkflowInvocation:
    """Test _invoke_atdd_workflow (now implemented with compiler integration)."""

    def test_invoke_returns_error_when_paths_not_initialized(
        self, handler: "ATDDHandler", state_story_1_1: State
    ) -> None:
        """Returns error PhaseResult when paths singleton not initialized.

        Note: Full integration tests are in test_atdd_integration.py which
        properly mocks get_paths().
        """
        result = handler._invoke_atdd_workflow(state_story_1_1)

        # Without paths initialized, the handler fails gracefully
        assert result.success is False
        assert "Paths not initialized" in result.error