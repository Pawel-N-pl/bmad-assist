"""Tests for loop position tracking (Story 3.4).

Story 3.4 Tests cover:
- AC1: Update position sets current epic/story/phase
- AC2: Update position sets started_at on first update
- AC3: Mark story completed adds to completed_stories
- AC4: Mark story completed is idempotent
- AC5: Advance state moves to next phase within story
- AC6: Advance state handles phase ordering correctly
- AC7: Advance state returns next phase info
- AC8: Advance state at RETROSPECTIVE indicates epic complete
- AC9: Update position with partial args updates only specified fields
- AC10: Functions have correct signatures and exports
- AC11: Google-style docstrings are complete and testable
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from bmad_assist.core.config import DEFAULT_LOOP_CONFIG
from bmad_assist.core.exceptions import StateError
from bmad_assist.core.state import (
    Phase,
    State,
    advance_state,
    mark_story_completed,
    update_position,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fresh_state() -> State:
    """State with all defaults (fresh start)."""
    return State()


@pytest.fixture
def mid_story_state() -> State:
    """State in middle of a story."""
    return State(
        current_epic=2,
        current_story="2.3",
        current_phase=Phase.DEV_STORY,
        completed_stories=["1.1", "1.2", "2.1", "2.2"],
        started_at=datetime(2025, 12, 10, 8, 0, 0),
        updated_at=datetime(2025, 12, 10, 14, 0, 0),
    )


@pytest.fixture
def retrospective_state() -> State:
    """State at RETROSPECTIVE phase."""
    return State(
        current_epic=2,
        current_story="2.5",
        current_phase=Phase.RETROSPECTIVE,
        completed_stories=["2.1", "2.2", "2.3", "2.4", "2.5"],
        started_at=datetime(2025, 12, 10, 8, 0, 0),
        updated_at=datetime(2025, 12, 10, 18, 0, 0),
    )


# =============================================================================
# AC1: Update position sets current epic/story/phase
# =============================================================================


class TestUpdatePositionBasic:
    """Test update_position sets epic/story/phase (AC1)."""

    def test_update_position_sets_epic(self, fresh_state: State) -> None:
        """AC1: update_position sets current_epic."""
        update_position(fresh_state, epic=2)
        assert fresh_state.current_epic == 2

    def test_update_position_sets_story(self, fresh_state: State) -> None:
        """AC1: update_position sets current_story."""
        update_position(fresh_state, story="2.3")
        assert fresh_state.current_story == "2.3"

    def test_update_position_sets_phase(self, fresh_state: State) -> None:
        """AC1: update_position sets current_phase."""
        update_position(fresh_state, phase=Phase.CODE_REVIEW)
        assert fresh_state.current_phase == Phase.CODE_REVIEW

    def test_update_position_sets_all_fields(self, fresh_state: State) -> None:
        """AC1: update_position sets all fields when provided."""
        update_position(fresh_state, epic=2, story="2.3", phase=Phase.CODE_REVIEW)
        assert fresh_state.current_epic == 2
        assert fresh_state.current_story == "2.3"
        assert fresh_state.current_phase == Phase.CODE_REVIEW

    def test_update_position_sets_updated_at(self, fresh_state: State) -> None:
        """AC1: update_position sets updated_at to current UTC datetime."""
        fixed_time = datetime(2025, 12, 10, 15, 0, 0)
        with patch("bmad_assist.core.state._get_now", return_value=fixed_time):
            update_position(fresh_state, epic=1)
        assert fresh_state.updated_at == fixed_time

    def test_update_position_preserves_completed_stories(self, mid_story_state: State) -> None:
        """AC1: update_position preserves completed_stories."""
        original_completed = mid_story_state.completed_stories.copy()
        update_position(mid_story_state, epic=3, story="3.1", phase=Phase.CREATE_STORY)
        assert mid_story_state.completed_stories == original_completed


# =============================================================================
# AC2: Update position sets started_at on first update
# =============================================================================


class TestUpdatePositionStartedAt:
    """Test update_position sets started_at on first update (AC2)."""

    def test_update_position_sets_started_at_on_fresh_state(self, fresh_state: State) -> None:
        """AC2: started_at is set on first update."""
        assert fresh_state.started_at is None
        fixed_time = datetime(2025, 12, 10, 15, 0, 0)
        with patch("bmad_assist.core.state._get_now", return_value=fixed_time):
            update_position(fresh_state, epic=1, story="1.1", phase=Phase.CREATE_STORY)
        assert fresh_state.started_at == fixed_time

    def test_update_position_started_at_equals_updated_at_on_first(
        self, fresh_state: State
    ) -> None:
        """AC2: started_at equals updated_at on first update."""
        fixed_time = datetime(2025, 12, 10, 15, 0, 0)
        with patch("bmad_assist.core.state._get_now", return_value=fixed_time):
            update_position(fresh_state, epic=1, story="1.1", phase=Phase.CREATE_STORY)
        assert fresh_state.started_at == fresh_state.updated_at

    def test_update_position_preserves_started_at_on_subsequent(
        self, mid_story_state: State
    ) -> None:
        """AC2: started_at is preserved on subsequent updates."""
        original_started = mid_story_state.started_at
        update_position(mid_story_state, epic=3)
        assert mid_story_state.started_at == original_started

    def test_update_position_updates_only_updated_at_on_subsequent(
        self, mid_story_state: State
    ) -> None:
        """AC2: updated_at is updated but started_at preserved on subsequent calls."""
        original_started = mid_story_state.started_at
        new_time = datetime(2025, 12, 10, 20, 0, 0)
        with patch("bmad_assist.core.state._get_now", return_value=new_time):
            update_position(mid_story_state, phase=Phase.CODE_REVIEW)
        assert mid_story_state.started_at == original_started
        assert mid_story_state.updated_at == new_time


# =============================================================================
# AC3: Mark story completed adds to completed_stories
# =============================================================================


class TestMarkStoryCompleted:
    """Test mark_story_completed adds to completed_stories (AC3)."""

    def test_mark_story_completed_adds_to_list(self, mid_story_state: State) -> None:
        """AC3: current_story is appended to completed_stories."""
        assert "2.3" not in mid_story_state.completed_stories
        mark_story_completed(mid_story_state)
        assert "2.3" in mid_story_state.completed_stories

    def test_mark_story_completed_appends_at_end(self, mid_story_state: State) -> None:
        """AC3: current_story is appended at end of list."""
        original_list = mid_story_state.completed_stories.copy()
        mark_story_completed(mid_story_state)
        assert mid_story_state.completed_stories == original_list + ["2.3"]

    def test_mark_story_completed_updates_updated_at(self, mid_story_state: State) -> None:
        """AC3: updated_at is updated."""
        fixed_time = datetime(2025, 12, 10, 16, 0, 0)
        with patch("bmad_assist.core.state._get_now", return_value=fixed_time):
            mark_story_completed(mid_story_state)
        assert mid_story_state.updated_at == fixed_time

    def test_mark_story_completed_preserves_current_story(self, mid_story_state: State) -> None:
        """AC3: current_story remains unchanged (advance_state handles transition)."""
        mark_story_completed(mid_story_state)
        assert mid_story_state.current_story == "2.3"

    def test_mark_story_completed_with_empty_list(self) -> None:
        """AC3: Works with empty completed_stories list."""
        state = State(current_story="1.1", completed_stories=[])
        mark_story_completed(state)
        assert state.completed_stories == ["1.1"]


# =============================================================================
# AC4: Mark story completed is idempotent
# =============================================================================


class TestMarkStoryCompletedIdempotent:
    """Test mark_story_completed is idempotent (AC4)."""

    def test_mark_story_completed_no_duplicate(self) -> None:
        """AC4: story not added again if already in list."""
        state = State(
            current_story="2.3",
            completed_stories=["1.1", "1.2", "2.1", "2.2", "2.3"],
        )
        original_length = len(state.completed_stories)
        mark_story_completed(state)
        assert len(state.completed_stories) == original_length

    def test_mark_story_completed_idempotent_still_updates_timestamp(self) -> None:
        """AC4: updated_at is still updated even if no list change."""
        state = State(
            current_story="2.3",
            completed_stories=["2.3"],
            updated_at=datetime(2025, 12, 10, 10, 0, 0),
        )
        new_time = datetime(2025, 12, 10, 16, 0, 0)
        with patch("bmad_assist.core.state._get_now", return_value=new_time):
            mark_story_completed(state)
        assert state.updated_at == new_time

    def test_mark_story_completed_multiple_calls(self, mid_story_state: State) -> None:
        """AC4: Multiple calls don't create multiple entries."""
        mark_story_completed(mid_story_state)
        mark_story_completed(mid_story_state)
        mark_story_completed(mid_story_state)
        count = mid_story_state.completed_stories.count("2.3")
        assert count == 1


