"""Tests for sharding sorting module."""

from __future__ import annotations

from bmad_assist.bmad.sharding.sorting import EPIC_NUMBER_PATTERN, get_sort_key


class TestEpicNumberPattern:
    """Tests for EPIC_NUMBER_PATTERN regex."""

    def test_matches_simple_epic(self) -> None:
        """Pattern matches simple epic-N.md format."""
        match = EPIC_NUMBER_PATTERN.match("epic-1.md")
        assert match is not None
        assert match.group(1) == "1"

    def test_matches_epic_with_name(self) -> None:
        """Pattern matches epic-N-name.md format."""
        match = EPIC_NUMBER_PATTERN.match("epic-2-integration.md")
        assert match is not None
        assert match.group(1) == "2"

    def test_matches_double_digit_epic(self) -> None:
        """Pattern matches double digit epic numbers."""
        match = EPIC_NUMBER_PATTERN.match("epic-10-final.md")
        assert match is not None
        assert match.group(1) == "10"

    def test_no_match_for_non_epic(self) -> None:
        """Pattern doesn't match non-epic files."""
        match = EPIC_NUMBER_PATTERN.match("index.md")
        assert match is None

    def test_no_match_for_architecture(self) -> None:
        """Pattern doesn't match architecture files."""
        match = EPIC_NUMBER_PATTERN.match("core-decisions.md")
        assert match is None


class TestGetSortKey:
    """Tests for get_sort_key function."""

    # --- Index.md handling ---
    # Note: index.md is excluded from content loading but the sort key
    # function still handles it for completeness

    def test_index_has_lowest_sort_key_for_epics(self) -> None:
        """Index.md has lowest sort key for epics (for reference)."""
        key = get_sort_key("epics", "index.md")
        assert key == (0, "")

    def test_index_has_lowest_sort_key_for_architecture(self) -> None:
        """Index.md has lowest sort key for architecture (for reference)."""
        key = get_sort_key("architecture", "index.md")
        assert key == (0, "")

    def test_index_has_lowest_sort_key_for_prd(self) -> None:
        """Index.md has lowest sort key for prd (for reference)."""
        key = get_sort_key("prd", "index.md")
        assert key == (0, "")

    def test_index_has_lowest_sort_key_for_ux(self) -> None:
        """Index.md has lowest sort key for ux (for reference)."""
        key = get_sort_key("ux", "index.md")
        assert key == (0, "")

    # --- Epic numeric sorting ---

    def test_epic_numeric_single_digit(self) -> None:
        """Epic files sorted by numeric value - single digit."""
        key = get_sort_key("epics", "epic-1-foundation.md")
        assert key == (1, 1)

    def test_epic_numeric_double_digit(self) -> None:
        """Epic files sorted by numeric value - double digit."""
        key = get_sort_key("epics", "epic-10-final.md")
        assert key == (1, 10)

    def test_epic_numeric_order(self) -> None:
        """Epic files sort correctly: 1, 2, 10 (not 1, 10, 2)."""
        keys = [
            get_sort_key("epics", "epic-10-final.md"),
            get_sort_key("epics", "epic-1-foundation.md"),
            get_sort_key("epics", "epic-2-integration.md"),
        ]
        sorted_keys = sorted(keys)
        # Verify correct numeric order: 1, 2, 10
        assert sorted_keys[0] == (1, 1)  # epic-1
        assert sorted_keys[1] == (1, 2)  # epic-2
        assert sorted_keys[2] == (1, 10)  # epic-10

    def test_epic_non_matching_files_last(self) -> None:
        """Non-matching files in epic directory sorted last."""
        key = get_sort_key("epics", "random-file.md")
        assert key[0] == 2  # Priority 2 = last
        assert key[1] == "random-file.md"

    # --- Architecture alphabetic sorting ---

    def test_architecture_alphabetic(self) -> None:
        """Architecture files sorted alphabetically."""
        key = get_sort_key("architecture", "core-decisions.md")
        assert key == (1, "core-decisions.md")

    def test_architecture_case_insensitive(self) -> None:
        """Architecture sorting is case-insensitive."""
        key1 = get_sort_key("architecture", "Core-Decisions.md")
        key2 = get_sort_key("architecture", "core-decisions.md")
        # Both should sort the same (lowercase)
        assert key1[1] == key2[1]

    def test_architecture_sort_order(self) -> None:
        """Architecture files sort alphabetically."""
        keys = [
            get_sort_key("architecture", "zebra.md"),
            get_sort_key("architecture", "alpha.md"),
            get_sort_key("architecture", "beta.md"),
        ]
        sorted_keys = sorted(keys)
        assert sorted_keys[0][1] == "alpha.md"
        assert sorted_keys[1][1] == "beta.md"
        assert sorted_keys[2][1] == "zebra.md"

    # --- PRD alphabetic sorting ---

    def test_prd_alphabetic(self) -> None:
        """PRD files sorted alphabetically."""
        key = get_sort_key("prd", "requirements.md")
        assert key == (1, "requirements.md")

    # --- UX alphabetic sorting ---

    def test_ux_alphabetic(self) -> None:
        """UX files sorted alphabetically."""
        key = get_sort_key("ux", "wireframes.md")
        assert key == (1, "wireframes.md")

    # --- Mixed sorting scenarios ---

    def test_index_before_any_content(self) -> None:
        """Index.md sorts before any content file."""
        index_key = get_sort_key("architecture", "index.md")
        content_key = get_sort_key("architecture", "aaa-first.md")
        assert index_key < content_key

    def test_epic_index_before_epic_files(self) -> None:
        """Index.md sorts before epic files even with low number."""
        index_key = get_sort_key("epics", "index.md")
        epic_key = get_sort_key("epics", "epic-0-prelude.md")
        assert index_key < epic_key
