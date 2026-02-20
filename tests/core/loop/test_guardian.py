"""Tests for guardian module.

Story 6.5: Main Loop Runner - Guardian functionality
- get_next_phase()
- guardian_check_anomaly()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass


class TestGetNextPhase:
    """AC7: get_next_phase() returns next phase in PHASE_ORDER."""

    def test_get_next_phase_returns_next_for_create_story(self) -> None:
        """AC7: CREATE_STORY -> VALIDATE_STORY."""
        from bmad_assist.core.loop import Phase, get_next_phase

        result = get_next_phase(Phase.CREATE_STORY)
        assert result == Phase.VALIDATE_STORY

    def test_get_next_phase_returns_next_for_dev_story(self) -> None:
        """AC7: DEV_STORY -> CODE_REVIEW."""
        from bmad_assist.core.loop import Phase, get_next_phase

        result = get_next_phase(Phase.DEV_STORY)
        assert result == Phase.CODE_REVIEW

    def test_get_next_phase_returns_none_for_code_review_synthesis_without_testarch(self) -> None:
        """AC7: CODE_REVIEW_SYNTHESIS returns None when testarch disabled (TEST_REVIEW skipped)."""
        from bmad_assist.core.loop import Phase, get_next_phase

        # CODE_REVIEW_SYNTHESIS returns None because TEST_REVIEW is skipped when testarch disabled
        result = get_next_phase(Phase.CODE_REVIEW_SYNTHESIS)
        assert result is None

    def test_get_next_phase_returns_test_review_for_code_review_synthesis_with_tea_loop(self) -> None:
        """AC7: CODE_REVIEW_SYNTHESIS -> TEST_REVIEW when using TEA_FULL_LOOP_CONFIG."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.core.config.loop_config import set_loop_config
        from bmad_assist.core.config.models.loop import TEA_FULL_LOOP_CONFIG
        from bmad_assist.core.loop import Phase, get_next_phase

        # Use TEA_FULL_LOOP_CONFIG which has TEST_REVIEW after CODE_REVIEW_SYNTHESIS
        set_loop_config(TEA_FULL_LOOP_CONFIG)
        try:
            # With testarch enabled, CODE_REVIEW_SYNTHESIS -> TEST_REVIEW
            mock_config = MagicMock()
            mock_config.testarch = MagicMock()  # Not None
            with patch("bmad_assist.core.config.get_config", return_value=mock_config):
                result = get_next_phase(Phase.CODE_REVIEW_SYNTHESIS)
            assert result == Phase.TEST_REVIEW
        finally:
            # Restore default
            from bmad_assist.core.config.models.loop import DEFAULT_LOOP_CONFIG
            set_loop_config(DEFAULT_LOOP_CONFIG)

    def test_get_next_phase_returns_none_for_test_review_with_tea_loop(self) -> None:
        """AC7: TEST_REVIEW is last in TEA_FULL_LOOP_CONFIG.story, returns None."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.core.config.loop_config import set_loop_config
        from bmad_assist.core.config.models.loop import DEFAULT_LOOP_CONFIG, TEA_FULL_LOOP_CONFIG
        from bmad_assist.core.loop import Phase, get_next_phase

        # Use TEA_FULL_LOOP_CONFIG which has TEST_REVIEW
        set_loop_config(TEA_FULL_LOOP_CONFIG)
        try:
            # With testarch enabled, TEST_REVIEW is the last story phase
            mock_config = MagicMock()
            mock_config.testarch = MagicMock()  # Not None
            with patch("bmad_assist.core.config.get_config", return_value=mock_config):
                result = get_next_phase(Phase.TEST_REVIEW)
            assert result is None
        finally:
            # Restore default
            set_loop_config(DEFAULT_LOOP_CONFIG)

    def test_get_next_phase_returns_none_for_retrospective(self) -> None:
        """AC7: RETROSPECTIVE returns None (last phase)."""
        from bmad_assist.core.loop import Phase, get_next_phase

        result = get_next_phase(Phase.RETROSPECTIVE)
        assert result is None

    def test_get_next_phase_all_phases_in_default_config(self) -> None:
        """AC7: All phases in DEFAULT_LOOP_CONFIG.story (minimal) advance correctly."""
        from bmad_assist.core.config import DEFAULT_LOOP_CONFIG
        from bmad_assist.core.loop import Phase, get_next_phase

        # DEFAULT_LOOP_CONFIG is minimal (no TEA phases)
        story_phases = DEFAULT_LOOP_CONFIG.story
        # Test all phases except the last one advance to next
        for i, phase_str in enumerate(story_phases[:-1]):
            phase = Phase(phase_str)
            expected = Phase(story_phases[i + 1])
            assert get_next_phase(phase) == expected, f"Failed for {phase}"

        # Last phase (CODE_REVIEW_SYNTHESIS) returns None
        last_phase = Phase(story_phases[-1])
        assert last_phase == Phase.CODE_REVIEW_SYNTHESIS
        assert get_next_phase(last_phase) is None

    def test_get_next_phase_without_qa_stops_at_retrospective(self) -> None:
        """RETROSPECTIVE is last phase when QA is disabled (default)."""
        from bmad_assist.core.loop import Phase, get_next_phase

        # QA is disabled by default
        result = get_next_phase(Phase.RETROSPECTIVE)
        assert result is None

    def test_get_next_phase_uses_default_loop_config(self) -> None:
        """get_next_phase uses DEFAULT_LOOP_CONFIG.story (minimal, no TEA phases)."""
        from bmad_assist.core.config import DEFAULT_LOOP_CONFIG
        from bmad_assist.core.loop import Phase, get_next_phase

        # DEFAULT_LOOP_CONFIG is minimal (no atdd or test_review)
        # VALIDATE_STORY_SYNTHESIS -> DEV_STORY (no atdd in between)
        result = get_next_phase(Phase.VALIDATE_STORY_SYNTHESIS)
        assert result == Phase.DEV_STORY

        # CODE_REVIEW_SYNTHESIS is last in story sequence -> None
        result = get_next_phase(Phase.CODE_REVIEW_SYNTHESIS)
        assert result is None

        # Verify this matches DEFAULT_LOOP_CONFIG.story
        assert DEFAULT_LOOP_CONFIG.story[-1] == "code_review_synthesis"


class TestGuardianCheckAnomaly:
    """AC5: guardian_check_anomaly() placeholder returns GuardianDecision.CONTINUE."""

    def test_guardian_halts_on_failure(self) -> None:
        """AC5: Guardian returns HALT on phase failure to prevent infinite loops."""
        from bmad_assist.core.loop import (
            GuardianDecision,
            PhaseResult,
            guardian_check_anomaly,
        )
        from bmad_assist.core.state import Phase, State

        result = PhaseResult.fail("Some error")
        state = State(current_phase=Phase.DEV_STORY, current_story="1.1")

        decision = guardian_check_anomaly(result, state)

        assert decision == GuardianDecision.HALT

    def test_guardian_continues_on_success(self) -> None:
        """AC5: Guardian returns CONTINUE on phase success."""
        from bmad_assist.core.loop import (
            GuardianDecision,
            PhaseResult,
            guardian_check_anomaly,
        )
        from bmad_assist.core.state import Phase, State

        result = PhaseResult.ok()
        state = State(current_phase=Phase.CREATE_STORY, current_story="1.1")

        decision = guardian_check_anomaly(result, state)

        assert decision == GuardianDecision.CONTINUE

    def test_guardian_logs_debug_on_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC5: Guardian logs debug message with phase and story on failure."""
        from bmad_assist.core.loop import PhaseResult, guardian_check_anomaly
        from bmad_assist.core.state import Phase, State

        result = PhaseResult.fail("Test error message")
        state = State(current_phase=Phase.CODE_REVIEW, current_story="2.3")

        with caplog.at_level(logging.DEBUG):
            guardian_check_anomaly(result, state)

        assert "CODE_REVIEW" in caplog.text
        assert "2.3" in caplog.text
        assert "FAILED" in caplog.text

    def test_guardian_handles_none_phase(self) -> None:
        """AC5: Guardian handles None current_phase gracefully (still halts on failure)."""
        from bmad_assist.core.loop import (
            GuardianDecision,
            PhaseResult,
            guardian_check_anomaly,
        )
        from bmad_assist.core.state import State

        result = PhaseResult.fail("Error")
        state = State(current_phase=None, current_story="1.1")

        decision = guardian_check_anomaly(result, state)

        # Should still halt on failure even with None phase
        assert decision == GuardianDecision.HALT