# =============================================================================
# AC5: Advance state moves to next phase within story
# =============================================================================


class TestAdvanceStateBasic:
    """Test advance_state moves to next phase (AC5)."""

    def test_advance_state_from_create_story(self) -> None:
        """AC5: CREATE_STORY advances to VALIDATE_STORY."""
        state = State(current_phase=Phase.CREATE_STORY)
        advance_state(state)
        assert state.current_phase == Phase.VALIDATE_STORY

    def test_advance_state_updates_updated_at(self) -> None:
        """AC5: updated_at is updated."""
        state = State(current_phase=Phase.CREATE_STORY)
        fixed_time = datetime(2025, 12, 10, 17, 0, 0)
        with patch("bmad_assist.core.state._get_now", return_value=fixed_time):
            advance_state(state)
        assert state.updated_at == fixed_time

    def test_advance_state_preserves_epic(self) -> None:
        """AC5: epic remains unchanged."""
        state = State(current_epic=2, current_story="2.3", current_phase=Phase.CREATE_STORY)
        advance_state(state)
        assert state.current_epic == 2

    def test_advance_state_preserves_story(self) -> None:
        """AC5: story remains unchanged."""
        state = State(current_epic=2, current_story="2.3", current_phase=Phase.CREATE_STORY)
        advance_state(state)
        assert state.current_story == "2.3"


