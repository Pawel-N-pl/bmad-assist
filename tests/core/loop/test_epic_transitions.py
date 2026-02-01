"""Tests for epic_transitions module.

Story 6.4: Epic Completion and Transition
- complete_epic()
- is_last_epic()
- get_next_epic()
- advance_to_next_epic()
- persist_epic_completion()
- handle_epic_completion()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import StateError

if TYPE_CHECKING:
    pass


class TestCompleteEpic:
    """AC1: complete_epic() marks epic as completed."""

    def test_complete_epic_adds_to_completed_list(self) -> None:
        """AC1: current_epic is added to completed_epics."""
        from bmad_assist.core.loop import complete_epic
        from bmad_assist.core.state import Phase, State

        state = State(
            current_epic=2,
            current_story="2.4",
            current_phase=Phase.RETROSPECTIVE,
            completed_epics=[1],
        )

        new_state = complete_epic(state)

        assert 2 in new_state.completed_epics
        assert new_state.completed_epics == [1, 2]

    def test_complete_epic_sets_updated_at(self) -> None:
        """AC1: updated_at is set to current naive UTC timestamp."""
        from datetime import UTC, datetime

        from bmad_assist.core.loop import complete_epic
        from bmad_assist.core.state import State

        state = State(current_epic=1, current_story="1.1")

        with patch("bmad_assist.core.loop.epic_transitions.datetime") as mock_dt:
            mock_now = datetime(2025, 12, 12, 10, 0, 0, tzinfo=UTC)
            mock_dt.now.return_value = mock_now
            mock_dt.UTC = UTC

            new_state = complete_epic(state)

        # State stores naive UTC (per project convention)
        assert new_state.updated_at == mock_now.replace(tzinfo=None)

    def test_complete_epic_does_not_modify_original(self) -> None:
        """AC1: Original state is not modified (immutability)."""
        from bmad_assist.core.loop import complete_epic
        from bmad_assist.core.state import State

        state = State(current_epic=2, completed_epics=[1])
        original_completed = state.completed_epics.copy()

        new_state = complete_epic(state)

        assert state.completed_epics == original_completed
        assert new_state is not state

    def test_complete_epic_raises_on_none_epic(self) -> None:
        """AC1: Raises StateError when current_epic is None."""
        from bmad_assist.core.loop import complete_epic
        from bmad_assist.core.state import State

        state = State(current_epic=None)

        with pytest.raises(StateError, match="no current epic set"):
            complete_epic(state)

    def test_complete_epic_idempotent_on_duplicate(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC1: Handles duplicate completion gracefully (crash-safe retry)."""
        from bmad_assist.core.loop import complete_epic
        from bmad_assist.core.state import State

        state = State(current_epic=2, completed_epics=[1, 2])  # Already completed

        with caplog.at_level(logging.INFO):
            new_state = complete_epic(state)

        # Should NOT add duplicate (idempotent)
        assert new_state.completed_epics.count(2) == 1
        assert new_state.completed_epics == [1, 2]
        # Should log info about idempotent retry
        assert "already in completed_epics" in caplog.text


class TestIsLastEpic:
    """AC2: is_last_epic() detects final epic."""

    def test_is_last_epic_returns_true_for_last(self) -> None:
        """AC2: Returns True when current_epic is last in list."""
        from bmad_assist.core.loop import is_last_epic

        epic_list = [1, 2, 3, 4]

        result = is_last_epic(4, epic_list)

        assert result is True

    def test_is_last_epic_returns_false_for_not_last(self) -> None:
        """AC2: Returns False when current_epic is not last."""
        from bmad_assist.core.loop import is_last_epic

        epic_list = [1, 2, 3, 4]

        result = is_last_epic(3, epic_list)

        assert result is False

    def test_is_last_epic_raises_on_empty_list(self) -> None:
        """AC2: Raises StateError when epic_list is empty."""
        from bmad_assist.core.loop import is_last_epic

        with pytest.raises(StateError, match="no epics in project"):
            is_last_epic(1, [])

    def test_is_last_epic_raises_on_epic_not_in_list(self) -> None:
        """AC2: Raises StateError when current_epic not in list."""
        from bmad_assist.core.loop import is_last_epic

        epic_list = [1, 2, 3, 4]

        with pytest.raises(StateError, match="not found in epic list"):
            is_last_epic(5, epic_list)


