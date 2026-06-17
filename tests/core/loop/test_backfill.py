"""Tests for backfill mode gap detection and story ordering.

Tests verify that detect_backfill_stories correctly identifies missed
stories across epics, respects sprint-status exclusions, and returns
them in natural sort order.
"""

from bmad_assist.core.loop.backfill import detect_backfill_stories


def _loader(stories_by_epic: dict) -> callable:
    """Create a mock epic_stories_loader from a dict."""
    def loader(epic_id):
        return stories_by_epic.get(epic_id, [])
    return loader


class TestDetectBackfillStories:
    """Test gap detection logic."""

    def test_no_gaps_when_all_completed(self) -> None:
        """No gaps if all stories before frontier are completed."""
        stories = {10: ["10.1", "10.2", "10.3"]}
        gaps = detect_backfill_stories(
            completed_stories=["10.1", "10.2"],
            current_story="10.3",
            epic_list=[10],
            epic_stories_loader=_loader(stories),
        )
        assert gaps == []

    def test_detects_simple_gap(self) -> None:
        """Detects a story that was skipped."""
        stories = {10: ["10.1", "10.2", "10.3", "10.4"]}
        gaps = detect_backfill_stories(
            completed_stories=["10.1", "10.3"],
            current_story="10.4",
            epic_list=[10],
            epic_stories_loader=_loader(stories),
        )
        assert gaps == ["10.2"]

    def test_detects_substory_gaps(self) -> None:
        """Detects sub-stories that were never seen."""
        stories = {10: ["10.1", "10.2", "10.3", "10.3a", "10.3b", "10.4"]}
        gaps = detect_backfill_stories(
            completed_stories=["10.1", "10.2", "10.3"],
            current_story="10.4",
            epic_list=[10],
            epic_stories_loader=_loader(stories),
        )
        assert gaps == ["10.3a", "10.3b"]

    def test_detects_cross_epic_gaps(self) -> None:
        """Detects gaps from earlier epics."""
        stories = {
            1: ["1.1", "1.2", "1.5a"],
            4: ["4.1", "4.1a"],
            10: ["10.1", "10.2"],
        }
        gaps = detect_backfill_stories(
            completed_stories=["1.1", "1.2", "4.1", "10.1"],
            current_story="10.2",
            epic_list=[1, 4, 10],
            epic_stories_loader=_loader(stories),
        )
        assert gaps == ["1.5a", "4.1a"]

    def test_excludes_done_in_sprint_status(self) -> None:
        """Stories marked done in sprint-status are not backfilled."""
        stories = {2: ["2.1", "2.3b", "2.3c"]}
        gaps = detect_backfill_stories(
            completed_stories=["2.1"],
            current_story="2.3c",
            epic_list=[2],
            epic_stories_loader=_loader(stories),
            sprint_statuses={"2.3b": "done"},
        )
        assert gaps == []  # 2.3b is done in sprint-status

    def test_excludes_deferred_in_sprint_status(self) -> None:
        """Stories marked deferred are intentionally skipped."""
        stories = {4: ["4.1", "4.1a", "4.2"]}
        gaps = detect_backfill_stories(
            completed_stories=["4.1"],
            current_story="4.2",
            epic_list=[4],
            epic_stories_loader=_loader(stories),
            sprint_statuses={"4.1a": "deferred"},
        )
        assert gaps == []

    def test_includes_backlog_in_sprint_status(self) -> None:
        """Stories with backlog status ARE backfilled."""
        stories = {8: ["8.1", "8.2a", "8.2b", "8.3"]}
        gaps = detect_backfill_stories(
            completed_stories=["8.1"],
            current_story="8.3",
            epic_list=[8],
            epic_stories_loader=_loader(stories),
            sprint_statuses={"8.2a": "backlog", "8.2b": "backlog"},
        )
        assert gaps == ["8.2a", "8.2b"]

    def test_stories_after_frontier_excluded(self) -> None:
        """Stories after the current position are NOT included."""
        stories = {10: ["10.1", "10.2", "10.3", "10.4", "10.5"]}
        gaps = detect_backfill_stories(
            completed_stories=["10.1", "10.2"],
            current_story="10.3",
            epic_list=[10],
            epic_stories_loader=_loader(stories),
        )
        # 10.4 and 10.5 come after frontier, must not be included
        assert gaps == []

    def test_real_world_scenario(self) -> None:
        """Simulate the user's actual state with epics 1-10."""
        stories = {
            1: ["1.1", "1.2", "1.3", "1.4", "1.5", "1.5a", "1.6", "1.7"],
            4: ["4.1", "4.1a", "4.2", "4.3", "4.4", "4.5"],
            8: ["8.1", "8.2", "8.2a", "8.2b", "8.2c", "8.3", "8.4", "8.5", "8.6"],
            10: [
                "10.1", "10.2", "10.3", "10.3a", "10.3a-ii", "10.3a-iii",
                "10.3b", "10.3c", "10.3d", "10.3e",
                "10.4", "10.4b", "10.4c", "10.4d",
                "10.5", "10.6", "10.7",
            ],
        }
        completed = [
            "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7",
            "4.1", "4.2", "4.3", "4.4", "4.5",
            "8.1", "8.2", "8.3", "8.4", "8.5", "8.6",
            "10.1", "10.2", "10.3", "10.4", "10.5", "10.6",
        ]
        gaps = detect_backfill_stories(
            completed_stories=completed,
            current_story="10.6",
            epic_list=[1, 4, 8, 10],
            epic_stories_loader=_loader(stories),
        )
        assert gaps == [
            "1.5a",
            "4.1a",
            "8.2a", "8.2b", "8.2c",
            "10.3a", "10.3a-ii", "10.3a-iii",
            "10.3b", "10.3c", "10.3d", "10.3e",
            "10.4b", "10.4c", "10.4d",
        ]

    def test_natural_sort_order(self) -> None:
        """Gap stories are returned in natural sort order."""
        stories = {10: [
            "10.1", "10.3a-ii", "10.3", "10.3a", "10.3b", "10.4",
        ]}
        gaps = detect_backfill_stories(
            completed_stories=["10.1"],
            current_story="10.4",
            epic_list=[10],
            epic_stories_loader=_loader(stories),
        )
        assert gaps == ["10.3", "10.3a", "10.3a-ii", "10.3b"]

    def test_empty_epic_list(self) -> None:
        """No crash with empty epic list."""
        gaps = detect_backfill_stories(
            completed_stories=[],
            current_story="1.1",
            epic_list=[],
            epic_stories_loader=_loader({}),
        )
        assert gaps == []

    def test_excludes_cancelled_and_skipped(self) -> None:
        """Stories with cancelled or skipped status are excluded."""
        stories = {5: ["5.1", "5.2", "5.3"]}
        gaps = detect_backfill_stories(
            completed_stories=[],
            current_story="5.3",
            epic_list=[5],
            epic_stories_loader=_loader(stories),
            sprint_statuses={"5.1": "cancelled", "5.2": "skipped"},
        )
        assert gaps == []

    def test_frontier_stays_fixed_across_backfill_completions(self) -> None:
        """Gaps are always relative to the original frontier, not the last backfill story."""
        stories = {
            1: ["1.1", "1.5a"],
            10: ["10.1", "10.3a", "10.3b", "10.6"],
        }
        frontier = "10.6"
        completed = ["1.1", "10.1", "10.6"]

        # First call: 3 gaps detected
        gaps1 = detect_backfill_stories(
            completed_stories=completed,
            current_story=frontier,
            epic_list=[1, 10],
            epic_stories_loader=_loader(stories),
        )
        assert gaps1 == ["1.5a", "10.3a", "10.3b"]

        # After completing 1.5a, frontier stays at 10.6
        completed.append("1.5a")
        gaps2 = detect_backfill_stories(
            completed_stories=completed,
            current_story=frontier,  # Same frontier!
            epic_list=[1, 10],
            epic_stories_loader=_loader(stories),
        )
        assert gaps2 == ["10.3a", "10.3b"]

        # After completing all gaps, empty
        completed.extend(["10.3a", "10.3b"])
        gaps3 = detect_backfill_stories(
            completed_stories=completed,
            current_story=frontier,
            epic_list=[1, 10],
            epic_stories_loader=_loader(stories),
        )
        assert gaps3 == []
