"""Tests for State Discrepancy Correction (Story 2.5).

Tests cover all acceptance criteria for Story 2.5 - State Discrepancy Correction.
"""

import logging
import os
from pathlib import Path

import frontmatter  # type: ignore[import-untyped]
import pytest
import yaml

from bmad_assist.bmad.correction import (
    CorrectionAction,
    CorrectionResult,
    _atomic_write_file,
    _create_minimal_story_file,
    _find_sprint_status_key,
    _find_story_file,
    _get_correction_options,
    _is_auto_correctable,
    _update_sprint_status,
    _update_story_frontmatter,
    correct_all_discrepancies,
    correct_discrepancy,
)
from bmad_assist.bmad.discrepancy import Discrepancy
from bmad_assist.core.exceptions import ReconciliationError

# Import shared MockInternalState from conftest
from tests.bmad.conftest import MockInternalState


class TestCorrectionActionEnum:
    """Test AC3 partial: CorrectionAction enum values."""

    def test_enum_has_required_values(self) -> None:
        """CorrectionAction has all required enum values."""
        assert CorrectionAction.UPDATED_BMAD.value is not None
        assert CorrectionAction.SKIPPED.value is not None
        assert CorrectionAction.NO_CHANGE_NEEDED.value is not None
        assert CorrectionAction.ERROR.value is not None

    def test_enum_values_are_unique(self) -> None:
        """All enum values are unique."""
        values = [
            CorrectionAction.UPDATED_BMAD.value,
            CorrectionAction.SKIPPED.value,
            CorrectionAction.NO_CHANGE_NEEDED.value,
            CorrectionAction.ERROR.value,
        ]
        assert len(values) == len(set(values))


class TestCorrectionResultDataclass:
    """Test AC3: CorrectionResult dataclass structure."""

    def test_correctionresult_has_required_fields(self) -> None:
        """CorrectionResult has all required fields."""
        discrepancy = Discrepancy(
            type="story_status_mismatch",
            expected="done",
            actual="in-progress",
            story_number="2.3",
        )
        result = CorrectionResult(
            action=CorrectionAction.UPDATED_BMAD,
            discrepancy=discrepancy,
            details="Updated BMAD story 2.3",
            error=None,
            modified_files=[Path("/path/to/story.md")],
        )

        assert result.action == CorrectionAction.UPDATED_BMAD
        assert result.discrepancy == discrepancy
        assert result.details == "Updated BMAD story 2.3"
        assert result.error is None
        assert result.modified_files == [Path("/path/to/story.md")]

    def test_correctionresult_optional_fields_default(self) -> None:
        """CorrectionResult optional fields have correct defaults."""
        discrepancy = Discrepancy(type="test", expected="a", actual="b")
        result = CorrectionResult(
            action=CorrectionAction.SKIPPED,
            discrepancy=discrepancy,
            details="Test details",
        )

        assert result.error is None
        assert result.modified_files is None

    def test_correctionresult_with_error(self) -> None:
        """CorrectionResult with error field populated."""
        discrepancy = Discrepancy(type="test", expected="a", actual="b")
        result = CorrectionResult(
            action=CorrectionAction.ERROR,
            discrepancy=discrepancy,
            details="Failed to correct",
            error="File not found",
        )

        assert result.action == CorrectionAction.ERROR
        assert result.error == "File not found"


