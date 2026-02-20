"""Tests for runner module.

Story 6.5: Main Loop Runner
- run_loop() function with all its scenarios
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.config import Config, load_config
from bmad_assist.core.exceptions import StateError

if TYPE_CHECKING:
    pass


class TestRunLoopStub:
    """Tests for run_loop() stub function."""

    @pytest.fixture
    def valid_config(self) -> Config:
        """Create a valid Config object for testing."""
        config_data = {
            "providers": {
                "master": {
                    "provider": "claude",
                    "model": "opus_4",
                }
            }
        }
        return load_config(config_data)

    def test_run_loop_is_importable(self) -> None:
        """run_loop can be imported from bmad_assist.core.loop."""
        from bmad_assist.core.loop import run_loop

        assert callable(run_loop)

    def test_run_loop_is_exported_from_core(self) -> None:
        """run_loop is exported from bmad_assist.core."""
        from bmad_assist.core import run_loop

        assert callable(run_loop)

    def test_run_loop_accepts_config_and_path(self, valid_config: Config, tmp_path: Path) -> None:
        """AC5: run_loop accepts Config and Path arguments (with epic_list, loader)."""
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import State

        # Story 6.5 update: run_loop now requires epic_list and epic_stories_loader
        with patch("bmad_assist.core.loop.runner.load_state", return_value=State()):
            with patch("bmad_assist.core.loop.runner.execute_phase", return_value=PhaseResult.ok()):
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                        mock_epic.return_value = (State(), True)

                        run_loop(valid_config, tmp_path, [1], lambda x: ["1.1"])

    def test_run_loop_returns_completed(self, valid_config: Config, tmp_path: Path) -> None:
        """AC5: run_loop returns LoopExitReason.COMPLETED (blocking call that completes)."""
        from bmad_assist.core.loop import LoopExitReason, PhaseResult, run_loop
        from bmad_assist.core.state import State

        # Story 6.5 update: run_loop now requires epic_list and epic_stories_loader
        # Story 6.6 update: run_loop returns LoopExitReason instead of None
        with patch("bmad_assist.core.loop.runner.load_state", return_value=State()):
            with patch("bmad_assist.core.loop.runner.execute_phase", return_value=PhaseResult.ok()):
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                        mock_epic.return_value = (State(), True)

                        result = run_loop(valid_config, tmp_path, [1], lambda x: ["1.1"])

        assert result == LoopExitReason.COMPLETED

    def test_run_loop_logs_debug_info(
        self, valid_config: Config, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """run_loop logs debug information about config and path."""
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import State

        # Story 6.5 update: run_loop now requires epic_list and epic_stories_loader
        with patch("bmad_assist.core.loop.runner.load_state", return_value=State()):
            with patch("bmad_assist.core.loop.runner.execute_phase", return_value=PhaseResult.ok()):
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                        mock_epic.return_value = (State(), True)

                        with caplog.at_level(logging.DEBUG):
                            run_loop(valid_config, tmp_path, [1], lambda x: ["1.1"])

        # Should log provider info
        assert "claude" in caplog.text.lower()
        # Should log path
        assert str(tmp_path) in caplog.text


class TestRunLoopIntegration:
    """Integration tests for run_loop with CLI."""

    def test_run_loop_callable_from_cli_context(self, tmp_path: Path) -> None:
        """run_loop works when called via CLI context."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import State

        config_data = {
            "providers": {
                "master": {
                    "provider": "gemini",
                    "model": "flash",
                }
            },
            "state_path": str(tmp_path / "state.yaml"),
        }
        config = load_config(config_data)
        project_path = tmp_path / "project"
        project_path.mkdir()

        # Must patch execute_phase in BOTH modules because each imports it separately:
        # - runner.py: from dispatch import execute_phase (for main loop)
        # - epic_phases.py: from dispatch import execute_phase (for teardown phases)
        # Python imports create separate references, so we must patch both
        with patch("bmad_assist.core.loop.runner.execute_phase", return_value=PhaseResult.ok()):
            with patch("bmad_assist.core.loop.epic_phases.execute_phase", return_value=PhaseResult.ok()):
                with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                    mock_epic.return_value = (State(), True)

                    run_loop(config, project_path, [1], lambda x: ["1.1"])

    def test_run_loop_with_different_providers(self, tmp_path: Path) -> None:
        """run_loop handles different provider configurations."""
        from bmad_assist.core.config import _reset_config, load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import State

        providers = [
            ("claude", "opus_4"),
            ("codex", "gpt-4"),
            ("gemini", "flash"),
        ]

        for provider, model in providers:
            _reset_config()
            config_data = {
                "providers": {
                    "master": {
                        "provider": provider,
                        "model": model,
                    }
                },
                "state_path": str(tmp_path / f"state-{provider}.yaml"),
            }
            config = load_config(config_data)

            # Must patch execute_phase in BOTH modules (each imports it separately)
            with patch("bmad_assist.core.loop.runner.execute_phase", return_value=PhaseResult.ok()):
                with patch("bmad_assist.core.loop.epic_phases.execute_phase", return_value=PhaseResult.ok()):
                    with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                        mock_epic.return_value = (State(), True)

                        run_loop(config, tmp_path, [1], lambda x: ["1.1"])


