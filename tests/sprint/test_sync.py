"""Tests for state-to-sprint synchronization module.

Tests cover:
- SyncResult dataclass properties and summary
- PHASE_TO_STATUS mapping completeness
- _find_story_key() helper for ID conversion
- sync_state_to_sprint() core function
- trigger_sync() convenience function
- Callback registration and invocation
- Error handling and edge cases
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bmad_assist.core.state import Phase, State
from bmad_assist.sprint.classifier import EntryType
from bmad_assist.sprint.models import (
    SprintStatus,
    SprintStatusEntry,
    SprintStatusMetadata,
)
from bmad_assist.sprint.sync import (
    PHASE_TO_STATUS,
    SyncResult,
    _find_epic_key,
    _find_story_key,
    clear_sync_callbacks,
    invoke_sync_callbacks,
    register_sync_callback,
    sync_state_to_sprint,
    trigger_sync,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_metadata() -> SprintStatusMetadata:
    """Create sample metadata for tests."""
    return SprintStatusMetadata(
        generated=datetime(2026, 1, 7, 12, 0, 0),
        project="test-project",
    )


@pytest.fixture
def sample_entries() -> dict[str, SprintStatusEntry]:
    """Create sample entries dict for tests."""
    return {
        "epic-20": SprintStatusEntry(
            key="epic-20",
            status="in-progress",
            entry_type=EntryType.EPIC_META,
        ),
        "20-1-setup": SprintStatusEntry(
            key="20-1-setup",
            status="done",
            entry_type=EntryType.EPIC_STORY,
        ),
        "20-2-feature": SprintStatusEntry(
            key="20-2-feature",
            status="in-progress",
            entry_type=EntryType.EPIC_STORY,
        ),
        "20-9-sync": SprintStatusEntry(
            key="20-9-sync",
            status="backlog",
            entry_type=EntryType.EPIC_STORY,
        ),
        "testarch-1-config": SprintStatusEntry(
            key="testarch-1-config",
            status="done",
            entry_type=EntryType.MODULE_STORY,
        ),
        "epic-testarch": SprintStatusEntry(
            key="epic-testarch",
            status="done",
            entry_type=EntryType.EPIC_META,
        ),
        "standalone-01-refactor": SprintStatusEntry(
            key="standalone-01-refactor",
            status="done",
            entry_type=EntryType.STANDALONE,
        ),
    }


@pytest.fixture
def sample_sprint_status(
    sample_metadata: SprintStatusMetadata,
    sample_entries: dict[str, SprintStatusEntry],
) -> SprintStatus:
    """Create sample SprintStatus for tests."""
    return SprintStatus(metadata=sample_metadata, entries=sample_entries)


@pytest.fixture
def sample_state() -> State:
    """Create sample State for tests."""
    return State(
        current_epic=20,
        current_story="20.9",
        current_phase=Phase.DEV_STORY,
        completed_stories=["20.1", "20.2"],
        completed_epics=[],
    )


@pytest.fixture(autouse=True)
def cleanup_callbacks():
    """Ensure callbacks are cleared before and after each test."""
    clear_sync_callbacks()
    yield
    clear_sync_callbacks()


# =============================================================================
# Test: SyncResult Dataclass (AC8)
# =============================================================================


class TestSyncResult:
    """Tests for SyncResult frozen dataclass."""

    def test_sync_result_default_values(self):
        """SyncResult has correct default values."""
        result = SyncResult()
        assert result.synced_stories == 0
        assert result.synced_epics == 0
        assert result.skipped_keys == ()
        assert result.errors == ()

    def test_sync_result_with_values(self):
        """SyncResult accepts all fields."""
        result = SyncResult(
            synced_stories=3,
            synced_epics=1,
            skipped_keys=("99.1", "99.2"),
            errors=("error1",),
        )
        assert result.synced_stories == 3
        assert result.synced_epics == 1
        assert result.skipped_keys == ("99.1", "99.2")
        assert result.errors == ("error1",)

    def test_sync_result_is_frozen(self):
        """SyncResult is immutable (frozen)."""
        result = SyncResult(synced_stories=1)
        with pytest.raises(AttributeError):
            result.synced_stories = 2  # type: ignore

    def test_sync_result_is_hashable(self):
        """SyncResult is hashable (can be used in sets/dicts)."""
        result = SyncResult(synced_stories=1)
        # Should not raise
        hash(result)
        {result}  # Can add to set

    def test_sync_result_repr(self):
        """SyncResult has informative repr."""
        result = SyncResult(
            synced_stories=3,
            synced_epics=1,
            skipped_keys=("99.1",),
            errors=("error",),
        )
        repr_str = repr(result)
        assert "synced_stories=3" in repr_str
        assert "synced_epics=1" in repr_str
        assert "skipped=1" in repr_str
        assert "errors=1" in repr_str

    def test_sync_result_summary_basic(self):
        """summary() returns basic sync counts."""
        result = SyncResult(synced_stories=3, synced_epics=1)
        summary = result.summary()
        assert "Synced 3 stories, 1 epics" in summary

    def test_sync_result_summary_with_skipped(self):
        """summary() includes skipped keys count."""
        result = SyncResult(
            synced_stories=3,
            synced_epics=1,
            skipped_keys=("99.1", "99.2"),
        )
        summary = result.summary()
        assert "Skipped 2 missing keys" in summary

    def test_sync_result_summary_with_errors(self):
        """summary() includes error count."""
        result = SyncResult(
            synced_stories=3,
            synced_epics=1,
            errors=("error1", "error2"),
        )
        summary = result.summary()
        assert "2 errors" in summary


# =============================================================================
# Test: PHASE_TO_STATUS Mapping (AC2)
# =============================================================================


class TestPhaseToStatusMapping:
    """Tests for PHASE_TO_STATUS mapping completeness."""

    def test_mapping_covers_all_phases(self):
        """PHASE_TO_STATUS has mapping for all Phase enum values."""
        all_phases = set(Phase)
        mapped_phases = set(PHASE_TO_STATUS.keys())
        assert mapped_phases == all_phases, f"Missing phases: {all_phases - mapped_phases}"

    def test_create_story_maps_to_in_progress(self):
        """CREATE_STORY maps to in-progress."""
        assert PHASE_TO_STATUS[Phase.CREATE_STORY] == "in-progress"

    def test_validate_story_maps_to_in_progress(self):
        """VALIDATE_STORY maps to in-progress."""
        assert PHASE_TO_STATUS[Phase.VALIDATE_STORY] == "in-progress"

    def test_validate_story_synthesis_maps_to_in_progress(self):
        """VALIDATE_STORY_SYNTHESIS maps to in-progress."""
        assert PHASE_TO_STATUS[Phase.VALIDATE_STORY_SYNTHESIS] == "in-progress"

    def test_atdd_maps_to_in_progress(self):
        """ATDD maps to in-progress."""
        assert PHASE_TO_STATUS[Phase.ATDD] == "in-progress"

    def test_dev_story_maps_to_in_progress(self):
        """DEV_STORY maps to in-progress."""
        assert PHASE_TO_STATUS[Phase.DEV_STORY] == "in-progress"

    def test_code_review_maps_to_review(self):
        """CODE_REVIEW maps to review."""
        assert PHASE_TO_STATUS[Phase.CODE_REVIEW] == "review"

    def test_code_review_synthesis_maps_to_review(self):
        """CODE_REVIEW_SYNTHESIS maps to review."""
        assert PHASE_TO_STATUS[Phase.CODE_REVIEW_SYNTHESIS] == "review"

    def test_test_review_maps_to_review(self):
        """TEST_REVIEW maps to review."""
        assert PHASE_TO_STATUS[Phase.TEST_REVIEW] == "review"

    def test_retrospective_maps_to_done(self):
        """RETROSPECTIVE maps to done."""
        assert PHASE_TO_STATUS[Phase.RETROSPECTIVE] == "done"


# =============================================================================
# Test: _find_story_key() Helper (AC7)
# =============================================================================


class TestFindStoryKey:
    """Tests for story key lookup helper."""

    def test_find_story_key_numeric_epic(self, sample_entries: dict[str, SprintStatusEntry]):
        """Finds key for numeric epic story ID."""
        result = _find_story_key("20.9", sample_entries)
        assert result == "20-9-sync"

    def test_find_story_key_module_story(self, sample_entries: dict[str, SprintStatusEntry]):
        """Finds key for module story ID."""
        result = _find_story_key("testarch.1", sample_entries)
        assert result == "testarch-1-config"

    def test_find_story_key_not_found(self, sample_entries: dict[str, SprintStatusEntry]):
        """Returns None for non-existent story."""
        result = _find_story_key("99.1", sample_entries)
        assert result is None

    def test_find_story_key_empty_id(self, sample_entries: dict[str, SprintStatusEntry]):
        """Returns None for empty story ID."""
        result = _find_story_key("", sample_entries)
        assert result is None

    def test_find_story_key_empty_entries(self):
        """Returns None when entries dict is empty."""
        result = _find_story_key("20.9", {})
        assert result is None

    def test_find_story_key_exact_match(self):
        """Handles edge case of exact key match (no suffix)."""
        entries = {
            "20-9": SprintStatusEntry(
                key="20-9",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        result = _find_story_key("20.9", entries)
        assert result == "20-9"

    def test_find_story_key_does_not_match_partial(self):
        """Does not match keys that only partially match prefix."""
        entries = {
            "20-90-different": SprintStatusEntry(
                key="20-90-different",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        # "20.9" should NOT match "20-90-different"
        result = _find_story_key("20.9", entries)
        assert result is None


# =============================================================================
# Test: _find_epic_key() Helper
# =============================================================================


class TestFindEpicKey:
    """Tests for epic key lookup helper."""

    def test_find_epic_key_numeric(self, sample_entries: dict[str, SprintStatusEntry]):
        """Finds key for numeric epic ID."""
        result = _find_epic_key(20, sample_entries)
        assert result == "epic-20"

    def test_find_epic_key_string(self, sample_entries: dict[str, SprintStatusEntry]):
        """Finds key for string epic ID."""
        result = _find_epic_key("testarch", sample_entries)
        assert result == "epic-testarch"

    def test_find_epic_key_not_found(self, sample_entries: dict[str, SprintStatusEntry]):
        """Returns None for non-existent epic."""
        result = _find_epic_key(99, sample_entries)
        assert result is None


# =============================================================================
# Test: sync_state_to_sprint() Core Function (AC1-AC5, AC7)
# =============================================================================


class TestSyncStateToSprint:
    """Tests for the core sync function."""

    def test_sync_updates_current_story_status(
        self,
        sample_state: State,
        sample_sprint_status: SprintStatus,
    ):
        """Current story status updated based on phase."""
        # State has current_story="20.9" at DEV_STORY phase
        updated, result = sync_state_to_sprint(sample_state, sample_sprint_status)

        # Story should be updated to "in-progress"
        assert updated.entries["20-9-sync"].status == "in-progress"
        assert result.synced_stories >= 1

    def test_sync_marks_completed_stories_done(
        self,
        sample_state: State,
        sample_sprint_status: SprintStatus,
    ):
        """Completed stories are marked as done."""
        # State has completed_stories=["20.1", "20.2"]
        updated, result = sync_state_to_sprint(sample_state, sample_sprint_status)

        assert updated.entries["20-1-setup"].status == "done"
        assert updated.entries["20-2-feature"].status == "done"

    def test_sync_marks_completed_epics_done(
        self,
        sample_sprint_status: SprintStatus,
    ):
        """Completed epics are marked as done."""
        state = State(
            current_epic=21,
            current_story="21.1",
            current_phase=Phase.CREATE_STORY,
            completed_epics=[20],
        )
        updated, result = sync_state_to_sprint(state, sample_sprint_status)

        assert updated.entries["epic-20"].status == "done"
        assert result.synced_epics == 1

    def test_sync_skips_missing_story_keys(
        self,
        sample_sprint_status: SprintStatus,
        caplog: pytest.LogCaptureFixture,
    ):
        """Missing story keys are skipped with warning."""
        state = State(
            current_epic=99,
            current_story="99.1",  # Not in sprint-status
            current_phase=Phase.DEV_STORY,
        )
        updated, result = sync_state_to_sprint(state, sample_sprint_status)

        assert "99.1" in result.skipped_keys
        assert any("not found" in r.message for r in caplog.records)

    def test_sync_skips_missing_epic_keys(
        self,
        sample_sprint_status: SprintStatus,
        caplog: pytest.LogCaptureFixture,
    ):
        """Missing epic keys are skipped with warning."""
        state = State(
            current_epic=21,
            current_story="21.1",
            current_phase=Phase.CREATE_STORY,
            completed_epics=[99],  # Not in sprint-status
        )
        updated, result = sync_state_to_sprint(state, sample_sprint_status)

        assert "epic-99" in result.skipped_keys

    def test_sync_handles_none_current_story(
        self,
        sample_sprint_status: SprintStatus,
    ):
        """Handles state with no current story."""
        state = State(
            current_epic=20,
            current_story=None,
            current_phase=Phase.CREATE_STORY,
        )
        updated, result = sync_state_to_sprint(state, sample_sprint_status)

        # Should not raise, no changes expected
        assert result.synced_stories == 0

    def test_sync_handles_none_phase(
        self,
        sample_sprint_status: SprintStatus,
    ):
        """Handles state with no current phase."""
        state = State(
            current_epic=20,
            current_story="20.9",
            current_phase=None,
        )
        updated, result = sync_state_to_sprint(state, sample_sprint_status)

        # Should not raise, no status update for current story
        # (entry count may still include completed if any)
        assert result.errors == ()

    def test_sync_does_not_mutate_original(
        self,
        sample_state: State,
        sample_sprint_status: SprintStatus,
    ):
        """sync_state_to_sprint does not mutate the original SprintStatus."""
        original_status = sample_sprint_status.entries["20-9-sync"].status
        updated, _ = sync_state_to_sprint(sample_state, sample_sprint_status)

        # Original unchanged
        assert sample_sprint_status.entries["20-9-sync"].status == original_status
        # Updated changed
        assert updated.entries["20-9-sync"].status == "in-progress"

    def test_sync_one_way_never_modifies_state(
        self,
        sample_sprint_status: SprintStatus,
    ):
        """Sync is ONE-WAY: state is never modified (AC5)."""
        state = State(
            current_epic=20,
            current_story="20.9",
            current_phase=Phase.DEV_STORY,
            completed_stories=[],
        )
        original_completed = list(state.completed_stories)

        sync_state_to_sprint(state, sample_sprint_status)

        # State should be unchanged
        assert state.completed_stories == original_completed
        assert state.current_story == "20.9"
        assert state.current_phase == Phase.DEV_STORY

    def test_sync_all_phases_produce_valid_status(
        self,
        sample_sprint_status: SprintStatus,
    ):
        """Each phase produces a valid ValidStatus value."""
        for phase in Phase:
            state = State(
                current_epic=20,
                current_story="20.9",
                current_phase=phase,
            )
            updated, _ = sync_state_to_sprint(state, sample_sprint_status)
            # Should not raise - status is valid
            entry = updated.entries["20-9-sync"]
            assert entry.status in (
                "backlog",
                "ready-for-dev",
                "in-progress",
                "review",
                "done",
                "blocked",
                "deferred",
            )


# =============================================================================
# Test: trigger_sync() Convenience Function (AC6)
# =============================================================================


class TestTriggerSync:
    """Tests for the trigger_sync convenience function."""

    def test_trigger_sync_creates_missing_file(
        self,
        sample_state: State,
        tmp_path: Path,
    ):
        """trigger_sync creates sprint-status if missing."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = trigger_sync(sample_state, project_root)

        sprint_path = (
            project_root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
        )
        assert sprint_path.exists()
        # Note: New file has no entries for the stories
        assert result.skipped_keys  # Story not found in empty sprint-status

    def test_trigger_sync_writes_atomically(
        self,
        sample_state: State,
        tmp_path: Path,
        sample_sprint_status: SprintStatus,
    ):
        """trigger_sync uses atomic write."""
        project_root = tmp_path / "project"
        sprint_dir = project_root / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        sprint_path = sprint_dir / "sprint-status.yaml"

        # Write initial sprint-status
        from bmad_assist.sprint.writer import write_sprint_status

        write_sprint_status(sample_sprint_status, sprint_path)

        # Trigger sync
        result = trigger_sync(sample_state, project_root)

        # File should be updated
        assert sprint_path.exists()
        # No temp file left behind
        assert not sprint_path.with_suffix(".yaml.tmp").exists()

    def test_trigger_sync_aborts_on_corrupted_file(
        self,
        sample_state: State,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """trigger_sync aborts and preserves corrupted file (prevents data loss).

        When a file exists but parser returns empty (corruption), sync must NOT
        overwrite the file. Returns SyncResult with error instead.
        """
        project_root = tmp_path / "project"
        sprint_dir = project_root / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        sprint_path = sprint_dir / "sprint-status.yaml"

        # Write invalid YAML (non-empty content that won't parse)
        original_content = "{{invalid yaml with content"
        sprint_path.write_text(original_content, encoding="utf-8")

        # Sync should abort with error, NOT overwrite
        result = trigger_sync(sample_state, project_root)

        # Should return error
        assert len(result.errors) > 0
        assert "Corrupted" in result.errors[0] or "corrupted" in result.errors[0].lower()
        # Should log error about corruption
        assert any("corrupted" in r.message.lower() for r in caplog.records)
        # File should NOT be overwritten
        assert sprint_path.read_text(encoding="utf-8") == original_content

    def test_trigger_sync_returns_sync_result(
        self,
        sample_state: State,
        tmp_path: Path,
        sample_sprint_status: SprintStatus,
    ):
        """trigger_sync returns SyncResult."""
        project_root = tmp_path / "project"
        sprint_dir = project_root / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        sprint_path = sprint_dir / "sprint-status.yaml"

        from bmad_assist.sprint.writer import write_sprint_status

        write_sprint_status(sample_sprint_status, sprint_path)

        result = trigger_sync(sample_state, project_root)

        assert isinstance(result, SyncResult)
        assert result.synced_stories > 0


# =============================================================================
# Test: Callback Registration and Invocation (AC9)
# =============================================================================


class TestCallbackPattern:
    """Tests for callback registration and invocation."""

    def test_register_sync_callback(self):
        """register_sync_callback adds callback to registry."""
        call_count = [0]

        def callback(state: State, project_root: Path) -> None:
            call_count[0] += 1

        register_sync_callback(callback)

        # Invoke to verify it was registered
        state = State()
        invoke_sync_callbacks(state, Path("/tmp"))

        assert call_count[0] == 1

    def test_clear_sync_callbacks(self):
        """clear_sync_callbacks removes all callbacks."""
        call_count = [0]

        def callback(state: State, project_root: Path) -> None:
            call_count[0] += 1

        register_sync_callback(callback)
        clear_sync_callbacks()

        state = State()
        invoke_sync_callbacks(state, Path("/tmp"))

        assert call_count[0] == 0

    def test_invoke_multiple_callbacks(self):
        """invoke_sync_callbacks invokes all registered callbacks."""
        call_counts = [0, 0]

        def callback1(state: State, project_root: Path) -> None:
            call_counts[0] += 1

        def callback2(state: State, project_root: Path) -> None:
            call_counts[1] += 1

        register_sync_callback(callback1)
        register_sync_callback(callback2)

        state = State()
        invoke_sync_callbacks(state, Path("/tmp"))

        assert call_counts[0] == 1
        assert call_counts[1] == 1

    def test_callback_exception_caught_and_logged(
        self,
        caplog: pytest.LogCaptureFixture,
    ):
        """Callback exceptions are caught and logged, not propagated."""

        def failing_callback(state: State, project_root: Path) -> None:
            raise RuntimeError("Test error")

        register_sync_callback(failing_callback)

        state = State()
        # Should NOT raise
        invoke_sync_callbacks(state, Path("/tmp"))

        # Should log warning
        assert any("failed" in r.message.lower() for r in caplog.records)

    def test_callback_exception_does_not_stop_other_callbacks(self):
        """One failing callback doesn't prevent others from running."""
        call_counts = [0, 0]

        def failing_callback(state: State, project_root: Path) -> None:
            call_counts[0] += 1
            raise RuntimeError("Error 1")

        def success_callback(state: State, project_root: Path) -> None:
            call_counts[1] += 1

        register_sync_callback(failing_callback)
        register_sync_callback(success_callback)

        state = State()
        invoke_sync_callbacks(state, Path("/tmp"))

        # Both called despite first failing
        assert call_counts[0] == 1
        assert call_counts[1] == 1

    def test_callback_receives_correct_arguments(self):
        """Callbacks receive state and project_root correctly."""
        received_args: list = []

        def capture_callback(state: State, project_root: Path) -> None:
            received_args.append((state, project_root))

        register_sync_callback(capture_callback)

        state = State(current_epic=20)
        project_root = Path("/my/project")
        invoke_sync_callbacks(state, project_root)

        assert len(received_args) == 1
        assert received_args[0][0] is state
        assert received_args[0][1] == project_root

    def test_functools_partial_callback(self):
        """functools.partial callbacks work without __name__ crash."""
        from functools import partial

        call_count = [0]

        def callback_with_extra(extra: str, state: State, project_root: Path) -> None:
            call_count[0] += 1

        partial_callback = partial(callback_with_extra, "extra_arg")
        register_sync_callback(partial_callback)

        state = State()
        invoke_sync_callbacks(state, Path("/tmp"))

        # Should work without AttributeError from missing __name__
        assert call_count[0] == 1


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_sync_empty_state(
        self,
        sample_sprint_status: SprintStatus,
    ):
        """Sync with empty state produces no changes."""
        state = State()
        updated, result = sync_state_to_sprint(state, sample_sprint_status)

        assert result.synced_stories == 0
        assert result.synced_epics == 0
        assert result.skipped_keys == ()

    def test_sync_empty_sprint_status(self):
        """Sync with empty sprint-status skips all."""
        state = State(
            current_epic=20,
            current_story="20.9",
            current_phase=Phase.DEV_STORY,
            completed_stories=["20.1"],
            completed_epics=[19],
        )
        sprint_status = SprintStatus.empty()

        updated, result = sync_state_to_sprint(state, sprint_status)

        # All should be skipped (not found)
        assert "20.9" in result.skipped_keys
        assert "20.1" in result.skipped_keys
        assert "epic-19" in result.skipped_keys

    def test_sync_does_not_change_already_correct_status(
        self,
        sample_sprint_status: SprintStatus,
    ):
        """Sync doesn't re-write status if already correct."""
        # Set up state where story is already done
        state = State(
            current_epic=20,
            current_story="20.1",  # Already done in sample
            current_phase=Phase.RETROSPECTIVE,  # Maps to "done"
        )
        updated, result = sync_state_to_sprint(state, sample_sprint_status)

        # Status should still be done (unchanged)
        assert updated.entries["20-1-setup"].status == "done"

    def test_sync_preserves_unrelated_entries(
        self,
        sample_state: State,
        sample_sprint_status: SprintStatus,
    ):
        """Sync preserves entries not touched by state."""
        updated, _ = sync_state_to_sprint(sample_state, sample_sprint_status)

        # Standalone entry should be unchanged
        assert updated.entries["standalone-01-refactor"].status == "done"
        # Module entry should be unchanged
        assert updated.entries["testarch-1-config"].status == "done"

    def test_sync_with_string_epic_in_completed(
        self,
        sample_sprint_status: SprintStatus,
    ):
        """Sync handles string epic IDs in completed_epics."""
        state = State(
            current_epic=21,
            current_story="21.1",
            current_phase=Phase.CREATE_STORY,
            completed_epics=["testarch"],  # String epic ID
        )
        updated, result = sync_state_to_sprint(state, sample_sprint_status)

        assert updated.entries["epic-testarch"].status == "done"
        assert result.synced_epics == 1


# =============================================================================
# Test: Integration
# =============================================================================


class TestIntegration:
    """Integration tests for complete sync cycles."""

    def test_full_sync_cycle(
        self,
        tmp_path: Path,
    ):
        """Complete sync cycle: create → sync → verify."""
        from bmad_assist.sprint.parser import parse_sprint_status
        from bmad_assist.sprint.writer import write_sprint_status

        project_root = tmp_path / "project"
        sprint_dir = project_root / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        sprint_path = sprint_dir / "sprint-status.yaml"

        # Create initial sprint-status
        meta = SprintStatusMetadata(
            generated=datetime.now(UTC).replace(tzinfo=None),
            project="integration-test",
        )
        entries = {
            "epic-1": SprintStatusEntry(
                key="epic-1",
                status="in-progress",
                entry_type=EntryType.EPIC_META,
            ),
            "1-1-setup": SprintStatusEntry(
                key="1-1-setup",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
            "1-2-feature": SprintStatusEntry(
                key="1-2-feature",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        initial_status = SprintStatus(metadata=meta, entries=entries)
        write_sprint_status(initial_status, sprint_path)

        # Create state simulating mid-development
        state = State(
            current_epic=1,
            current_story="1.2",
            current_phase=Phase.CODE_REVIEW,
            completed_stories=["1.1"],
        )

        # Trigger sync
        result = trigger_sync(state, project_root)

        # Verify results
        final_status = parse_sprint_status(sprint_path)
        assert final_status.entries["1-1-setup"].status == "done"
        assert final_status.entries["1-2-feature"].status == "review"

    def test_callback_integration_with_trigger_sync(
        self,
        tmp_path: Path,
    ):
        """Callback that calls trigger_sync works correctly."""
        from bmad_assist.sprint.writer import write_sprint_status

        project_root = tmp_path / "project"
        sprint_dir = project_root / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        sprint_path = sprint_dir / "sprint-status.yaml"

        # Create initial sprint-status
        initial_status = SprintStatus.empty("callback-test")
        write_sprint_status(initial_status, sprint_path)

        # Track callback invocations
        sync_results: list[SyncResult] = []

        def sync_callback(state: State, proj_root: Path) -> None:
            result = trigger_sync(state, proj_root)
            sync_results.append(result)

        register_sync_callback(sync_callback)

        state = State()
        invoke_sync_callbacks(state, project_root)

        assert len(sync_results) == 1
        assert isinstance(sync_results[0], SyncResult)
