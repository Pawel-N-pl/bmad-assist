"""Tests for State Discrepancy Detection (Story 2.4).

Tests cover all acceptance criteria:

Story 2.4 - State Discrepancy Detection:
- AC1: Detect story status discrepancy
- AC2: Detect current story position discrepancy
- AC3: Detect current epic position discrepancy
- AC4: Detect completed stories list discrepancy
- AC5: Return Discrepancy dataclass
- AC6: Return empty list when states match
- AC7: Handle internal state with no current position
- AC8: Handle BMAD state with no stories
- AC9: Detect multiple discrepancies
- AC10: Handle story not in BMAD files
- AC11: Handle story not in internal state
"""

import logging
from pathlib import Path

import pytest

from bmad_assist.bmad.discrepancy import (
    Discrepancy,
    _build_story_status_map,
    detect_discrepancies,
)
from bmad_assist.bmad.state_reader import read_project_state

# Import shared MockInternalState from conftest
from tests.bmad.conftest import MockInternalState


class TestDiscrepancyDataclass:
    """Test AC5: Discrepancy dataclass structure."""

    def test_discrepancy_has_required_fields(self) -> None:
        """Discrepancy dataclass has all required fields."""
        d = Discrepancy(
            type="story_status_mismatch",
            expected="in-progress",
            actual="done",
            story_number="2.3",
            file_path="/path/to/epic-2.md",
            description="Story 2.3 status mismatch",
        )

        assert d.type == "story_status_mismatch"
        assert d.expected == "in-progress"
        assert d.actual == "done"
        assert d.story_number == "2.3"
        assert d.file_path == "/path/to/epic-2.md"
        assert d.description == "Story 2.3 status mismatch"

    def test_discrepancy_optional_fields_default_to_none(self) -> None:
        """Discrepancy optional fields default to None."""
        d = Discrepancy(
            type="current_epic_mismatch",
            expected=2,
            actual=3,
        )

        assert d.story_number is None
        assert d.file_path is None
        assert d.description == ""

    def test_discrepancy_str_with_description(self) -> None:
        """Discrepancy __str__ returns description when present."""
        d = Discrepancy(
            type="test_type",
            expected="a",
            actual="b",
            description="Human readable description",
        )

        assert str(d) == "Human readable description"

    def test_discrepancy_str_without_description(self) -> None:
        """Discrepancy __str__ returns formatted string when no description."""
        d = Discrepancy(
            type="test_type",
            expected="a",
            actual="b",
        )

        assert str(d) == "test_type: expected=a, actual=b"

    def test_discrepancy_any_type_for_expected_actual(self) -> None:
        """Discrepancy expected/actual can hold Any type."""
        # Lists
        d1 = Discrepancy(
            type="completed_stories_mismatch",
            expected=["1.1", "1.2"],
            actual=["1.1", "1.2", "1.3"],
        )
        assert d1.expected == ["1.1", "1.2"]
        assert d1.actual == ["1.1", "1.2", "1.3"]

        # Integers
        d2 = Discrepancy(type="current_epic_mismatch", expected=2, actual=3)
        assert d2.expected == 2
        assert d2.actual == 3

        # None
        d3 = Discrepancy(type="story_not_in_bmad", expected="2.6", actual=None)
        assert d3.expected == "2.6"
        assert d3.actual is None


class TestStateComparableProtocol:
    """Test StateComparable Protocol compliance (Story 2.4 AC5)."""

    def test_mock_internal_state_satisfies_protocol(self) -> None:
        """MockInternalState satisfies StateComparable protocol."""
        state = MockInternalState()

        # Verify all required attributes exist
        assert hasattr(state, "current_epic")
        assert hasattr(state, "current_story")
        assert hasattr(state, "completed_stories")

        # Verify types
        assert isinstance(state.current_epic, int) or state.current_epic is None
        assert isinstance(state.current_story, str) or state.current_story is None
        assert isinstance(state.completed_stories, list)

    def test_protocol_with_none_values(self) -> None:
        """StateComparable works with None values."""
        state = MockInternalState(
            current_epic=None,
            current_story=None,
            completed_stories=[],
        )

        assert state.current_epic is None
        assert state.current_story is None
        assert state.completed_stories == []


class TestDetectDiscrepanciesBasic:
    """Test AC1-AC4: Basic discrepancy detection."""

    def test_ac1_story_status_mismatch(self, tmp_path: Path) -> None:
        """AC1: Detect story status mismatch."""
        # Internal state says story 2.3 is "in-progress" (current_story)
        # BMAD shows story 2.3 as "done"
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: First
**Status:** done