class TestRunLoopFreshStart:
    """AC1: run_loop() creates fresh state when no state file."""

    def test_run_loop_empty_epic_list_raises(self, tmp_path: Path) -> None:
        """AC1: Raises StateError when epic_list is empty."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import run_loop

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        with pytest.raises(StateError, match="No epics found"):
            run_loop(config, tmp_path, [], lambda x: [])

    def test_run_loop_empty_stories_raises(self, tmp_path: Path) -> None:
        """AC1: Raises StateError when first epic has no stories."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import run_loop

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        with pytest.raises(StateError, match="No stories found in epic 1"):
            run_loop(config, tmp_path, [1], lambda x: [])

    def test_run_loop_creates_fresh_state(self, tmp_path: Path) -> None:
        """AC1: Creates fresh state with first epic/story when no state file."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase

        state_file = tmp_path / "state.yaml"
        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(state_file),
            }
        )

        epic_list = [1, 2, 3]
        loader = lambda x: [f"{x}.1", f"{x}.2"]

        saved_states = []

        with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:
            mock_exec.return_value = PhaseResult.ok()
            with patch("bmad_assist.core.loop.runner.save_state") as mock_save:
                mock_save.side_effect = lambda state, path: saved_states.append(state)
                with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                    mock_epic.return_value = (MagicMock(), True)  # Project complete

                    run_loop(config, tmp_path, epic_list, loader)

        # First saved state should be fresh start
        assert len(saved_states) >= 1
        initial_state = saved_states[0]
        assert initial_state.current_epic == 1
        assert initial_state.current_story == "1.1"
        assert initial_state.current_phase == Phase.CREATE_STORY


class TestRunLoopResume:
    """AC1: run_loop() loads existing state on resume."""

    def test_run_loop_loads_existing_state(self, tmp_path: Path) -> None:
        """AC1: Loads state from file if exists."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        existing_state = State(
            current_epic=2,
            current_story="2.1",  # Changed to valid story ID
            current_phase=Phase.DEV_STORY,
        )

        with patch("bmad_assist.core.loop.runner.load_state", return_value=existing_state):
            with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:
                mock_exec.return_value = PhaseResult.ok()
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                        mock_epic.return_value = (existing_state, True)

                        run_loop(config, tmp_path, [1, 2], lambda x: [f"{x}.1", f"{x}.2"])

        # Should have executed at least one phase
        assert mock_exec.called

    def test_run_loop_propagates_state_error(self, tmp_path: Path) -> None:
        """AC1: Propagates StateError from load_state for corrupted files."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import run_loop

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        with patch("bmad_assist.core.loop.runner.load_state") as mock_load:
            mock_load.side_effect = StateError("Corrupted state file")

            with pytest.raises(StateError, match="Corrupted state file"):
                run_loop(config, tmp_path, [1], lambda x: ["1.1"])


class TestRunLoopPhaseExecution:
    """AC2: run_loop() executes phases in sequence."""

    def test_run_loop_executes_phase(self, tmp_path: Path) -> None:
        """AC2: execute_phase is called."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        state = State(current_epic=1, current_story="1.1", current_phase=Phase.CREATE_STORY)

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch("bmad_assist.core.loop.runner.execute_phase") as mock_exec:
                mock_exec.return_value = PhaseResult.ok()
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                        mock_epic.return_value = (state, True)

                        run_loop(config, tmp_path, [1], lambda x: ["1.1"])

        assert mock_exec.called

    def test_run_loop_advances_phases(self, tmp_path: Path) -> None:
        """AC2/AC7: Phases advance after successful execution."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        state = State(current_epic=1, current_story="1.1", current_phase=Phase.CREATE_STORY)
        executed_phases = []

        def track_execute(s):
            executed_phases.append(s.current_phase)
            if len(executed_phases) >= 3:
                # Stop after a few phases by returning to epic completion
                return PhaseResult.ok()
            return PhaseResult.ok()

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch("bmad_assist.core.loop.runner.execute_phase", side_effect=track_execute):
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                        mock_epic.return_value = (state, True)

                        run_loop(config, tmp_path, [1], lambda x: ["1.1"])

        # Should have executed CREATE_STORY first
        assert Phase.CREATE_STORY in executed_phases


class TestRunLoopStoryCompletion:
    """AC3: run_loop() handles story completion."""

    def test_run_loop_handles_story_completion_not_last(self, tmp_path: Path) -> None:
        """AC3: Story completion advances to next story when not last."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        # Start at CODE_REVIEW_SYNTHESIS (triggers story completion)
        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
        )

        next_state = State(
            current_epic=1,
            current_story="1.2",
            current_phase=Phase.CREATE_STORY,
        )

        call_count = [0]

        def controlled_execute(s):
            call_count[0] += 1
            if call_count[0] > 3:
                # Prevent infinite loop
                raise StateError("Breaking loop for test")
            return PhaseResult.ok()

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch(
                "bmad_assist.core.loop.runner.execute_phase", side_effect=controlled_execute
            ):
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch(
                        "bmad_assist.core.loop.runner.handle_story_completion"
                    ) as mock_story:
                        mock_story.return_value = (next_state, False)
                        with patch(
                            "bmad_assist.core.loop.runner.handle_epic_completion"
                        ) as mock_epic:
                            mock_epic.return_value = (next_state, True)

                            try:
                                run_loop(config, tmp_path, [1], lambda x: ["1.1", "1.2"])
                            except StateError:
                                pass  # Expected when breaking loop

        mock_story.assert_called()

    def test_run_loop_sets_retrospective_when_epic_complete(self, tmp_path: Path) -> None:
        """AC3: run_loop sets phase to RETROSPECTIVE when is_epic_complete=True."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        state = State(
            current_epic=1,
            current_story="1.2",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
            completed_stories=["1.1"],
        )

        completed_state = State(
            current_epic=1,
            current_story="1.2",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
            completed_stories=["1.1", "1.2"],
        )

        saved_states = []

        def track_save(s, path):
            saved_states.append(s)

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch("bmad_assist.core.loop.runner.execute_phase", return_value=PhaseResult.ok()):
                with patch(
                    "bmad_assist.core.loop.epic_phases.execute_phase", return_value=PhaseResult.ok()
                ):
                    # Both runner and epic_phases import save_state separately
                    with patch("bmad_assist.core.loop.runner.save_state", side_effect=track_save):
                        with patch(
                            "bmad_assist.core.loop.epic_phases.save_state", side_effect=track_save
                        ):
                            with patch(
                                "bmad_assist.core.loop.runner.handle_story_completion"
                            ) as mock_story:
                                mock_story.return_value = (
                                    completed_state,
                                    True,
                                )  # is_epic_complete=True
                                with patch(
                                    "bmad_assist.core.loop.runner.handle_epic_completion"
                                ) as mock_epic:
                                    mock_epic.return_value = (completed_state, True)

                                    run_loop(config, tmp_path, [1], lambda x: ["1.1", "1.1"])

        # Should have saved state with RETROSPECTIVE phase
        retrospective_saves = [s for s in saved_states if s.current_phase == Phase.RETROSPECTIVE]
        assert len(retrospective_saves) >= 1


class TestRunLoopEpicCompletion:
    """AC4: run_loop() handles epic completion."""

    def test_run_loop_handles_epic_completion_not_last(self, tmp_path: Path) -> None:
        """AC4: Epic completion advances to next epic when not last."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.RETROSPECTIVE,
            completed_epics=[],
        )

        next_state = State(
            current_epic=2,
            current_story="2.1",
            current_phase=Phase.CREATE_STORY,
            completed_epics=[1],
        )

        call_count = [0]

        def controlled_execute(s):
            call_count[0] += 1
            if call_count[0] > 3:
                raise StateError("Breaking loop for test")
            return PhaseResult.ok()

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch(
                "bmad_assist.core.loop.runner.execute_phase", side_effect=controlled_execute
            ):
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                        # First call: not complete, second: complete to break loop
                        mock_epic.side_effect = [
                            (next_state, False),
                            (next_state, True),
                        ]

                        try:
                            run_loop(config, tmp_path, [1, 2], lambda x: [f"{x}.1"])
                        except StateError:
                            pass

        assert mock_epic.called

    def test_run_loop_terminates_on_project_complete(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC4: Loop terminates gracefully when project is complete."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.RETROSPECTIVE,
            completed_epics=[],
        )

        final_state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.RETROSPECTIVE,
            completed_epics=[1],
        )

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch("bmad_assist.core.loop.runner.execute_phase", return_value=PhaseResult.ok()):
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                        mock_epic.return_value = (final_state, True)

                        with caplog.at_level(logging.INFO):
                            run_loop(config, tmp_path, [1], lambda x: ["1.1"])

        assert "project complete" in caplog.text.lower()


