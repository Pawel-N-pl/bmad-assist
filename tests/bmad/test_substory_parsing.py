"""Tests for sub-story parsing support.

Verifies that stories with alphanumeric suffixes (3a, 3a-ii, 4b, etc.)
are correctly parsed from epic files and sprint-status.yaml.
"""


from bmad_assist.bmad.parser import STORY_HEADER_PATTERN, EpicDocument, EpicStory
from bmad_assist.bmad.state_reader import (
    _flatten_stories,
    _natural_story_sort_key,
    _parse_sprint_status_key,
)


class TestStoryHeaderPattern:
    """Test STORY_HEADER_PATTERN regex with sub-stories."""

    def test_matches_standard_numeric(self) -> None:
        """Standard numeric stories match."""
        m = STORY_HEADER_PATTERN.search("### Story 10.1: Implement Shell")
        assert m is not None
        assert m.group(1) == "10"
        assert m.group(2) == "1"
        assert m.group(3) == "Implement Shell"

    def test_matches_letter_suffix(self) -> None:
        """Letter-suffixed stories match (3a, 4b)."""
        m = STORY_HEADER_PATTERN.search("### Story 10.3a: Command Registry")
        assert m is not None
        assert m.group(1) == "10"
        assert m.group(2) == "3a"
        assert m.group(3) == "Command Registry"

    def test_matches_hyphenated_suffix(self) -> None:
        """Hyphenated sub-stories match (3a-ii, 3a-iii)."""
        m = STORY_HEADER_PATTERN.search("### Story 10.3a-ii: Tab Completion")
        assert m is not None
        assert m.group(1) == "10"
        assert m.group(2) == "3a-ii"

    def test_matches_triple_hyphenated(self) -> None:
        """Triple-part sub-stories match (3a-iii)."""
        m = STORY_HEADER_PATTERN.search("### Story 10.3a-iii: Slash Commands")
        assert m is not None
        assert m.group(2) == "3a-iii"

    def test_matches_multi_digit(self) -> None:
        """Multi-digit story numbers match (10.10)."""
        m = STORY_HEADER_PATTERN.search("### Story 10.10: Onboarding")
        assert m is not None
        assert m.group(2) == "10"

    def test_matches_various_header_levels(self) -> None:
        """Works with ##, ###, ####."""
        for level in ("##", "###", "####"):
            m = STORY_HEADER_PATTERN.search(f"{level} Story 2.3b: Title")
            assert m is not None, f"Failed for header level {level}"
            assert m.group(2) == "3b"

    def test_matches_all_real_substories(self) -> None:
        """Verify all known sub-story formats from the user's epics.md."""
        cases = [
            ("### Story 1.5a: Initialize Testing", "1", "5a"),
            ("### Story 2.3b: SecureMemFile", "2", "3b"),
            ("### Story 2.3c: Memory Protection", "2", "3c"),
            ("### Story 3.3a: Office365 OAuth", "3", "3a"),
            ("### Story 3.3b: Office365 EWS", "3", "3b"),
            ("### Story 3.3c: Office365 OWA", "3", "3c"),
            ("### Story 4.1a: LLM Runtime", "4", "1a"),
            ("### Story 8.2a: Core Scheduler", "8", "2a"),
            ("### Story 8.2b: Catch-Up", "8", "2b"),
            ("### Story 8.2c: Timezone", "8", "2c"),
            ("### Story 10.3a: Command Registry", "10", "3a"),
            ("### Story 10.3a-ii: Tab Completion", "10", "3a-ii"),
            ("### Story 10.3a-iii: Slash Commands", "10", "3a-iii"),
            ("### Story 10.3b: Inline Confirmation", "10", "3b"),
            ("### Story 10.3c: Feedback Loop", "10", "3c"),
            ("### Story 10.3d: NL Actions", "10", "3d"),
            ("### Story 10.3e: Workflow Rendering", "10", "3e"),
            ("### Story 10.4b: Draft Display", "10", "4b"),
            ("### Story 10.4c: Journal Display", "10", "4c"),
            ("### Story 10.4d: Calendar Display", "10", "4d"),
            ("### Story 11.2a: Auto-Pair IPC", "11", "2a"),
            ("### Story 11.2b: Remote Token", "11", "2b"),
            ("### Story 11.2c: Manual Key", "11", "2c"),
            ("### Story 11.2d: Cross-Signing", "11", "2d"),
            ("### Story 12.1b: Desktop Panes", "12", "1b"),
            ("### Story 12.1c: Desktop Theme", "12", "1c"),
            ("### Story 12.1d: Desktop Integration", "12", "1d"),
        ]
        for header, expected_epic, expected_story in cases:
            m = STORY_HEADER_PATTERN.search(header)
            assert m is not None, f"Failed to match: {header}"
            assert m.group(1) == expected_epic, f"Epic mismatch for {header}"
            assert m.group(2) == expected_story, f"Story mismatch for {header}"

    def test_no_match_for_invalid(self) -> None:
        """Non-story headers don't match."""
        assert STORY_HEADER_PATTERN.search("## Epic 10: TUI") is None
        assert STORY_HEADER_PATTERN.search("# Story 10.1: Title") is None  # single #


