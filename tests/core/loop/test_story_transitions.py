"""Tests for story_transitions module.

Story 6.3: Story Completion and Transition
- complete_story()
- is_last_story_in_epic()
- get_next_story_id()
- advance_to_next_story()
- persist_story_completion()
- handle_story_completion()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from bmad_assist.core.exceptions import StateError

if TYPE_CHECKING:
    pass


class TestCompleteStory:
    """AC1: complete_story() marks story as completed."""

    def test_complete_story_adds_to_completed_list(self) -> None:
        """AC1: current_story is added to completed_stories."""
        from bmad_assist.core.loop import complete_story
        from bmad_assist.core.state import Phase, State

        state = State(
            current_epic=2,
            current_story="2.3",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
            completed_stories=["2.1", "2.2"],
        )

        new_state = complete_story(state)

        assert "2.3" in new_state.completed_stories
        assert new_state.completed_stories == ["2.1", "2.2", "2.3"]

    def test_complete_story_sets_updated_at(self) -> None:
        """AC1: updated_at is set to current naive UTC timestamp."""
        from datetime import UTC, datetime

        from bmad_assist.core.loop import complete_story
        from bmad_assist.core.state import State

        state = State(current_story="1.1")

        with patch("bmad_assist.core.loop.story_transitions.datetime") as mock_dt:
            mock_now = datetime(2025, 12, 12, 10, 0, 0, tzinfo=UTC)
            mock_dt.now.return_value = mock_now

            new_state = complete_story(state)

        # State stores naive UTC (per project convention)
        assert new_state.updated_at == mock_now.replace(tzinfo=None)

    def test_complete_story_does_not_modify_original(self) -> None:
        """AC1: Original state is not modified (immutability)."""
        from bmad_assist.core.loop import complete_story
        from bmad_assist.core.state import State

        state = State(current_story="1.1", completed_stories=["1.0"])
        original_completed = state.completed_stories.copy()

        new_state = complete_story(state)

        assert state.completed_stories == original_completed
        assert new_state is not state

    def test_complete_story_raises_on_none_story(self) -> None:
        """AC1: Raises StateError when current_story is None."""
        from bmad_assist.core.loop import complete_story
        from bmad_assist.core.state import State

        state = State(current_story=None)

        with pytest.raises(StateError, match="no current story set"):
            complete_story(state)

    def test_complete_story_empty_completed_list(self) -> None:
        """AC1: Works with empty completed_stories list."""
        from bmad_assist.core.loop import complete_story
        from bmad_assist.core.state import State

        state = State(current_story="1.1", completed_stories=[])

        new_state = complete_story(state)

        assert new_state.completed_stories == ["1.1"]

    def test_complete_story_idempotent_on_duplicate(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC1: complete_story() handles duplicate story gracefully (crash retry)."""
        from bmad_assist.core.loop import complete_story
        from bmad_assist.core.state import State

        state = State(
            current_story="2.3",
            completed_stories=["2.1", "2.2", "2.3"],  # Already completed
        )

        with caplog.at_level(logging.WARNING):
            new_state = complete_story(state)

        # Should NOT add duplicate (idempotent)
        assert new_state.completed_stories.count("2.3") == 1
        assert new_state.completed_stories == ["2.1", "2.2", "2.3"]
        # Should log warning about retry
        assert "already in completed_stories" in caplog.text