class TestRunLoopFailureHandling:
    """AC5: run_loop() handles phase failures."""

    def test_run_loop_handles_phase_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC5: Loop logs warning and calls guardian on failure."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import GuardianDecision, PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.CREATE_STORY,
        )

        call_count = [0]

        def failing_execute(s):
            call_count[0] += 1
            if call_count[0] == 1:
                return PhaseResult.fail("Test failure")
            return PhaseResult.ok()

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch("bmad_assist.core.loop.runner.execute_phase", side_effect=failing_execute):
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch(
                        "bmad_assist.core.loop.runner.guardian_check_anomaly",
                        return_value=GuardianDecision.CONTINUE,
                    ) as mock_guard:
                        with patch(
                            "bmad_assist.core.loop.runner.handle_epic_completion"
                        ) as mock_epic:
                            mock_epic.return_value = (state, True)

                            with caplog.at_level(logging.WARNING):
                                run_loop(config, tmp_path, [1], lambda x: ["1.1"])

        mock_guard.assert_called()
        assert "fail" in caplog.text.lower()

    def test_run_loop_saves_state_before_guardian(self, tmp_path: Path) -> None:
        """AC5: State is saved BEFORE guardian call on failures."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import GuardianDecision, PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.CREATE_STORY,
        )

        call_order = []

        def track_save(s, path):
            call_order.append("save")

        def track_guardian(result, s):
            call_order.append("guardian")
            return GuardianDecision.CONTINUE

        call_count = [0]

        def failing_then_success(s):
            call_count[0] += 1
            if call_count[0] == 1:
                return PhaseResult.fail("Error")
            return PhaseResult.ok()

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch(
                "bmad_assist.core.loop.runner.execute_phase", side_effect=failing_then_success
            ):
                with patch("bmad_assist.core.loop.runner.save_state", side_effect=track_save):
                    with patch(
                        "bmad_assist.core.loop.runner.guardian_check_anomaly",
                        side_effect=track_guardian,
                    ):
                        with patch(
                            "bmad_assist.core.loop.runner.handle_epic_completion"
                        ) as mock_epic:
                            mock_epic.return_value = (state, True)

                            run_loop(config, tmp_path, [1], lambda x: ["1.1"])

        # Verify save happens before guardian
        save_idx = call_order.index("save")
        guardian_idx = call_order.index("guardian")
        assert save_idx < guardian_idx

    def test_run_loop_guardian_halt_terminates(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC5: Guardian 'halt' response terminates loop gracefully."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import GuardianDecision, LoopExitReason, PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.CREATE_STORY,
        )

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch(
                "bmad_assist.core.loop.runner.execute_phase",
                return_value=PhaseResult.fail("Error"),
            ):
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch(
                        "bmad_assist.core.loop.runner.guardian_check_anomaly",
                        return_value=GuardianDecision.HALT,
                    ):
                        with caplog.at_level(logging.DEBUG):
                            # Should return normally (not exception)
                            result = run_loop(config, tmp_path, [1], lambda x: ["1.1"])

        # Guardian halt returns GUARDIAN_HALT exit reason
        assert result == LoopExitReason.GUARDIAN_HALT

    def test_run_loop_retrospective_failure_moves_to_next_epic(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """RETROSPECTIVE failure should log warning and move to next epic or complete project."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import LoopExitReason, PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        # Start with an epic in RETROSPECTIVE phase, and a next epic available
        initial_state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.RETROSPECTIVE,
            completed_epics=[],  # Epic 1 is not yet completed in state
        )

        # State after handle_epic_completion for the *next* epic
        next_epic_state = State(
            current_epic=2,
            current_story="2.1",
            current_phase=Phase.CREATE_STORY,
            completed_epics=[1],  # Epic 1 now completed
        )

        # Use a callable for side_effect to handle arbitrary number of calls after the first failure
        call_count = [0]

        def execute_phase_side_effect(state):
            call_count[0] += 1
            if call_count[0] == 1:
                return PhaseResult.fail("Retrospective analysis failed")
            return PhaseResult.ok()

        with patch("bmad_assist.core.loop.runner.load_state", return_value=initial_state):
            with patch(
                "bmad_assist.core.loop.runner.execute_phase",
                side_effect=execute_phase_side_effect,
            ) as mock_execute_phase:
                with patch("bmad_assist.core.loop.runner.save_state") as mock_save_state:
                    with patch(
                        "bmad_assist.core.loop.runner.handle_epic_completion",
                        # First time, move to next epic (not project complete)
                        # Second time (after completing next epic's phases), project complete
                        side_effect=[
                            (next_epic_state, False),
                            (next_epic_state.model_copy(update={"completed_epics": [1, 2]}), True),
                        ],
                    ) as mock_handle_epic_completion:
                        with caplog.at_level(logging.WARNING):
                            result = run_loop(config, tmp_path, [1, 2], lambda x: [f"{x}.1"])

        # Assertions - look for either old or new log format
        assert "RETROSPECTIVE" in caplog.text and "failed" in caplog.text
        # handle_epic_completion is called once for the failed retrospective, and once for the subsequent epic's completion
        assert mock_handle_epic_completion.call_count == 2
        mock_save_state.assert_called()  # Should have saved state at least once
        assert result == LoopExitReason.COMPLETED