# =============================================================================
# AC6: Advance state handles phase ordering correctly
# =============================================================================


class TestAdvanceStatePhaseOrdering:
    """Test advance_state handles phase ordering (AC6)."""

    def test_default_loop_config_has_expected_phases(self) -> None:
        """AC6: DEFAULT_LOOP_CONFIG.story contains expected phases (minimal, no TEA)."""
        # Default config has 6-phase story loop without TEA phases
        expected_story = [
            "create_story",
            "validate_story",
            "validate_story_synthesis",
            "dev_story",
            "code_review",
            "code_review_synthesis",
        ]
        assert DEFAULT_LOOP_CONFIG.story == expected_story

    def test_default_loop_config_teardown(self) -> None:
        """AC6: DEFAULT_LOOP_CONFIG.epic_teardown contains only retrospective (no TEA)."""
        assert DEFAULT_LOOP_CONFIG.epic_teardown == ["retrospective"]

    @pytest.mark.parametrize(
        "current_phase,expected_next",
        [
            # Test transitions within DEFAULT_LOOP_CONFIG.story (minimal, no TEA)
            (Phase.CREATE_STORY, Phase.VALIDATE_STORY),
            (Phase.VALIDATE_STORY, Phase.VALIDATE_STORY_SYNTHESIS),
            (Phase.VALIDATE_STORY_SYNTHESIS, Phase.DEV_STORY),  # No ATDD in default
            (Phase.DEV_STORY, Phase.CODE_REVIEW),
            (Phase.CODE_REVIEW, Phase.CODE_REVIEW_SYNTHESIS),
        ],
    )
    def test_advance_state_transitions_correctly(
        self, current_phase: Phase, expected_next: Phase
    ) -> None:
        """AC6: Each phase advances to correct next phase."""
        state = State(current_phase=current_phase)
        advance_state(state)
        assert state.current_phase == expected_next


# =============================================================================
# AC7: Advance state returns next phase info
# =============================================================================


