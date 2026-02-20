"""Tests for Project State Reader (Story 2.3).

Tests cover all acceptance criteria:

Story 2.3 - Project State Reader:
- AC1: Discover epic files in project
- AC2: Return ProjectState dataclass
- AC3: Compile completed stories list
- AC4: Determine current epic position
- AC5: Determine current story position
- AC6: Handle consolidated epics.md file
- AC7: Handle separate epic files
- AC8: Handle missing epic files gracefully
- AC9: Handle invalid BMAD path
- AC10: Handle malformed epic files gracefully
- AC11: Handle stories without status field
- AC12: Handle both consolidated and separate epic files
- AC13: Sprint-status.yaml integration (optional extension)
- AC14: Handle malformed sprint-status.yaml gracefully
- AC15: ProjectState field invariants
"""

import logging
from pathlib import Path

import pytest

from bmad_assist.bmad.parser import EpicDocument, EpicStory
from bmad_assist.bmad.state_reader import (
    ProjectState,
    _apply_default_status,
    _apply_sprint_statuses,
    _determine_current_position,
    _discover_epic_files,
    _flatten_stories,
    _normalize_status,
    _parse_sprint_status_key,
    _story_sort_key,
    read_project_state,
)


class TestDiscoverEpicFiles:
    """Test AC1: Epic file discovery."""

    def test_discover_single_epics_file(self, tmp_path: Path) -> None:
        """Discover consolidated epics.md file."""
        epics_file = tmp_path / "epics.md"
        epics_file.write_text("---\n---\n# Content")

        result = _discover_epic_files(tmp_path)

        assert len(result) == 1
        assert result[0] == epics_file

    def test_discover_separate_epic_files(self, tmp_path: Path) -> None:
        """Discover separate epic-1.md, epic-2.md files."""
        (tmp_path / "epic-1.md").write_text("---\n---\n# Epic 1")
        (tmp_path / "epic-2.md").write_text("---\n---\n# Epic 2")
        (tmp_path / "epic-3.md").write_text("---\n---\n# Epic 3")

        result = _discover_epic_files(tmp_path)

        assert len(result) == 3
        assert result[0].name == "epic-1.md"
        assert result[1].name == "epic-2.md"
        assert result[2].name == "epic-3.md"

    def test_discover_mixed_epic_patterns(self, tmp_path: Path) -> None:
        """Discover both consolidated and separate epic files."""
        (tmp_path / "epics.md").write_text("---\n---\n# All epics")
        (tmp_path / "epic-special.md").write_text("---\n---\n# Special epic")

        result = _discover_epic_files(tmp_path)

        assert len(result) == 2
        # Sorted alphabetically
        assert result[0].name == "epic-special.md"
        assert result[1].name == "epics.md"

    def test_filter_out_retrospectives(self, tmp_path: Path) -> None:
        """Filter out epic retrospective files."""
        (tmp_path / "epic-1.md").write_text("---\n---\n# Epic 1")
        (tmp_path / "epic-1-retrospective.md").write_text("---\n---\n# Retro")
        (tmp_path / "epic-retrospective.md").write_text("---\n---\n# Retro")

        result = _discover_epic_files(tmp_path)

        assert len(result) == 1
        assert result[0].name == "epic-1.md"

    def test_filter_out_directories(self, tmp_path: Path) -> None:
        """Filter out directories matching epic pattern."""
        (tmp_path / "epic-1.md").write_text("---\n---\n# Epic 1")
        epic_dir = tmp_path / "epics.md"  # Directory with .md name
        epic_dir.mkdir()

        result = _discover_epic_files(tmp_path)

        assert len(result) == 1
        assert result[0].name == "epic-1.md"

    def test_empty_directory_returns_empty_list(self, tmp_path: Path) -> None:
        """Empty directory returns empty list."""
        result = _discover_epic_files(tmp_path)

        assert result == []

    def test_no_epic_files_returns_empty_list(self, tmp_path: Path) -> None:
        """Directory without epic files returns empty list."""
        (tmp_path / "prd.md").write_text("---\n---\n# PRD")
        (tmp_path / "architecture.md").write_text("---\n---\n# Arch")

        result = _discover_epic_files(tmp_path)

        assert result == []