class TestRunLoopStatePersistence:
    """AC6: run_loop() saves state after each phase."""

    def test_run_loop_saves_state_after_each_phase(self, tmp_path: Path) -> None:
        """AC6: State is saved after every phase completion."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.CREATE_STORY,
        )

        save_count = [0]

        def track_save(s, path):
            save_count[0] += 1

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch("bmad_assist.core.loop.runner.execute_phase", return_value=PhaseResult.ok()):
                with patch("bmad_assist.core.loop.runner.save_state", side_effect=track_save):
                    with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                        mock_epic.return_value = (state, True)

                        run_loop(config, tmp_path, [1], lambda x: ["1.1"])

        # Should have saved at least once
        assert save_count[0] >= 1


class TestRunLoopPhaseAdvancement:
    """AC7: run_loop() advances phases correctly."""

    def test_run_loop_uses_get_next_phase(self, tmp_path: Path) -> None:
        """AC7: Normal phases advance via get_next_phase()."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.CREATE_STORY,
        )

        phases_seen = []

        def track_execute(s):
            phases_seen.append(s.current_phase)
            if len(phases_seen) >= 4:
                raise StateError("Breaking loop")
            return PhaseResult.ok()

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch("bmad_assist.core.loop.runner.execute_phase", side_effect=track_execute):
                with patch("bmad_assist.core.loop.runner.save_state"):
                    with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                        mock_epic.return_value = (state, True)

                        try:
                            run_loop(config, tmp_path, [1], lambda x: ["1.1"])
                        except StateError:
                            pass

        # Phases should advance in order
        assert phases_seen[0] == Phase.CREATE_STORY
        if len(phases_seen) > 1:
            assert phases_seen[1] == Phase.VALIDATE_STORY