class TestIsLastStoryInEpic:
    """AC2: is_last_story_in_epic() detects final story."""

    def test_is_last_story_returns_true_for_last(self) -> None:
        """AC2: Returns True when current_story is last in list."""
        from bmad_assist.core.loop import is_last_story_in_epic
        from bmad_assist.core.state import State

        state = State(current_epic=2, current_story="2.4")
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]

        result = is_last_story_in_epic(state, epic_stories)

        assert result is True

    def test_is_last_story_returns_false_for_not_last(self) -> None:
        """AC2: Returns False when current_story is not last."""
        from bmad_assist.core.loop import is_last_story_in_epic
        from bmad_assist.core.state import State

        state = State(current_epic=2, current_story="2.3")
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]

        result = is_last_story_in_epic(state, epic_stories)

        assert result is False

    def test_is_last_story_raises_on_none_story(self) -> None:
        """AC2: Raises StateError when current_story is None."""
        from bmad_assist.core.loop import is_last_story_in_epic
        from bmad_assist.core.state import State

        state = State(current_story=None)

        with pytest.raises(StateError, match="no current story set"):
            is_last_story_in_epic(state, ["1.1", "1.2"])

    def test_is_last_story_empty_list_returns_true(self) -> None:
        """AC2: Empty epic_stories returns True (all stories done after crash/resume)."""
        from bmad_assist.core.loop import is_last_story_in_epic
        from bmad_assist.core.state import State

        state = State(current_story="1.1")

        # Empty list means all stories filtered out as "done" → last story
        result = is_last_story_in_epic(state, [])
        assert result is True

    def test_is_last_story_single_story_epic(self) -> None:
        """AC2: Single story epic returns True when it matches."""
        from bmad_assist.core.loop import is_last_story_in_epic
        from bmad_assist.core.state import State

        state = State(current_story="1.1")
        epic_stories = ["1.1"]

        result = is_last_story_in_epic(state, epic_stories)

        assert result is True


class TestGetNextStoryId:
    """AC5: get_next_story_id() calculates next story."""

    def test_get_next_story_returns_next(self) -> None:
        """AC5: Returns next story ID in sequence."""
        from bmad_assist.core.loop import get_next_story_id

        epic_stories = ["2.1", "2.2", "2.3", "2.4"]

        result = get_next_story_id("2.2", epic_stories)

        assert result == "2.3"

    def test_get_next_story_returns_none_for_last(self) -> None:
        """AC5: Returns None when current is last story."""
        from bmad_assist.core.loop import get_next_story_id

        epic_stories = ["2.1", "2.2", "2.3", "2.4"]

        result = get_next_story_id("2.4", epic_stories)

        assert result is None

    def test_get_next_story_raises_on_not_found(self) -> None:
        """AC5: Raises StateError when story not in list."""
        from bmad_assist.core.loop import get_next_story_id

        epic_stories = ["2.1", "2.2", "2.3"]

        with pytest.raises(StateError, match="not found in epic stories"):
            get_next_story_id("2.5", epic_stories)

    def test_get_next_story_raises_on_empty_list(self) -> None:
        """AC5: Raises StateError when epic_stories is empty."""
        from bmad_assist.core.loop import get_next_story_id

        with pytest.raises(StateError, match="epic has no stories"):
            get_next_story_id("1.1", [])

    def test_get_next_story_first_returns_second(self) -> None:
        """AC5: First story returns second."""
        from bmad_assist.core.loop import get_next_story_id

        epic_stories = ["2.1", "2.2", "2.3"]

        result = get_next_story_id("2.1", epic_stories)

        assert result == "2.2"