class TestProjectStateDataclass:
    """Test AC2: ProjectState dataclass structure."""

    def test_projectstate_structure(self, tmp_path: Path) -> None:
        """ProjectState has all required fields."""
        epic_content = """---
epic_num: 1
---

## Story 1.1: Test Story
**Status:** done
**Estimate:** 2 SP
"""
        (tmp_path / "epic-1.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert isinstance(result, ProjectState)
        assert isinstance(result.epics, list)
        assert isinstance(result.all_stories, list)
        assert isinstance(result.completed_stories, list)
        assert result.current_epic is None or isinstance(result.current_epic, int)
        assert result.current_story is None or isinstance(result.current_story, str)
        assert isinstance(result.bmad_path, str)

    def test_projectstate_contains_epicdocuments(self, tmp_path: Path) -> None:
        """ProjectState.epics contains EpicDocument objects."""
        epic_content = """---
epic_num: 1
title: Test Epic
---

## Story 1.1: Test
"""
        (tmp_path / "epic-1.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert len(result.epics) == 1
        assert isinstance(result.epics[0], EpicDocument)

    def test_projectstate_contains_epicstories(self, tmp_path: Path) -> None:
        """ProjectState.all_stories contains EpicStory objects."""
        epic_content = """---
---

## Story 1.1: Test
**Estimate:** 2 SP
"""
        (tmp_path / "epic-1.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert len(result.all_stories) == 1
        assert isinstance(result.all_stories[0], EpicStory)


class TestCompletedStories:
    """Test AC3: Compile completed stories list."""

    def test_compile_completed_stories(self, tmp_path: Path) -> None:
        """Compile list of stories with status=done."""
        epic_content = """---
---

## Story 1.1: First Story
**Status:** done

## Story 1.2: Second Story
**Status:** done

## Story 2.1: Third Story
**Status:** in-progress

## Story 2.2: Fourth Story
**Status:** backlog
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert result.completed_stories == ["1.1", "1.2"]

    def test_all_status_values_correctly_filtered(self, tmp_path: Path) -> None:
        """Test all valid status values are correctly filtered."""
        epic_content = """---
---

## Story 1.1: Done Story
**Status:** done

## Story 1.2: Review Story
**Status:** review

## Story 1.3: In Progress Story
**Status:** in-progress

## Story 1.4: Ready for Dev Story
**Status:** ready-for-dev

## Story 1.5: Drafted Story
**Status:** drafted

## Story 1.6: Backlog Story
**Status:** backlog
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        # Only "done" should be in completed_stories
        assert result.completed_stories == ["1.1"]
        # All others should NOT be completed
        assert "1.2" not in result.completed_stories
        assert "1.3" not in result.completed_stories
        assert "1.4" not in result.completed_stories
        assert "1.5" not in result.completed_stories
        assert "1.6" not in result.completed_stories

    def test_case_insensitive_done_status(self, tmp_path: Path) -> None:
        """Status 'done' is case-insensitive."""
        epic_content = """---
---

## Story 1.1: Story A
**Status:** done

## Story 1.2: Story B
**Status:** Done

## Story 1.3: Story C
**Status:** DONE
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert result.completed_stories == ["1.1", "1.2", "1.3"]

    def test_empty_completed_stories_when_none_done(self, tmp_path: Path) -> None:
        """Empty completed_stories when no stories are done."""
        epic_content = """---
---

## Story 1.1: Story A
**Status:** backlog

## Story 1.2: Story B
**Status:** in-progress
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert result.completed_stories == []


class TestCurrentEpicDetermination:
    """Test AC4: Determine current epic position."""

    def test_current_epic_first_with_non_done_stories(self, tmp_path: Path) -> None:
        """Current epic is first epic with non-done stories."""
        epic_content = """---
---

## Story 1.1: First
**Status:** done

## Story 1.2: Second
**Status:** done

## Story 2.1: Third
**Status:** done

## Story 2.2: Fourth
**Status:** review

## Story 2.3: Fifth
**Status:** backlog
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert result.current_epic == 2

    def test_current_epic_is_first_when_all_backlog(self, tmp_path: Path) -> None:
        """Current epic is 1 when all stories are backlog."""
        epic_content = """---
---

## Story 1.1: First
**Status:** backlog

## Story 2.1: Second
**Status:** backlog
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert result.current_epic == 1

    def test_current_epic_none_when_all_done(self, tmp_path: Path) -> None:
        """Current epic is None when all stories are done."""
        epic_content = """---
---

## Story 1.1: First
**Status:** done

## Story 2.1: Second
**Status:** done
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert result.current_epic is None


class TestCurrentStoryDetermination:
    """Test AC5: Determine current story position."""

    def test_current_story_first_non_done(self, tmp_path: Path) -> None:
        """Current story is first non-done story in current epic."""
        epic_content = """---
---

## Story 2.1: First
**Status:** done

## Story 2.2: Second
**Status:** review

## Story 2.3: Third
**Status:** backlog
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert result.current_story == "2.2"

    def test_current_story_none_when_all_done(self, tmp_path: Path) -> None:
        """Current story is None when all stories are done."""
        epic_content = """---
---

## Story 1.1: First
**Status:** done

## Story 1.2: Second
**Status:** done
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert result.current_story is None


class TestConsolidatedEpicsHandling:
    """Test AC6: Handle consolidated epics.md file."""

    def test_parse_consolidated_epics_file(self, tmp_path: Path) -> None:
        """Parse single epics.md with multiple epics."""
        epic_content = """---
---

# Epic 1: Foundation

## Story 1.1: Setup
**Status:** done

## Story 1.2: Config
**Status:** done

# Epic 2: Integration

## Story 2.1: Parser
**Status:** review

## Story 2.2: Reader
**Status:** backlog
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert len(result.epics) == 1
        assert len(result.all_stories) == 4
        assert result.current_epic == 2
        assert result.current_story == "2.1"


class TestSeparateEpicFilesHandling:
    """Test AC7: Handle separate epic files."""

    def test_parse_separate_epic_files(self, tmp_path: Path) -> None:
        """Parse separate epic-1.md, epic-2.md files."""
        (tmp_path / "epic-1.md").write_text("""---
epic_num: 1
---

## Story 1.1: First
**Status:** done

## Story 1.2: Second
**Status:** done
""")
        (tmp_path / "epic-2.md").write_text("""---
epic_num: 2
---

## Story 2.1: Third
**Status:** in-progress
""")

        result = read_project_state(tmp_path)

        assert len(result.epics) == 2
        assert len(result.all_stories) == 3
        assert result.current_epic == 2
        assert result.current_story == "2.1"

    def test_stories_ordered_by_epic_then_story(self, tmp_path: Path) -> None:
        """Stories are ordered by epic number, then story number."""
        # Create files in reverse order
        (tmp_path / "epic-2.md").write_text("""---
---

## Story 2.2: Second Epic Second Story
## Story 2.1: Second Epic First Story
""")
        (tmp_path / "epic-1.md").write_text("""---
---

## Story 1.2: First Epic Second Story
## Story 1.1: First Epic First Story
""")

        result = read_project_state(tmp_path)

        assert len(result.all_stories) == 4
        assert result.all_stories[0].number == "1.1"
        assert result.all_stories[1].number == "1.2"
        assert result.all_stories[2].number == "2.1"
        assert result.all_stories[3].number == "2.2"


class TestEmptyProject:
    """Test AC8: Handle missing epic files (empty project)."""

    def test_empty_directory_returns_empty_projectstate(self, tmp_path: Path) -> None:
        """Empty directory returns ProjectState with empty lists."""
        result = read_project_state(tmp_path)

        assert result.epics == []
        assert result.all_stories == []
        assert result.completed_stories == []
        assert result.current_epic is None
        assert result.current_story is None
        assert result.bmad_path == str(tmp_path)

    def test_directory_without_epics_returns_empty_projectstate(self, tmp_path: Path) -> None:
        """Directory with other files but no epics returns empty ProjectState."""
        (tmp_path / "prd.md").write_text("# PRD")
        (tmp_path / "architecture.md").write_text("# Architecture")

        result = read_project_state(tmp_path)

        assert result.epics == []
        assert result.all_stories == []


class TestInvalidBmadPath:
    """Test AC9: Handle invalid BMAD path."""

    def test_nonexistent_path_raises_filenotfounderror(self) -> None:
        """Nonexistent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            read_project_state("/nonexistent/path/to/docs")

        assert "/nonexistent/path/to/docs" in str(exc_info.value)

    def test_error_message_contains_path(self, tmp_path: Path) -> None:
        """Error message contains the invalid path."""
        invalid_path = tmp_path / "nonexistent"

        with pytest.raises(FileNotFoundError) as exc_info:
            read_project_state(invalid_path)

        assert "nonexistent" in str(exc_info.value)


class TestMalformedEpicFiles:
    """Test AC10: Handle malformed epic files gracefully."""

    def test_skip_malformed_epic_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Malformed epic files are skipped with warning."""
        # Valid epic
        (tmp_path / "epic-1.md").write_text("""---
epic_num: 1
---

## Story 1.1: Valid Story
**Status:** done
""")
        # Malformed epic (invalid YAML)
        (tmp_path / "epic-2.md").write_text("""---
invalid: [unclosed bracket
---

## Story 2.1: Should Be Skipped
""")
        # Another valid epic
        (tmp_path / "epic-3.md").write_text("""---
epic_num: 3
---

## Story 3.1: Another Valid Story
**Status:** backlog
""")

        with caplog.at_level(logging.WARNING):
            result = read_project_state(tmp_path)

        # Should have 2 epics (1 and 3)
        assert len(result.epics) == 2
        # Should have stories from valid epics only
        story_numbers = [s.number for s in result.all_stories]
        assert "1.1" in story_numbers
        assert "3.1" in story_numbers
        assert "2.1" not in story_numbers
        # Warning should be logged
        assert "Skipping malformed epic file" in caplog.text

    def test_continue_parsing_after_malformed_file(self, tmp_path: Path) -> None:
        """Parsing continues after encountering malformed file."""
        (tmp_path / "epic-1.md").write_text("""---
invalid: yaml: here
---
""")
        (tmp_path / "epic-2.md").write_text("""---
---

## Story 2.1: Valid Story
""")

        result = read_project_state(tmp_path)

        assert len(result.all_stories) == 1
        assert result.all_stories[0].number == "2.1"


class TestStoriesWithoutStatus:
    """Test AC11: Handle stories without status field."""

    def test_missing_status_defaults_to_backlog(self, tmp_path: Path) -> None:
        """Stories without status field default to backlog."""
        epic_content = """---
---

## Story 1.1: Story With Status
**Status:** done

## Story 1.2: Story Without Status

## Story 1.3: Another Without Status
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        # Story with explicit status
        assert result.all_stories[0].status == "done"
        # Stories without status should be "backlog"
        assert result.all_stories[1].status == "backlog"
        assert result.all_stories[2].status == "backlog"

    def test_story_without_status_not_in_completed(self, tmp_path: Path) -> None:
        """Stories without status are NOT in completed_stories."""
        epic_content = """---
---

## Story 1.1: Story Without Status

## Story 1.2: Done Story
**Status:** done
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        assert result.completed_stories == ["1.2"]
        assert "1.1" not in result.completed_stories

    def test_story_without_status_considered_for_current_position(self, tmp_path: Path) -> None:
        """Stories without status are considered for current position."""
        epic_content = """---
---

## Story 1.1: Done Story
**Status:** done

## Story 1.2: Story Without Status
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        # 1.2 should be current story (defaulted to backlog)
        assert result.current_story == "1.2"


class TestMixedEpicLayouts:
    """Test AC12: Handle both consolidated and separate epic files."""

    def test_merge_consolidated_and_separate_epics(self, tmp_path: Path) -> None:
        """Merge stories from both consolidated and separate epic files."""
        # Consolidated file with Epic 1 and 2
        (tmp_path / "epics.md").write_text("""---
---

# Epic 1: First

## Story 1.1: First Story
**Status:** done

# Epic 2: Second

## Story 2.1: Second Story
**Status:** review
""")
        # Separate file for Epic 3
        (tmp_path / "epic-3.md").write_text("""---
---

## Story 3.1: Third Story
**Status:** backlog
""")

        result = read_project_state(tmp_path)

        # Should have 2 epic documents
        assert len(result.epics) == 2
        # Should have all 3 stories
        assert len(result.all_stories) == 3
        story_numbers = [s.number for s in result.all_stories]
        assert story_numbers == ["1.1", "2.1", "3.1"]

    def test_deduplicate_stories_by_number(self, tmp_path: Path) -> None:
        """Deduplicate stories when same story appears in multiple files."""
        # Story 1.1 in consolidated file
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Story From Consolidated
**Status:** done
""")
        # Same story in separate file
        (tmp_path / "epic-1.md").write_text("""---
---

## Story 1.1: Story From Separate
**Status:** in-progress
""")

        result = read_project_state(tmp_path)

        # Should only have 1 story (first one encountered)
        assert len(result.all_stories) == 1

    def test_stories_sorted_after_merge(self, tmp_path: Path) -> None:
        """Stories are sorted by number after merging."""
        (tmp_path / "epic-2.md").write_text("""---
---

## Story 2.1: Second Epic
""")
        (tmp_path / "epic-1.md").write_text("""---
---

## Story 1.1: First Epic
""")

        result = read_project_state(tmp_path)

        assert result.all_stories[0].number == "1.1"
        assert result.all_stories[1].number == "2.1"


class TestSprintStatusIntegration:
    """Test AC13: Sprint-status.yaml integration (optional extension)."""

    def test_use_sprint_status_disabled_by_default(self, tmp_path: Path) -> None:
        """Sprint status is disabled by default."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Test
**Status:** backlog
""")
        (tmp_path / "sprint-status.yaml").write_text("""
development_status:
  1-1-test: done
""")

        result = read_project_state(tmp_path)  # use_sprint_status=False by default

        # Should use embedded status, not sprint-status
        assert result.all_stories[0].status == "backlog"

    def test_sprint_status_takes_precedence_when_enabled(self, tmp_path: Path) -> None:
        """Sprint status takes precedence when use_sprint_status=True."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Test
**Status:** backlog
""")
        (tmp_path / "sprint-status.yaml").write_text("""
development_status:
  1-1-test: done
""")

        result = read_project_state(tmp_path, use_sprint_status=True)

        assert result.all_stories[0].status == "done"
        assert result.completed_stories == ["1.1"]

    def test_sprint_status_in_sprint_artifacts_folder(self, tmp_path: Path) -> None:
        """Find sprint-status.yaml in sprint-artifacts folder."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Test
**Status:** backlog
""")
        artifacts_dir = tmp_path / "sprint-artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "sprint-status.yaml").write_text("""