class TestRunLoopIntegrationFull:
    """Integration test for full loop cycle."""

    def test_run_loop_full_single_story_cycle(self, tmp_path: Path) -> None:
        """Integration: Full loop for single story, single epic."""
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        phases_executed = []

        def track_execute(s):
            phases_executed.append(s.current_phase)
            return PhaseResult.ok()

        with patch("bmad_assist.core.loop.runner.load_state", return_value=State()):
            with patch("bmad_assist.core.loop.runner.execute_phase", side_effect=track_execute):
                with patch(
                    "bmad_assist.core.loop.epic_phases.execute_phase", side_effect=track_execute
                ):
                    with patch("bmad_assist.core.loop.runner.save_state"):
                        with patch(
                            "bmad_assist.core.loop.runner.handle_story_completion"
                        ) as mock_story:
                            completed_state = State(
                                current_epic=1,
                                current_story="1.1",
                                current_phase=Phase.CODE_REVIEW_SYNTHESIS,
                                completed_stories=["1.1"],
                            )
                            mock_story.return_value = (completed_state, True)  # Last in epic
                            with patch(
                                "bmad_assist.core.loop.runner.handle_epic_completion"
                            ) as mock_epic:
                                final_state = State(
                                    current_epic=1,
                                    current_story="1.1",
                                    current_phase=Phase.RETROSPECTIVE,
                                    completed_epics=[1],
                                )
                                mock_epic.return_value = (final_state, True)  # Project complete

                                run_loop(config, tmp_path, [1], lambda x: ["1.1"])

        # DEFAULT_LOOP_CONFIG is minimal (no TEA phases):
        # DEFAULT_LOOP_CONFIG is minimal (no TEA phases):
        # 6 story phases + RETROSPECTIVE, HARDENING in epic_teardown = 8 total
        # With --tea flag (TEA_FULL_LOOP_CONFIG), would be 11 phases
        assert len(phases_executed) == 8
        assert phases_executed[0] == Phase.CREATE_STORY
        assert phases_executed[-1] == Phase.HARDENING


