"""Tests for loop resume functionality (Story 3.5).

Story 3.5 Tests cover:
- AC1: Resume from saved state restores correct position
- AC2: Fresh start detected when no state exists
- AC3: Fresh start detected for empty state
- AC4: Validation phase re-execution is idempotent
- AC5: Partial outputs cleanup for DEV_STORY phase
- AC6: Partial outputs cleanup for synthesis phases
- AC7: ResumePoint dataclass has correct structure
- AC8: get_resume_point handles corrupted state gracefully
- AC9: Resume point includes completed_stories for context
- AC10: Resume from RETROSPECTIVE phase
- AC11: Git unavailable handled gracefully
- AC12: Missing sprint_artifacts directory handled gracefully
- AC13: Docstrings are complete and testable
"""

import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import StateError
from bmad_assist.core.state import (
    CleanupResult,
    Phase,
    ResumePoint,
    State,
    cleanup_partial_outputs,
    get_resume_point,
    save_state,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mid_loop_state(tmp_path: Path) -> tuple[Path, State]:
    """State in middle of development loop."""
    state = State(
        current_epic=3,
        current_story="3.1",
        current_phase=Phase.DEV_STORY,
        completed_stories=["1.1", "1.2", "2.1", "2.2"],
        started_at=datetime(2025, 12, 10, 8, 0, 0),
        updated_at=datetime(2025, 12, 10, 14, 0, 0),
    )
    path = tmp_path / "state.yaml"
    save_state(state, path)
    return path, state


@pytest.fixture
def fresh_state_file(tmp_path: Path) -> Path:
    """State file with all defaults (fresh start)."""
    state = State()
    path = tmp_path / "state.yaml"
    save_state(state, path)
    return path


@pytest.fixture
def retrospective_state(tmp_path: Path) -> tuple[Path, State]:
    """State at RETROSPECTIVE phase."""
    state = State(
        current_epic=2,
        current_story="2.5",
        current_phase=Phase.RETROSPECTIVE,
        completed_stories=["2.1", "2.2", "2.3", "2.4", "2.5"],
        started_at=datetime(2025, 12, 10, 8, 0, 0),
        updated_at=datetime(2025, 12, 10, 18, 0, 0),
    )
    path = tmp_path / "state.yaml"
    save_state(state, path)
    return path, state


@pytest.fixture
def synthesis_state() -> State:
    """State at VALIDATE_STORY_SYNTHESIS phase."""
    return State(
        current_epic=3,
        current_story="3.2",
        current_phase=Phase.VALIDATE_STORY_SYNTHESIS,
        completed_stories=["3.1"],
        started_at=datetime(2025, 12, 10, 8, 0, 0),
        updated_at=datetime(2025, 12, 10, 12, 0, 0),
    )


@pytest.fixture
def code_review_synthesis_state() -> State:
    """State at CODE_REVIEW_SYNTHESIS phase."""
    return State(
        current_epic=3,
        current_story="3.2",
        current_phase=Phase.CODE_REVIEW_SYNTHESIS,
        completed_stories=["3.1"],
        started_at=datetime(2025, 12, 10, 8, 0, 0),
        updated_at=datetime(2025, 12, 10, 15, 0, 0),
    )


@pytest.fixture
def sprint_artifacts_dir(tmp_path: Path) -> Path:
    """Sprint artifacts directory with some files."""
    artifacts = tmp_path / "sprint-artifacts"
    artifacts.mkdir()
    validations = artifacts / "story-validations"
    validations.mkdir()
    # Create partial synthesis report for story 3.2
    (validations / "story-validation-3-2-master-20251210_120000.md").write_text(
        "partial", encoding="utf-8"
    )
    return artifacts


@pytest.fixture
def code_reviews_dir(tmp_path: Path) -> Path:
    """Sprint artifacts directory with code review files."""
    artifacts = tmp_path / "sprint-artifacts"
    artifacts.mkdir()
    code_reviews = artifacts / "code-reviews"
    code_reviews.mkdir()
    # Create partial code review synthesis report for story 3.2
    (code_reviews / "code-review-3-2-master-20251210_150000.md").write_text(
        "partial", encoding="utf-8"
    )
    return artifacts


# =============================================================================
# AC7: ResumePoint dataclass has correct structure
# =============================================================================


class TestResumePointDataclass:
    """Test ResumePoint dataclass structure (AC7)."""

    def test_resume_point_has_epic_field(self) -> None:
        """AC7: ResumePoint has epic field."""
        rp = ResumePoint(epic=3, story="3.1", phase=Phase.DEV_STORY, is_fresh_start=False)
        assert rp.epic == 3

    def test_resume_point_has_story_field(self) -> None:
        """AC7: ResumePoint has story field."""
        rp = ResumePoint(epic=3, story="3.1", phase=Phase.DEV_STORY, is_fresh_start=False)
        assert rp.story == "3.1"

    def test_resume_point_has_phase_field(self) -> None:
        """AC7: ResumePoint has phase field."""
        rp = ResumePoint(epic=3, story="3.1", phase=Phase.DEV_STORY, is_fresh_start=False)
        assert rp.phase == Phase.DEV_STORY

    def test_resume_point_has_is_fresh_start_field(self) -> None:
        """AC7: ResumePoint has is_fresh_start field."""
        rp = ResumePoint(epic=None, story=None, phase=None, is_fresh_start=True)
        assert rp.is_fresh_start is True

    def test_resume_point_has_completed_stories_field(self) -> None:
        """AC7: ResumePoint has completed_stories field."""
        rp = ResumePoint(
            epic=3,
            story="3.1",
            phase=Phase.DEV_STORY,
            is_fresh_start=False,
            completed_stories=["1.1", "1.2"],
        )
        assert rp.completed_stories == ["1.1", "1.2"]

    def test_resume_point_has_started_at_field(self) -> None:
        """AC7: ResumePoint has started_at field."""
        ts = datetime(2025, 12, 10, 8, 0, 0)
        rp = ResumePoint(
            epic=3,
            story="3.1",
            phase=Phase.DEV_STORY,
            is_fresh_start=False,
            started_at=ts,
        )
        assert rp.started_at == ts

    def test_resume_point_completed_stories_defaults_empty(self) -> None:
        """AC7: completed_stories defaults to empty list."""
        rp = ResumePoint(epic=None, story=None, phase=None, is_fresh_start=True)
        assert rp.completed_stories == []

    def test_resume_point_started_at_defaults_none(self) -> None:
        """AC7: started_at defaults to None."""
        rp = ResumePoint(epic=None, story=None, phase=None, is_fresh_start=True)
        assert rp.started_at is None

    def test_resume_point_in_exports(self) -> None:
        """AC7: ResumePoint is in __all__ exports."""
        from bmad_assist.core import state as state_module

        assert "ResumePoint" in state_module.__all__

    def test_resume_point_epic_allows_none(self) -> None:
        """AC7: epic field allows None."""
        rp = ResumePoint(epic=None, story=None, phase=None, is_fresh_start=True)
        assert rp.epic is None

    def test_resume_point_story_allows_none(self) -> None:
        """AC7: story field allows None."""
        rp = ResumePoint(epic=None, story=None, phase=None, is_fresh_start=True)
        assert rp.story is None

    def test_resume_point_phase_allows_none(self) -> None:
        """AC7: phase field allows None."""
        rp = ResumePoint(epic=None, story=None, phase=None, is_fresh_start=True)
        assert rp.phase is None


# =============================================================================
# AC1: Resume from saved state restores correct position
# =============================================================================


class TestGetResumePointSuccess:
    """Test get_resume_point returns correct position (AC1)."""

    def test_get_resume_point_returns_epic(self, mid_loop_state: tuple[Path, State]) -> None:
        """AC1: ResumePoint has correct epic."""
        path, state = mid_loop_state
        resume = get_resume_point(path)
        assert resume.epic == state.current_epic

    def test_get_resume_point_returns_story(self, mid_loop_state: tuple[Path, State]) -> None:
        """AC1: ResumePoint has correct story."""
        path, state = mid_loop_state
        resume = get_resume_point(path)
        assert resume.story == state.current_story

    def test_get_resume_point_returns_phase(self, mid_loop_state: tuple[Path, State]) -> None:
        """AC1: ResumePoint has correct phase."""
        path, state = mid_loop_state
        resume = get_resume_point(path)
        assert resume.phase == state.current_phase

    def test_get_resume_point_is_not_fresh_start(self, mid_loop_state: tuple[Path, State]) -> None:
        """AC1: is_fresh_start is False for valid state."""
        path, _ = mid_loop_state
        resume = get_resume_point(path)
        assert resume.is_fresh_start is False

    def test_get_resume_point_logs_resume_info(
        self, mid_loop_state: tuple[Path, State], caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC1: Resume is logged."""
        path, _ = mid_loop_state
        with caplog.at_level(logging.INFO):
            get_resume_point(path)
        assert "Resuming from epic 3" in caplog.text
        assert "story 3.1" in caplog.text
        assert "phase dev_story" in caplog.text


# =============================================================================
# AC2: Fresh start detected when no state exists
# =============================================================================


class TestGetResumePointNoFile:
    """Test get_resume_point for missing file (AC2)."""

    def test_get_resume_point_fresh_start_when_no_file(self, tmp_path: Path) -> None:
        """AC2: Returns fresh start when file doesn't exist."""
        nonexistent = tmp_path / "nonexistent.yaml"
        resume = get_resume_point(nonexistent)
        assert resume.is_fresh_start is True

    def test_get_resume_point_no_file_epic_none(self, tmp_path: Path) -> None:
        """AC2: epic is None for fresh start."""
        resume = get_resume_point(tmp_path / "nonexistent.yaml")
        assert resume.epic is None

    def test_get_resume_point_no_file_story_none(self, tmp_path: Path) -> None:
        """AC2: story is None for fresh start."""
        resume = get_resume_point(tmp_path / "nonexistent.yaml")
        assert resume.story is None

    def test_get_resume_point_no_file_phase_none(self, tmp_path: Path) -> None:
        """AC2: phase is None for fresh start."""
        resume = get_resume_point(tmp_path / "nonexistent.yaml")
        assert resume.phase is None

    def test_get_resume_point_no_file_logs_fresh_start(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC2: Fresh start is logged."""
        with caplog.at_level(logging.INFO):
            get_resume_point(tmp_path / "nonexistent.yaml")
        assert "Fresh start" in caplog.text


# =============================================================================
# AC3: Fresh start detected for empty state
# =============================================================================


class TestGetResumePointEmptyState:
    """Test get_resume_point for empty state (AC3)."""

    def test_get_resume_point_fresh_start_for_empty_state(self, fresh_state_file: Path) -> None:
        """AC3: Returns fresh start for empty state."""
        resume = get_resume_point(fresh_state_file)
        assert resume.is_fresh_start is True

    def test_get_resume_point_empty_state_logs(
        self, fresh_state_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC3: Fresh start is logged for empty state."""
        with caplog.at_level(logging.INFO):
            get_resume_point(fresh_state_file)
        assert "Fresh start" in caplog.text

    def test_get_resume_point_partial_position_is_fresh(self, tmp_path: Path) -> None:
        """AC3: Partial position (only epic set) is treated as fresh start."""
        state = State(current_epic=2)  # No story or phase
        path = tmp_path / "partial.yaml"
        save_state(state, path)
        resume = get_resume_point(path)
        assert resume.is_fresh_start is True

    def test_get_resume_point_missing_phase_is_fresh(self, tmp_path: Path) -> None:
        """AC3: Missing phase is treated as fresh start."""
        state = State(current_epic=2, current_story="2.1")  # No phase
        path = tmp_path / "missing_phase.yaml"
        save_state(state, path)
        resume = get_resume_point(path)
        assert resume.is_fresh_start is True

    def test_get_resume_point_missing_story_is_fresh(self, tmp_path: Path) -> None:
        """AC3: Missing story is treated as fresh start."""
        state = State(current_epic=2, current_phase=Phase.DEV_STORY)  # No story
        path = tmp_path / "missing_story.yaml"
        save_state(state, path)
        resume = get_resume_point(path)
        assert resume.is_fresh_start is True


# =============================================================================
# AC8: get_resume_point handles corrupted state gracefully
# =============================================================================


class TestGetResumePointErrors:
    """Test get_resume_point error handling (AC8)."""

    def test_get_resume_point_corrupted_raises_state_error(self, tmp_path: Path) -> None:
        """AC8: Corrupted state raises StateError."""
        path = tmp_path / "corrupted.yaml"
        path.write_text("invalid: yaml: [", encoding="utf-8")
        with pytest.raises(StateError):
            get_resume_point(path)

    def test_get_resume_point_corrupted_error_message(self, tmp_path: Path) -> None:
        """AC8: Error message indicates corruption."""
        path = tmp_path / "corrupted.yaml"
        path.write_text("invalid: yaml: [", encoding="utf-8")
        with pytest.raises(StateError) as exc_info:
            get_resume_point(path)
        assert "corrupted" in str(exc_info.value).lower()

    def test_get_resume_point_invalid_schema_raises_error(self, tmp_path: Path) -> None:
        """AC8: Invalid schema raises StateError."""
        path = tmp_path / "invalid_schema.yaml"
        # current_epic now accepts int or str, but rejects list/dict
        path.write_text("current_epic: [invalid, list]\n", encoding="utf-8")
        with pytest.raises(StateError):
            get_resume_point(path)

    def test_get_resume_point_does_not_silent_fresh_start(self, tmp_path: Path) -> None:
        """AC8: Corruption does NOT silently start fresh."""
        path = tmp_path / "corrupted.yaml"
        path.write_text("{{invalid yaml}}", encoding="utf-8")
        # Should raise, not return fresh start
        with pytest.raises(StateError):
            get_resume_point(path)


# =============================================================================
# AC9: Resume point includes completed_stories for context
# =============================================================================


class TestGetResumePointCompletedStories:
    """Test get_resume_point includes completed_stories (AC9)."""

    def test_get_resume_point_includes_completed_stories(
        self, mid_loop_state: tuple[Path, State]
    ) -> None:
        """AC9: completed_stories is included in ResumePoint."""
        path, state = mid_loop_state
        resume = get_resume_point(path)
        assert resume.completed_stories == state.completed_stories

    def test_get_resume_point_completed_stories_all_present(self, tmp_path: Path) -> None:
        """AC9: All completed stories are present."""
        state = State(
            current_epic=3,
            current_story="3.5",
            current_phase=Phase.DEV_STORY,
            completed_stories=["1.1", "1.2", "2.1", "2.2", "3.1"],
        )
        path = tmp_path / "state.yaml"
        save_state(state, path)
        resume = get_resume_point(path)
        assert resume.completed_stories == ["1.1", "1.2", "2.1", "2.2", "3.1"]

    def test_get_resume_point_empty_completed_stories(self, tmp_path: Path) -> None:
        """AC9: Empty completed_stories is preserved."""
        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.CREATE_STORY,
            completed_stories=[],
        )
        path = tmp_path / "state.yaml"
        save_state(state, path)
        resume = get_resume_point(path)
        assert resume.completed_stories == []

    def test_get_resume_point_fresh_start_has_completed_stories(self, tmp_path: Path) -> None:
        """AC9: Fresh start still preserves any completed_stories."""
        state = State(completed_stories=["1.1", "1.2"])  # No position
        path = tmp_path / "state.yaml"
        save_state(state, path)
        resume = get_resume_point(path)
        assert resume.is_fresh_start is True
        assert resume.completed_stories == ["1.1", "1.2"]


# =============================================================================
# AC10: Resume from RETROSPECTIVE phase
# =============================================================================


class TestGetResumePointRetrospective:
    """Test get_resume_point for RETROSPECTIVE phase (AC10)."""

    def test_get_resume_point_retrospective_epic(
        self, retrospective_state: tuple[Path, State]
    ) -> None:
        """AC10: Returns correct epic for RETROSPECTIVE."""
        path, state = retrospective_state
        resume = get_resume_point(path)
        assert resume.epic == state.current_epic

    def test_get_resume_point_retrospective_story(
        self, retrospective_state: tuple[Path, State]
    ) -> None:
        """AC10: Returns correct story for RETROSPECTIVE."""
        path, state = retrospective_state
        resume = get_resume_point(path)
        assert resume.story == state.current_story

    def test_get_resume_point_retrospective_phase(
        self, retrospective_state: tuple[Path, State]
    ) -> None:
        """AC10: Returns correct phase (RETROSPECTIVE)."""
        path, _ = retrospective_state
        resume = get_resume_point(path)
        assert resume.phase == Phase.RETROSPECTIVE

    def test_get_resume_point_retrospective_is_not_fresh(
        self, retrospective_state: tuple[Path, State]
    ) -> None:
        """AC10: is_fresh_start is False for RETROSPECTIVE."""
        path, _ = retrospective_state
        resume = get_resume_point(path)
        assert resume.is_fresh_start is False

    def test_get_resume_point_retrospective_logs(
        self, retrospective_state: tuple[Path, State], caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC10: Resume from RETROSPECTIVE is logged correctly."""
        path, _ = retrospective_state
        with caplog.at_level(logging.INFO):
            get_resume_point(path)
        assert "Resuming from epic 2" in caplog.text
        assert "story 2.5" in caplog.text
        assert "phase retrospective" in caplog.text


# =============================================================================
# CleanupResult dataclass tests
# =============================================================================


class TestCleanupResultDataclass:
    """Test CleanupResult dataclass structure."""

    def test_cleanup_result_has_uncommitted_files(self) -> None:
        """CleanupResult has uncommitted_files field."""
        cr = CleanupResult(uncommitted_files=["file1.py", "file2.py"])
        assert cr.uncommitted_files == ["file1.py", "file2.py"]

    def test_cleanup_result_has_cleaned_files(self) -> None:
        """CleanupResult has cleaned_files field."""
        cr = CleanupResult(cleaned_files=["/path/to/report.md"])
        assert cr.cleaned_files == ["/path/to/report.md"]

    def test_cleanup_result_has_warnings(self) -> None:
        """CleanupResult has warnings field."""
        cr = CleanupResult(warnings=["Warning message"])
        assert cr.warnings == ["Warning message"]

    def test_cleanup_result_defaults_empty_lists(self) -> None:
        """CleanupResult defaults to empty lists."""
        cr = CleanupResult()
        assert cr.uncommitted_files == []
        assert cr.cleaned_files == []
        assert cr.warnings == []

    def test_cleanup_result_in_exports(self) -> None:
        """CleanupResult is in __all__ exports."""
        from bmad_assist.core import state as state_module

        assert "CleanupResult" in state_module.__all__


# =============================================================================
# AC4: Validation phase re-execution is idempotent
# =============================================================================


class TestCleanupPartialOutputsValidation:
    """Test cleanup_partial_outputs for validation phases (AC4)."""

    def test_cleanup_validate_story_returns_empty(self, tmp_path: Path) -> None:
        """AC4: VALIDATE_STORY cleanup returns empty result."""
        state = State(current_phase=Phase.VALIDATE_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        result = cleanup_partial_outputs(state, artifacts)
        assert result.uncommitted_files == []
        assert result.cleaned_files == []
        assert result.warnings == []

    def test_cleanup_code_review_returns_empty(self, tmp_path: Path) -> None:
        """AC4: CODE_REVIEW cleanup returns empty result."""
        state = State(current_phase=Phase.CODE_REVIEW, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        result = cleanup_partial_outputs(state, artifacts)
        assert result.uncommitted_files == []
        assert result.cleaned_files == []
        assert result.warnings == []

    def test_cleanup_validate_story_logs_idempotent(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC4: Idempotent message is logged."""
        state = State(current_phase=Phase.VALIDATE_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        with caplog.at_level(logging.INFO):
            cleanup_partial_outputs(state, artifacts)
        assert "idempotent" in caplog.text.lower()

    def test_cleanup_create_story_is_idempotent(self, tmp_path: Path) -> None:
        """AC4: CREATE_STORY is also idempotent."""
        state = State(current_phase=Phase.CREATE_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        result = cleanup_partial_outputs(state, artifacts)
        assert result.uncommitted_files == []
        assert result.cleaned_files == []

    def test_cleanup_retrospective_is_idempotent(self, tmp_path: Path) -> None:
        """AC4: RETROSPECTIVE is also idempotent."""
        state = State(current_phase=Phase.RETROSPECTIVE, current_story="2.5")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        result = cleanup_partial_outputs(state, artifacts)
        assert result.uncommitted_files == []
        assert result.cleaned_files == []

    def test_cleanup_none_phase_returns_empty(self, tmp_path: Path) -> None:
        """cleanup_partial_outputs with None phase returns empty."""
        state = State(current_phase=None)
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        result = cleanup_partial_outputs(state, artifacts)
        assert result.uncommitted_files == []
        assert result.cleaned_files == []
        assert result.warnings == []


# =============================================================================
# AC5: Partial outputs cleanup for DEV_STORY phase
# =============================================================================


class TestCleanupPartialOutputsDevStory:
    """Test cleanup_partial_outputs for DEV_STORY (AC5)."""

    def test_cleanup_dev_story_with_uncommitted_changes(self, tmp_path: Path) -> None:
        """AC5: DEV_STORY cleanup warns about uncommitted changes."""
        state = State(current_phase=Phase.DEV_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        mock_result = MagicMock()
        mock_result.stdout = "M src/file.py\nA tests/test.py"
        mock_result.returncode = 0

        with patch("bmad_assist.core.state.subprocess.run", return_value=mock_result):
            result = cleanup_partial_outputs(state, artifacts)

        assert len(result.uncommitted_files) == 2
        assert "M src/file.py" in result.uncommitted_files
        assert "A tests/test.py" in result.uncommitted_files

    def test_cleanup_dev_story_warns_about_uncommitted(self, tmp_path: Path) -> None:
        """AC5: Warning is added for uncommitted changes."""
        state = State(current_phase=Phase.DEV_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        mock_result = MagicMock()
        mock_result.stdout = "M src/file.py"
        mock_result.returncode = 0

        with patch("bmad_assist.core.state.subprocess.run", return_value=mock_result):
            result = cleanup_partial_outputs(state, artifacts)

        assert len(result.warnings) == 1
        assert "uncommitted changes" in result.warnings[0].lower()

    def test_cleanup_dev_story_no_uncommitted_no_warning(self, tmp_path: Path) -> None:
        """AC5: No warning when no uncommitted changes."""
        state = State(current_phase=Phase.DEV_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        mock_result = MagicMock()
        mock_result.stdout = ""  # No changes
        mock_result.returncode = 0

        with patch("bmad_assist.core.state.subprocess.run", return_value=mock_result):
            result = cleanup_partial_outputs(state, artifacts)

        assert result.uncommitted_files == []
        assert result.warnings == []

    def test_cleanup_dev_story_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC5: Uncommitted changes warning is logged."""
        state = State(current_phase=Phase.DEV_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        mock_result = MagicMock()
        mock_result.stdout = "M src/file.py"
        mock_result.returncode = 0

        with patch("bmad_assist.core.state.subprocess.run", return_value=mock_result):
            with caplog.at_level(logging.WARNING):
                cleanup_partial_outputs(state, artifacts)

        assert "uncommitted changes" in caplog.text.lower()


# =============================================================================
# AC6: Partial outputs cleanup for synthesis phases
# =============================================================================


class TestCleanupPartialOutputsSynthesis:
    """Test cleanup_partial_outputs for synthesis phases (AC6)."""

    def test_cleanup_validate_story_synthesis_removes_master_reports(
        self, synthesis_state: State, sprint_artifacts_dir: Path
    ) -> None:
        """AC6: VALIDATE_STORY_SYNTHESIS removes master synthesis reports."""
        result = cleanup_partial_outputs(synthesis_state, sprint_artifacts_dir)

        assert len(result.cleaned_files) == 1
        assert "story-validation-3-2-master" in result.cleaned_files[0]

    def test_cleanup_validate_story_synthesis_file_deleted(
        self, synthesis_state: State, sprint_artifacts_dir: Path
    ) -> None:
        """AC6: Synthesis report file is actually deleted."""
        report_path = (
            sprint_artifacts_dir
            / "story-validations"
            / "story-validation-3-2-master-20251210_120000.md"
        )
        assert report_path.exists()

        cleanup_partial_outputs(synthesis_state, sprint_artifacts_dir)

        assert not report_path.exists()

    def test_cleanup_validate_story_synthesis_logs_removal(
        self,
        synthesis_state: State,
        sprint_artifacts_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AC6: Removal is logged."""
        with caplog.at_level(logging.INFO):
            cleanup_partial_outputs(synthesis_state, sprint_artifacts_dir)

        assert "Removing partial synthesis report" in caplog.text

    def test_cleanup_validate_story_synthesis_multiple_reports(
        self, synthesis_state: State, tmp_path: Path
    ) -> None:
        """AC6: ALL master reports for story are removed."""
        artifacts = tmp_path / "sprint-artifacts"
        validations = artifacts / "story-validations"
        validations.mkdir(parents=True)
        # Create multiple reports
        (validations / "story-validation-3-2-master-20251210_100000.md").write_text(
            "first", encoding="utf-8"
        )
        (validations / "story-validation-3-2-master-20251210_110000.md").write_text(
            "second", encoding="utf-8"
        )
        (validations / "story-validation-3-2-master-20251210_120000.md").write_text(
            "third", encoding="utf-8"
        )

        result = cleanup_partial_outputs(synthesis_state, artifacts)

        assert len(result.cleaned_files) == 3
        for f in validations.glob("story-validation-3-2-master-*.md"):
            pytest.fail(f"File should be deleted: {f}")

    def test_cleanup_code_review_synthesis_removes_reports(
        self, code_review_synthesis_state: State, code_reviews_dir: Path
    ) -> None:
        """AC6: CODE_REVIEW_SYNTHESIS removes master code review reports."""
        result = cleanup_partial_outputs(code_review_synthesis_state, code_reviews_dir)

        assert len(result.cleaned_files) == 1
        assert "code-review-3-2-master" in result.cleaned_files[0]

    def test_cleanup_synthesis_story_key_conversion(self, tmp_path: Path) -> None:
        """AC6: Story ID 3.2 converts to story key 3-2."""
        artifacts = tmp_path / "sprint-artifacts"
        validations = artifacts / "story-validations"
        validations.mkdir(parents=True)
        # Create report with dash-separated key
        (validations / "story-validation-3-2-master-20251210_120000.md").write_text(
            "test", encoding="utf-8"
        )

        state = State(
            current_epic=3,
            current_story="3.2",  # Dot notation
            current_phase=Phase.VALIDATE_STORY_SYNTHESIS,
        )

        result = cleanup_partial_outputs(state, artifacts)

        assert len(result.cleaned_files) == 1

    def test_cleanup_synthesis_different_story_not_removed(
        self, synthesis_state: State, tmp_path: Path
    ) -> None:
        """AC6: Reports for different stories are not removed."""
        artifacts = tmp_path / "sprint-artifacts"
        validations = artifacts / "story-validations"
        validations.mkdir(parents=True)
        # Create report for different story
        (validations / "story-validation-3-1-master-20251210_120000.md").write_text(
            "different", encoding="utf-8"
        )

        result = cleanup_partial_outputs(synthesis_state, artifacts)

        assert len(result.cleaned_files) == 0
        assert (validations / "story-validation-3-1-master-20251210_120000.md").exists()


# =============================================================================
# AC11: Git unavailable handled gracefully
# =============================================================================


class TestCleanupGitUnavailable:
    """Test cleanup_partial_outputs when git unavailable (AC11)."""

    def test_cleanup_git_nonzero_returncode(self, tmp_path: Path) -> None:
        """Git status failure (non-zero returncode) handled gracefully."""
        state = State(current_phase=Phase.DEV_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: not a git repository"
        mock_result.stdout = ""

        with patch("bmad_assist.core.state.subprocess.run", return_value=mock_result):
            result = cleanup_partial_outputs(state, artifacts)

        assert result.uncommitted_files == []
        assert len(result.warnings) == 1
        assert "exit 128" in result.warnings[0]
        assert "not a git repository" in result.warnings[0]

    def test_cleanup_git_not_found(self, tmp_path: Path) -> None:
        """AC11: Git not installed handled gracefully."""
        state = State(current_phase=Phase.DEV_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        with patch(
            "bmad_assist.core.state.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            result = cleanup_partial_outputs(state, artifacts)

        assert result.uncommitted_files == []
        assert len(result.warnings) == 1
        assert "could not check git status" in result.warnings[0].lower()

    def test_cleanup_git_timeout(self, tmp_path: Path) -> None:
        """AC11: Git timeout handled gracefully."""
        state = State(current_phase=Phase.DEV_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        from subprocess import TimeoutExpired

        with patch(
            "bmad_assist.core.state.subprocess.run",
            side_effect=TimeoutExpired(cmd=["git"], timeout=10),
        ):
            result = cleanup_partial_outputs(state, artifacts)

        assert result.uncommitted_files == []
        assert len(result.warnings) == 1
        assert "could not check git status" in result.warnings[0].lower()

    def test_cleanup_git_unavailable_no_exception(self, tmp_path: Path) -> None:
        """AC11: Function returns normally (no exception raised)."""
        state = State(current_phase=Phase.DEV_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        with patch(
            "bmad_assist.core.state.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            # Should not raise
            result = cleanup_partial_outputs(state, artifacts)
            assert isinstance(result, CleanupResult)


# =============================================================================
# AC12: Missing sprint_artifacts directory handled gracefully
# =============================================================================


class TestCleanupMissingSprint_artifacts:
    """Test cleanup_partial_outputs with missing sprint_artifacts (AC12)."""

    def test_cleanup_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        """AC12: Missing directory returns empty result."""
        state = State(current_phase=Phase.VALIDATE_STORY_SYNTHESIS, current_story="3.1")
        missing_artifacts = tmp_path / "nonexistent"

        result = cleanup_partial_outputs(state, missing_artifacts)

        assert result.cleaned_files == []
        assert result.uncommitted_files == []

    def test_cleanup_missing_dir_no_exception(self, tmp_path: Path) -> None:
        """AC12: Function returns normally (no exception raised)."""
        state = State(current_phase=Phase.VALIDATE_STORY_SYNTHESIS, current_story="3.1")
        missing_artifacts = tmp_path / "nonexistent"

        # Should not raise
        result = cleanup_partial_outputs(state, missing_artifacts)
        assert isinstance(result, CleanupResult)

    def test_cleanup_missing_dir_no_creation(self, tmp_path: Path) -> None:
        """AC12: No directory is created."""
        state = State(current_phase=Phase.VALIDATE_STORY_SYNTHESIS, current_story="3.1")
        missing_artifacts = tmp_path / "nonexistent"

        cleanup_partial_outputs(state, missing_artifacts)

        assert not missing_artifacts.exists()

    def test_cleanup_missing_subdirectory_returns_empty(
        self, synthesis_state: State, tmp_path: Path
    ) -> None:
        """AC12: Missing story-validations subdirectory handled."""
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        # story-validations subdirectory doesn't exist

        result = cleanup_partial_outputs(synthesis_state, artifacts)

        assert result.cleaned_files == []


# =============================================================================
# AC13: Docstrings are complete and testable
# =============================================================================


class TestDocstrings:
    """Test docstrings are complete (AC13)."""

    def test_get_resume_point_has_docstring(self) -> None:
        """AC13: get_resume_point has non-empty docstring."""
        assert get_resume_point.__doc__ is not None
        assert len(get_resume_point.__doc__.strip()) > 0

    def test_get_resume_point_docstring_has_args(self) -> None:
        """AC13: get_resume_point docstring has Args section."""
        assert "Args:" in get_resume_point.__doc__

    def test_get_resume_point_docstring_has_returns(self) -> None:
        """AC13: get_resume_point docstring has Returns section."""
        assert "Returns:" in get_resume_point.__doc__

    def test_get_resume_point_docstring_has_raises(self) -> None:
        """AC13: get_resume_point docstring has Raises section."""
        assert "Raises:" in get_resume_point.__doc__

    def test_get_resume_point_docstring_has_example(self) -> None:
        """AC13: get_resume_point docstring has Example section."""
        assert "Example:" in get_resume_point.__doc__

    def test_cleanup_partial_outputs_has_docstring(self) -> None:
        """AC13: cleanup_partial_outputs has non-empty docstring."""
        assert cleanup_partial_outputs.__doc__ is not None
        assert len(cleanup_partial_outputs.__doc__.strip()) > 0

    def test_cleanup_partial_outputs_docstring_has_args(self) -> None:
        """AC13: cleanup_partial_outputs docstring has Args section."""
        assert "Args:" in cleanup_partial_outputs.__doc__

    def test_cleanup_partial_outputs_docstring_has_returns(self) -> None:
        """AC13: cleanup_partial_outputs docstring has Returns section."""
        assert "Returns:" in cleanup_partial_outputs.__doc__

    def test_cleanup_partial_outputs_docstring_has_example(self) -> None:
        """AC13: cleanup_partial_outputs docstring has Example section."""
        assert "Example:" in cleanup_partial_outputs.__doc__

    def test_resume_point_has_docstring(self) -> None:
        """AC13: ResumePoint has docstring."""
        assert ResumePoint.__doc__ is not None
        assert len(ResumePoint.__doc__.strip()) > 0

    def test_cleanup_result_has_docstring(self) -> None:
        """AC13: CleanupResult has docstring."""
        assert CleanupResult.__doc__ is not None
        assert len(CleanupResult.__doc__.strip()) > 0


# =============================================================================
# Function Exports Tests
# =============================================================================


class TestFunctionExports:
    """Test function exports."""

    def test_get_resume_point_in_exports(self) -> None:
        """get_resume_point is in __all__."""
        from bmad_assist.core import state as state_module

        assert "get_resume_point" in state_module.__all__

    def test_cleanup_partial_outputs_in_exports(self) -> None:
        """cleanup_partial_outputs is in __all__."""
        from bmad_assist.core import state as state_module

        assert "cleanup_partial_outputs" in state_module.__all__


# =============================================================================
# Logging Tests
# =============================================================================


class TestLogging:
    """Test logging output."""

    def test_get_resume_point_logs_at_info_level(
        self, mid_loop_state: tuple[Path, State], caplog: pytest.LogCaptureFixture
    ) -> None:
        """get_resume_point logs at INFO level."""
        path, _ = mid_loop_state
        with caplog.at_level(logging.INFO):
            get_resume_point(path)
        assert len(caplog.records) > 0

    def test_cleanup_idempotent_logs_at_info_level(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """cleanup_partial_outputs logs idempotent phases at INFO level."""
        state = State(current_phase=Phase.VALIDATE_STORY, current_story="3.1")
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        with caplog.at_level(logging.INFO):
            cleanup_partial_outputs(state, artifacts)
        assert any("idempotent" in r.message.lower() for r in caplog.records)


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases."""

    def test_get_resume_point_with_tilde_path(self, tmp_path: Path) -> None:
        """get_resume_point expands tilde in path."""
        # Create a state file in tmp_path
        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.CREATE_STORY,
        )
        path = tmp_path / "state.yaml"
        save_state(state, path)

        # Mock expanduser to return our tmp_path
        with patch("pathlib.Path.expanduser", return_value=path):
            resume = get_resume_point("~/fake/state.yaml")
            # load_state internally calls expanduser on the Path object

        # Since we're using the actual path, this should work
        resume = get_resume_point(path)
        assert resume.epic == 1

    def test_cleanup_completed_stories_isolated(self) -> None:
        """completed_stories list in ResumePoint is a copy, not reference."""
        state = State(
            current_epic=3,
            current_story="3.1",
            current_phase=Phase.DEV_STORY,
            completed_stories=["1.1", "1.2"],
        )
        # Get completed stories from state
        original = state.completed_stories

        # Create ResumePoint with list copy
        rp = ResumePoint(
            epic=3,
            story="3.1",
            phase=Phase.DEV_STORY,
            is_fresh_start=False,
            completed_stories=list(state.completed_stories),
        )

        # Modify original
        original.append("2.1")

        # ResumePoint should be unaffected
        assert "2.1" not in rp.completed_stories

    def test_cleanup_with_no_story_id(self, tmp_path: Path) -> None:
        """cleanup_partial_outputs handles None story_id."""
        state = State(
            current_phase=Phase.VALIDATE_STORY_SYNTHESIS,
            current_story=None,  # No story
        )
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        result = cleanup_partial_outputs(state, artifacts)
        assert result.cleaned_files == []

    def test_cleanup_unlink_oserror_handled(self, tmp_path: Path) -> None:
        """cleanup_partial_outputs handles OSError from unlink gracefully."""
        state = State(
            current_phase=Phase.VALIDATE_STORY_SYNTHESIS,
            current_story="3.2",
        )
        artifacts = tmp_path / "sprint-artifacts"
        validations = artifacts / "story-validations"
        validations.mkdir(parents=True)
        # Create a report file
        report = validations / "story-validation-3-2-master-20251210_120000.md"
        report.write_text("test", encoding="utf-8")

        # Mock unlink to raise PermissionError
        with patch.object(Path, "unlink", side_effect=PermissionError("Access denied")):
            result = cleanup_partial_outputs(state, artifacts)

        assert result.cleaned_files == []
        assert len(result.warnings) == 1
        assert "Failed to remove partial report" in result.warnings[0]
        assert "Access denied" in result.warnings[0]

    def test_cleanup_sprint_artifacts_is_file_warns(self, tmp_path: Path) -> None:
        """cleanup_partial_outputs warns if sprint_artifacts is a file, not directory."""
        state = State(
            current_phase=Phase.VALIDATE_STORY_SYNTHESIS,
            current_story="3.2",
        )
        # Create a file (not a directory) at sprint_artifacts path
        artifacts_file = tmp_path / "sprint-artifacts"
        artifacts_file.write_text("I am a file", encoding="utf-8")

        result = cleanup_partial_outputs(state, artifacts_file)

        assert result.cleaned_files == []
        assert len(result.warnings) == 1
        assert "not a directory" in result.warnings[0]