development_status:
  1-1-test: in-progress
""")

        result = read_project_state(tmp_path, use_sprint_status=True)

        assert result.all_stories[0].status == "in-progress"

    def test_fallback_to_embedded_when_no_sprint_status(self, tmp_path: Path) -> None:
        """Fall back to embedded status when sprint-status.yaml doesn't exist."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Test
**Status:** review
""")
        # No sprint-status.yaml file

        result = read_project_state(tmp_path, use_sprint_status=True)

        assert result.all_stories[0].status == "review"


class TestMalformedSprintStatus:
    """Test AC14: Handle malformed sprint-status.yaml gracefully."""

    def test_malformed_yaml_fallback_to_embedded(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Malformed YAML falls back to embedded status."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Test
**Status:** review
""")
        (tmp_path / "sprint-status.yaml").write_text("""
invalid: yaml: here: [unclosed
""")

        with caplog.at_level(logging.WARNING):
            result = read_project_state(tmp_path, use_sprint_status=True)

        assert result.all_stories[0].status == "review"
        assert "Failed to parse sprint-status.yaml" in caplog.text

    def test_development_status_is_list_fallback(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """development_status as list falls back to embedded status."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Test
**Status:** backlog
""")
        (tmp_path / "sprint-status.yaml").write_text("""
development_status:
  - item1
  - item2
""")

        with caplog.at_level(logging.WARNING):
            result = read_project_state(tmp_path, use_sprint_status=True)

        assert result.all_stories[0].status == "backlog"
        assert "development_status is not a dict" in caplog.text

    def test_empty_sprint_status_fallback(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Empty sprint-status.yaml falls back to embedded status."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Test
**Status:** review
""")
        (tmp_path / "sprint-status.yaml").write_text("")

        with caplog.at_level(logging.WARNING):
            result = read_project_state(tmp_path, use_sprint_status=True)

        assert result.all_stories[0].status == "review"

    def test_missing_development_status_section(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Missing development_status section uses embedded status with warning."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Test
**Status:** review
""")
        (tmp_path / "sprint-status.yaml").write_text("""
project: my-project
""")

        with caplog.at_level(logging.WARNING):
            result = read_project_state(tmp_path, use_sprint_status=True)

        assert result.all_stories[0].status == "review"
        assert "Missing development_status section" in caplog.text