class TestAdvanceStateReturnValue:
    """Test advance_state returns next phase info (AC7)."""

    def test_advance_state_returns_dict(self) -> None:
        """AC7: advance_state returns a dict."""
        state = State(current_phase=Phase.DEV_STORY)
        result = advance_state(state)
        assert isinstance(result, dict)

    def test_advance_state_returns_previous_phase(self) -> None:
        """AC7: result contains previous_phase."""
        state = State(current_phase=Phase.DEV_STORY)
        result = advance_state(state)
        assert result["previous_phase"] == Phase.DEV_STORY

    def test_advance_state_returns_new_phase(self) -> None:
        """AC7: result contains new_phase."""
        state = State(current_phase=Phase.DEV_STORY)
        result = advance_state(state)
        assert result["new_phase"] == Phase.CODE_REVIEW

    def test_advance_state_returns_transitioned_true(self) -> None:
        """AC7: result contains transitioned=True."""
        state = State(current_phase=Phase.DEV_STORY)
        result = advance_state(state)
        assert result["transitioned"] is True

    def test_advance_state_returns_epic_complete_false(self) -> None:
        """AC7: result contains epic_complete=False when not at RETROSPECTIVE."""
        state = State(current_phase=Phase.DEV_STORY)
        result = advance_state(state)
        assert result["epic_complete"] is False


# =============================================================================
# AC8: Advance state at RETROSPECTIVE indicates epic complete
# =============================================================================


class TestAdvanceStateAtLastStoryPhase:
    """Test advance_state at last story phase indicates epic complete (AC8).

    Note: In the configurable loop architecture, advance_state uses LoopConfig.story.
    The last phase in DEFAULT_LOOP_CONFIG.story is TEST_REVIEW (Story 25.12).
    """

    @pytest.fixture
    def last_story_phase_state(self) -> State:
        """State at the last phase in the story sequence (CODE_REVIEW_SYNTHESIS)."""
        return State(
            current_epic=2,
            current_story="2.5",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,  # Last phase in minimal loop
            completed_stories=["2.1", "2.2", "2.3", "2.4", "2.5"],
            started_at=datetime(2025, 12, 10, 8, 0, 0),
            updated_at=datetime(2025, 12, 10, 18, 0, 0),
        )

    def test_advance_state_at_last_story_phase_returns_epic_complete(
        self, last_story_phase_state: State
    ) -> None:
        """AC8: epic_complete is True at last story phase."""
        result = advance_state(last_story_phase_state)
        assert result["epic_complete"] is True

    def test_advance_state_at_last_story_phase_not_transitioned(
        self, last_story_phase_state: State
    ) -> None:
        """AC8: transitioned is False at last story phase."""
        result = advance_state(last_story_phase_state)
        assert result["transitioned"] is False

    def test_advance_state_at_last_story_phase_phase_unchanged(
        self, last_story_phase_state: State
    ) -> None:
        """AC8: current_phase remains at last story phase."""
        advance_state(last_story_phase_state)
        assert last_story_phase_state.current_phase == Phase.CODE_REVIEW_SYNTHESIS

    def test_advance_state_at_last_story_phase_previous_equals_new(
        self, last_story_phase_state: State
    ) -> None:
        """AC8: previous_phase equals new_phase."""
        result = advance_state(last_story_phase_state)
        assert result["previous_phase"] == result["new_phase"]
        assert result["previous_phase"] == Phase.CODE_REVIEW_SYNTHESIS

    def test_advance_state_at_last_story_phase_updates_timestamp(
        self, last_story_phase_state: State
    ) -> None:
        """AC8: updated_at is still updated even when no transition occurs."""
        original_updated = last_story_phase_state.updated_at
        fixed_time = datetime(2025, 12, 10, 20, 0, 0)
        with patch("bmad_assist.core.state._get_now", return_value=fixed_time):
            advance_state(last_story_phase_state)
        assert last_story_phase_state.updated_at == fixed_time
        assert last_story_phase_state.updated_at != original_updated


# =============================================================================
# AC9: Update position with partial args updates only specified fields
# =============================================================================


