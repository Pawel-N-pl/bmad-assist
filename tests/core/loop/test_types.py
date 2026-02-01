"""Tests for loop types: PhaseResult, PhaseHandler, LoopExitReason, GuardianDecision.

Story 6.1: Tests for PhaseResult, PhaseHandler.
Story 6.5: Tests for LoopExitReason, GuardianDecision.
"""

from dataclasses import FrozenInstanceError

import pytest


class TestPhaseReExports:
    """AC1/AC7: Phase and PHASE_ORDER are re-exported from loop.py."""

    def test_phase_is_same_object_as_state(self) -> None:
        """AC1: Phase is imported, not recreated."""
        from bmad_assist.core.loop import Phase as LoopPhase
        from bmad_assist.core.state import Phase as StatePhase

        assert LoopPhase is StatePhase  # Identity, not equality

    def test_default_loop_config_is_singleton(self) -> None:
        """AC1: DEFAULT_LOOP_CONFIG is a singleton constant."""
        from bmad_assist.core.config import DEFAULT_LOOP_CONFIG as config1
        from bmad_assist.core.config import DEFAULT_LOOP_CONFIG as config2

        assert config1 is config2  # Identity, not equality

    def test_default_loop_config_story_phases(self) -> None:
        """AC7: DEFAULT_LOOP_CONFIG.story contains 6 phases (minimal, no TEA)."""
        from bmad_assist.core.config import DEFAULT_LOOP_CONFIG

        # 6 phases in minimal story sequence (no atdd, no test_review)
        assert len(DEFAULT_LOOP_CONFIG.story) == 6

    def test_default_loop_config_first_is_create_story(self) -> None:
        """AC7: First phase is create_story."""
        from bmad_assist.core.config import DEFAULT_LOOP_CONFIG

        assert DEFAULT_LOOP_CONFIG.story[0] == "create_story"

    def test_default_loop_config_last_is_code_review_synthesis(self) -> None:
        """Last story phase is code_review_synthesis (minimal loop, no TEA)."""
        from bmad_assist.core.config import DEFAULT_LOOP_CONFIG

        assert DEFAULT_LOOP_CONFIG.story[-1] == "code_review_synthesis"

    def test_default_loop_config_epic_teardown_has_retrospective(self) -> None:
        """epic_teardown contains retrospective."""
        from bmad_assist.core.config import DEFAULT_LOOP_CONFIG

        assert "retrospective" in DEFAULT_LOOP_CONFIG.epic_teardown