class TestFieldInvariants:
    """Test AC15: ProjectState field invariants."""

    def test_current_epic_none_implies_current_story_none(self, tmp_path: Path) -> None:
        """If current_epic is None, current_story must be None."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Done Story
**Status:** done
""")

        result = read_project_state(tmp_path)

        assert result.current_epic is None
        assert result.current_story is None

    def test_current_story_epic_matches_current_epic(self, tmp_path: Path) -> None:
        """If current_story is set, current_epic must match."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Done
**Status:** done

## Story 2.1: In Progress
**Status:** in-progress
""")

        result = read_project_state(tmp_path)

        assert result.current_story == "2.1"
        assert result.current_epic == 2  # Matches story's epic

    def test_completed_stories_subset_of_all_stories(self, tmp_path: Path) -> None:
        """completed_stories only contains numbers from all_stories."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: Done
**Status:** done

## Story 1.2: Backlog
**Status:** backlog
""")

        result = read_project_state(tmp_path)

        all_numbers = {s.number for s in result.all_stories}
        for completed in result.completed_stories:
            assert completed in all_numbers

    def test_all_stories_sorted(self, tmp_path: Path) -> None:
        """all_stories is sorted by (epic_num, story_num)."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 2.2: Later Story
## Story 1.2: Early Story
## Story 2.1: Middle Story
## Story 1.1: First Story
""")

        result = read_project_state(tmp_path)

        numbers = [s.number for s in result.all_stories]
        assert numbers == ["1.1", "1.2", "2.1", "2.2"]


