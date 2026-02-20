"""Tests for handler stubs, WORKFLOW_HANDLERS, and get_handler.

Story 6.1: Tests for WORKFLOW_HANDLERS, handler stubs, get_handler().
"""

import pytest

from bmad_assist.core.exceptions import StateError


class TestWorkflowHandlers:
    """AC4: WORKFLOW_HANDLERS maps all 9 phases (including ATDD and TEST_REVIEW)."""

    def test_workflow_handlers_maps_all_phases(self) -> None:
        """AC4: All phases have handlers."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS, Phase

        for phase in Phase:
            assert phase in WORKFLOW_HANDLERS

        assert len(WORKFLOW_HANDLERS) == len(Phase)

    def test_workflow_handlers_values_are_callable(self) -> None:
        """AC4: All handlers are callable functions."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        for phase, handler in WORKFLOW_HANDLERS.items():
            assert callable(handler), f"Handler for {phase} is not callable"

    def test_workflow_handlers_has_correct_handler_names(self) -> None:
        """AC4: Handlers have expected function names."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS, Phase

        expected_handlers = {
            Phase.CREATE_STORY: "create_story_handler",
            Phase.VALIDATE_STORY: "validate_story_handler",
            Phase.VALIDATE_STORY_SYNTHESIS: "validate_story_synthesis_handler",
            Phase.ATDD: "atdd_handler",
            Phase.DEV_STORY: "dev_story_handler",
            Phase.CODE_REVIEW: "code_review_handler",
            Phase.CODE_REVIEW_SYNTHESIS: "code_review_synthesis_handler",
            Phase.TEST_REVIEW: "test_review_handler",
            Phase.RETROSPECTIVE: "retrospective_handler",
            Phase.HARDENING: "hardening_handler",
        }

        for phase, expected_name in expected_handlers.items():
            handler = WORKFLOW_HANDLERS[phase]
            assert handler.__name__ == expected_name


class TestHandlerStubs:
    """AC5: Handler stub functions return PhaseResult failure."""

    def test_all_handlers_return_phase_result(self) -> None:
        """AC5: All handlers return PhaseResult instances."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS, PhaseResult
        from bmad_assist.core.state import State

        state = State()

        for phase, handler in WORKFLOW_HANDLERS.items():
            result = handler(state)
            assert isinstance(result, PhaseResult), (
                f"Handler for {phase} doesn't return PhaseResult"
            )

    def test_all_handlers_return_not_implemented_failure(self) -> None:
        """AC5: Stub handlers return failure with 'not yet implemented'."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS
        from bmad_assist.core.state import State

        state = State()

        for phase, handler in WORKFLOW_HANDLERS.items():
            result = handler(state)
            assert result.success is False, f"Handler for {phase} should return success=False"
            assert "not yet implemented" in result.error, (
                f"Handler for {phase} error should contain 'not yet implemented'"
            )

    def test_handler_error_contains_phase_name(self) -> None:
        """AC5: Error message contains dynamic phase name."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS
        from bmad_assist.core.state import State

        state = State()

        for phase, handler in WORKFLOW_HANDLERS.items():
            result = handler(state)
            assert phase.value in result.error, (
                f"Handler for {phase} error should contain '{phase.value}'"
            )

    def test_create_story_handler_has_docstring(self) -> None:
        """AC5: Handler has Google-style docstring."""
        from bmad_assist.core.loop import create_story_handler

        assert create_story_handler.__doc__ is not None
        assert len(create_story_handler.__doc__) > 0

    def test_dev_story_handler_has_docstring(self) -> None:
        """AC5: Handler has Google-style docstring."""
        from bmad_assist.core.loop import dev_story_handler

        assert dev_story_handler.__doc__ is not None
        assert len(dev_story_handler.__doc__) > 0


class TestGetHandler:
    """AC6: get_handler() returns correct handler."""

    @pytest.fixture(autouse=True)
    def reset_handlers(self) -> None:
        """Reset global handler state to ensure tests use stubs."""
        from bmad_assist.core.loop import dispatch
        dispatch._handlers_initialized = False
        dispatch._handler_instances = {}
        yield
        dispatch._handlers_initialized = False
        dispatch._handler_instances = {}

    def test_get_handler_returns_correct_function(self) -> None:
        """AC6: get_handler dispatches correctly."""
        from bmad_assist.core.loop import (
            Phase,
            dev_story_handler,
            get_handler,
        )

        assert get_handler(Phase.DEV_STORY) is dev_story_handler

    def test_get_handler_returns_all_handlers(self) -> None:
        """AC6: get_handler works for all phases."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS, Phase, get_handler

        for phase in Phase:
            handler = get_handler(phase)
            assert handler is WORKFLOW_HANDLERS[phase]

    def test_get_handler_raises_stateerror_for_invalid(self) -> None:
        """AC6: get_handler raises StateError for invalid phase."""
        from bmad_assist.core.loop import get_handler

        with pytest.raises(StateError, match="Unknown workflow phase"):
            get_handler("invalid")  # type: ignore[arg-type]

    def test_get_handler_raises_stateerror_for_none(self) -> None:
        """AC6: get_handler raises StateError for None input."""
        from bmad_assist.core.loop import get_handler

        with pytest.raises(StateError, match="Unknown workflow phase"):
            get_handler(None)  # type: ignore[arg-type]


class TestModuleExports:
    """Test __all__ exports from loop.py."""

    def test_phase_exported_from_loop(self) -> None:
        """Phase is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "Phase" in loop.__all__

    def test_default_loop_config_importable_from_config(self) -> None:
        """DEFAULT_LOOP_CONFIG is importable from config module."""
        from bmad_assist.core.config import DEFAULT_LOOP_CONFIG

        assert hasattr(DEFAULT_LOOP_CONFIG, "story")

    def test_phase_result_exported_from_loop(self) -> None:
        """PhaseResult is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "PhaseResult" in loop.__all__

    def test_phase_handler_exported_from_loop(self) -> None:
        """PhaseHandler is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "PhaseHandler" in loop.__all__

    def test_workflow_handlers_exported_from_loop(self) -> None:
        """WORKFLOW_HANDLERS is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "WORKFLOW_HANDLERS" in loop.__all__

    def test_get_handler_exported_from_loop(self) -> None:
        """get_handler is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "get_handler" in loop.__all__
