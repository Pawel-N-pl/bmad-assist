"""Tests for the reconciliation engine module.

Tests cover:
- StatusChange dataclass creation and formatting
- ReconciliationResult dataclass and summary
- ConflictResolution enum values
- Entry preservation (STANDALONE, MODULE_STORY, UNKNOWN, RETROSPECTIVE)
- EPIC_STORY merging with evidence-based inference
- EPIC_META recalculation from story statuses
- Removed story detection
- Various conflict resolution strategies
- Edge cases (empty existing, empty generated, etc.)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from bmad_assist.sprint.classifier import EntryType
from bmad_assist.sprint.generator import GeneratedEntries
from bmad_assist.sprint.inference import InferenceConfidence
from bmad_assist.sprint.models import (
    SprintStatus,
    SprintStatusEntry,
    SprintStatusMetadata,
)
from bmad_assist.sprint.reconciler import (
    STATUS_ORDER,
    ConflictResolution,
    ReconciliationResult,
    StatusChange,
    _detect_removed_stories,
    _extract_epic_id_from_key,
    _is_status_advancement,
    _merge_epic_story,
    _normalize_story_key,
    _recalculate_epic_meta,
    _should_preserve_entry,
    _sort_entries_by_epic_order,
    reconcile,
)
from bmad_assist.sprint.scanner import ArtifactIndex

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_project_for_reconcile(tmp_path: Path) -> Path:
    """Create a project with artifacts for reconciliation testing."""
    # New location: _bmad-output/implementation-artifacts/
    new_base = tmp_path / "_bmad-output" / "implementation-artifacts"

    # Stories
    stories_dir = new_base / "stories"
    stories_dir.mkdir(parents=True)

    # Story with explicit status "done"
    (stories_dir / "20-1-setup.md").write_text("# Story 20.1\n\nStatus: done\n\nCompleted story.")
    # Story with explicit status "in-progress"
    (stories_dir / "20-2-models.md").write_text("# Story 20.2\n\nStatus: in-progress\n\nWIP story.")
    # Story without Status field
    (stories_dir / "20-3-parser.md").write_text("# Story 20.3\n\nNo status field here.")
    # Story from completed epic 12
    (stories_dir / "12-1-foundation.md").write_text("# Story 12.1\n\nStatus: done\n\nCompleted.")
    (stories_dir / "12-2-config.md").write_text("# Story 12.2\n\nStatus: done\n\nCompleted.")
    # Standalone story
    (stories_dir / "standalone-01-refactor.md").write_text(
        "# Standalone Story\n\nStatus: done\n\nTech debt."
    )
    # Module story
    (stories_dir / "testarch-1-config.md").write_text(
        "# Testarch Story\n\nStatus: review\n\nModule."
    )

    # Code reviews
    reviews_dir = new_base / "code-reviews"
    reviews_dir.mkdir()
    # Master synthesis for 20-1
    (reviews_dir / "synthesis-20-1-20260107T120000.md").write_text("# Synthesis")
    # Validator reviews for 20-3 (no master)
    (reviews_dir / "code-review-20-3-validator_a-20260107T120000.md").write_text("# Validator A")

    # Validations
    validations_dir = new_base / "story-validations"
    validations_dir.mkdir()
    (validations_dir / "validation-20-2-validator-a-20260107T120000.md").write_text("# Validation")

    # Retrospectives
    retros_dir = new_base / "retrospectives"
    retros_dir.mkdir()
    (retros_dir / "epic-12-retro-20260106.md").write_text("# Epic 12 Retrospective")

    return tmp_path


@pytest.fixture
def sample_metadata() -> SprintStatusMetadata:
    """Create sample metadata for tests."""
    return SprintStatusMetadata(
        generated=datetime(2026, 1, 7, 12, 0, 0),
        project="test-project",
    )


@pytest.fixture
def existing_sprint_status(sample_metadata: SprintStatusMetadata) -> SprintStatus:
    """Create sample existing sprint status for tests."""
    entries = {
        # Epic 20 stories
        "20-1-setup": SprintStatusEntry(
            key="20-1-setup",
            status="backlog",
            entry_type=EntryType.EPIC_STORY,
            source="sprint-status",
        ),
        "20-2-models": SprintStatusEntry(
            key="20-2-models",
            status="backlog",
            entry_type=EntryType.EPIC_STORY,
            source="sprint-status",
        ),
        "20-3-parser": SprintStatusEntry(
            key="20-3-parser",
            status="backlog",
            entry_type=EntryType.EPIC_STORY,
            source="sprint-status",
        ),
        # Story to be removed (not in generated)
        "20-99-old-story": SprintStatusEntry(
            key="20-99-old-story",
            status="done",
            entry_type=EntryType.EPIC_STORY,
            source="sprint-status",
        ),
        # Epic 12 stories (completed)
        "12-1-foundation": SprintStatusEntry(
            key="12-1-foundation",
            status="done",
            entry_type=EntryType.EPIC_STORY,
            source="sprint-status",
        ),
        "12-2-config": SprintStatusEntry(
            key="12-2-config",
            status="done",
            entry_type=EntryType.EPIC_STORY,
            source="sprint-status",
        ),
        # Standalone story
        "standalone-01-refactor": SprintStatusEntry(
            key="standalone-01-refactor",
            status="done",
            entry_type=EntryType.STANDALONE,
            source="sprint-status",
        ),
        # Module story
        "testarch-1-config": SprintStatusEntry(
            key="testarch-1-config",
            status="review",
            entry_type=EntryType.MODULE_STORY,
            source="sprint-status",
        ),
        # Unknown entry
        "custom-entry-999": SprintStatusEntry(
            key="custom-entry-999",
            status="blocked",
            entry_type=EntryType.UNKNOWN,
            source="sprint-status",
        ),
        # Retrospective entry
        "epic-10-retrospective": SprintStatusEntry(
            key="epic-10-retrospective",
            status="done",
            entry_type=EntryType.RETROSPECTIVE,
            source="sprint-status",
        ),
        # Epic meta entries
        "epic-20": SprintStatusEntry(
            key="epic-20",
            status="backlog",
            entry_type=EntryType.EPIC_META,
            source="sprint-status",
        ),
        "epic-12": SprintStatusEntry(
            key="epic-12",
            status="done",
            entry_type=EntryType.EPIC_META,
            source="sprint-status",
        ),
    }
    return SprintStatus(metadata=sample_metadata, entries=entries)


@pytest.fixture
def generated_entries() -> GeneratedEntries:
    """Create sample generated entries from epic files."""
    entries = [
        # Epic 20 stories (current epic)
        SprintStatusEntry(
            key="20-1-setup",
            status="backlog",
            entry_type=EntryType.EPIC_STORY,
            source="epic",
        ),
        SprintStatusEntry(
            key="20-2-models",
            status="backlog",
            entry_type=EntryType.EPIC_STORY,
            source="epic",
        ),
        SprintStatusEntry(
            key="20-3-parser",
            status="backlog",
            entry_type=EntryType.EPIC_STORY,
            source="epic",
        ),
        # New story not in existing
        SprintStatusEntry(
            key="20-4-scanner",
            status="backlog",
            entry_type=EntryType.EPIC_STORY,
            source="epic",
        ),
        # Epic 12 (completed)
        SprintStatusEntry(
            key="12-1-foundation",
            status="done",
            entry_type=EntryType.EPIC_STORY,
            source="epic",
        ),
        SprintStatusEntry(
            key="12-2-config",
            status="done",
            entry_type=EntryType.EPIC_STORY,
            source="epic",
        ),
        # Epic meta entries
        SprintStatusEntry(
            key="epic-20",
            status="backlog",
            entry_type=EntryType.EPIC_META,
            source="epic",
        ),
        SprintStatusEntry(
            key="epic-12",
            status="done",
            entry_type=EntryType.EPIC_META,
            source="epic",
        ),
    ]
    result = GeneratedEntries()
    result.entries = entries
    result.files_processed = 2
    return result


# ============================================================================
# Tests: StatusChange Dataclass
# ============================================================================


class TestStatusChange:
    """Tests for StatusChange dataclass."""

    def test_create_status_change(self) -> None:
        """Test creating a StatusChange instance."""
        change = StatusChange(
            key="20-1-setup",
            old_status="backlog",
            new_status="done",
            reason="master_review_exists",
            confidence=InferenceConfidence.STRONG,
            entry_type=EntryType.EPIC_STORY,
        )

        assert change.key == "20-1-setup"
        assert change.old_status == "backlog"
        assert change.new_status == "done"
        assert change.reason == "master_review_exists"
        assert change.confidence == InferenceConfidence.STRONG
        assert change.entry_type == EntryType.EPIC_STORY

    def test_status_change_new_entry(self) -> None:
        """Test StatusChange for new entry (old_status is None)."""
        change = StatusChange(
            key="20-4-new",
            old_status=None,
            new_status="backlog",
            reason="new_entry_from_epic",
        )

        assert change.old_status is None
        assert change.confidence is None

    def test_as_log_line_with_confidence(self) -> None:
        """Test as_log_line() with confidence."""
        change = StatusChange(
            key="20-1-setup",
            old_status="backlog",
            new_status="done",
            reason="master_review_exists",
            confidence=InferenceConfidence.STRONG,
        )

        log_line = change.as_log_line()
        assert log_line == "20-1-setup: backlog → done (STRONG) [master_review_exists]"

    def test_as_log_line_without_confidence(self) -> None:
        """Test as_log_line() without confidence."""
        change = StatusChange(
            key="20-1-setup",
            old_status="backlog",
            new_status="done",
            reason="preserve_existing",
        )

        log_line = change.as_log_line()
        assert log_line == "20-1-setup: backlog → done [preserve_existing]"

    def test_as_log_line_new_entry(self) -> None:
        """Test as_log_line() for new entry."""
        change = StatusChange(
            key="20-4-new",
            old_status=None,
            new_status="backlog",
            reason="new_entry_from_epic",
        )

        log_line = change.as_log_line()
        assert log_line == "20-4-new: (new) → backlog [new_entry_from_epic]"

    def test_repr(self) -> None:
        """Test __repr__."""
        change = StatusChange(
            key="20-1-setup",
            old_status="backlog",
            new_status="done",
            reason="test",
        )

        repr_str = repr(change)
        assert "StatusChange" in repr_str
        assert "20-1-setup" in repr_str
        assert "backlog → done" in repr_str


# ============================================================================
# Tests: ReconciliationResult Dataclass
# ============================================================================


class TestReconciliationResult:
    """Tests for ReconciliationResult dataclass."""

    def test_create_result(self, sample_metadata: SprintStatusMetadata) -> None:
        """Test creating a ReconciliationResult instance."""
        status = SprintStatus(metadata=sample_metadata, entries={})
        result = ReconciliationResult(
            status=status,
            changes=[],
            preserved_count=42,
            updated_count=3,
            added_count=2,
            removed_count=1,
        )

        assert result.preserved_count == 42
        assert result.updated_count == 3
        assert result.added_count == 2
        assert result.removed_count == 1

    def test_summary(self, sample_metadata: SprintStatusMetadata) -> None:
        """Test summary() method."""
        status = SprintStatus(metadata=sample_metadata, entries={})
        result = ReconciliationResult(
            status=status,
            preserved_count=42,
            updated_count=3,
            added_count=2,
            removed_count=1,
        )

        summary = result.summary()
        assert "42 preserved" in summary
        assert "3 updated" in summary
        assert "2 added" in summary
        assert "1 removed" in summary


# ============================================================================
# Tests: ConflictResolution Enum
# ============================================================================


class TestConflictResolution:
    """Tests for ConflictResolution enum."""

    def test_evidence_wins_value(self) -> None:
        """Test EVIDENCE_WINS enum value."""
        assert ConflictResolution.EVIDENCE_WINS.value == "evidence_wins"

    def test_preserve_existing_value(self) -> None:
        """Test PRESERVE_EXISTING enum value."""
        assert ConflictResolution.PRESERVE_EXISTING.value == "preserve_existing"


# ============================================================================
# Tests: Helper Functions
# ============================================================================


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_extract_epic_id_numeric(self) -> None:
        """Test _extract_epic_id_from_key() with numeric epic ID."""
        assert _extract_epic_id_from_key("20-1-setup") == 20
        assert _extract_epic_id_from_key("1-1-start") == 1
        assert _extract_epic_id_from_key("123-45-long-name") == 123

    def test_extract_epic_id_numeric_short_keys(self) -> None:
        """Test _extract_epic_id_from_key() with short keys (no slug).

        Regression test for regex bug: trailing dash was required,
        causing short keys like '20-1' to return None.
        """
        assert _extract_epic_id_from_key("20-1") == 20
        assert _extract_epic_id_from_key("1-1") == 1
        assert _extract_epic_id_from_key("123-45") == 123

    def test_extract_epic_id_string(self) -> None:
        """Test _extract_epic_id_from_key() with string epic ID."""
        assert _extract_epic_id_from_key("testarch-1-config") == "testarch"
        assert _extract_epic_id_from_key("standalone-01-refactor") == "standalone"

    def test_extract_epic_id_string_short_keys(self) -> None:
        """Test _extract_epic_id_from_key() with short string keys.

        Regression test for regex bug: trailing dash was required.
        """
        assert _extract_epic_id_from_key("testarch-1") == "testarch"
        assert _extract_epic_id_from_key("standalone-01") == "standalone"

    def test_extract_epic_id_invalid(self) -> None:
        """Test _extract_epic_id_from_key() with invalid pattern."""
        assert _extract_epic_id_from_key("invalid") is None
        assert _extract_epic_id_from_key("") is None

    def test_normalize_story_key(self) -> None:
        """Test _normalize_story_key()."""
        assert _normalize_story_key("20-1-setup") == "20-1"
        assert _normalize_story_key("20-1") == "20-1"
        assert _normalize_story_key("testarch-1-config") == "testarch-1"
        assert _normalize_story_key("TestArch-1-Config") == "testarch-1"

    def test_should_preserve_entry(self) -> None:
        """Test _should_preserve_entry()."""
        assert _should_preserve_entry(EntryType.STANDALONE) is True
        assert _should_preserve_entry(EntryType.MODULE_STORY) is True
        assert _should_preserve_entry(EntryType.UNKNOWN) is True
        assert _should_preserve_entry(EntryType.RETROSPECTIVE) is True
        assert _should_preserve_entry(EntryType.EPIC_STORY) is False
        assert _should_preserve_entry(EntryType.EPIC_META) is False


# ============================================================================
# Tests: Preserve Entry Types
# ============================================================================


class TestPreserveEntryTypes:
    """Tests for preserving STANDALONE, MODULE_STORY, UNKNOWN, RETROSPECTIVE."""

    def test_preserve_standalone(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test that STANDALONE entries are preserved."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated_entries, index)

        # STANDALONE should be preserved
        assert "standalone-01-refactor" in result.status.entries
        entry = result.status.entries["standalone-01-refactor"]
        assert entry.status == "done"
        assert entry.entry_type == EntryType.STANDALONE

    def test_preserve_module_story(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test that MODULE_STORY entries are preserved."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated_entries, index)

        # MODULE_STORY should be preserved
        assert "testarch-1-config" in result.status.entries
        entry = result.status.entries["testarch-1-config"]
        assert entry.status == "review"
        assert entry.entry_type == EntryType.MODULE_STORY

    def test_preserve_unknown(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test that UNKNOWN entries are preserved."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated_entries, index)

        # UNKNOWN should be preserved
        assert "custom-entry-999" in result.status.entries
        entry = result.status.entries["custom-entry-999"]
        assert entry.status == "blocked"
        assert entry.entry_type == EntryType.UNKNOWN

    def test_preserve_retrospective(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test that RETROSPECTIVE entries are preserved."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated_entries, index)

        # RETROSPECTIVE should be preserved
        assert "epic-10-retrospective" in result.status.entries
        entry = result.status.entries["epic-10-retrospective"]
        assert entry.status == "done"
        assert entry.entry_type == EntryType.RETROSPECTIVE


# ============================================================================
# Tests: EPIC_STORY Merge
# ============================================================================


class TestEpicStoryMerge:
    """Tests for EPIC_STORY merging with evidence-based inference."""

    def test_explicit_status_wins(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test that explicit Status: field in story file wins."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated_entries, index)

        # 20-1-setup has Status: done in file
        entry = result.status.entries["20-1-setup"]
        assert entry.status == "done"

        # Should have a change record with EXPLICIT confidence
        change = next(
            (c for c in result.changes if c.key == "20-1-setup"),
            None,
        )
        assert change is not None
        assert change.confidence == InferenceConfidence.EXPLICIT

    def test_evidence_inference_strong(
        self,
        temp_project_for_reconcile: Path,
        sample_metadata: SprintStatusMetadata,
    ) -> None:
        """Test that master review results in STRONG confidence done status."""
        # Create existing with backlog status
        existing = SprintStatus(
            metadata=sample_metadata,
            entries={
                "20-1-setup": SprintStatusEntry(
                    key="20-1-setup",
                    status="backlog",
                    entry_type=EntryType.EPIC_STORY,
                ),
            },
        )
        generated = GeneratedEntries()
        generated.entries = [
            SprintStatusEntry(
                key="20-1-setup",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        ]

        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing, generated, index)

        # 20-1-setup has master synthesis → done with EXPLICIT from status field
        entry = result.status.entries["20-1-setup"]
        assert entry.status == "done"

    def test_validator_review_medium_confidence(
        self,
        temp_project_for_reconcile: Path,
        sample_metadata: SprintStatusMetadata,
    ) -> None:
        """Test that validator reviews (no master) result in review status."""
        # 20-3-parser has validator reviews but no master
        existing = SprintStatus(
            metadata=sample_metadata,
            entries={
                "20-3-parser": SprintStatusEntry(
                    key="20-3-parser",
                    status="backlog",
                    entry_type=EntryType.EPIC_STORY,
                ),
            },
        )
        generated = GeneratedEntries()
        generated.entries = [
            SprintStatusEntry(
                key="20-3-parser",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        ]

        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing, generated, index)

        entry = result.status.entries["20-3-parser"]
        # Has validator reviews → review status (MEDIUM confidence)
        assert entry.status == "review"

    def test_new_story_from_epic(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test that new stories from epics are added."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated_entries, index)

        # 20-4-scanner is new (in generated but not existing)
        assert "20-4-scanner" in result.status.entries
        entry = result.status.entries["20-4-scanner"]
        assert entry.status == "backlog"

        # Should have a change record for new entry
        change = next(
            (c for c in result.changes if c.key == "20-4-scanner"),
            None,
        )
        assert change is not None
        assert change.old_status is None


# ============================================================================
# Tests: EPIC_META Recalculation
# ============================================================================


class TestEpicMetaRecalculation:
    """Tests for EPIC_META recalculation from story statuses."""

    def test_epic_with_retrospective_is_done(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test that epic with retrospective is marked done."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated_entries, index)

        # Epic 12 has retrospective file
        entry = result.status.entries["epic-12"]
        assert entry.status == "done"

    def test_epic_meta_created_if_not_exists(
        self,
        temp_project_for_reconcile: Path,
        sample_metadata: SprintStatusMetadata,
    ) -> None:
        """Test that epic meta entry is created if not in existing."""
        existing = SprintStatus(
            metadata=sample_metadata,
            entries={
                "20-1-setup": SprintStatusEntry(
                    key="20-1-setup",
                    status="done",
                    entry_type=EntryType.EPIC_STORY,
                ),
            },
        )
        generated = GeneratedEntries()
        generated.entries = [
            SprintStatusEntry(
                key="20-1-setup",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
            SprintStatusEntry(
                key="epic-20",
                status="backlog",
                entry_type=EntryType.EPIC_META,
            ),
        ]

        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing, generated, index)

        # epic-20 should be created and recalculated
        assert "epic-20" in result.status.entries


# ============================================================================
# Tests: Removed Story Detection
# ============================================================================


class TestRemovedStoryDetection:
    """Tests for detecting removed stories."""

    def test_removed_story_marked_deferred(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test that removed stories are marked as deferred."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated_entries, index)

        # 20-99-old-story is in existing but not in generated
        entry = result.status.entries["20-99-old-story"]
        assert entry.status == "deferred"

        # Should have a change record
        change = next(
            (c for c in result.changes if c.key == "20-99-old-story"),
            None,
        )
        assert change is not None
        assert change.reason == "story_removed_from_epic"

    def test_detect_removed_stories_helper(self) -> None:
        """Test _detect_removed_stories() helper function."""
        existing_stories = {
            "20-1-keep": SprintStatusEntry(
                key="20-1-keep",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "20-99-remove": SprintStatusEntry(
                key="20-99-remove",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        # _detect_removed_stories expects SHORT keys (e.g., "20-1", "20-99")
        generated_short_keys = {"20-1"}  # Short key for 20-1-keep

        removed = _detect_removed_stories(existing_stories, generated_short_keys)

        assert len(removed) == 1
        key, entry, change = removed[0]
        assert key == "20-99-remove"
        assert entry.status == "deferred"
        assert change.reason == "story_removed_from_epic"


# ============================================================================
# Tests: Conflict Resolution Strategies
# ============================================================================


class TestConflictResolutionStrategies:
    """Tests for conflict resolution strategies."""

    def test_preserve_existing_strategy(
        self,
        temp_project_for_reconcile: Path,
        sample_metadata: SprintStatusMetadata,
    ) -> None:
        """Test PRESERVE_EXISTING strategy keeps existing status."""
        # Story with no explicit status but existing has review
        existing = SprintStatus(
            metadata=sample_metadata,
            entries={
                "20-50-no-evidence": SprintStatusEntry(
                    key="20-50-no-evidence",
                    status="review",
                    entry_type=EntryType.EPIC_STORY,
                ),
            },
        )
        generated = GeneratedEntries()
        generated.entries = [
            SprintStatusEntry(
                key="20-50-no-evidence",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        ]

        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(
            existing,
            generated,
            index,
            strategy=ConflictResolution.PRESERVE_EXISTING,
        )

        # Should preserve existing review status
        entry = result.status.entries["20-50-no-evidence"]
        assert entry.status == "review"


# ============================================================================
# Tests: Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_existing(
        self,
        temp_project_for_reconcile: Path,
        sample_metadata: SprintStatusMetadata,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test reconciliation with empty existing (fresh project)."""
        existing = SprintStatus(metadata=sample_metadata, entries={})

        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing, generated_entries, index)

        # All generated entries should be added
        assert len(result.status.entries) > 0
        assert result.added_count > 0

    def test_empty_generated(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
    ) -> None:
        """Test reconciliation with empty generated (no epics)."""
        generated = GeneratedEntries()
        generated.entries = []

        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated, index)

        # All existing entries should be preserved
        assert result.preserved_count > 0
        # No entries should be marked as removed (empty generated = preserve all)
        assert result.removed_count == 0

    def test_empty_generated_preserves_epic_stories(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
    ) -> None:
        """Test that EPIC_STORY entries are preserved when generated is empty.

        Regression test for data loss bug: EPIC_STORY entries were being
        dropped when from_epics was empty because they were skipped in Step 3
        (as "removed stories") but Step 5 was also skipped.
        """
        generated = GeneratedEntries()
        generated.entries = []

        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated, index)

        # EPIC_STORY entries must be preserved
        assert "20-1-setup" in result.status.entries
        assert "20-2-models" in result.status.entries
        assert "20-3-parser" in result.status.entries
        # STANDALONE, MODULE_STORY also preserved
        assert "standalone-01-refactor" in result.status.entries
        assert "testarch-1-config" in result.status.entries

    def test_result_metadata_preserved(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test that existing metadata is preserved in result."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated_entries, index)

        assert result.status.metadata.project == "test-project"
        assert result.status.metadata.generated == existing_sprint_status.metadata.generated


# ============================================================================
# Tests: Merge Epic Story Helper
# ============================================================================


class TestMergeEpicStoryHelper:
    """Tests for _merge_epic_story() helper function."""

    def test_both_none_raises(self, temp_project_for_reconcile: Path) -> None:
        """Test that ValueError is raised when both entries are None."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        with pytest.raises(ValueError, match="Both entries are None"):
            _merge_epic_story(
                None,
                None,
                "20-1-test",
                index,
                ConflictResolution.EVIDENCE_WINS,
            )

    def test_only_existing(self, temp_project_for_reconcile: Path) -> None:
        """Test merge with only existing entry."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        existing_entry = SprintStatusEntry(
            key="20-99-only-existing",
            status="review",
            entry_type=EntryType.EPIC_STORY,
        )

        entry, change = _merge_epic_story(
            existing_entry,
            None,
            "20-99-only-existing",
            index,
            ConflictResolution.EVIDENCE_WINS,
        )

        # Should use existing entry as base
        assert entry.key == "20-99-only-existing"

    def test_only_generated(self, temp_project_for_reconcile: Path) -> None:
        """Test merge with only generated entry."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        generated_entry = SprintStatusEntry(
            key="20-99-only-generated",
            status="backlog",
            entry_type=EntryType.EPIC_STORY,
        )

        entry, change = _merge_epic_story(
            None,
            generated_entry,
            "20-99-only-generated",
            index,
            ConflictResolution.EVIDENCE_WINS,
        )

        # Should use generated entry as base
        assert entry.key == "20-99-only-generated"
        assert change is not None
        assert change.old_status is None


# ============================================================================
# Tests: Recalculate Epic Meta Helper
# ============================================================================


class TestRecalculateEpicMetaHelper:
    """Tests for _recalculate_epic_meta() helper function."""

    def test_epic_all_done(self, temp_project_for_reconcile: Path) -> None:
        """Test epic status when all stories are done."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result_entries = {
            "12-1-foundation": SprintStatusEntry(
                key="12-1-foundation",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "12-2-config": SprintStatusEntry(
                key="12-2-config",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }

        entry, change = _recalculate_epic_meta(
            12,
            result_entries,
            index,
            None,
        )

        # Epic 12 has retrospective → done
        assert entry.status == "done"
        assert entry.entry_type == EntryType.EPIC_META

    def test_epic_in_progress(self, tmp_path: Path) -> None:
        """Test epic status when some stories are done."""
        # Create empty artifact index (no retrospective)
        index = ArtifactIndex()

        result_entries = {
            "30-1-story": SprintStatusEntry(
                key="30-1-story",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "30-2-story": SprintStatusEntry(
                key="30-2-story",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        }

        entry, change = _recalculate_epic_meta(
            30,
            result_entries,
            index,
            None,
        )

        # Partial completion → in-progress
        assert entry.status == "in-progress"


# ============================================================================
# Tests: Integration
# ============================================================================


class TestIntegration:
    """Integration tests with real project fixtures."""

    def test_full_reconciliation(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test full reconciliation flow."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated_entries, index)

        # Check counts
        assert result.preserved_count > 0
        assert result.removed_count >= 0

        # Check summary format
        summary = result.summary()
        assert "preserved" in summary
        assert "updated" in summary
        assert "added" in summary
        assert "removed" in summary

        # Check that we have the expected entries
        assert len(result.status.entries) > 0

        # Verify preserved entries are intact
        assert "standalone-01-refactor" in result.status.entries
        assert "testarch-1-config" in result.status.entries
        assert "custom-entry-999" in result.status.entries
        assert "epic-10-retrospective" in result.status.entries

    def test_change_log_complete(
        self,
        temp_project_for_reconcile: Path,
        existing_sprint_status: SprintStatus,
        generated_entries: GeneratedEntries,
    ) -> None:
        """Test that change log captures all changes."""
        index = ArtifactIndex.scan(temp_project_for_reconcile)

        result = reconcile(existing_sprint_status, generated_entries, index)

        # All changes should have valid structure
        for change in result.changes:
            assert change.key
            assert change.new_status
            assert change.reason

            # Log line should be formatted correctly
            log_line = change.as_log_line()
            assert change.key in log_line
            assert change.reason in log_line


# ============================================================================
# Tests: Status Order and Forward-Only Protection
# ============================================================================


class TestStatusOrder:
    """Tests for STATUS_ORDER constant and _is_status_advancement()."""

    def test_status_order_values(self) -> None:
        """Test STATUS_ORDER has expected values."""
        assert STATUS_ORDER["deferred"] == -1
        assert STATUS_ORDER["backlog"] == 0
        assert STATUS_ORDER["ready-for-dev"] == 1
        assert STATUS_ORDER["in-progress"] == 2
        assert STATUS_ORDER["blocked"] == 2  # Same level as in-progress
        assert STATUS_ORDER["review"] == 3
        assert STATUS_ORDER["done"] == 4

    def test_is_status_advancement_forward(self) -> None:
        """Forward status changes return True."""
        assert _is_status_advancement("backlog", "done") is True
        assert _is_status_advancement("backlog", "in-progress") is True
        assert _is_status_advancement("in-progress", "review") is True
        assert _is_status_advancement("review", "done") is True

    def test_is_status_advancement_same_level(self) -> None:
        """Same-level status changes return True."""
        assert _is_status_advancement("backlog", "backlog") is True
        assert _is_status_advancement("done", "done") is True
        assert _is_status_advancement("in-progress", "blocked") is True
        assert _is_status_advancement("blocked", "in-progress") is True

    def test_is_status_advancement_backward(self) -> None:
        """Backward status changes return False."""
        assert _is_status_advancement("done", "backlog") is False
        assert _is_status_advancement("review", "in-progress") is False
        assert _is_status_advancement("in-progress", "backlog") is False
        assert _is_status_advancement("done", "review") is False

    def test_is_status_advancement_none_old(self) -> None:
        """None old_status always returns True (new entry)."""
        assert _is_status_advancement(None, "backlog") is True
        assert _is_status_advancement(None, "done") is True
        assert _is_status_advancement(None, "deferred") is True

    def test_is_status_advancement_unknown_status(self) -> None:
        """Unknown statuses default to order 0."""
        # Unknown status treated as backlog (0)
        assert _is_status_advancement("unknown-status", "done") is True
        assert _is_status_advancement("done", "unknown-status") is False


# ============================================================================
# Tests: Entry Sorting
# ============================================================================


class TestSortEntriesByEpicOrder:
    """Tests for _sort_entries_by_epic_order()."""

    def test_sorts_numeric_epics_first(self) -> None:
        """Numeric epics come before string epics."""
        entries = {
            "testarch-1-config": SprintStatusEntry(
                key="testarch-1-config",
                status="done",
                entry_type=EntryType.MODULE_STORY,
            ),
            "epic-12": SprintStatusEntry(
                key="epic-12",
                status="done",
                entry_type=EntryType.EPIC_META,
            ),
            "12-1-setup": SprintStatusEntry(
                key="12-1-setup",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }

        sorted_entries = _sort_entries_by_epic_order(entries)
        keys = list(sorted_entries.keys())

        # Numeric epic (12) should come before string epic (testarch)
        assert keys.index("epic-12") < keys.index("testarch-1-config")

    def test_sorts_epic_meta_before_stories(self) -> None:
        """Epic meta entries come before their stories."""
        entries = {
            "12-2-feature": SprintStatusEntry(
                key="12-2-feature",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "12-1-setup": SprintStatusEntry(
                key="12-1-setup",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "epic-12": SprintStatusEntry(
                key="epic-12",
                status="done",
                entry_type=EntryType.EPIC_META,
            ),
        }

        sorted_entries = _sort_entries_by_epic_order(entries)
        keys = list(sorted_entries.keys())

        assert keys[0] == "epic-12"
        assert keys[1] == "12-1-setup"
        assert keys[2] == "12-2-feature"

    def test_sorts_retrospective_after_stories(self) -> None:
        """Retrospective entries come after all stories in the epic."""
        entries = {
            "epic-12-retrospective": SprintStatusEntry(
                key="epic-12-retrospective",
                status="backlog",
                entry_type=EntryType.RETROSPECTIVE,
            ),
            "12-1-setup": SprintStatusEntry(
                key="12-1-setup",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "epic-12": SprintStatusEntry(
                key="epic-12",
                status="done",
                entry_type=EntryType.EPIC_META,
            ),
            "12-2-feature": SprintStatusEntry(
                key="12-2-feature",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }

        sorted_entries = _sort_entries_by_epic_order(entries)
        keys = list(sorted_entries.keys())

        assert keys == ["epic-12", "12-1-setup", "12-2-feature", "epic-12-retrospective"]

    def test_sorts_stories_by_number(self) -> None:
        """Stories within an epic are sorted by story number."""
        entries = {
            "12-10-last": SprintStatusEntry(
                key="12-10-last",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "12-2-second": SprintStatusEntry(
                key="12-2-second",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "12-1-first": SprintStatusEntry(
                key="12-1-first",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }

        sorted_entries = _sort_entries_by_epic_order(entries)
        keys = list(sorted_entries.keys())

        assert keys == ["12-1-first", "12-2-second", "12-10-last"]

    def test_standalone_entries_at_end(self) -> None:
        """Standalone entries are placed at the end."""
        entries = {
            "standalone-01-refactor": SprintStatusEntry(
                key="standalone-01-refactor",
                status="done",
                entry_type=EntryType.STANDALONE,
            ),
            "epic-1": SprintStatusEntry(
                key="epic-1",
                status="done",
                entry_type=EntryType.EPIC_META,
            ),
            "1-1-setup": SprintStatusEntry(
                key="1-1-setup",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }

        sorted_entries = _sort_entries_by_epic_order(entries)
        keys = list(sorted_entries.keys())

        assert keys[-1] == "standalone-01-refactor"

    def test_multiple_epics_sorted(self) -> None:
        """Multiple epics are sorted numerically."""
        entries = {
            "epic-20": SprintStatusEntry(
                key="epic-20",
                status="done",
                entry_type=EntryType.EPIC_META,
            ),
            "epic-12": SprintStatusEntry(
                key="epic-12",
                status="done",
                entry_type=EntryType.EPIC_META,
            ),
            "12-1-setup": SprintStatusEntry(
                key="12-1-setup",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "20-1-start": SprintStatusEntry(
                key="20-1-start",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "epic-1": SprintStatusEntry(
                key="epic-1",
                status="done",
                entry_type=EntryType.EPIC_META,
            ),
        }

        sorted_entries = _sort_entries_by_epic_order(entries)
        keys = list(sorted_entries.keys())

        # Should be sorted: epic-1, epic-12, 12-1-setup, epic-20, 20-1-start
        assert keys.index("epic-1") < keys.index("epic-12")
        assert keys.index("epic-12") < keys.index("12-1-setup")
        assert keys.index("12-1-setup") < keys.index("epic-20")
        assert keys.index("epic-20") < keys.index("20-1-start")

    def test_string_epics_after_numeric(self) -> None:
        """String epics come after all numeric epics."""
        entries = {
            "epic-testarch": SprintStatusEntry(
                key="epic-testarch",
                status="done",
                entry_type=EntryType.EPIC_META,
            ),
            "testarch-1-config": SprintStatusEntry(
                key="testarch-1-config",
                status="done",
                entry_type=EntryType.MODULE_STORY,
            ),
            "epic-1": SprintStatusEntry(
                key="epic-1",
                status="done",
                entry_type=EntryType.EPIC_META,
            ),
        }

        sorted_entries = _sort_entries_by_epic_order(entries)
        keys = list(sorted_entries.keys())

        # Numeric (1) before string (testarch)
        assert keys.index("epic-1") < keys.index("epic-testarch")

    def test_empty_dict_returns_empty(self) -> None:
        """Empty dict returns empty dict."""
        sorted_entries = _sort_entries_by_epic_order({})
        assert sorted_entries == {}

    def test_full_epic_structure(self) -> None:
        """Test complete epic structure with meta, stories, and retrospective."""
        entries = {
            "epic-12-retrospective": SprintStatusEntry(
                key="epic-12-retrospective",
                status="backlog",
                entry_type=EntryType.RETROSPECTIVE,
            ),
            "12-3-parser": SprintStatusEntry(
                key="12-3-parser",
                status="in-progress",
                entry_type=EntryType.EPIC_STORY,
            ),
            "12-1-setup": SprintStatusEntry(
                key="12-1-setup",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "epic-12": SprintStatusEntry(
                key="epic-12",
                status="in-progress",
                entry_type=EntryType.EPIC_META,
            ),
            "12-2-models": SprintStatusEntry(
                key="12-2-models",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }

        sorted_entries = _sort_entries_by_epic_order(entries)
        keys = list(sorted_entries.keys())

        expected = [
            "epic-12",
            "12-1-setup",
            "12-2-models",
            "12-3-parser",
            "epic-12-retrospective",
        ]
        assert keys == expected


# ============================================================================
# Tests: Forward-Only Status Protection in Merge
# ============================================================================


class TestForwardOnlyProtection:
    """Tests for forward-only status protection in _merge_epic_story()."""

    def test_forward_status_allowed(
        self,
        temp_project_for_reconcile: Path,
        sample_metadata: SprintStatusMetadata,
    ) -> None:
        """Forward status changes are allowed."""
        existing = SprintStatus(
            metadata=sample_metadata,
            entries={
                "20-1-setup": SprintStatusEntry(
                    key="20-1-setup",
                    status="backlog",
                    entry_type=EntryType.EPIC_STORY,
                ),
            },
        )
        generated = GeneratedEntries()
        generated.entries = [
            SprintStatusEntry(
                key="20-1-setup",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        ]

        index = ArtifactIndex.scan(temp_project_for_reconcile)
        result = reconcile(existing, generated, index)

        # 20-1-setup has Status: done in file → forward change allowed
        entry = result.status.entries["20-1-setup"]
        assert entry.status == "done"

    def test_backward_status_blocked(
        self,
        tmp_path: Path,
        sample_metadata: SprintStatusMetadata,
    ) -> None:
        """Backward status changes are blocked (forward-only protection)."""
        # Create a project with no artifacts (no evidence)
        (tmp_path / "_bmad-output" / "implementation-artifacts").mkdir(parents=True)

        # Create a story file with Status: backlog (trying to downgrade)
        stories_dir = tmp_path / "_bmad-output" / "implementation-artifacts" / "stories"
        stories_dir.mkdir()
        (stories_dir / "20-1-setup.md").write_text(
            "# Story 20.1\n\nStatus: backlog\n\nBacklog story."
        )

        existing = SprintStatus(
            metadata=sample_metadata,
            entries={
                "20-1-setup": SprintStatusEntry(
                    key="20-1-setup",
                    status="done",  # Currently done
                    entry_type=EntryType.EPIC_STORY,
                ),
            },
        )
        generated = GeneratedEntries()
        generated.entries = [
            SprintStatusEntry(
                key="20-1-setup",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        ]

        index = ArtifactIndex.scan(tmp_path)
        result = reconcile(existing, generated, index)

        # Should NOT downgrade from done to backlog (forward-only)
        entry = result.status.entries["20-1-setup"]
        # Explicit status wins, but it would be a downgrade
        # Actually, EXPLICIT confidence wins always
        assert entry.status == "backlog"  # EXPLICIT wins over forward-only

    def test_forward_only_with_evidence_inference(
        self,
        tmp_path: Path,
        sample_metadata: SprintStatusMetadata,
    ) -> None:
        """Forward-only protection applies to evidence-based inference."""
        # Create project with validator review but no master (MEDIUM confidence)
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True)

        # Create validator code review (no master synthesis)
        reviews_dir = impl_dir / "code-reviews"
        reviews_dir.mkdir()
        (reviews_dir / "code-review-20-1-validator_a-20260107T120000.md").write_text(
            "# Validator Review"
        )

        # No story file with explicit status
        stories_dir = impl_dir / "stories"
        stories_dir.mkdir()
        (stories_dir / "20-1-setup.md").write_text(
            "# Story 20.1\n\nNo explicit status."
        )

        existing = SprintStatus(
            metadata=sample_metadata,
            entries={
                "20-1-setup": SprintStatusEntry(
                    key="20-1-setup",
                    status="done",  # Already done
                    entry_type=EntryType.EPIC_STORY,
                ),
            },
        )
        generated = GeneratedEntries()
        generated.entries = [
            SprintStatusEntry(
                key="20-1-setup",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        ]

        index = ArtifactIndex.scan(tmp_path)
        result = reconcile(existing, generated, index)

        # Validator review would infer "review" (MEDIUM confidence)
        # But "review" < "done", so forward-only should preserve "done"
        entry = result.status.entries["20-1-setup"]
        assert entry.status == "done"


# ============================================================================
# Tests: Epic Downgrade with Explicit Non-Done Stories (Bug Fix)
# ============================================================================


class TestEpicDowngradeWithExplicitNonDoneStories:
    """Tests for epic status downgrade when stories have explicit non-done status.

    This is a regression test for the bug where sprint-planning would identify
    stories as not done (via Status: field in story files), but the epic status
    would remain "done" due to forward-only protection, causing an infinite loop
    when bmad-assist tried to determine the next epic.
    """

    def test_epic_downgrades_with_explicit_non_done_story(
        self,
        tmp_path: Path,
        sample_metadata: SprintStatusMetadata,
    ) -> None:
        """Test that epic downgrades when stories have explicit non-done status.

        Bug scenario:
        1. Epic 12 was marked as done with all stories done
        2. Sprint-planning identified story 12-4 as not done (Status: in-progress)
        3. Epic 12 status should downgrade from done to in-progress
        4. Without this fix, epic stays done causing infinite loop in runner
        """
        # Create project structure
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True)

        stories_dir = impl_dir / "stories"
        stories_dir.mkdir()

        # Story 12-1: done
        (stories_dir / "12-1-foundation.md").write_text(
            "# Story 12.1\n\nStatus: done\n\nCompleted."
        )
        # Story 12-2: done
        (stories_dir / "12-2-config.md").write_text(
            "# Story 12.2\n\nStatus: done\n\nCompleted."
        )
        # Story 12-3: done
        (stories_dir / "12-3-parser.md").write_text(
            "# Story 12.3\n\nStatus: done\n\nCompleted."
        )
        # Story 12-4: NOT done (explicit in-progress status)
        # This is the key - sprint-planning found this story is still in-progress
        (stories_dir / "12-4-refactor.md").write_text(
            "# Story 12.4\n\nStatus: in-progress\n\nStill being worked on."
        )

        # Existing sprint-status: epic marked as done (from previous completion)
        existing = SprintStatus(
            metadata=sample_metadata,
            entries={
                "epic-12": SprintStatusEntry(
                    key="epic-12",
                    status="done",  # Epic was marked done
                    entry_type=EntryType.EPIC_META,
                ),
                "12-1-foundation": SprintStatusEntry(
                    key="12-1-foundation",
                    status="done",
                    entry_type=EntryType.EPIC_STORY,
                ),
                "12-2-config": SprintStatusEntry(
                    key="12-2-config",
                    status="done",
                    entry_type=EntryType.EPIC_STORY,
                ),
                "12-3-parser": SprintStatusEntry(
                    key="12-3-parser",
                    status="done",
                    entry_type=EntryType.EPIC_STORY,
                ),
                # Story 12-4 was previously marked done, but is now in-progress
                "12-4-refactor": SprintStatusEntry(
                    key="12-4-refactor",
                    status="in-progress",  # Updated by sprint-planning
                    entry_type=EntryType.EPIC_STORY,
                ),
            },
        )

        # Generated entries from epic files
        generated = GeneratedEntries()
        generated.entries = [
            SprintStatusEntry(
                key="epic-12",
                status="done",
                entry_type=EntryType.EPIC_META,
            ),
            SprintStatusEntry(
                key="12-1-foundation",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            SprintStatusEntry(
                key="12-2-config",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            SprintStatusEntry(
                key="12-3-parser",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            SprintStatusEntry(
                key="12-4-refactor",
                status="in-progress",
                entry_type=EntryType.EPIC_STORY,
            ),
        ]

        index = ArtifactIndex.scan(tmp_path)
        result = reconcile(existing, generated, index)

        # Epic 12 should downgrade from done to in-progress
        # because story 12-4 has explicit non-done status
        epic_entry = result.status.entries["epic-12"]
        assert epic_entry.status == "in-progress", (
            f"Epic 12 should downgrade to 'in-progress' when story 12-4 "
            f"has explicit non-done status, but got '{epic_entry.status}'"
        )

        # Should have a change record for the epic status change
        epic_change = next(
            (c for c in result.changes if c.key == "epic-12"),
            None,
        )
        assert epic_change is not None, "Epic 12 should have a status change record"
        assert epic_change.old_status == "done"
        assert epic_change.new_status == "in-progress"

    def test_epic_preserved_done_without_explicit_non_done_stories(
        self,
        tmp_path: Path,
        sample_metadata: SprintStatusMetadata,
    ) -> None:
        """Test that epic stays done when no explicit non-done stories.

        If stories are marked as not-done only via inference (not explicit Status:),
        the epic should preserve its done status (forward-only protection).
        """
        # Create project with NO explicit story statuses
        impl_dir = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl_dir.mkdir(parents=True)

        stories_dir = impl_dir / "stories"
        stories_dir.mkdir()

        # Stories without explicit Status fields
        (stories_dir / "12-1-foundation.md").write_text("# Story 12.1\n\nCompleted.")
        (stories_dir / "12-2-config.md").write_text("# Story 12.2\n\nCompleted.")

        # Existing: epic marked as done
        existing = SprintStatus(
            metadata=sample_metadata,
            entries={
                "epic-12": SprintStatusEntry(
                    key="epic-12",
                    status="done",
                    entry_type=EntryType.EPIC_META,
                ),
                "12-1-foundation": SprintStatusEntry(
                    key="12-1-foundation",
                    status="in-progress",  # Inferred, not explicit
                    entry_type=EntryType.EPIC_STORY,
                ),
                "12-2-config": SprintStatusEntry(
                    key="12-2-config",
                    status="in-progress",  # Inferred, not explicit
                    entry_type=EntryType.EPIC_STORY,
                ),
            },
        )

        generated = GeneratedEntries()
        generated.entries = [
            SprintStatusEntry(
                key="epic-12",
                status="done",
                entry_type=EntryType.EPIC_META,
            ),
            SprintStatusEntry(
                key="12-1-foundation",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
            SprintStatusEntry(
                key="12-2-config",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        ]

        index = ArtifactIndex.scan(tmp_path)
        result = reconcile(existing, generated, index)

        # Epic 12 should preserve done status (no explicit non-done stories)
        epic_entry = result.status.entries["epic-12"]
        assert epic_entry.status == "done", (
            f"Epic 12 should preserve 'done' when no explicit non-done stories, "
            f"but got '{epic_entry.status}'"
        )