class TestAdvanceToNextStory:
    """AC3: advance_to_next_story() transitions to next story."""

    def test_advance_to_next_story_transitions(self) -> None:
        """AC3: Returns new state with next story and CREATE_STORY phase."""
        from bmad_assist.core.loop import advance_to_next_story
        from bmad_assist.core.state import Phase, State

        state = State(
            current_epic=2,
            current_story="2.3",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
        )
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]

        new_state = advance_to_next_story(state, epic_stories)

        assert new_state is not None
        assert new_state.current_story == "2.4"
        assert new_state.current_phase == Phase.CREATE_STORY

    def test_advance_to_next_story_returns_none_for_last(self) -> None:
        """AC3: Returns None when current story is last."""
        from bmad_assist.core.loop import advance_to_next_story
        from bmad_assist.core.state import State

        state = State(current_epic=2, current_story="2.4")
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]

        result = advance_to_next_story(state, epic_stories)

        assert result is None

    def test_advance_to_next_story_raises_on_none_story(self) -> None:
        """AC3: Raises StateError when current_story is None."""
        from bmad_assist.core.loop import advance_to_next_story
        from bmad_assist.core.state import State

        state = State(current_story=None)

        with pytest.raises(StateError, match="no current story set"):
            advance_to_next_story(state, ["1.1", "1.2"])

    def test_advance_to_next_story_logs_transition(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC3: Logs story transition at INFO level."""
        from bmad_assist.core.loop import advance_to_next_story
        from bmad_assist.core.state import State

        state = State(current_epic=2, current_story="2.3")
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]

        with caplog.at_level(logging.INFO):
            advance_to_next_story(state, epic_stories)

        assert "Advancing to story 2.4" in caplog.text

    def test_advance_to_next_story_logs_last_story(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC3: Logs when current story is last in epic."""
        from bmad_assist.core.loop import advance_to_next_story
        from bmad_assist.core.state import State

        state = State(current_epic=2, current_story="2.4")
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]

        with caplog.at_level(logging.INFO):
            advance_to_next_story(state, epic_stories)

        assert "last in epic" in caplog.text

    def test_advance_to_next_story_raises_on_empty_list(self) -> None:
        """AC3: Raises StateError when epic_stories is empty."""
        from bmad_assist.core.loop import advance_to_next_story
        from bmad_assist.core.state import State

        state = State(current_story="1.1")

        with pytest.raises(StateError, match="epic has no stories"):
            advance_to_next_story(state, [])

    def test_advance_to_next_story_sets_updated_at(self) -> None:
        """AC3: updated_at is set on transition."""
        from datetime import UTC, datetime

        from bmad_assist.core.loop import advance_to_next_story
        from bmad_assist.core.state import State

        state = State(current_story="2.3")
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]

        with patch("bmad_assist.core.loop.story_transitions.datetime") as mock_dt:
            mock_now = datetime(2025, 12, 12, 10, 0, 0, tzinfo=UTC)
            mock_dt.now.return_value = mock_now

            new_state = advance_to_next_story(state, epic_stories)

        assert new_state is not None
        assert new_state.updated_at == mock_now.replace(tzinfo=None)


class TestPersistStoryCompletion:
    """AC4: persist_story_completion() saves state."""

    def test_persist_story_completion_calls_save_state(self) -> None:
        """AC4: Calls save_state with state and path."""
        from bmad_assist.core.loop import persist_story_completion
        from bmad_assist.core.state import State

        state = State(current_story="1.1", completed_stories=["1.1"])
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.story_transitions.save_state") as mock_save:
            persist_story_completion(state, state_path)

            mock_save.assert_called_once_with(state, state_path)

    def test_persist_story_completion_propagates_state_error(self) -> None:
        """AC4: Propagates StateError from save_state."""
        from bmad_assist.core.loop import persist_story_completion
        from bmad_assist.core.state import State

        state = State(current_story="1.1")
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.story_transitions.save_state") as mock_save:
            mock_save.side_effect = StateError("Write failed")

            with pytest.raises(StateError, match="Write failed"):
                persist_story_completion(state, state_path)

    def test_persist_story_completion_returns_none(self) -> None:
        """AC4: Returns None on success (void operation)."""
        from bmad_assist.core.loop import persist_story_completion
        from bmad_assist.core.state import State

        state = State(current_story="1.1")
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.story_transitions.save_state"):
            result = persist_story_completion(state, state_path)

            assert result is None