class TestUpdatePositionPartialArgs:
    """Test update_position with partial args (AC9)."""

    def test_update_position_only_phase(self, mid_story_state: State) -> None:
        """AC9: Only phase specified updates only phase."""
        update_position(mid_story_state, phase=Phase.CODE_REVIEW)
        assert mid_story_state.current_phase == Phase.CODE_REVIEW
        assert mid_story_state.current_epic == 2
        assert mid_story_state.current_story == "2.3"

    def test_update_position_only_epic(self, mid_story_state: State) -> None:
        """AC9: Only epic specified updates only epic."""
        update_position(mid_story_state, epic=5)
        assert mid_story_state.current_epic == 5
        assert mid_story_state.current_story == "2.3"
        assert mid_story_state.current_phase == Phase.DEV_STORY

    def test_update_position_only_story(self, mid_story_state: State) -> None:
        """AC9: Only story specified updates only story."""
        update_position(mid_story_state, story="5.1")
        assert mid_story_state.current_story == "5.1"
        assert mid_story_state.current_epic == 2
        assert mid_story_state.current_phase == Phase.DEV_STORY

    def test_update_position_no_args_only_updates_timestamp(self, mid_story_state: State) -> None:
        """AC9: No args specified still updates timestamp."""
        original_epic = mid_story_state.current_epic
        original_story = mid_story_state.current_story
        original_phase = mid_story_state.current_phase
        new_time = datetime(2025, 12, 10, 20, 0, 0)
        with patch("bmad_assist.core.state._get_now", return_value=new_time):
            update_position(mid_story_state)
        assert mid_story_state.current_epic == original_epic
        assert mid_story_state.current_story == original_story
        assert mid_story_state.current_phase == original_phase
        assert mid_story_state.updated_at == new_time


# =============================================================================
# AC10: Functions have correct signatures and exports
# =============================================================================


class TestFunctionSignaturesAndExports:
    """Test function signatures and exports (AC10)."""

    def test_update_position_in_all(self) -> None:
        """AC10: update_position is in __all__."""
        from bmad_assist.core import state as state_module

        assert "update_position" in state_module.__all__

    def test_mark_story_completed_in_all(self) -> None:
        """AC10: mark_story_completed is in __all__."""
        from bmad_assist.core import state as state_module

        assert "mark_story_completed" in state_module.__all__

    def test_advance_state_in_all(self) -> None:
        """AC10: advance_state is in __all__."""
        from bmad_assist.core import state as state_module

        assert "advance_state" in state_module.__all__

    def test_default_loop_config_exported(self) -> None:
        """AC10: DEFAULT_LOOP_CONFIG is importable from config."""
        from bmad_assist.core.config import DEFAULT_LOOP_CONFIG as config

        # Verify it's a LoopConfig instance with required fields
        assert hasattr(config, "story")
        assert hasattr(config, "epic_setup")
        assert hasattr(config, "epic_teardown")

    def test_update_position_keyword_only_args(self) -> None:
        """AC10: update_position requires keyword-only args."""
        state = State()
        # Should work with keyword args
        update_position(state, epic=1, story="1.1", phase=Phase.CREATE_STORY)
        # Attempting positional args should fail (won't compile but test pattern)
        # Verify keyword-only by checking function signature
        import inspect

        sig = inspect.signature(update_position)
        params = list(sig.parameters.values())
        # First param is 'state', rest should be keyword-only
        assert params[0].name == "state"
        for param in params[1:]:
            assert param.kind == inspect.Parameter.KEYWORD_ONLY

    def test_mark_story_completed_signature(self) -> None:
        """AC10: mark_story_completed(state: State) -> None."""
        import inspect

        sig = inspect.signature(mark_story_completed)
        params = list(sig.parameters.values())
        assert len(params) == 1
        assert params[0].name == "state"
        assert sig.return_annotation is None or sig.return_annotation is type(None)

    def test_advance_state_signature(self) -> None:
        """AC10: advance_state(state: State, phase_list: list[str] | None = None) -> dict[str, Any]."""
        import inspect

        sig = inspect.signature(advance_state)
        params = list(sig.parameters.values())
        # First param is 'state' (required), second is optional 'phase_list'
        assert len(params) == 2
        assert params[0].name == "state"
        assert params[1].name == "phase_list"
        assert params[1].default is None  # Optional with default None


# =============================================================================
# AC11: Google-style docstrings are complete and testable
# =============================================================================