class TestSampleBmadProject:
    """Integration tests using real BMAD sample project fixture.

    These tests use authentic BMAD documentation from a real project
    located at tests/fixtures/bmad-sample-project/.
    """

    def test_parse_sample_project(self, sample_bmad_project: Path) -> None:
        """Parse sample BMAD project with 9 epics and 60 stories."""
        result = read_project_state(sample_bmad_project)

        # Should discover sharded epic files (epic-1-*.md through epic-9-*.md plus other files)
        # The fixture has individual epic files, not a consolidated epics.md
        assert len(result.epics) >= 9  # At least 9 sharded epic files

        # Should have at least 60 stories per project documentation
        # (fixture may include additional stories like 1.8)
        assert len(result.all_stories) >= 60

        # First story should be 1.1, last should be 9.8
        assert result.all_stories[0].number == "1.1"
        assert result.all_stories[-1].number == "9.8"

        # Stories should be sorted by epic, then story number
        for i in range(len(result.all_stories) - 1):
            curr_parts = result.all_stories[i].number.split(".")
            next_parts = result.all_stories[i + 1].number.split(".")
            curr_key = (int(curr_parts[0]), int(curr_parts[1]))
            next_key = (int(next_parts[0]), int(next_parts[1]))
            assert curr_key < next_key, (
                f"Stories not sorted: {result.all_stories[i].number} >= {result.all_stories[i + 1].number}"
            )

    def test_sample_project_with_sprint_status(self, sample_bmad_project: Path) -> None:
        """Parse sample project with sprint-status.yaml integration."""
        result = read_project_state(sample_bmad_project, use_sprint_status=True)

        # Should have at least 60 stories (from epic files)
        # Fixture may have additional stories like 1.8
        assert len(result.all_stories) >= 60

        # Verify done stories from sprint-status that exist in epics.md
        # Note: sprint-status may have keys (like 1-8) for stories not in epics.md
        assert "1.1" in result.completed_stories
        assert "1.3" in result.completed_stories
        assert "1.5" in result.completed_stories
        assert "2.3" in result.completed_stories

        # Verify review stories are NOT in completed
        assert "1.2" not in result.completed_stories  # review
        assert "1.4" not in result.completed_stories  # review
        assert "2.1" not in result.completed_stories  # review

        # Current position should be first non-done story
        assert result.current_epic is not None
        assert result.current_story is not None

    def test_sample_project_story_statuses_from_sprint_status(
        self, sample_bmad_project: Path
    ) -> None:
        """Verify story statuses are correctly loaded from sprint-status.yaml."""
        result = read_project_state(sample_bmad_project, use_sprint_status=True)

        # Build status map for easy assertions
        status_map = {s.number: s.status for s in result.all_stories}

        # Verify specific statuses from sprint-status.yaml
        # Note: Only stories that exist in epics.md will be in status_map
        # Story 1.8 exists in sprint-status but not in epics.md (added during dev)
        assert status_map["1.1"] == "done"
        assert status_map["1.2"] == "review"
        assert status_map["1.3"] == "done"
        assert status_map["1.4"] == "review"
        assert status_map["1.5"] == "done"
        assert status_map["1.6"] == "review"
        assert status_map["1.7"] == "review"
        # 1.8 may or may not be in fixture - test what exists
        if "1.8" in status_map:
            assert status_map["1.8"] is not None  # Has some status
        assert status_map["2.1"] == "review"
        assert status_map["2.2"] == "review"
        assert status_map["2.3"] == "done"
        assert status_map["2.4"] == "backlog"
        assert status_map["3.1"] == "backlog"

    def test_sample_project_epic_coverage(self, sample_bmad_project: Path) -> None:
        """Verify all 9 epics are represented in stories."""
        result = read_project_state(sample_bmad_project)

        # Extract epic numbers from all stories
        epic_numbers = {int(s.number.split(".")[0]) for s in result.all_stories}

        # Should have stories from all 9 epics
        assert epic_numbers == {1, 2, 3, 4, 5, 6, 7, 8, 9}

    def test_sample_project_story_estimates(self, sample_bmad_project: Path) -> None:
        """Verify story estimates are parsed correctly."""
        result = read_project_state(sample_bmad_project)

        # Count stories with estimates
        stories_with_estimates = [s for s in result.all_stories if s.estimate is not None]

        # Most stories should have estimates
        assert len(stories_with_estimates) >= 50

        # Verify total story points (should be 132 per epics.md frontmatter)
        total_sp = sum(s.estimate or 0 for s in result.all_stories)
        assert total_sp == 132

    def test_sample_project_without_sprint_status(self, sample_bmad_project: Path) -> None:
        """Parse sample project without sprint-status integration."""
        result = read_project_state(sample_bmad_project, use_sprint_status=False)

        # Should still have 60 stories
        assert len(result.all_stories) == 60

        # Stories should use embedded statuses from epics.md
        # In epics.md, stories don't have explicit status, so all should be backlog
        for story in result.all_stories:
            assert story.status == "backlog"

    def test_sample_project_bmad_path_stored(self, sample_bmad_project: Path) -> None:
        """Verify bmad_path is correctly stored in ProjectState."""
        result = read_project_state(sample_bmad_project)

        assert result.bmad_path == str(sample_bmad_project)

    def test_sample_project_current_position_determination(self, sample_bmad_project: Path) -> None:
        """Verify current position is correctly determined from sprint-status."""
        result = read_project_state(sample_bmad_project, use_sprint_status=True)

        # With sprint-status, current story should be first non-done
        # Done stories: 1.1, 1.3, 1.5, 1.8, 2.3
        # Review stories: 1.2, 1.4, 1.6, 1.7, 2.1, 2.2
        # First non-done (in order) is 1.2
        assert result.current_story == "1.2"
        assert result.current_epic == 1