## Story 1.2: Second
**Status:** done

## Story 2.3: Third
**Status:** done
""")
        internal = MockInternalState(
            current_epic=2,
            current_story="2.3",
            completed_stories=["1.1", "1.2"],
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        # Should detect story status mismatch
        status_mismatches = [d for d in result if d.type == "story_status_mismatch"]
        assert len(status_mismatches) >= 1

        mismatch = status_mismatches[0]
        assert mismatch.story_number == "2.3"
        assert mismatch.expected == "in-progress"
        assert mismatch.actual == "done"
        assert mismatch.file_path is not None
        assert "2.3" in mismatch.description

    def test_ac2_current_story_mismatch(self, tmp_path: Path) -> None:
        """AC2: Detect current story position mismatch."""
        # Internal: current_story="2.3"
        # BMAD: 2.3 and 2.4 are done, so current would be 2.5
        (tmp_path / "epics.md").write_text("""---
---

## Story 2.3: Story 3
**Status:** done

## Story 2.4: Story 4
**Status:** done

## Story 2.5: Story 5
**Status:** backlog
""")
        internal = MockInternalState(
            current_epic=2,
            current_story="2.3",
            completed_stories=[],
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        story_mismatches = [d for d in result if d.type == "current_story_mismatch"]
        assert len(story_mismatches) == 1

        mismatch = story_mismatches[0]
        assert mismatch.expected == "2.3"
        assert mismatch.actual == "2.5"
        assert "2.3" in mismatch.description
        assert "2.5" in mismatch.description

    def test_ac3_current_epic_mismatch(self, tmp_path: Path) -> None:
        """AC3: Detect current epic position mismatch."""
        # Internal: current_epic=2
        # BMAD: all epic 2 stories done, current is epic 3
        (tmp_path / "epics.md").write_text("""---
---

## Story 2.1: Epic 2 Story
**Status:** done