class TestDocstrings:
    """Test Google-style docstrings (AC11)."""

    def test_update_position_has_docstring(self) -> None:
        """AC11: update_position has non-empty docstring."""
        assert update_position.__doc__ is not None
        assert len(update_position.__doc__.strip()) > 0

    def test_update_position_docstring_has_args(self) -> None:
        """AC11: update_position docstring has Args section."""
        assert "Args:" in update_position.__doc__

    def test_update_position_docstring_has_example(self) -> None:
        """AC11: update_position docstring has Example section."""
        assert "Example:" in update_position.__doc__

    def test_mark_story_completed_has_docstring(self) -> None:
        """AC11: mark_story_completed has non-empty docstring."""
        assert mark_story_completed.__doc__ is not None
        assert len(mark_story_completed.__doc__.strip()) > 0

    def test_mark_story_completed_docstring_has_args(self) -> None:
        """AC11: mark_story_completed docstring has Args section."""
        assert "Args:" in mark_story_completed.__doc__

    def test_mark_story_completed_docstring_has_raises(self) -> None:
        """AC11: mark_story_completed docstring has Raises section."""
        assert "Raises:" in mark_story_completed.__doc__

    def test_mark_story_completed_docstring_has_example(self) -> None:
        """AC11: mark_story_completed docstring has Example section."""
        assert "Example:" in mark_story_completed.__doc__

    def test_advance_state_has_docstring(self) -> None:
        """AC11: advance_state has non-empty docstring."""
        assert advance_state.__doc__ is not None
        assert len(advance_state.__doc__.strip()) > 0

    def test_advance_state_docstring_has_args(self) -> None:
        """AC11: advance_state docstring has Args section."""
        assert "Args:" in advance_state.__doc__

    def test_advance_state_docstring_has_returns(self) -> None:
        """AC11: advance_state docstring has Returns section."""
        assert "Returns:" in advance_state.__doc__

    def test_advance_state_docstring_has_raises(self) -> None:
        """AC11: advance_state docstring has Raises section."""
        assert "Raises:" in advance_state.__doc__

    def test_advance_state_docstring_has_example(self) -> None:
        """AC11: advance_state docstring has Example section."""
        assert "Example:" in advance_state.__doc__

    def test_docstrings_have_one_line_summary(self) -> None:
        """AC11: Each docstring starts with one-line summary."""
        for func in [update_position, mark_story_completed, advance_state]:
            docstring = func.__doc__
            lines = [line.strip() for line in docstring.split("\n") if line.strip()]
            assert len(lines) > 0, f"{func.__name__} docstring has no content"
            # First line should be a complete sentence (ends with period or similar)
            first_line = lines[0]
            assert len(first_line) > 10, f"{func.__name__} summary too short"


# =============================================================================
# Error Cases
# =============================================================================


class TestErrorCases:
    """Test error handling for position functions."""

    def test_mark_story_completed_raises_when_no_story(self) -> None:
        """mark_story_completed raises StateError if current_story is None."""
        state = State(current_story=None)
        with pytest.raises(StateError) as exc_info:
            mark_story_completed(state)
        assert "no current story" in str(exc_info.value).lower()

    def test_advance_state_raises_when_no_phase(self) -> None:
        """advance_state raises StateError if current_phase is None."""
        state = State(current_phase=None)
        with pytest.raises(StateError) as exc_info:
            advance_state(state)
        assert "no current phase" in str(exc_info.value).lower()

    def test_advance_state_raises_stateerror_for_invalid_phase(self) -> None:
        """advance_state raises StateError for phase not in loop config."""
        # Use a phase that's not in DEFAULT_LOOP_CONFIG.story (e.g. RETROSPECTIVE)
        state = State(current_phase=Phase.RETROSPECTIVE)
        # RETROSPECTIVE is in epic_teardown, not story, so advance_state should fail
        with pytest.raises(StateError) as exc_info:
            advance_state(state)
        assert "not in loop config" in str(exc_info.value).lower()