class TestNaturalStorySortKey:
    """Test _natural_story_sort_key ordering."""

    def test_pure_numeric_ordering(self) -> None:
        """Pure numeric: 1 < 2 < 10."""
        assert _natural_story_sort_key("1") < _natural_story_sort_key("2")
        assert _natural_story_sort_key("2") < _natural_story_sort_key("10")

    def test_letter_suffix_after_numeric(self) -> None:
        """Letter suffix sorts after base: 3 < 3a < 3b."""
        assert _natural_story_sort_key("3") < _natural_story_sort_key("3a")
        assert _natural_story_sort_key("3a") < _natural_story_sort_key("3b")

    def test_hyphenated_after_base_letter(self) -> None:
        """Hyphenated sorts after base letter: 3a < 3a-ii < 3a-iii."""
        assert _natural_story_sort_key("3a") < _natural_story_sort_key("3a-ii")
        assert _natural_story_sort_key("3a-ii") < _natural_story_sort_key("3a-iii")

    def test_full_ordering(self) -> None:
        """Complete ordering: 3 < 3a < 3a-ii < 3a-iii < 3b < 3c < 4."""
        keys = ["3", "3a", "3a-ii", "3a-iii", "3b", "3c", "4"]
        sorted_keys = sorted(keys, key=_natural_story_sort_key)
        assert sorted_keys == keys

    def test_real_epic10_ordering(self) -> None:
        """Verify ordering of actual epic 10 story parts."""
        parts = [
            "1", "2", "3", "3a", "3a-ii", "3a-iii", "3b", "3c",
            "3d", "3e", "4", "4b", "4c", "4d", "5", "6", "7",
            "8", "9", "10",
        ]
        sorted_parts = sorted(parts, key=_natural_story_sort_key)
        assert sorted_parts == parts


class TestFlattenStoriesWithSubstories:
    """Test _flatten_stories ordering with sub-stories."""

    def test_sorts_substories_correctly(self) -> None:
        """Sub-stories sort in natural order within their epic."""
        epic = EpicDocument(
            epic_num=10,
            title="Epic 10",
            status=None,
            stories=[
                EpicStory(number="10.4b", title="Draft Display"),
                EpicStory(number="10.3", title="Chat Pane"),
                EpicStory(number="10.3a", title="Command Registry"),
                EpicStory(number="10.4", title="Dynamic View"),
                EpicStory(number="10.3a-ii", title="Tab Completion"),
                EpicStory(number="10.1", title="Shell"),
            ],
            path="epic-10.md",
        )
        result = _flatten_stories([epic])
        numbers = [s.number for s in result]
        assert numbers == [
            "10.1", "10.3", "10.3a", "10.3a-ii", "10.4", "10.4b",
        ]


class TestSprintStatusSubstories:
    """Test sprint-status.yaml parsing with sub-stories."""

    def test_parse_all_substory_key_formats(self) -> None:
        """All sprint-status key formats for sub-stories parse correctly."""
        assert _parse_sprint_status_key("10-3a-implement-registry") == "10.3a"
        assert _parse_sprint_status_key("10-3a-ii-implement-tab") == "10.3a-ii"
        assert _parse_sprint_status_key("10-3a-iii-implement-slash") == "10.3a-iii"
        assert _parse_sprint_status_key("2-3b-implement-securememfile") == "2.3b"
        assert _parse_sprint_status_key("8-2c-implement-scheduler") == "8.2c"
        assert _parse_sprint_status_key("1-5a-initialize-testing") == "1.5a"

    def test_numeric_keys_still_work(self) -> None:
        """Standard numeric keys continue to work."""
        assert _parse_sprint_status_key("1-1-project-init") == "1.1"
        assert _parse_sprint_status_key("10-10-implement-onboarding") == "10.10"

    def test_module_epic_keys_work(self) -> None:
        """Module-prefixed keys still parse correctly."""
        assert _parse_sprint_status_key("qs1-security-infrastructure") is None
        # qs1 starts with non-digit so won't match the regex; that's fine