class TestGetNextEpic:
    """AC3: get_next_epic() calculates next epic."""

    def test_get_next_epic_returns_next(self) -> None:
        """AC3: Returns next epic number in sequence."""
        from bmad_assist.core.loop import get_next_epic

        epic_list = [1, 2, 3, 4]

        result = get_next_epic(2, epic_list)

        assert result == 3

    def test_get_next_epic_returns_none_for_last(self) -> None:
        """AC3: Returns None when current is last epic."""
        from bmad_assist.core.loop import get_next_epic

        epic_list = [1, 2, 3, 4]

        result = get_next_epic(4, epic_list)

        assert result is None

    def test_get_next_epic_raises_on_not_found(self) -> None:
        """AC3: Raises StateError when epic not in list."""
        from bmad_assist.core.loop import get_next_epic

        epic_list = [1, 2, 3]

        with pytest.raises(StateError, match="not found in epic list"):
            get_next_epic(5, epic_list)

    def test_get_next_epic_raises_on_empty_list(self) -> None:
        """AC3: Raises StateError when epic_list is empty."""
        from bmad_assist.core.loop import get_next_epic

        with pytest.raises(StateError, match="no epics in project"):
            get_next_epic(1, [])


class TestAdvanceToNextEpic:
    """AC4: advance_to_next_epic() transitions to next epic."""

    def test_advance_to_next_epic_transitions(self) -> None:
        """AC4: Returns new state with next epic's first story."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import Phase, State

        state = State(
            current_epic=2,
            current_story="2.4",
            current_phase=Phase.RETROSPECTIVE,
        )
        epic_list = [1, 2, 3, 4]
        epic_stories_loader = MagicMock(return_value=["3.1", "3.2", "3.3"])

        new_state = advance_to_next_epic(state, epic_list, epic_stories_loader)

        assert new_state is not None
        assert new_state.current_epic == 3
        assert new_state.current_story == "3.1"
        assert new_state.current_phase == Phase.CREATE_STORY
        epic_stories_loader.assert_called_once_with(3)

    def test_advance_to_next_epic_returns_none_for_last(self) -> None:
        """AC4: Returns None when current epic is last."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import State

        state = State(current_epic=4, current_story="4.3")
        epic_list = [1, 2, 3, 4]
        epic_stories_loader = MagicMock()

        result = advance_to_next_epic(state, epic_list, epic_stories_loader)

        assert result is None
        epic_stories_loader.assert_not_called()

    def test_advance_to_next_epic_raises_on_none_epic(self) -> None:
        """AC4: Raises StateError when current_epic is None."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import State

        state = State(current_epic=None)

        with pytest.raises(StateError, match="no current epic set"):
            advance_to_next_epic(state, [1, 2, 3], MagicMock())

    def test_advance_to_next_epic_raises_on_empty_list(self) -> None:
        """AC4: Raises StateError when epic_list is empty."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import State

        state = State(current_epic=1)

        with pytest.raises(StateError, match="no epics in project"):
            advance_to_next_epic(state, [], MagicMock())

    def test_advance_to_next_epic_logs_transition(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC4: Logs epic transition at INFO level."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import State

        state = State(current_epic=2, current_story="2.4")
        epic_list = [1, 2, 3, 4]
        epic_stories_loader = MagicMock(return_value=["3.1"])

        with caplog.at_level(logging.INFO):
            advance_to_next_epic(state, epic_list, epic_stories_loader)

        assert "Advancing to epic 3" in caplog.text

    def test_advance_to_next_epic_logs_final_epic(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC4: Logs when current epic is final."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import State

        state = State(current_epic=4, current_story="4.3")
        epic_list = [1, 2, 3, 4]

        with caplog.at_level(logging.INFO):
            advance_to_next_epic(state, epic_list, MagicMock())

        assert "final epic" in caplog.text.lower()

    def test_advance_to_next_epic_skips_epics_with_no_stories(self) -> None:
        """Epics with no stories are skipped (returns None if all are empty)."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import State

        state = State(current_epic=2, current_story="2.4")
        epic_list = [1, 2, 3, 4]
        epic_stories_loader = MagicMock(return_value=[])  # No stories!

        # Should return None (project complete) since all remaining epics have no stories
        result = advance_to_next_epic(state, epic_list, epic_stories_loader)
        assert result is None

    def test_advance_to_next_epic_skips_completed_epics(self) -> None:
        """Skips epics that are already in completed_epics."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import State

        # Epic 19 completed, epic 20 already in completed_epics
        state = State(
            current_epic=19,
            current_story="19.3",
            completed_epics=[20],  # Epic 20 already done!
        )
        epic_list = [19, 20, 21]
        epic_stories_loader = MagicMock(return_value=["21.1", "21.2"])

        new_state = advance_to_next_epic(state, epic_list, epic_stories_loader)

        # Should skip 20 and go to 21
        assert new_state is not None
        assert new_state.current_epic == 21
        assert new_state.current_story == "21.1"
        # Loader called only for epic 21, not 20
        epic_stories_loader.assert_called_once_with(21)

    def test_advance_to_next_epic_skips_multiple_completed(self) -> None:
        """Skips multiple consecutive completed epics."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import State

        state = State(
            current_epic=18,
            current_story="18.5",
            completed_epics=[19, 20, 21],  # Next 3 epics already done!
        )
        epic_list = [18, 19, 20, 21, 22]
        epic_stories_loader = MagicMock(return_value=["22.1"])

        new_state = advance_to_next_epic(state, epic_list, epic_stories_loader)

        # Should skip 19, 20, 21 and go to 22
        assert new_state is not None
        assert new_state.current_epic == 22
        epic_stories_loader.assert_called_once_with(22)

    def test_advance_to_next_epic_returns_none_if_all_remaining_completed(
        self,
    ) -> None:
        """Returns None if all remaining epics are completed."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import State

        state = State(
            current_epic=18,
            current_story="18.5",
            completed_epics=[19, 20],  # All remaining epics done
        )
        epic_list = [18, 19, 20]
        epic_stories_loader = MagicMock()

        result = advance_to_next_epic(state, epic_list, epic_stories_loader)

        # Should return None (project complete)
        assert result is None
        epic_stories_loader.assert_not_called()

    def test_advance_to_next_epic_logs_skipped_epics(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Logs when skipping completed epics."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import State

        state = State(
            current_epic=19,
            current_story="19.3",
            completed_epics=[20],
        )
        epic_list = [19, 20, 21]
        epic_stories_loader = MagicMock(return_value=["21.1"])

        with caplog.at_level(logging.INFO):
            advance_to_next_epic(state, epic_list, epic_stories_loader)

        assert "Skipping epic 20" in caplog.text
        assert "already in completed_epics" in caplog.text

    def test_advance_to_next_epic_all_stories_done_goes_to_retrospective(self) -> None:
        """When all stories in next epic are done, go directly to RETROSPECTIVE."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import Phase, State

        # All stories in epic 20 are already completed
        state = State(
            current_epic=19,
            current_story="19.3",
            completed_stories=["20.1", "20.2", "20.3"],  # All epic 20 stories done
            completed_epics=[],
        )
        epic_list = [19, 20]
        epic_stories_loader = MagicMock(return_value=["20.1", "20.2", "20.3"])

        new_state = advance_to_next_epic(state, epic_list, epic_stories_loader)

        assert new_state is not None
        assert new_state.current_epic == 20
        assert new_state.current_story == "20.3"  # Last story
        # Minimal loop: RETROSPECTIVE is first (and only) in epic_teardown
        assert new_state.current_phase == Phase.RETROSPECTIVE

    def test_advance_to_next_epic_some_stories_done_starts_at_first_incomplete(
        self,
    ) -> None:
        """When some stories are done, start at first incomplete story."""
        from bmad_assist.core.loop import advance_to_next_epic
        from bmad_assist.core.state import Phase, State

        # First two stories in epic 20 are done
        state = State(
            current_epic=19,
            current_story="19.3",
            completed_stories=["20.1", "20.2"],  # Only first two done
            completed_epics=[],
        )
        epic_list = [19, 20]
        epic_stories_loader = MagicMock(return_value=["20.1", "20.2", "20.3"])

        new_state = advance_to_next_epic(state, epic_list, epic_stories_loader)

        assert new_state is not None
        assert new_state.current_epic == 20
        assert new_state.current_story == "20.3"  # First incomplete
        assert new_state.current_phase == Phase.CREATE_STORY


class TestPersistEpicCompletion:
    """AC6: persist_epic_completion() saves state."""

    def test_persist_epic_completion_calls_save_state(self) -> None:
        """AC6: Calls save_state with state and path."""
        from bmad_assist.core.loop import persist_epic_completion
        from bmad_assist.core.state import State

        state = State(current_epic=2, completed_epics=[1, 2])
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.epic_transitions.save_state") as mock_save:
            persist_epic_completion(state, state_path)

            mock_save.assert_called_once_with(state, state_path)

    def test_persist_epic_completion_propagates_state_error(self) -> None:
        """AC6: Propagates StateError from save_state."""
        from bmad_assist.core.loop import persist_epic_completion
        from bmad_assist.core.state import State

        state = State(current_epic=1)
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.epic_transitions.save_state") as mock_save:
            mock_save.side_effect = StateError("Write failed")

            with pytest.raises(StateError, match="Write failed"):
                persist_epic_completion(state, state_path)


class TestHandleEpicCompletion:
    """AC5: handle_epic_completion() orchestrates full flow."""

    def test_handle_epic_completion_full_flow_not_last(self) -> None:
        """AC5: Full flow when NOT last epic - advances to next."""
        from bmad_assist.core.loop import handle_epic_completion
        from bmad_assist.core.state import Phase, State

        state = State(
            current_epic=2,
            current_story="2.4",
            current_phase=Phase.RETROSPECTIVE,
            completed_epics=[1],
        )
        epic_list = [1, 2, 3, 4]
        epic_stories_loader = MagicMock(return_value=["3.1", "3.2", "3.3"])
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.epic_transitions.save_state"):
            new_state, is_project_complete = handle_epic_completion(
                state, epic_list, epic_stories_loader, state_path
            )

        assert 2 in new_state.completed_epics
        assert new_state.current_epic == 3
        assert new_state.current_story == "3.1"
        assert new_state.current_phase == Phase.CREATE_STORY
        assert is_project_complete is False

    def test_handle_epic_completion_full_flow_last_epic(self) -> None:
        """AC5: Full flow when last epic - signals project complete."""
        from bmad_assist.core.loop import handle_epic_completion
        from bmad_assist.core.state import Phase, State

        state = State(
            current_epic=4,
            current_story="4.3",
            current_phase=Phase.RETROSPECTIVE,
            completed_epics=[1, 2, 3],
        )
        epic_list = [1, 2, 3, 4]
        epic_stories_loader = MagicMock()
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.epic_transitions.save_state"):
            new_state, is_project_complete = handle_epic_completion(
                state, epic_list, epic_stories_loader, state_path
            )

        assert 4 in new_state.completed_epics
        assert is_project_complete is True
        epic_stories_loader.assert_not_called()  # No next epic to load

    def test_handle_epic_completion_persists_state_once(self) -> None:
        """AC5: Persists FINAL state only (single atomic persist pattern)."""
        from bmad_assist.core.loop import handle_epic_completion
        from bmad_assist.core.state import State

        state = State(current_epic=2, current_story="2.4", completed_epics=[1])
        epic_list = [1, 2, 3, 4]
        epic_stories_loader = MagicMock(return_value=["3.1"])
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.epic_transitions.save_state") as mock_save:
            handle_epic_completion(state, epic_list, epic_stories_loader, state_path)

            # Called ONCE with final state (prevents race condition)
            assert mock_save.call_count == 1
            # Verify final state has both completion and transition applied
            saved_state = mock_save.call_args[0][0]
            assert 2 in saved_state.completed_epics
            assert saved_state.current_epic == 3

    def test_handle_epic_completion_logs_project_complete(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC5: Logs when project is complete."""
        from bmad_assist.core.loop import handle_epic_completion
        from bmad_assist.core.state import State

        state = State(current_epic=4, current_story="4.3", completed_epics=[1, 2, 3])
        epic_list = [1, 2, 3, 4]
        state_path = Path("/tmp/state.yaml")

        with patch("bmad_assist.core.loop.epic_transitions.save_state"):
            with caplog.at_level(logging.INFO):
                handle_epic_completion(state, epic_list, MagicMock(), state_path)

        assert "project complete" in caplog.text.lower()


class TestStory64Exports:
    """Test Story 6.4 functions are properly exported."""

    def test_complete_epic_exported(self) -> None:
        """complete_epic is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "complete_epic" in loop.__all__

    def test_is_last_epic_exported(self) -> None:
        """is_last_epic is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "is_last_epic" in loop.__all__

    def test_get_next_epic_exported(self) -> None:
        """get_next_epic is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "get_next_epic" in loop.__all__

    def test_advance_to_next_epic_exported(self) -> None:
        """advance_to_next_epic is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "advance_to_next_epic" in loop.__all__

    def test_persist_epic_completion_exported(self) -> None:
        """persist_epic_completion is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "persist_epic_completion" in loop.__all__

    def test_handle_epic_completion_exported(self) -> None:
        """handle_epic_completion is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "handle_epic_completion" in loop.__all__