# =============================================================================
# Timestamp Tests
# =============================================================================


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases for position functions."""

    def test_update_position_first_story_in_first_epic(self) -> None:
        """First story of first epic sets all timestamps correctly."""
        state = State()
        fixed_time = datetime(2025, 12, 10, 8, 0, 0)
        with patch("bmad_assist.core.state._get_now", return_value=fixed_time):
            update_position(state, epic=1, story="1.1", phase=Phase.CREATE_STORY)
        assert state.current_epic == 1
        assert state.current_story == "1.1"
        assert state.current_phase == Phase.CREATE_STORY
        assert state.started_at == fixed_time
        assert state.updated_at == fixed_time
        assert state.completed_stories == []

    def test_mark_story_completed_on_first_story(self) -> None:
        """First story can be marked completed."""
        state = State(current_story="1.1", completed_stories=[])
        mark_story_completed(state)
        assert state.completed_stories == ["1.1"]

    def test_advance_state_full_cycle(self) -> None:
        """State can advance through all story phases until epic_complete is signaled.

        Uses DEFAULT_LOOP_CONFIG.story phases and expects epic_complete=True
        at the end of the story phase sequence.
        """
        state = State(current_phase=Phase.CREATE_STORY)
        phases_traversed = [state.current_phase]

        while True:
            result = advance_state(state)
            phases_traversed.append(state.current_phase)
            if result["epic_complete"]:
                break

        # Expected: traverse all story phases, then epic_complete at the last one
        # DEFAULT_LOOP_CONFIG.story = [create_story, validate_story, validate_story_synthesis,
        #                              dev_story, code_review, code_review_synthesis]
        # (minimal loop, no TEA phases like atdd or test_review)
        expected = [
            Phase.CREATE_STORY,
            Phase.VALIDATE_STORY,
            Phase.VALIDATE_STORY_SYNTHESIS,
            Phase.DEV_STORY,
            Phase.CODE_REVIEW,
            Phase.CODE_REVIEW_SYNTHESIS,
            Phase.CODE_REVIEW_SYNTHESIS,  # No transition at last phase
        ]
        assert phases_traversed == expected

    def test_completed_stories_order_preserved(self) -> None:
        """Completed stories maintain insertion order."""
        state = State(current_story="1.1", completed_stories=[])
        mark_story_completed(state)
        state.current_story = "1.2"
        mark_story_completed(state)
        state.current_story = "1.3"
        mark_story_completed(state)
        assert state.completed_stories == ["1.1", "1.2", "1.3"]


# =============================================================================
# ATDD Epic Flag Reset (Story testarch-6)
# =============================================================================


class TestUpdatePositionATDDReset:
    """Test update_position resets atdd_ran_in_epic on epic change."""

    def test_update_position_resets_atdd_ran_in_epic_on_epic_change(self) -> None:
        """update_position resets atdd_ran_in_epic when epic changes."""
        state = State(
            current_epic=1,
            current_story="1.5",
            atdd_ran_in_epic=True,
        )

        # Change epic
        update_position(state, epic=2)

        # Flag should be reset
        assert state.atdd_ran_in_epic is False
        assert state.current_epic == 2

    def test_update_position_preserves_atdd_ran_in_epic_when_same_epic(self) -> None:
        """update_position preserves atdd_ran_in_epic when epic stays the same."""
        state = State(
            current_epic=1,
            current_story="1.5",
            atdd_ran_in_epic=True,
        )

        # Update story within same epic
        update_position(state, story="1.6")

        # Flag should be preserved
        assert state.atdd_ran_in_epic is True
        assert state.current_story == "1.6"

    def test_update_position_preserves_atdd_ran_in_epic_when_epic_none(self) -> None:
        """update_position preserves atdd_ran_in_epic when epic arg is None."""
        state = State(
            current_epic=1,
            current_story="1.5",
            atdd_ran_in_epic=True,
        )

        # Update phase only
        update_position(state, phase=Phase.DEV_STORY)

        # Flag should be preserved
        assert state.atdd_ran_in_epic is True

    def test_update_position_resets_atdd_ran_in_epic_numeric_to_string_epic(
        self,
    ) -> None:
        """update_position resets atdd_ran_in_epic when changing to string epic."""
        state = State(
            current_epic=1,
            current_story="1.5",
            atdd_ran_in_epic=True,
        )

        # Change to string epic (module epic)
        update_position(state, epic="testarch")

        # Flag should be reset
        assert state.atdd_ran_in_epic is False
        assert state.current_epic == "testarch"

    def test_update_position_does_not_reset_atdd_ran_for_story(self) -> None:
        """update_position does NOT reset atdd_ran_for_story (handler's responsibility)."""
        state = State(
            current_epic=1,
            current_story="1.5",
            atdd_ran_for_story=True,
        )

        # Change epic
        update_position(state, epic=2)

        # atdd_ran_for_story should NOT be reset by update_position
        # (only atdd_ran_in_epic is reset, atdd_ran_for_story is reset by handler)
        assert state.atdd_ran_for_story is True


# =============================================================================
# Framework/CI Epic Flag Reset (Story 25.9)
# =============================================================================


class TestUpdatePositionFrameworkCIReset:
    """Test update_position resets framework_ran_in_epic and ci_ran_in_epic on epic change."""

    def test_update_position_resets_framework_ran_in_epic_on_epic_change(self) -> None:
        """update_position resets framework_ran_in_epic when epic changes."""
        state = State(
            current_epic=1,
            current_story="1.5",
            framework_ran_in_epic=True,
        )

        # Change epic
        update_position(state, epic=2)

        # Flag should be reset
        assert state.framework_ran_in_epic is False
        assert state.current_epic == 2

    def test_update_position_resets_ci_ran_in_epic_on_epic_change(self) -> None:
        """update_position resets ci_ran_in_epic when epic changes."""
        state = State(
            current_epic=1,
            current_story="1.5",
            ci_ran_in_epic=True,
        )

        # Change epic
        update_position(state, epic=2)

        # Flag should be reset
        assert state.ci_ran_in_epic is False
        assert state.current_epic == 2

    def test_update_position_preserves_framework_ran_in_epic_when_same_epic(self) -> None:
        """update_position preserves framework_ran_in_epic when epic stays the same."""
        state = State(
            current_epic=1,
            current_story="1.5",
            framework_ran_in_epic=True,
        )

        # Update story within same epic
        update_position(state, story="1.6")

        # Flag should be preserved
        assert state.framework_ran_in_epic is True
        assert state.current_story == "1.6"

    def test_update_position_preserves_ci_ran_in_epic_when_same_epic(self) -> None:
        """update_position preserves ci_ran_in_epic when epic stays the same."""
        state = State(
            current_epic=1,
            current_story="1.5",
            ci_ran_in_epic=True,
        )

        # Update story within same epic
        update_position(state, story="1.6")

        # Flag should be preserved
        assert state.ci_ran_in_epic is True

    def test_update_position_resets_all_epic_flags_on_epic_change(self) -> None:
        """update_position resets all epic-scoped flags when epic changes."""
        state = State(
            current_epic=1,
            current_story="1.5",
            atdd_ran_in_epic=True,
            framework_ran_in_epic=True,
            ci_ran_in_epic=True,
            test_design_ran_in_epic=True,
            automate_ran_in_epic=True,
            nfr_assess_ran_in_epic=True,
        )

        # Change epic
        update_position(state, epic=2)

        # All epic-scoped flags should be reset
        assert state.atdd_ran_in_epic is False
        assert state.framework_ran_in_epic is False
        assert state.ci_ran_in_epic is False
        assert state.test_design_ran_in_epic is False
        assert state.automate_ran_in_epic is False
        assert state.nfr_assess_ran_in_epic is False

    def test_update_position_preserves_all_flags_when_epic_none(self) -> None:
        """update_position preserves all epic flags when epic arg is None."""
        state = State(
            current_epic=1,
            current_story="1.5",
            atdd_ran_in_epic=True,
            framework_ran_in_epic=True,
            ci_ran_in_epic=True,
            test_design_ran_in_epic=True,
            automate_ran_in_epic=True,
            nfr_assess_ran_in_epic=True,
        )

        # Update phase only
        update_position(state, phase=Phase.DEV_STORY)

        # All flags should be preserved
        assert state.atdd_ran_in_epic is True
        assert state.framework_ran_in_epic is True
        assert state.ci_ran_in_epic is True
        assert state.test_design_ran_in_epic is True
        assert state.automate_ran_in_epic is True
        assert state.nfr_assess_ran_in_epic is True