class TestHandleStoryCompletion:
    """AC6: handle_story_completion() orchestrates full flow."""

    def test_handle_story_completion_full_flow_not_last(self) -> None:
        """AC6: Full flow when NOT last story - advances to next."""
        from bmad_assist.core.loop import handle_story_completion
        from bmad_assist.core.state import Phase, State

        state = State(
            current_epic=2,
            current_story="2.3",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
            completed_stories=["2.1", "2.2"],
        )
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.story_transitions.save_state"):
            new_state, is_epic_complete = handle_story_completion(state, epic_stories, state_path)

        assert "2.3" in new_state.completed_stories
        assert new_state.current_story == "2.4"
        assert new_state.current_phase == Phase.CREATE_STORY
        assert is_epic_complete is False

    def test_handle_story_completion_full_flow_last_story(self) -> None:
        """AC6: Full flow when last story - signals epic complete."""
        from bmad_assist.core.loop import handle_story_completion
        from bmad_assist.core.state import Phase, State

        state = State(
            current_epic=2,
            current_story="2.4",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
            completed_stories=["2.1", "2.2", "2.3"],
        )
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.story_transitions.save_state"):
            new_state, is_epic_complete = handle_story_completion(state, epic_stories, state_path)

        assert "2.4" in new_state.completed_stories
        assert is_epic_complete is True

    def test_handle_story_completion_persists_state_once(self) -> None:
        """AC6: Persists FINAL state only (single atomic persist pattern)."""
        from bmad_assist.core.loop import handle_story_completion
        from bmad_assist.core.state import State

        state = State(current_epic=2, current_story="2.3", completed_stories=["2.1", "2.2"])
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.story_transitions.save_state") as mock_save:
            handle_story_completion(state, epic_stories, state_path)

            # Called ONCE with final state (prevents race condition)
            assert mock_save.call_count == 1
            # Verify final state has both completion and transition applied
            saved_state = mock_save.call_args[0][0]
            assert "2.3" in saved_state.completed_stories
            assert saved_state.current_story == "2.4"

    def test_handle_story_completion_logs_epic_complete(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC6: Logs when epic stories are complete."""
        from bmad_assist.core.loop import handle_story_completion
        from bmad_assist.core.state import State

        state = State(current_epic=2, current_story="2.4", completed_stories=["2.1", "2.2", "2.3"])
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.story_transitions.save_state"):
            with caplog.at_level(logging.INFO):
                handle_story_completion(state, epic_stories, state_path)

        # Should log about epic completion or retrospective
        assert "retrospective needed" in caplog.text.lower() or "epic" in caplog.text.lower()

    def test_handle_story_completion_last_story_keeps_phase(self) -> None:
        """AC6: Last story keeps current phase (caller handles RETROSPECTIVE)."""
        from bmad_assist.core.loop import handle_story_completion
        from bmad_assist.core.state import Phase, State

        state = State(
            current_epic=2,
            current_story="2.4",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
            completed_stories=["2.1", "2.2", "2.3"],
        )
        epic_stories = ["2.1", "2.2", "2.3", "2.4"]
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.story_transitions.save_state"):
            new_state, is_epic_complete = handle_story_completion(state, epic_stories, state_path)

        # Per AC6: current_story remains, current_phase unchanged
        assert new_state.current_story == "2.4"
        assert new_state.current_phase == Phase.CODE_REVIEW_SYNTHESIS
        assert is_epic_complete is True

    def test_handle_story_completion_raises_on_none_story(self) -> None:
        """AC6: Propagates StateError from complete_story when no current story."""
        from bmad_assist.core.loop import handle_story_completion
        from bmad_assist.core.state import State

        state = State(current_story=None)
        state_path = Path("/tmp/state.yaml")

        with pytest.raises(StateError, match="no current story set"):
            handle_story_completion(state, ["1.1", "1.2"], state_path)


class TestStory63Exports:
    """Test Story 6.3 functions are properly exported."""

    def test_complete_story_exported(self) -> None:
        """complete_story is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "complete_story" in loop.__all__

    def test_is_last_story_in_epic_exported(self) -> None:
        """is_last_story_in_epic is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "is_last_story_in_epic" in loop.__all__

    def test_get_next_story_id_exported(self) -> None:
        """get_next_story_id is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "get_next_story_id" in loop.__all__

    def test_advance_to_next_story_exported(self) -> None:
        """advance_to_next_story is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "advance_to_next_story" in loop.__all__

    def test_persist_story_completion_exported(self) -> None:
        """persist_story_completion is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "persist_story_completion" in loop.__all__

    def test_handle_story_completion_exported(self) -> None:
        """handle_story_completion is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "handle_story_completion" in loop.__all__