class TestPhaseTimingReset:
    """Story standalone-03: Phase timing is reset before each phase execution."""

    def test_start_phase_timing_called_before_each_execute_phase(self, tmp_path: Path) -> None:
        """AC1: start_phase_timing() is called BEFORE each execute_phase() in main loop.

        The bug was that start_phase_timing was only called on resume, not before
        each phase execution. This test verifies that for every execute_phase call
        in the main loop, there's a preceding start_phase_timing call.
        """
        from bmad_assist.core.config import load_config
        from bmad_assist.core.loop import PhaseResult, run_loop
        from bmad_assist.core.state import Phase, State

        config = load_config(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(tmp_path / "state.yaml"),
            }
        )

        # State with phase_started_at already set (so resume path won't call timing)
        from datetime import datetime

        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.CREATE_STORY,
            phase_started_at=datetime(2026, 1, 1, 12, 0, 0),  # Pre-set to skip resume timing
        )

        call_sequence: list[str] = []
        execute_count = [0]

        def track_start_phase_timing(s):
            call_sequence.append("start_timing")

        def track_execute_phase(s):
            execute_count[0] += 1
            call_sequence.append(f"execute_{execute_count[0]}")
            return PhaseResult.ok()

        with patch("bmad_assist.core.loop.runner.load_state", return_value=state):
            with patch(
                "bmad_assist.core.loop.runner.start_phase_timing",
                side_effect=track_start_phase_timing,
            ):
                with patch(
                    "bmad_assist.core.loop.runner.execute_phase",
                    side_effect=track_execute_phase,
                ):
                    with patch("bmad_assist.core.loop.runner.save_state"):
                        with patch("bmad_assist.core.loop.runner.handle_epic_completion") as mock_epic:
                            mock_epic.return_value = (state, True)

                            run_loop(config, tmp_path, [1], lambda x: ["1.1"])

        # For every execute_phase call, there should be a start_phase_timing before it
        # The pattern should be: start_timing, execute_1, start_timing, execute_2, ...
        timing_count = call_sequence.count("start_timing")
        execute_count_total = execute_count[0]

        # Each execute should have been preceded by a timing call
        assert timing_count >= execute_count_total, (
            f"Expected at least {execute_count_total} start_phase_timing calls "
            f"(one per execute_phase), but got {timing_count}. "
            f"Sequence: {call_sequence}"
        )

        # Verify the pattern: timing should immediately precede each execute
        for i, item in enumerate(call_sequence):
            if item.startswith("execute_"):
                # The item before should be start_timing
                assert i > 0 and call_sequence[i - 1] == "start_timing", (
                    f"execute_phase at position {i} was not preceded by start_timing. "
                    f"Sequence: {call_sequence}"
                )