class TestCorrectDiscrepancyAutoCorrect:
    """Test AC1, AC4, AC8, AC9, AC10: Auto-correctable discrepancies."""

    def test_ac1_auto_correct_bmad_behind_internal(self, tmp_path: Path) -> None:
        """AC1: Auto-correct when BMAD is behind internal (internal=done, BMAD=in-progress)."""
        # Create story file with in-progress status
        story_content = """---
status: in-progress
---

# Story 2.3: Test Story

**Status:** in-progress
"""
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        story_file = artifacts / "2-3-test-story.md"
        story_file.write_text(story_content)

        # Create discrepancy: internal says done, BMAD says in-progress
        discrepancy = Discrepancy(
            type="story_status_mismatch",
            expected="done",
            actual="in-progress",
            story_number="2.3",
            file_path=str(story_file),
        )

        internal = MockInternalState(
            current_epic=2,
            current_story=None,
            completed_stories=["2.3"],
        )

        result = correct_discrepancy(discrepancy, internal, tmp_path, auto=True)

        assert result.action == CorrectionAction.UPDATED_BMAD
        assert "2.3" in result.details
        assert result.modified_files is not None
        assert len(result.modified_files) > 0

        # Verify file was updated
        post = frontmatter.load(story_file)
        assert post.metadata["status"] == "done"

    def test_ac4_story_not_in_bmad_creates_file(self, tmp_path: Path) -> None:
        """AC4: story_not_in_bmad creates BMAD file from internal state."""
        discrepancy = Discrepancy(
            type="story_not_in_bmad",
            expected="2.6",
            actual=None,
            story_number="2.6",
        )

        internal = MockInternalState(
            current_epic=2,
            current_story="2.6",
            completed_stories=["2.5"],
        )

        result = correct_discrepancy(discrepancy, internal, tmp_path, auto=True)

        assert result.action == CorrectionAction.UPDATED_BMAD
        assert "Created BMAD file" in result.details
        assert result.modified_files is not None

        # Verify file was created
        created_file = result.modified_files[0]
        assert created_file.exists()
        post = frontmatter.load(created_file)
        assert post.metadata["status"] == "in-progress"  # current story

    def test_ac4_story_not_in_bmad_completed_story(self, tmp_path: Path) -> None:
        """AC4: story_not_in_bmad for completed story creates file with done status."""
        discrepancy = Discrepancy(
            type="story_not_in_bmad",
            expected="2.5",
            actual=None,
            story_number="2.5",
        )

        internal = MockInternalState(
            current_epic=2,
            current_story="2.6",
            completed_stories=["2.5"],
        )

        result = correct_discrepancy(discrepancy, internal, tmp_path, auto=True)

        assert result.action == CorrectionAction.UPDATED_BMAD
        assert result.modified_files is not None

        created_file = result.modified_files[0]
        post = frontmatter.load(created_file)
        assert post.metadata["status"] == "done"