## Story 3.1: Epic 3 Story
**Status:** backlog
""")
        internal = MockInternalState(
            current_epic=2,
            current_story="2.1",
            completed_stories=[],
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        epic_mismatches = [d for d in result if d.type == "current_epic_mismatch"]
        assert len(epic_mismatches) == 1

        mismatch = epic_mismatches[0]
        assert mismatch.expected == 2
        assert mismatch.actual == 3
        assert "internal=2" in mismatch.description
        assert "bmad=3" in mismatch.description

    def test_ac4_completed_stories_mismatch(self, tmp_path: Path) -> None:
        """AC4: Detect completed stories list mismatch."""
        # Internal: completed=["1.1", "1.2"]
        # BMAD: completed=["1.1", "1.2", "1.3"]
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: First
**Status:** done

## Story 1.2: Second
**Status:** done

## Story 1.3: Third
**Status:** done

## Story 2.1: Current
**Status:** backlog
""")
        internal = MockInternalState(
            current_epic=2,
            current_story="2.1",
            completed_stories=["1.1", "1.2"],
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        completed_mismatches = [d for d in result if d.type == "completed_stories_mismatch"]
        assert len(completed_mismatches) == 1

        mismatch = completed_mismatches[0]
        assert mismatch.expected == ["1.1", "1.2"]
        assert mismatch.actual == ["1.1", "1.2", "1.3"]
        assert mismatch.story_number is None
        assert mismatch.file_path is None
        assert "missing_from_internal" in mismatch.description
        assert "1.3" in mismatch.description

    def test_ac4_order_independent_comparison(self, tmp_path: Path) -> None:
        """AC4: Completed stories comparison is order-independent."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: First
**Status:** done

## Story 1.2: Second
**Status:** done

## Story 2.1: Current
**Status:** backlog
""")
        # Internal has same stories but in different order
        internal = MockInternalState(
            current_epic=2,
            current_story="2.1",
            completed_stories=["1.2", "1.1"],  # Reverse order
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        # Should NOT have completed_stories_mismatch (same content, different order)
        completed_mismatches = [d for d in result if d.type == "completed_stories_mismatch"]
        assert len(completed_mismatches) == 0


class TestDetectDiscrepanciesEdgeCases:
    """Test AC6-AC11: Edge cases."""

    def test_ac6_matching_states_returns_empty_list(self, tmp_path: Path) -> None:
        """AC6: Return empty list when states match exactly."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: First
**Status:** done

## Story 1.2: Second
**Status:** done

## Story 2.3: Current
**Status:** in-progress
""")
        # Internal state matches BMAD exactly
        internal = MockInternalState(
            current_epic=2,
            current_story="2.3",
            completed_stories=["1.1", "1.2"],
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        assert result == []

    def test_ac7_internal_state_with_none_positions(self, tmp_path: Path) -> None:
        """AC7: Handle internal state with None current positions."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: First
**Status:** done

## Story 1.2: Second
**Status:** backlog
""")
        # Internal has None positions
        internal = MockInternalState(
            current_epic=None,
            current_story=None,
            completed_stories=[],
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        # Should detect mismatches without errors
        assert isinstance(result, list)
        epic_mismatches = [d for d in result if d.type == "current_epic_mismatch"]
        story_mismatches = [d for d in result if d.type == "current_story_mismatch"]
        assert len(epic_mismatches) == 1  # None vs 1
        assert len(story_mismatches) == 1  # None vs "1.1"

    def test_ac8_empty_bmad_state(self, tmp_path: Path) -> None:
        """AC8: Handle BMAD state with no stories (empty project)."""
        # Empty directory - no epic files
        internal = MockInternalState(
            current_epic=2,
            current_story="2.3",
            completed_stories=["1.1", "1.2"],
        )
        bmad_state = read_project_state(tmp_path)  # Empty project

        result = detect_discrepancies(internal, bmad_state)

        # Should detect bmad_empty discrepancy
        bmad_empty = [d for d in result if d.type == "bmad_empty"]
        assert len(bmad_empty) == 1

        d = bmad_empty[0]
        assert d.expected == ["1.1", "1.2"]
        assert d.actual == []
        assert d.story_number is None
        assert d.file_path is None
        assert "no stories" in d.description.lower()
        assert "2" in d.description  # mentions count of internal stories

    def test_ac9_multiple_discrepancies(self, tmp_path: Path) -> None:
        """AC9: Detect and return all discrepancies, not just first."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: First
**Status:** done

## Story 1.2: Second
**Status:** done

## Story 1.3: Third
**Status:** done

## Story 3.1: Different Epic
**Status:** backlog
""")
        # Multiple mismatches
        internal = MockInternalState(
            current_epic=2,  # Mismatch: BMAD has 3
            current_story="2.5",  # Mismatch: BMAD has 3.1
            completed_stories=["1.1"],  # Mismatch: BMAD has 1.1, 1.2, 1.3
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        # Should have multiple discrepancies
        assert len(result) >= 3  # Epic, story, completed list, plus possibly more

        # Verify ordering by type, then story_number
        types = [d.type for d in result]
        assert types == sorted(types)

    def test_ac9_discrepancies_sorted_by_type_then_story(self, tmp_path: Path) -> None:
        """AC9: Discrepancies are ordered by type, then story_number."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: First
**Status:** review

## Story 1.2: Second
**Status:** review

## Story 2.1: Third
**Status:** backlog
""")
        internal = MockInternalState(
            current_epic=2,
            current_story="2.1",
            completed_stories=["1.2", "1.1"],  # Both marked done in internal
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        # Extract story status mismatches
        status_mismatches = [d for d in result if d.type == "story_status_mismatch"]

        # Should be sorted by story_number
        story_numbers = [d.story_number for d in status_mismatches]
        assert story_numbers == sorted(story_numbers)

    def test_ac10_story_not_in_bmad(self, tmp_path: Path) -> None:
        """AC10: Detect story in internal state but not in BMAD files."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 2.1: First
**Status:** backlog

## Story 2.5: Last
**Status:** backlog
""")
        # Internal tracks story 2.6 which doesn't exist in BMAD
        internal = MockInternalState(
            current_epic=2,
            current_story="2.6",  # Not in BMAD
            completed_stories=["2.1"],
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        not_in_bmad = [d for d in result if d.type == "story_not_in_bmad"]
        assert len(not_in_bmad) >= 1

        d = not_in_bmad[0]
        assert d.expected == "2.6"
        assert d.actual is None
        assert d.story_number == "2.6"
        assert d.file_path is None
        assert "2.6" in d.description
        assert "not found in BMAD" in d.description

    def test_ac11_story_not_in_internal(self, tmp_path: Path) -> None:
        """AC11: Detect story in BMAD files but not in internal state."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 2.1: First
**Status:** done

## Story 2.6: New Story
**Status:** done
""")
        # Internal doesn't track story 2.6
        internal = MockInternalState(
            current_epic=2,
            current_story="2.1",
            completed_stories=[],
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        not_in_internal = [d for d in result if d.type == "story_not_in_internal"]
        assert len(not_in_internal) >= 1

        # Find the 2.6 discrepancy specifically
        d_2_6 = next((d for d in not_in_internal if d.story_number == "2.6"), None)
        assert d_2_6 is not None
        assert d_2_6.expected is None
        assert d_2_6.actual == "2.6"
        assert d_2_6.file_path is not None  # Should have file path
        assert "2.6" in d_2_6.description
        assert "not tracked" in d_2_6.description

    def test_ac11_story_not_in_internal_any_status(self, tmp_path: Path) -> None:
        """AC11: Detect ALL stories in BMAD not tracked, regardless of status."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 2.1: First
**Status:** done

## Story 2.6: New Backlog Story
**Status:** backlog

## Story 2.7: New In-Progress Story
**Status:** in-progress
""")
        # Internal only tracks 2.1
        internal = MockInternalState(
            current_epic=2,
            current_story="2.1",
            completed_stories=[],
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)

        not_in_internal = [d for d in result if d.type == "story_not_in_internal"]

        # Should flag BOTH 2.6 (backlog) and 2.7 (in-progress), not just done stories
        story_nums = {d.story_number for d in not_in_internal}
        assert "2.6" in story_nums, "Should flag backlog story not tracked"
        assert "2.7" in story_nums, "Should flag in-progress story not tracked"

        # Verify description includes status
        d_2_6 = next(d for d in not_in_internal if d.story_number == "2.6")
        assert "backlog" in d_2_6.description
        d_2_7 = next(d for d in not_in_internal if d.story_number == "2.7")
        assert "in-progress" in d_2_7.description