class TestStory65Exports:
    """Test Story 6.5 functions are properly exported."""

    def test_get_next_phase_exported(self) -> None:
        """get_next_phase is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "get_next_phase" in loop.__all__

    def test_guardian_check_anomaly_exported(self) -> None:
        """guardian_check_anomaly is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "guardian_check_anomaly" in loop.__all__

    def test_run_loop_exported(self) -> None:
        """run_loop is in loop module's __all__."""
        from bmad_assist.core import loop

        assert "run_loop" in loop.__all__


class TestArchiveArtifacts:
    """Tests for _run_archive_artifacts helper function."""

    def test_archive_called_on_code_review_synthesis_success(self, tmp_path: Path) -> None:
        """Archive script is called after CODE_REVIEW_SYNTHESIS phase success."""
        from bmad_assist.core.loop.runner import _run_archive_artifacts

        # Create mock script
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        script_path = scripts_dir / "archive-artifacts.sh"
        script_path.write_text("#!/bin/bash\nexit 0\n")
        script_path.chmod(0o755)

        # subprocess is imported in sprint_sync.py, not runner.py
        with patch("bmad_assist.core.loop.sprint_sync.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _run_archive_artifacts(tmp_path)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert str(script_path) in call_args[0][0]
        assert "-s" in call_args[0][0]  # Silent mode

    def test_archive_skipped_when_script_missing(self, tmp_path: Path) -> None:
        """Archive is skipped gracefully when script doesn't exist."""
        from bmad_assist.core.loop.runner import _run_archive_artifacts

        # subprocess is imported in sprint_sync.py, not runner.py
        with patch("bmad_assist.core.loop.sprint_sync.subprocess.run") as mock_run:
            _run_archive_artifacts(tmp_path)

        mock_run.assert_not_called()

    def test_archive_handles_script_failure(self, tmp_path: Path) -> None:
        """Archive handles script failure gracefully without crashing."""
        from bmad_assist.core.loop.runner import _run_archive_artifacts

        # Create mock script
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        script_path = scripts_dir / "archive-artifacts.sh"
        script_path.write_text("#!/bin/bash\nexit 1\n")
        script_path.chmod(0o755)

        # subprocess is imported in sprint_sync.py, not runner.py
        with patch("bmad_assist.core.loop.sprint_sync.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            # Should not raise
            _run_archive_artifacts(tmp_path)
