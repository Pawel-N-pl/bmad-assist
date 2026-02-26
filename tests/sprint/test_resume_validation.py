"""Tests for sprint resume validation module."""


import pytest

from bmad_assist.core.state import Phase, State
from bmad_assist.sprint.resume_validation import (
    ResumeValidationResult,
    _find_next_incomplete_epic,
    _find_next_incomplete_story,
    _is_epic_done_in_sprint,
    _is_story_done_in_sprint,
    validate_resume_state,
)


@pytest.fixture
def basic_sprint_status_yaml() -> str:
    """Sprint-status YAML with mixed done/in-progress entries."""
    return """
generated: '2026-01-01T00:00:00'
project: test-project
development_status:
  epic-1: done
  1-1-first-story: done
  1-2-second-story: done
  epic-2: in-progress
  2-1-first-story: done
  2-2-second-story: in-progress
  2-3-third-story: backlog
  epic-3: backlog
  3-1-first-story: backlog
"""


@pytest.fixture
def all_done_sprint_status_yaml() -> str:
    """Sprint-status YAML where all epics, stories, and retrospectives are done."""
    return """
generated: '2026-01-01T00:00:00'
project: test-project
development_status:
  epic-1: done
  epic-1-retrospective: done
  1-1-first-story: done
  1-2-second-story: done
  epic-2: done
  epic-2-retrospective: done
  2-1-first-story: done
  2-2-second-story: done
  epic-3: done
  epic-3-retrospective: done
  3-1-first-story: done
"""


@pytest.fixture
def state_at_epic_2_story_1() -> State:
    """State pointing to Epic 2, Story 2.1, CREATE_STORY phase."""
    return State(
        current_epic=2,
        current_story="2.1",
        current_phase=Phase.CREATE_STORY,
        completed_stories=[],
        completed_epics=[1],
    )


@pytest.fixture
def epic_stories_loader():
    """Mock epic_stories_loader that returns predefined stories."""

    def loader(epic_id):
        stories = {
            1: ["1.1", "1.2"],
            2: ["2.1", "2.2", "2.3"],
            3: ["3.1"],
        }
        return stories.get(epic_id, [])

    return loader


class TestIsStoryDoneInSprint:
    """Tests for _is_story_done_in_sprint helper."""

    def test_story_done(self, tmp_path, basic_sprint_status_yaml):
        """Story marked done returns True."""
        from bmad_assist.sprint.parser import parse_sprint_status

        path = tmp_path / "sprint-status.yaml"
        path.write_text(basic_sprint_status_yaml)
        sprint_status = parse_sprint_status(path)

        assert _is_story_done_in_sprint("1.1", sprint_status) is True
        assert _is_story_done_in_sprint("2.1", sprint_status) is True

    def test_story_in_progress(self, tmp_path, basic_sprint_status_yaml):
        """Story marked in-progress returns False."""
        from bmad_assist.sprint.parser import parse_sprint_status

        path = tmp_path / "sprint-status.yaml"
        path.write_text(basic_sprint_status_yaml)
        sprint_status = parse_sprint_status(path)

        assert _is_story_done_in_sprint("2.2", sprint_status) is False

    def test_story_backlog(self, tmp_path, basic_sprint_status_yaml):
        """Story marked backlog returns False."""
        from bmad_assist.sprint.parser import parse_sprint_status

        path = tmp_path / "sprint-status.yaml"
        path.write_text(basic_sprint_status_yaml)
        sprint_status = parse_sprint_status(path)

        assert _is_story_done_in_sprint("2.3", sprint_status) is False

    def test_story_not_found(self, tmp_path, basic_sprint_status_yaml):
        """Story not in sprint-status returns False."""
        from bmad_assist.sprint.parser import parse_sprint_status

        path = tmp_path / "sprint-status.yaml"
        path.write_text(basic_sprint_status_yaml)
        sprint_status = parse_sprint_status(path)

        assert _is_story_done_in_sprint("99.1", sprint_status) is False