class TestDetectDiscrepanciesTypeError:
    """Test TypeError handling for None inputs."""

    def test_none_internal_state_raises_typeerror(self, tmp_path: Path) -> None:
        """TypeError raised when internal_state is None."""
        (tmp_path / "epics.md").write_text("---\n---\n## Story 1.1: Test")
        bmad_state = read_project_state(tmp_path)

        with pytest.raises(TypeError) as exc_info:
            detect_discrepancies(None, bmad_state)  # type: ignore[arg-type]

        assert "internal_state must not be None" in str(exc_info.value)

    def test_none_bmad_state_raises_typeerror(self) -> None:
        """TypeError raised when bmad_state is None."""
        internal = MockInternalState()

        with pytest.raises(TypeError) as exc_info:
            detect_discrepancies(internal, None)  # type: ignore[arg-type]

        assert "bmad_state must not be None" in str(exc_info.value)


class TestDetectDiscrepanciesLogging:
    """Test logging behavior in detect_discrepancies."""

    def test_logs_comparison_info(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Logs info about comparison counts."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: First
**Status:** done

## Story 1.2: Second
**Status:** done
""")
        internal = MockInternalState(
            current_epic=1,
            current_story="1.2",
            completed_stories=["1.1"],
        )
        bmad_state = read_project_state(tmp_path)

        with caplog.at_level(logging.INFO):
            detect_discrepancies(internal, bmad_state)

        assert "Comparing" in caplog.text
        assert "internal stories" in caplog.text
        assert "BMAD stories" in caplog.text


class TestBuildStoryStatusMap:
    """Test _build_story_status_map helper function."""

    def test_builds_correct_map(self, tmp_path: Path) -> None:
        """_build_story_status_map builds correct status map."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: First
**Status:** done

## Story 1.2: Second
**Status:** review
""")
        state = read_project_state(tmp_path)

        result = _build_story_status_map(state)

        assert "1.1" in result
        assert "1.2" in result
        assert result["1.1"][0] == "done"
        assert result["1.2"][0] == "review"
        # File paths should be present
        assert result["1.1"][1] is not None
        assert result["1.2"][1] is not None

    def test_empty_state_returns_empty_map(self, tmp_path: Path) -> None:
        """_build_story_status_map returns empty map for empty state."""
        state = read_project_state(tmp_path)  # Empty project

        result = _build_story_status_map(state)

        assert result == {}


class TestDiscrepancyDescriptionFormats:
    """Test that discrepancy descriptions follow standard templates."""

    def test_current_epic_mismatch_description_format(self, tmp_path: Path) -> None:
        """current_epic_mismatch follows template format."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 3.1: Story
**Status:** backlog
""")
        internal = MockInternalState(current_epic=2, current_story="2.1")
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)
        d = next((x for x in result if x.type == "current_epic_mismatch"), None)

        assert d is not None
        assert "Current epic mismatch:" in d.description
        assert "internal=2" in d.description
        assert "bmad=3" in d.description

    def test_current_story_mismatch_description_format(self, tmp_path: Path) -> None:
        """current_story_mismatch follows template format."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 2.5: Story
**Status:** backlog
""")
        internal = MockInternalState(current_epic=2, current_story="2.3")
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)
        d = next((x for x in result if x.type == "current_story_mismatch"), None)

        assert d is not None
        assert "Current story mismatch:" in d.description
        assert "internal=2.3" in d.description
        assert "bmad=2.5" in d.description

    def test_completed_stories_mismatch_description_format(self, tmp_path: Path) -> None:
        """completed_stories_mismatch follows template format."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 1.1: First
**Status:** done

## Story 1.3: Third
**Status:** done

## Story 2.1: Current
**Status:** backlog
""")
        internal = MockInternalState(
            current_epic=2,
            current_story="2.1",
            completed_stories=["1.1", "1.2"],
        )
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)
        d = next((x for x in result if x.type == "completed_stories_mismatch"), None)

        assert d is not None
        assert "Completed stories mismatch:" in d.description
        assert "missing_from_internal=" in d.description
        assert "missing_from_bmad=" in d.description

    def test_story_status_mismatch_description_format(self, tmp_path: Path) -> None:
        """story_status_mismatch follows template format."""
        (tmp_path / "epics.md").write_text("""---
---

## Story 2.3: Story
**Status:** review
""")
        internal = MockInternalState(
            current_epic=2,
            current_story="2.3",
            completed_stories=[],
        )
        # Mark 2.3 as done in internal (via completed_stories for this test)
        internal.completed_stories = ["2.3"]
        internal.current_story = None
        bmad_state = read_project_state(tmp_path)

        result = detect_discrepancies(internal, bmad_state)
        d = next((x for x in result if x.type == "story_status_mismatch"), None)

        assert d is not None
        assert "Story 2.3 status mismatch:" in d.description
        assert "internal=" in d.description
        assert "bmad=" in d.description


class TestDiscrepancyIntegration:
    """Integration tests for discrepancy detection."""

    def test_full_workflow_with_sample_project(self, sample_bmad_project: Path) -> None:
        """Full workflow test using sample BMAD project."""
        bmad_state = read_project_state(sample_bmad_project, use_sprint_status=True)

        # Create internal state that matches - must include ALL stories from BMAD
        # to avoid story_not_in_internal discrepancies (AC11 flags ALL untracked stories)
        all_story_numbers = [s.number for s in bmad_state.all_stories]
        internal = MockInternalState(
            current_epic=bmad_state.current_epic,
            current_story=bmad_state.current_story,
            # Include all stories: completed + current + all others
            completed_stories=bmad_state.completed_stories.copy(),
        )
        # For a perfect match, internal must track all BMAD stories
        # completed_stories + current_story should cover all stories
        # But since MockInternalState only tracks completed + current,
        # we need to check only for the discrepancies we care about

        result = detect_discrepancies(internal, bmad_state)

        # With AC11 fix, any BMAD story not tracked by internal state is flagged
        # Since internal only tracks completed_stories + current_story, we expect
        # story_not_in_internal for all other (backlog/review) stories
        # This is correct behavior per AC11 - filter out story_not_in_internal
        # and verify no OTHER discrepancies exist
        other_discrepancies = [d for d in result if d.type != "story_not_in_internal"]
        assert other_discrepancies == [], f"Unexpected discrepancies: {other_discrepancies}"

    def test_full_workflow_with_mismatched_state(self, sample_bmad_project: Path) -> None:
        """Full workflow with intentional mismatches."""
        bmad_state = read_project_state(sample_bmad_project, use_sprint_status=True)

        # Create internal state with intentional mismatches
        internal = MockInternalState(
            current_epic=9,  # Different epic
            current_story="9.1",  # Different story
            completed_stories=["1.1"],  # Fewer completed
        )

        result = detect_discrepancies(internal, bmad_state)

        # Should detect multiple discrepancies
        assert len(result) > 0

        # Verify types are present
        types = {d.type for d in result}
        assert "current_epic_mismatch" in types or "current_story_mismatch" in types