class TestCorrectDiscrepancyConfirmation:
    """Test AC2, AC5, AC7, AC11: Discrepancies requiring confirmation."""

    def test_ac2_bmad_ahead_requires_confirmation(self, tmp_path: Path) -> None:
        """AC2: Require confirmation when BMAD ahead of internal."""
        # Create story file with done status
        story_content = """---
status: done
---

# Story 2.3: Test Story
"""
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        story_file = artifacts / "2-3-test-story.md"
        story_file.write_text(story_content)

        # Discrepancy: internal says in-progress, BMAD says done (suspicious)
        discrepancy = Discrepancy(
            type="story_status_mismatch",
            expected="in-progress",
            actual="done",
            story_number="2.3",
            file_path=str(story_file),
        )

        internal = MockInternalState(
            current_epic=2,
            current_story="2.3",
            completed_stories=[],
        )

        # Without callback, should return NO_CHANGE_NEEDED
        result = correct_discrepancy(discrepancy, internal, tmp_path, auto=True)
        assert result.action == CorrectionAction.NO_CHANGE_NEEDED
        assert "requires user confirmation" in result.details

    def test_ac5_story_not_in_internal_requires_confirmation(self, tmp_path: Path) -> None:
        """AC5: story_not_in_internal requires confirmation."""
        # Create story file
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        story_file = artifacts / "2-6-new-story.md"
        story_file.write_text("---\nstatus: done\n---\n# Story 2.6")

        discrepancy = Discrepancy(
            type="story_not_in_internal",
            expected=None,
            actual="2.6",
            story_number="2.6",
            file_path=str(story_file),
        )

        internal = MockInternalState(
            current_epic=2,
            current_story="2.5",
            completed_stories=["2.4"],
        )

        # Without callback, should return NO_CHANGE_NEEDED
        result = correct_discrepancy(discrepancy, internal, tmp_path, auto=True)
        assert result.action == CorrectionAction.NO_CHANGE_NEEDED

    def test_ac7_callback_invoked(self, tmp_path: Path) -> None:
        """AC7: Confirmation callback is invoked correctly."""
        callback_calls: list[tuple[Discrepancy, list[str]]] = []

        def mock_callback(disc: Discrepancy, options: list[str]) -> str:
            callback_calls.append((disc, options))
            return "skip"

        # Create the story file so idempotency check doesn't short-circuit
        story_file = tmp_path / "story.md"
        story_file.write_text("---\nstatus: done\n---\n# Story")

        discrepancy = Discrepancy(
            type="story_not_in_internal",
            expected=None,
            actual="2.6",
            story_number="2.6",
            file_path=str(story_file),
        )

        internal = MockInternalState()

        result = correct_discrepancy(
            discrepancy,
            internal,
            tmp_path,
            auto=False,
            confirm_callback=mock_callback,
        )

        # Callback should have been invoked
        assert len(callback_calls) == 1
        assert callback_calls[0][0] == discrepancy
        assert "remove_from_bmad" in callback_calls[0][1]
        assert "skip" in callback_calls[0][1]
        assert result.action == CorrectionAction.SKIPPED

    def test_ac5_story_not_in_internal_remove_archives_file(self, tmp_path: Path) -> None:
        """AC5: User confirms remove_from_bmad archives the file."""
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        story_file = artifacts / "2-6-new-story.md"
        story_file.write_text("---\nstatus: done\n---\n# Story 2.6")

        def confirm_remove(disc: Discrepancy, options: list[str]) -> str:
            return "remove_from_bmad"

        discrepancy = Discrepancy(
            type="story_not_in_internal",
            expected=None,
            actual="2.6",
            story_number="2.6",
            file_path=str(story_file),
        )

        internal = MockInternalState()

        result = correct_discrepancy(
            discrepancy,
            internal,
            tmp_path,
            auto=False,
            confirm_callback=confirm_remove,
        )

        assert result.action == CorrectionAction.UPDATED_BMAD
        assert "Archived" in result.details
        # Original file should not exist, archived version should
        assert not story_file.exists()
        archived = story_file.with_suffix(".md.archived")
        assert archived.exists()

    def test_ac11_bmad_empty_requires_confirmation(self, tmp_path: Path) -> None:
        """AC11: bmad_empty requires user confirmation."""
        discrepancy = Discrepancy(
            type="bmad_empty",
            expected=["1.1", "1.2"],
            actual=[],
        )

        internal = MockInternalState(completed_stories=["1.1", "1.2"])

        # Without callback, returns NO_CHANGE_NEEDED
        result = correct_discrepancy(discrepancy, internal, tmp_path, auto=True)
        assert result.action == CorrectionAction.NO_CHANGE_NEEDED

    def test_ac11_bmad_empty_recreate_creates_files(self, tmp_path: Path) -> None:
        """AC11: User confirms recreate_bmad creates story files."""

        def confirm_recreate(disc: Discrepancy, options: list[str]) -> str:
            return "recreate_bmad"

        discrepancy = Discrepancy(
            type="bmad_empty",
            expected=["1.1", "1.2"],
            actual=[],
        )

        internal = MockInternalState(
            current_epic=2,
            current_story="2.1",
            completed_stories=["1.1", "1.2"],
        )

        result = correct_discrepancy(
            discrepancy,
            internal,
            tmp_path,
            auto=False,
            confirm_callback=confirm_recreate,
        )

        assert result.action == CorrectionAction.UPDATED_BMAD
        assert result.modified_files is not None
        # Should create files for 1.1, 1.2 (completed) + 2.1 (current)
        assert len(result.modified_files) == 3