class TestIsEpicDoneInSprint:
    """Tests for _is_epic_done_in_sprint helper."""

    def test_epic_done_with_retro_done(self, tmp_path):
        """Epic is done only when both epic AND retrospective are done."""
        from bmad_assist.sprint.parser import parse_sprint_status

        yaml_content = """
generated: '2026-01-01'
development_status:
  epic-1: done
  epic-1-retrospective: done
"""
        path = tmp_path / "sprint-status.yaml"
        path.write_text(yaml_content)
        sprint_status = parse_sprint_status(path)

        assert _is_epic_done_in_sprint(1, sprint_status) is True

    def test_epic_done_but_retro_backlog(self, tmp_path):
        """Epic is NOT done if retrospective is backlog."""
        from bmad_assist.sprint.parser import parse_sprint_status

        yaml_content = """
generated: '2026-01-01'
development_status:
  epic-1: done
  epic-1-retrospective: backlog
"""
        path = tmp_path / "sprint-status.yaml"
        path.write_text(yaml_content)
        sprint_status = parse_sprint_status(path)

        assert _is_epic_done_in_sprint(1, sprint_status) is False

    def test_epic_done_no_retro_entry(self, tmp_path):
        """Epic is done if no retrospective entry exists (legacy compat)."""
        from bmad_assist.sprint.parser import parse_sprint_status

        yaml_content = """
generated: '2026-01-01'
development_status:
  epic-1: done
"""
        path = tmp_path / "sprint-status.yaml"
        path.write_text(yaml_content)
        sprint_status = parse_sprint_status(path)

        assert _is_epic_done_in_sprint(1, sprint_status) is True

    def test_epic_in_progress(self, tmp_path, basic_sprint_status_yaml):
        """Epic marked in-progress returns False."""
        from bmad_assist.sprint.parser import parse_sprint_status

        path = tmp_path / "sprint-status.yaml"
        path.write_text(basic_sprint_status_yaml)
        sprint_status = parse_sprint_status(path)

        assert _is_epic_done_in_sprint(2, sprint_status) is False

    def test_epic_backlog(self, tmp_path, basic_sprint_status_yaml):
        """Epic marked backlog returns False."""
        from bmad_assist.sprint.parser import parse_sprint_status

        path = tmp_path / "sprint-status.yaml"
        path.write_text(basic_sprint_status_yaml)
        sprint_status = parse_sprint_status(path)

        assert _is_epic_done_in_sprint(3, sprint_status) is False


class TestFindNextIncompleteStory:
    """Tests for _find_next_incomplete_story helper."""

    def test_finds_first_incomplete(self, tmp_path, basic_sprint_status_yaml):
        """Finds first story not done in sprint-status."""
        from bmad_assist.sprint.parser import parse_sprint_status

        path = tmp_path / "sprint-status.yaml"
        path.write_text(basic_sprint_status_yaml)
        sprint_status = parse_sprint_status(path)

        result = _find_next_incomplete_story("2.1", ["2.1", "2.2", "2.3"], ["2.1"], sprint_status)
        assert result == "2.2"

    def test_skips_done_stories(self, tmp_path):
        """Skips stories that are done in sprint-status."""
        from bmad_assist.sprint.parser import parse_sprint_status

        yaml_content = """
generated: '2026-01-01'
development_status:
  1-1-first: done
  1-2-second: done
  1-3-third: in-progress
"""
        path = tmp_path / "sprint-status.yaml"
        path.write_text(yaml_content)
        sprint_status = parse_sprint_status(path)

        result = _find_next_incomplete_story("1.1", ["1.1", "1.2", "1.3"], [], sprint_status)
        assert result == "1.3"

    def test_returns_none_when_all_done(self, tmp_path, all_done_sprint_status_yaml):
        """Returns None when all remaining stories are done."""
        from bmad_assist.sprint.parser import parse_sprint_status

        path = tmp_path / "sprint-status.yaml"
        path.write_text(all_done_sprint_status_yaml)
        sprint_status = parse_sprint_status(path)

        result = _find_next_incomplete_story("1.1", ["1.1", "1.2"], [], sprint_status)
        assert result is None


class TestFindNextIncompleteEpic:
    """Tests for _find_next_incomplete_epic helper."""

    def test_finds_first_incomplete(self, tmp_path, basic_sprint_status_yaml):
        """Finds first epic not done in sprint-status."""
        from bmad_assist.sprint.parser import parse_sprint_status

        path = tmp_path / "sprint-status.yaml"
        path.write_text(basic_sprint_status_yaml)
        sprint_status = parse_sprint_status(path)

        result = _find_next_incomplete_epic(1, [1, 2, 3], [1], sprint_status)
        assert result == 2

    def test_skips_completed_epics(self, tmp_path, basic_sprint_status_yaml):
        """Skips epics in completed_epics list."""
        from bmad_assist.sprint.parser import parse_sprint_status

        path = tmp_path / "sprint-status.yaml"
        path.write_text(basic_sprint_status_yaml)
        sprint_status = parse_sprint_status(path)

        result = _find_next_incomplete_epic(1, [1, 2, 3], [1, 2], sprint_status)
        assert result == 3

    def test_returns_none_when_all_done(self, tmp_path, all_done_sprint_status_yaml):
        """Returns None when all epics are done."""
        from bmad_assist.sprint.parser import parse_sprint_status

        path = tmp_path / "sprint-status.yaml"
        path.write_text(all_done_sprint_status_yaml)
        sprint_status = parse_sprint_status(path)

        result = _find_next_incomplete_epic(1, [1, 2, 3], [], sprint_status)
        assert result is None