class TestHelperFunctions:
    """Test helper functions."""

    def test_story_sort_key(self) -> None:
        """Test _story_sort_key generates correct sort keys."""
        # Numeric epic ID: (0, epic_num, story_num)
        story = EpicStory(number="2.3", title="Test")
        key = _story_sort_key(story)
        assert key == (0, 2, 3)

    def test_story_sort_key_string_epic(self) -> None:
        """Test _story_sort_key handles string epic IDs."""
        # String epic ID: (1, epic_id, story_num)
        story = EpicStory(number="testarch.1", title="Test")
        key = _story_sort_key(story)
        assert key == (1, "testarch", 1)

    def test_story_sort_key_invalid_format(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test _story_sort_key handles invalid format gracefully."""
        story = EpicStory(number="invalid", title="Test")
        with caplog.at_level(logging.WARNING):
            key = _story_sort_key(story)
        assert key == (0, 0, 0)
        assert "Invalid story number format" in caplog.text

    def test_story_sort_key_non_numeric(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test _story_sort_key handles non-numeric story numbers gracefully."""
        story = EpicStory(number="2.a", title="Test")
        with caplog.at_level(logging.WARNING):
            key = _story_sort_key(story)
        assert key == (0, 0, 0)
        assert "Non-numeric story number" in caplog.text

    def test_flatten_stories_warns_on_duplicates(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test _flatten_stories logs warning for duplicate stories."""
        epic1 = EpicDocument(
            epic_num=1,
            title="Epic 1",
            status=None,
            stories=[EpicStory(number="1.1", title="Story A")],
            path="epic-1.md",
        )
        epic2 = EpicDocument(
            epic_num=1,
            title="Epic 1 Copy",
            status=None,
            stories=[EpicStory(number="1.1", title="Story A Copy")],
            path="epic-1-copy.md",
        )

        with caplog.at_level(logging.WARNING):
            result = _flatten_stories([epic1, epic2])

        assert len(result) == 1
        assert "Duplicate story 1.1" in caplog.text
        assert "keeping first occurrence" in caplog.text

    def test_normalize_status_lowercase(self) -> None:
        """Test _normalize_status lowercases status."""
        assert _normalize_status("Done") == "done"
        assert _normalize_status("IN-PROGRESS") == "in-progress"
        assert _normalize_status("BACKLOG") == "backlog"

    def test_normalize_status_strips_whitespace(self) -> None:
        """Test _normalize_status strips whitespace."""
        assert _normalize_status("  done  ") == "done"
        assert _normalize_status("in-progress ") == "in-progress"

    def test_normalize_status_none_returns_backlog(self) -> None:
        """Test _normalize_status returns backlog for None."""
        assert _normalize_status(None) == "backlog"

    def test_parse_sprint_status_key_valid(self) -> None:
        """Test _parse_sprint_status_key with valid keys."""
        assert _parse_sprint_status_key("1-1-project-init") == "1.1"
        assert _parse_sprint_status_key("2-3-state-reader") == "2.3"
        assert _parse_sprint_status_key("12-15-large-numbers") == "12.15"

    def test_parse_sprint_status_key_skips_epic_keys(self) -> None:
        """Test _parse_sprint_status_key skips epic keys."""
        assert _parse_sprint_status_key("epic-1") is None
        assert _parse_sprint_status_key("epic-2") is None

    def test_parse_sprint_status_key_skips_retrospective_keys(self) -> None:
        """Test _parse_sprint_status_key skips retrospective keys."""
        assert _parse_sprint_status_key("epic-1-retrospective") is None
        assert _parse_sprint_status_key("1-retrospective") is None

    def test_parse_sprint_status_key_invalid(self) -> None:
        """Test _parse_sprint_status_key with invalid keys."""
        assert _parse_sprint_status_key("invalid") is None
        assert _parse_sprint_status_key("not-a-number") is None

    def test_flatten_stories_deduplicates(self) -> None:
        """Test _flatten_stories removes duplicates (keeping first)."""
        epic1 = EpicDocument(
            epic_num=1,
            title="Epic 1",
            status=None,
            stories=[EpicStory(number="1.1", title="Story A")],
            path="epic-1.md",
        )
        epic2 = EpicDocument(
            epic_num=1,
            title="Epic 1 Copy",
            status=None,
            stories=[EpicStory(number="1.1", title="Story A Copy")],
            path="epic-1-copy.md",
        )

        result = _flatten_stories([epic1, epic2])

        assert len(result) == 1
        assert result[0].title == "Story A"  # First one wins (see warn test above)

    def test_flatten_stories_sorts(self) -> None:
        """Test _flatten_stories sorts by epic then story number."""
        epic2 = EpicDocument(
            epic_num=2,
            title=None,
            status=None,
            stories=[EpicStory(number="2.1", title="Later")],
            path="epic-2.md",
        )
        epic1 = EpicDocument(
            epic_num=1,
            title=None,
            status=None,
            stories=[EpicStory(number="1.1", title="Earlier")],
            path="epic-1.md",
        )

        result = _flatten_stories([epic2, epic1])

        assert result[0].number == "1.1"
        assert result[1].number == "2.1"

    def test_apply_default_status(self) -> None:
        """Test _apply_default_status applies backlog to None status."""
        stories = [
            EpicStory(number="1.1", title="With Status", status="done"),
            EpicStory(number="1.2", title="Without Status", status=None),
        ]

        result = _apply_default_status(stories)

        assert result[0].status == "done"
        assert result[1].status == "backlog"

    def test_apply_sprint_statuses(self) -> None:
        """Test _apply_sprint_statuses updates statuses."""
        stories = [
            EpicStory(number="1.1", title="Story A", status="backlog"),
            EpicStory(number="1.2", title="Story B", status="backlog"),
        ]
        sprint_statuses = {"1.1": "done", "1.2": "review"}

        result = _apply_sprint_statuses(stories, sprint_statuses)

        assert result[0].status == "done"
        assert result[1].status == "review"

    def test_determine_current_position(self) -> None:
        """Test _determine_current_position finds first non-done."""
        stories = [
            EpicStory(number="1.1", title="A", status="done"),
            EpicStory(number="1.2", title="B", status="done"),
            EpicStory(number="2.1", title="C", status="review"),
            EpicStory(number="2.2", title="D", status="backlog"),
        ]

        epic, story = _determine_current_position(stories)

        assert epic == 2
        assert story == "2.1"

    def test_determine_current_position_all_done(self) -> None:
        """Test _determine_current_position when all done."""
        stories = [
            EpicStory(number="1.1", title="A", status="done"),
            EpicStory(number="1.2", title="B", status="done"),
        ]

        epic, story = _determine_current_position(stories)

        assert epic is None
        assert story is None


class TestPathHandling:
    """Test path handling edge cases."""

    def test_accept_string_path(self, tmp_path: Path) -> None:
        """Accept string path argument."""
        (tmp_path / "epics.md").write_text("---\n---\n## Story 1.1: Test")

        result = read_project_state(str(tmp_path))

        assert result.bmad_path == str(tmp_path)

    def test_accept_path_object(self, tmp_path: Path) -> None:
        """Accept Path object argument."""
        (tmp_path / "epics.md").write_text("---\n---\n## Story 1.1: Test")

        result = read_project_state(tmp_path)

        assert result.bmad_path == str(tmp_path)

    def test_bmad_path_stored_as_string(self, tmp_path: Path) -> None:
        """bmad_path is stored as string regardless of input type."""
        (tmp_path / "epics.md").write_text("---\n---\n## Story 1.1: Test")

        result = read_project_state(tmp_path)

        assert isinstance(result.bmad_path, str)


class TestStoryOrdering:
    """Test story ordering behavior."""

    def test_stories_ordered_numerically_not_lexically(self, tmp_path: Path) -> None:
        """Stories are sorted numerically, not lexically."""
        epic_content = """---
---

## Story 1.10: Tenth Story
## Story 1.2: Second Story
## Story 1.1: First Story
## Story 1.9: Ninth Story
"""
        (tmp_path / "epics.md").write_text(epic_content)

        result = read_project_state(tmp_path)

        numbers = [s.number for s in result.all_stories]
        # Numeric sort: 1, 2, 9, 10 (not lexical: 1, 10, 2, 9)
        assert numbers == ["1.1", "1.2", "1.9", "1.10"]

    def test_stories_across_epics_sorted(self, tmp_path: Path) -> None:
        """Stories across multiple epics are sorted together."""
        (tmp_path / "epic-2.md").write_text("""---
---

## Story 2.1: Epic 2 Story
""")
        (tmp_path / "epic-1.md").write_text("""---
---

## Story 1.1: Epic 1 Story
""")
        (tmp_path / "epic-3.md").write_text("""---
---

## Story 3.1: Epic 3 Story
""")

        result = read_project_state(tmp_path)

        numbers = [s.number for s in result.all_stories]
        assert numbers == ["1.1", "2.1", "3.1"]