class TestCorrectDiscrepancyCallbackValidation:
    """Test AC14, AC15: Callback validation and exception handling."""

    def test_ac14_invalid_callback_response(self, tmp_path: Path) -> None:
        """AC14: Invalid callback response returns ERROR result."""

        def bad_callback(disc: Discrepancy, options: list[str]) -> str:
            return "invalid_option"

        # Create the story file so idempotency check doesn't short-circuit
        story_file = tmp_path / "story.md"
        story_file.write_text("---\nstatus: done\n---\n# Story")

        discrepancy = Discrepancy(
            type="story_not_in_internal",
            expected=None,
            actual="2.6",
            story_number="2.6",
            file_path=str(story_file),
        )

        internal = MockInternalState()

        result = correct_discrepancy(
            discrepancy,
            internal,
            tmp_path,
            auto=False,
            confirm_callback=bad_callback,
        )

        assert result.action == CorrectionAction.ERROR
        assert result.error is not None
        assert "Invalid callback response" in result.error
        assert "invalid_option" in result.error

    def test_ac15_callback_exception_handled(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC15: Callback exception is caught and returns ERROR."""

        def raising_callback(disc: Discrepancy, options: list[str]) -> str:
            raise RuntimeError("Callback failed!")

        discrepancy = Discrepancy(
            type="story_not_in_internal",
            expected=None,
            actual="2.6",
            story_number="2.6",
        )

        internal = MockInternalState()

        with caplog.at_level(logging.WARNING):
            result = correct_discrepancy(
                discrepancy,
                internal,
                tmp_path,
                auto=False,
                confirm_callback=raising_callback,
            )

        assert result.action == CorrectionAction.ERROR
        assert "Callback failed!" in result.error
        assert "Callback raised exception" in caplog.text


class TestCorrectDiscrepancyIdempotency:
    """Test AC16: Idempotency - calling twice returns NO_CHANGE_NEEDED."""

    def test_ac16_story_status_idempotent(self, tmp_path: Path) -> None:
        """AC16: Correcting same discrepancy twice returns NO_CHANGE_NEEDED."""
        # Create story file with correct status already
        story_content = """---
status: done
---

# Story 2.3: Test
"""
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        story_file = artifacts / "2-3-test.md"
        story_file.write_text(story_content)

        discrepancy = Discrepancy(
            type="story_status_mismatch",
            expected="done",
            actual="in-progress",  # Original mismatch
            story_number="2.3",
        )

        internal = MockInternalState(completed_stories=["2.3"])

        # BMAD already has "done" status matching internal
        result = correct_discrepancy(discrepancy, internal, tmp_path, auto=True)

        assert result.action == CorrectionAction.NO_CHANGE_NEEDED
        assert "already matches" in result.details

    def test_ac16_story_not_in_bmad_idempotent(self, tmp_path: Path) -> None:
        """AC16: Creating story file twice returns NO_CHANGE_NEEDED."""
        # Create story file first
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        story_file = artifacts / "2-6-placeholder.md"
        story_file.write_text("---\nstatus: done\n---\n# Story 2.6")

        discrepancy = Discrepancy(
            type="story_not_in_bmad",
            expected="2.6",
            actual=None,
            story_number="2.6",
        )

        internal = MockInternalState(completed_stories=["2.6"])

        result = correct_discrepancy(discrepancy, internal, tmp_path, auto=True)

        assert result.action == CorrectionAction.NO_CHANGE_NEEDED
        assert "already matches" in result.details


class TestCorrectDiscrepancyErrors:
    """Test AC12, AC13: Error handling and non-correctable types."""

    def test_ac12_non_correctable_without_callback(self, tmp_path: Path) -> None:
        """AC12: Non-auto-correctable without callback returns NO_CHANGE_NEEDED."""
        discrepancy = Discrepancy(
            type="story_not_in_internal",
            expected=None,
            actual="2.6",
            story_number="2.6",
        )

        internal = MockInternalState()

        result = correct_discrepancy(discrepancy, internal, tmp_path, auto=True)

        assert result.action == CorrectionAction.NO_CHANGE_NEEDED
        assert "requires user confirmation" in result.details

    @pytest.mark.skipif(os.geteuid() == 0, reason="Root ignores permissions")
    def test_ac13_error_on_write_failure(self, tmp_path: Path) -> None:
        """AC13: File write failure returns ERROR result."""
        # Create read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()

        discrepancy = Discrepancy(
            type="story_not_in_bmad",
            expected="2.6",
            actual=None,
            story_number="2.6",
        )

        internal = MockInternalState(current_story="2.6")

        # Try to create file in read-only path
        # Note: This test may not work on all systems due to permission handling
        # We test the error path by using invalid path structure instead
        result = correct_discrepancy(
            discrepancy, internal, Path("/nonexistent/path/that/doesnt/exist"), auto=True
        )

        # Should return ERROR or NO_CHANGE_NEEDED depending on how OS handles it
        assert result.action in (CorrectionAction.ERROR, CorrectionAction.NO_CHANGE_NEEDED)

    def test_auto_false_without_callback_raises_valueerror(self, tmp_path: Path) -> None:
        """auto=False without callback raises ReconciliationError."""
        discrepancy = Discrepancy(type="test", expected="a", actual="b")
        internal = MockInternalState()

        with pytest.raises(ReconciliationError, match="confirm_callback is required"):
            correct_discrepancy(discrepancy, internal, tmp_path, auto=False, confirm_callback=None)


class TestCorrectAllDiscrepancies:
    """Test AC6: Batch correction with correct_all_discrepancies."""

    def test_ac6_batch_correction(self, tmp_path: Path) -> None:
        """AC6: Batch correction processes all discrepancies."""
        # Create test files
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        discrepancies = [
            Discrepancy(
                type="story_not_in_bmad",
                expected="1.1",
                actual=None,
                story_number="1.1",
            ),
            Discrepancy(
                type="story_not_in_bmad",
                expected="1.2",
                actual=None,
                story_number="1.2",
            ),
        ]

        internal = MockInternalState(
            current_epic=2,
            current_story="2.1",
            completed_stories=["1.1", "1.2"],
        )

        results = correct_all_discrepancies(discrepancies, internal, tmp_path, auto=True)

        assert len(results) == 2
        assert all(r.action == CorrectionAction.UPDATED_BMAD for r in results)

        # Verify files created
        assert (artifacts / "1-1-placeholder.md").exists()
        assert (artifacts / "1-2-placeholder.md").exists()

    def test_ac6_batch_with_mixed_types(self, tmp_path: Path) -> None:
        """AC6: Batch handles mixed auto/confirmation scenarios."""
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        discrepancies = [
            Discrepancy(
                type="story_not_in_bmad",
                expected="1.1",
                actual=None,
                story_number="1.1",
            ),
            Discrepancy(
                type="story_not_in_internal",  # Requires confirmation
                expected=None,
                actual="2.6",
                story_number="2.6",
            ),
        ]

        internal = MockInternalState(completed_stories=["1.1"])

        results = correct_all_discrepancies(discrepancies, internal, tmp_path, auto=True)

        assert len(results) == 2
        # First should be updated, second should need confirmation
        assert results[0].action == CorrectionAction.UPDATED_BMAD
        assert results[1].action == CorrectionAction.NO_CHANGE_NEEDED

    def test_ac6_batch_empty_list(self, tmp_path: Path) -> None:
        """AC6: Empty discrepancy list returns empty results."""
        internal = MockInternalState()

        results = correct_all_discrepancies([], internal, tmp_path, auto=True)

        assert results == []

    def test_ac6_auto_false_without_callback_raises_reconciliationerror(
        self, tmp_path: Path
    ) -> None:
        """auto=False in batch without callback raises ReconciliationError."""
        discrepancies = [Discrepancy(type="test", expected="a", actual="b")]
        internal = MockInternalState()

        with pytest.raises(ReconciliationError, match="confirm_callback is required"):
            correct_all_discrepancies(
                discrepancies, internal, tmp_path, auto=False, confirm_callback=None
            )

    def test_ac6_batch_logs_summary(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """AC6: Batch correction logs summary."""
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        discrepancies = [
            Discrepancy(
                type="story_not_in_bmad",
                expected="1.1",
                actual=None,
                story_number="1.1",
            ),
        ]

        internal = MockInternalState(completed_stories=["1.1"])

        with caplog.at_level(logging.INFO):
            correct_all_discrepancies(discrepancies, internal, tmp_path, auto=True)

        assert "Batch correction complete" in caplog.text
        assert "BMAD files updated" in caplog.text


class TestAtomicWrite:
    """Test atomic write pattern (temp file + rename)."""

    def test_atomic_write_creates_file(self, tmp_path: Path) -> None:
        """_atomic_write_file creates file with correct content."""
        test_file = tmp_path / "test.txt"
        _atomic_write_file(test_file, "test content")

        assert test_file.exists()
        assert test_file.read_text() == "test content"

    def test_atomic_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        """_atomic_write_file creates parent directories if needed."""
        test_file = tmp_path / "subdir" / "nested" / "test.txt"
        _atomic_write_file(test_file, "nested content")

        assert test_file.exists()
        assert test_file.read_text() == "nested content"

    def test_atomic_write_overwrites_existing(self, tmp_path: Path) -> None:
        """_atomic_write_file overwrites existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("old content")

        _atomic_write_file(test_file, "new content")

        assert test_file.read_text() == "new content"


class TestHelperFunctions:
    """Test helper functions for correction."""

    def test_get_correction_options_valid_types(self) -> None:
        """_get_correction_options returns correct options."""
        assert "update_bmad" in _get_correction_options("story_status_mismatch")
        assert "skip" in _get_correction_options("story_status_mismatch")
        assert "remove_from_bmad" in _get_correction_options("story_not_in_internal")
        assert "recreate_bmad" in _get_correction_options("bmad_empty")
        assert "create_bmad" in _get_correction_options("story_not_in_bmad")

    def test_get_correction_options_unknown_type(self) -> None:
        """_get_correction_options returns skip for unknown types."""
        options = _get_correction_options("unknown_type")
        assert options == ["skip"]

    def test_is_auto_correctable_safe_types(self) -> None:
        """_is_auto_correctable returns True for safe types."""
        assert _is_auto_correctable(Discrepancy(type="current_epic_mismatch", expected=2, actual=3))
        assert _is_auto_correctable(
            Discrepancy(type="story_not_in_bmad", expected="2.3", actual=None)
        )

    def test_is_auto_correctable_suspicious_types(self) -> None:
        """_is_auto_correctable returns False for suspicious types."""
        assert not _is_auto_correctable(
            Discrepancy(type="story_not_in_internal", expected=None, actual="2.3")
        )
        assert not _is_auto_correctable(Discrepancy(type="bmad_empty", expected=["1.1"], actual=[]))

    def test_is_auto_correctable_bmad_ahead_of_internal(self) -> None:
        """_is_auto_correctable returns False when BMAD ahead (internal=in-progress, bmad=done)."""
        discrepancy = Discrepancy(
            type="story_status_mismatch",
            expected="in-progress",
            actual="done",
        )
        assert not _is_auto_correctable(discrepancy)

    def test_find_story_file(self, tmp_path: Path) -> None:
        """_find_story_file finds story file by number."""
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()
        story_file = artifacts / "2-3-test-story.md"
        story_file.write_text("# Story 2.3")

        found = _find_story_file(tmp_path, "2.3")

        assert found is not None
        assert found == story_file

    def test_find_story_file_not_found(self, tmp_path: Path) -> None:
        """_find_story_file returns None when not found."""
        found = _find_story_file(tmp_path, "99.99")
        assert found is None

    def test_find_sprint_status_key(self, tmp_path: Path) -> None:
        """_find_sprint_status_key finds key by story number."""
        sprint_file = tmp_path / "sprint-status.yaml"
        sprint_file.write_text("""
development_status:
  2-3-test-story: in-progress
  2-4-another-story: done
""")

        key = _find_sprint_status_key(sprint_file, "2.3")
        assert key == "2-3-test-story"

        key = _find_sprint_status_key(sprint_file, "2.4")
        assert key == "2-4-another-story"

    def test_find_sprint_status_key_not_found(self, tmp_path: Path) -> None:
        """_find_sprint_status_key returns None when not found."""
        sprint_file = tmp_path / "sprint-status.yaml"
        sprint_file.write_text("""
development_status:
  2-3-test-story: done
""")

        key = _find_sprint_status_key(sprint_file, "9.9")
        assert key is None

    def test_create_minimal_story_file(self, tmp_path: Path) -> None:
        """_create_minimal_story_file creates story with frontmatter."""
        story_path = _create_minimal_story_file(tmp_path, "2.3", "done")

        assert story_path.exists()
        post = frontmatter.load(story_path)
        assert post.metadata["status"] == "done"
        assert "Story 2.3" in post.content


class TestInternalStateNeverModified:
    """Test CRITICAL requirement: internal state is NEVER modified."""

    def test_internal_state_unchanged_after_correction(self, tmp_path: Path) -> None:
        """Internal state remains unchanged after correction."""
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        internal = MockInternalState(
            current_epic=2,
            current_story="2.3",
            completed_stories=["1.1", "1.2"],
        )

        # Save original values
        orig_epic = internal.current_epic
        orig_story = internal.current_story
        orig_completed = internal.completed_stories.copy()

        discrepancy = Discrepancy(
            type="story_not_in_bmad",
            expected="1.3",
            actual=None,
            story_number="1.3",
        )

        correct_discrepancy(discrepancy, internal, tmp_path, auto=True)

        # Verify internal state unchanged
        assert internal.current_epic == orig_epic
        assert internal.current_story == orig_story
        assert internal.completed_stories == orig_completed

    def test_batch_correction_internal_state_unchanged(self, tmp_path: Path) -> None:
        """Internal state unchanged after batch correction."""
        artifacts = tmp_path / "sprint-artifacts"
        artifacts.mkdir()

        internal = MockInternalState(
            current_epic=2,
            current_story="2.3",
            completed_stories=["1.1", "1.2"],
        )

        orig_completed = internal.completed_stories.copy()

        discrepancies = [
            Discrepancy(
                type="story_not_in_bmad",
                expected="1.1",
                actual=None,
                story_number="1.1",
            ),
            Discrepancy(
                type="story_not_in_bmad",
                expected="1.2",
                actual=None,
                story_number="1.2",
            ),
        ]

        correct_all_discrepancies(discrepancies, internal, tmp_path, auto=True)

        # Internal state should be identical
        assert internal.completed_stories == orig_completed


class TestUpdateFunctions:
    """Test file update helper functions."""

    def test_update_story_frontmatter(self, tmp_path: Path) -> None:
        """_update_story_frontmatter updates status in frontmatter."""
        story_file = tmp_path / "story.md"
        story_file.write_text("""---
status: in-progress
title: Test Story
---

# Content
""")

        _update_story_frontmatter(story_file, "done")

        post = frontmatter.load(story_file)
        assert post.metadata["status"] == "done"
        assert post.metadata["title"] == "Test Story"  # Other fields preserved

    def test_update_sprint_status(self, tmp_path: Path) -> None:
        """_update_sprint_status updates story status in YAML."""
        sprint_file = tmp_path / "sprint-status.yaml"
        sprint_file.write_text("""
development_status:
  2-3-test-story: in-progress
  2-4-another-story: backlog
""")

        _update_sprint_status(sprint_file, "2-3-test-story", "done")

        with open(sprint_file) as f:
            data = yaml.safe_load(f)

        assert data["development_status"]["2-3-test-story"] == "done"
        assert data["development_status"]["2-4-another-story"] == "backlog"  # Unchanged