class TestValidateResumeState:
    """Tests for validate_resume_state main function."""

    def test_no_sprint_status_file(self, tmp_path, state_at_epic_2_story_1, epic_stories_loader):
        """Returns unchanged state when no sprint-status file exists."""
        result = validate_resume_state(
            state_at_epic_2_story_1,
            tmp_path,
            [1, 2, 3],
            epic_stories_loader,
        )

        assert result.state == state_at_epic_2_story_1
        assert result.advanced is False
        assert result.stories_skipped == []
        assert result.epics_skipped == []
        assert result.project_complete is False

    def test_skips_done_story(
        self, tmp_path, state_at_epic_2_story_1, epic_stories_loader, basic_sprint_status_yaml
    ):
        """Advances state when current story is done in sprint-status."""
        # Setup: story 2.1 is marked done in sprint-status
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)
        (impl_artifacts / "sprint-status.yaml").write_text(basic_sprint_status_yaml)

        result = validate_resume_state(
            state_at_epic_2_story_1,
            tmp_path,
            [1, 2, 3],
            epic_stories_loader,
        )

        assert result.advanced is True
        assert "2.1" in result.stories_skipped
        assert result.state.current_story == "2.2"
        assert result.state.current_phase == Phase.CREATE_STORY
        assert "2.1" in result.state.completed_stories

    def test_skips_done_epic(self, tmp_path, epic_stories_loader):
        """Advances to next epic when current epic is done in sprint-status."""
        yaml_content = """
generated: '2026-01-01'
development_status:
  epic-1: done
  1-1-first: done
  1-2-second: done
  epic-2: backlog
  2-1-first: backlog
"""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)
        (impl_artifacts / "sprint-status.yaml").write_text(yaml_content)

        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.CREATE_STORY,
            completed_stories=[],
            completed_epics=[],
        )

        result = validate_resume_state(state, tmp_path, [1, 2], epic_stories_loader)

        assert result.advanced is True
        assert 1 in result.epics_skipped
        assert result.state.current_epic == 2
        assert result.state.current_story == "2.1"
        assert 1 in result.state.completed_epics

    def test_project_complete_all_done(
        self, tmp_path, epic_stories_loader, all_done_sprint_status_yaml
    ):
        """Detects project completion when all epics are done."""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)
        (impl_artifacts / "sprint-status.yaml").write_text(all_done_sprint_status_yaml)

        state = State(
            current_epic=1,
            current_story="1.1",
            current_phase=Phase.CREATE_STORY,
            completed_stories=[],
            completed_epics=[],
        )

        result = validate_resume_state(state, tmp_path, [1, 2, 3], epic_stories_loader)

        assert result.project_complete is True
        assert result.advanced is True

    def test_no_changes_when_current_not_done(
        self, tmp_path, epic_stories_loader, basic_sprint_status_yaml
    ):
        """No changes when current story is not done."""
        impl_artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True)
        (impl_artifacts / "sprint-status.yaml").write_text(basic_sprint_status_yaml)

        state = State(
            current_epic=2,
            current_story="2.2",  # This is in-progress in sprint-status
            current_phase=Phase.DEV_STORY,
            completed_stories=["2.1"],
            completed_epics=[1],
        )

        result = validate_resume_state(state, tmp_path, [1, 2, 3], epic_stories_loader)

        assert result.advanced is False
        assert result.state == state

    def test_result_summary(self):
        """ResumeValidationResult.summary() produces readable output."""
        state = State()

        # No changes
        result = ResumeValidationResult(
            state=state,
            stories_skipped=[],
            epics_skipped=[],
            advanced=False,
            project_complete=False,
        )
        assert "no changes" in result.summary()

        # Stories skipped
        result = ResumeValidationResult(
            state=state,
            stories_skipped=["1.1", "1.2"],
            epics_skipped=[],
            advanced=True,
            project_complete=False,
        )
        assert "2 done stories" in result.summary()

        # Project complete
        result = ResumeValidationResult(
            state=state, stories_skipped=[], epics_skipped=[1], advanced=True, project_complete=True
        )
        assert "project complete" in result.summary()