class TestPhaseResult:
    """AC2: PhaseResult frozen dataclass with factory methods."""

    def test_phase_result_is_frozen(self) -> None:
        """AC2: PhaseResult is immutable."""
        from bmad_assist.core.loop import PhaseResult

        result = PhaseResult(success=True)
        with pytest.raises(FrozenInstanceError):
            result.success = False  # type: ignore[misc]

    def test_phase_result_required_success_field(self) -> None:
        """AC2: success is a required field."""
        from bmad_assist.core.loop import PhaseResult

        result = PhaseResult(success=True)
        assert result.success is True

        result_fail = PhaseResult(success=False)
        assert result_fail.success is False

    def test_phase_result_default_next_phase_is_none(self) -> None:
        """AC2: next_phase defaults to None."""
        from bmad_assist.core.loop import PhaseResult

        result = PhaseResult(success=True)
        assert result.next_phase is None

    def test_phase_result_default_error_is_none(self) -> None:
        """AC2: error defaults to None."""
        from bmad_assist.core.loop import PhaseResult

        result = PhaseResult(success=True)
        assert result.error is None

    def test_phase_result_default_outputs_is_empty_dict(self) -> None:
        """AC2: outputs defaults to empty dict via default_factory."""
        from bmad_assist.core.loop import PhaseResult

        result = PhaseResult(success=True)
        assert result.outputs == {}

    def test_phase_result_outputs_no_mutable_default_bug(self) -> None:
        """AC2: Each instance gets its own outputs dict (no shared mutable)."""
        from bmad_assist.core.loop import PhaseResult

        result1 = PhaseResult(success=True)
        result2 = PhaseResult(success=True)

        # Different instances should have different dict objects
        assert result1.outputs is not result2.outputs

    def test_phase_result_with_explicit_values(self) -> None:
        """AC2: All fields can be set explicitly."""
        from bmad_assist.core.loop import Phase, PhaseResult

        result = PhaseResult(
            success=False,
            next_phase=Phase.CODE_REVIEW,
            error="Something failed",
            outputs={"file": "test.md"},
        )
        assert result.success is False
        assert result.next_phase == Phase.CODE_REVIEW
        assert result.error == "Something failed"
        assert result.outputs == {"file": "test.md"}

    def test_phase_result_ok_factory(self) -> None:
        """AC2: Factory method creates success result."""
        from bmad_assist.core.loop import PhaseResult

        result = PhaseResult.ok({"file": "test.md"})
        assert result.success is True
        assert result.next_phase is None
        assert result.error is None
        assert result.outputs == {"file": "test.md"}

    def test_phase_result_ok_factory_no_outputs(self) -> None:
        """AC2: Factory method with no outputs returns empty dict."""
        from bmad_assist.core.loop import PhaseResult

        result = PhaseResult.ok()
        assert result.success is True
        assert result.outputs == {}

    def test_phase_result_ok_factory_with_none_outputs(self) -> None:
        """AC2: Factory method with explicit None outputs returns empty dict."""
        from bmad_assist.core.loop import PhaseResult

        result = PhaseResult.ok(None)
        assert result.success is True
        assert result.outputs == {}

    def test_phase_result_fail_factory(self) -> None:
        """AC2: Factory method creates failure result."""
        from bmad_assist.core.loop import PhaseResult

        result = PhaseResult.fail("Something broke")
        assert result.success is False
        assert result.next_phase is None
        assert result.error == "Something broke"
        assert result.outputs == {}

    def test_phase_result_ok_defensive_copy(self) -> None:
        """PhaseResult.ok() makes defensive copy of outputs dict."""
        from bmad_assist.core.loop import PhaseResult

        original = {"key": "value"}
        result = PhaseResult.ok(original)

        # Should be equal but different object (defensive copy)
        assert result.outputs == original
        assert result.outputs is not original

        # Mutating original should not affect result
        original["new_key"] = "new_value"
        assert "new_key" not in result.outputs


class TestPhaseHandler:
    """AC3: PhaseHandler type alias."""

    def test_phase_handler_type_alias_exists(self) -> None:
        """AC3: PhaseHandler is importable TypeAlias.

        Note: Full type signature is verified by mypy at compile time.
        This test validates the alias is exported and usable at runtime.
        """
        from bmad_assist.core.loop import PhaseHandler, PhaseResult
        from bmad_assist.core.state import State

        # Verify handlers match the type alias signature at runtime
        def sample_handler(state: State) -> PhaseResult:
            return PhaseResult.ok()

        # This would fail type checking if PhaseHandler signature changed
        handler: PhaseHandler = sample_handler
        assert callable(handler)


class TestLoopExitReason:
    """Tests for LoopExitReason enum."""

    def test_loop_exit_reason_values(self) -> None:
        """LoopExitReason has expected values."""
        from bmad_assist.core.loop import LoopExitReason

        assert LoopExitReason.COMPLETED.value == "completed"
        assert LoopExitReason.GUARDIAN_HALT.value == "guardian_halt"
        assert LoopExitReason.INTERRUPTED_SIGINT.value == "interrupted_sigint"
        assert LoopExitReason.INTERRUPTED_SIGTERM.value == "interrupted_sigterm"

    def test_loop_exit_reason_is_exported(self) -> None:
        """LoopExitReason is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "LoopExitReason" in loop.__all__


class TestGuardianDecision:
    """Tests for GuardianDecision enum."""

    def test_guardian_decision_values(self) -> None:
        """GuardianDecision has expected values."""
        from bmad_assist.core.loop import GuardianDecision

        assert GuardianDecision.CONTINUE.value == "continue"
        assert GuardianDecision.HALT.value == "halt"

    def test_guardian_decision_is_exported(self) -> None:
        """GuardianDecision is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "GuardianDecision" in loop.__all__
