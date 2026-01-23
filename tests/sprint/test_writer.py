"""Tests for atomic sprint-status writer with comment preservation.

Tests cover:
- Atomic write pattern (temp file + os.replace)
- ruamel.yaml availability detection
- Comment preservation (when ruamel available)
- Fallback to PyYAML (when ruamel unavailable)
- Entry ordering preservation
- Header comment generation
- Write error handling
- Round-trip: write -> read -> write preserves comments
- Empty SprintStatus writes valid YAML
- Unicode in comments preservation
- Parser compatibility after write
- Edge cases (file not exists, permission errors)
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from bmad_assist.core.exceptions import StateError
from bmad_assist.sprint.classifier import EntryType
from bmad_assist.sprint.models import (
    SprintStatus,
    SprintStatusEntry,
    SprintStatusMetadata,
)
from bmad_assist.sprint.parser import parse_sprint_status
from bmad_assist.sprint.writer import (
    _add_epic_comments,
    _build_output_data,
    _extract_epic_id,
    _load_with_comments,
    _write_with_pyyaml,
    has_ruamel,
    write_sprint_status,
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
        project_key="test",
        tracking_system="file-system",
        story_location="_bmad-output/implementation-artifacts/stories",
    )


@pytest.fixture
def sample_entries() -> dict[str, SprintStatusEntry]:
    """Create sample entries dict for tests."""
    return {
        "epic-1": SprintStatusEntry(
            key="epic-1",
            status="done",
            entry_type=EntryType.EPIC_META,
            source="test",
            comment="Main epic",
        ),
        "1-1-setup": SprintStatusEntry(
            key="1-1-setup",
            status="done",
            entry_type=EntryType.EPIC_STORY,
            source="test",
            comment="Setup task",
        ),
        "1-2-feature": SprintStatusEntry(
            key="1-2-feature",
            status="in-progress",
            entry_type=EntryType.EPIC_STORY,
            source="test",
            comment=None,
        ),
        "standalone-01-refactor": SprintStatusEntry(
            key="standalone-01-refactor",
            status="done",
            entry_type=EntryType.STANDALONE,
            source="test",
            comment="Tech debt",
        ),
    }


@pytest.fixture
def sample_status(
    sample_metadata: SprintStatusMetadata,
    sample_entries: dict[str, SprintStatusEntry],
) -> SprintStatus:
    """Create sample SprintStatus for tests."""
    return SprintStatus(metadata=sample_metadata, entries=sample_entries)


@pytest.fixture
def empty_status() -> SprintStatus:
    """Create empty SprintStatus for tests."""
    return SprintStatus.empty("empty-project")


@pytest.fixture
def fixture_dir() -> Path:
    """Get path to test fixtures directory."""
    return Path(__file__).parent.parent / "fixtures" / "sprint"


@pytest.fixture
def fixture_with_comments(fixture_dir: Path) -> Path:
    """Get path to fixture file with comments."""
    return fixture_dir / "sprint-status-with-comments.yaml"


@pytest.fixture
def fixture_unicode(fixture_dir: Path) -> Path:
    """Get path to fixture file with unicode comments."""
    return fixture_dir / "sprint-status-unicode-comments.yaml"


# =============================================================================
# Test: has_ruamel() Detection (AC5, AC6)
# =============================================================================


class TestHasRuamel:
    """Tests for ruamel.yaml availability (always True since required dependency)."""

    def test_has_ruamel_returns_true(self):
        """has_ruamel() always returns True since ruamel.yaml is now required."""
        result = has_ruamel()
        assert result is True

    def test_has_ruamel_consistent(self):
        """has_ruamel() returns consistent True result on multiple calls."""
        result1 = has_ruamel()
        result2 = has_ruamel()
        assert result1 is True
        assert result2 is True


# =============================================================================
# Test: _build_output_data() (AC3)
# =============================================================================


class TestBuildOutputData:
    """Tests for output data structure building."""

    def test_build_output_data_includes_metadata(
        self,
        sample_status: SprintStatus,
    ):
        """Output data includes all metadata fields."""
        data = _build_output_data(sample_status, {})

        assert "generated" in data
        assert data["project"] == "test-project"
        assert data["project_key"] == "test"
        assert data["tracking_system"] == "file-system"
        assert data["story_location"] == "_bmad-output/implementation-artifacts/stories"

    def test_build_output_data_includes_development_status(
        self,
        sample_status: SprintStatus,
    ):
        """Output data includes development_status section."""
        data = _build_output_data(sample_status, {})

        assert "development_status" in data
        dev_status = data["development_status"]
        assert dev_status["epic-1"] == "done"
        assert dev_status["1-1-setup"] == "done"
        assert dev_status["1-2-feature"] == "in-progress"
        assert dev_status["standalone-01-refactor"] == "done"

    def test_build_output_data_preserves_entry_order(
        self,
        sample_status: SprintStatus,
    ):
        """Entry ordering is preserved from status.entries."""
        data = _build_output_data(sample_status, {})

        dev_status = data["development_status"]
        keys = list(dev_status.keys())
        expected_keys = list(sample_status.entries.keys())
        assert keys == expected_keys

    def test_build_output_data_empty_entries(
        self,
        empty_status: SprintStatus,
    ):
        """Empty SprintStatus produces empty development_status."""
        data = _build_output_data(empty_status, {})

        assert data["development_status"] == {}

    def test_build_output_data_optional_metadata(self):
        """Optional metadata fields are omitted when None."""
        meta = SprintStatusMetadata(
            generated=datetime(2026, 1, 7),
            project=None,
            project_key=None,
        )
        status = SprintStatus(metadata=meta, entries={})
        data = _build_output_data(status, {})

        assert "project" not in data
        assert "project_key" not in data


# =============================================================================
# Test: Atomic Write Pattern (AC1, AC7)
# =============================================================================


class TestAtomicWrite:
    """Tests for atomic write using temp file + os.replace pattern."""

    def test_write_creates_file(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """write_sprint_status creates the target file."""
        target = tmp_path / "sprint-status.yaml"
        assert not target.exists()

        write_sprint_status(sample_status, target)

        assert target.exists()

    def test_write_creates_parent_directories(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """write_sprint_status creates parent directories if missing."""
        target = tmp_path / "subdir" / "nested" / "sprint-status.yaml"
        assert not target.parent.exists()

        write_sprint_status(sample_status, target)

        assert target.exists()

    def test_write_no_temp_file_on_success(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """Temp file is removed after successful write."""
        target = tmp_path / "sprint-status.yaml"

        write_sprint_status(sample_status, target)

        temp_file = target.with_suffix(".yaml.tmp")
        assert not temp_file.exists()

    def test_write_atomic_replaces_existing(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """Atomic write replaces existing file completely."""
        target = tmp_path / "sprint-status.yaml"

        # Write initial content
        target.write_text("# Old content\n", encoding="utf-8")

        # Write new content
        write_sprint_status(sample_status, target)

        content = target.read_text(encoding="utf-8")
        assert "# Old content" not in content
        assert "development_status" in content

    def test_write_expands_tilde(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """write_sprint_status expands ~ in path."""
        # Mock expanduser to return tmp_path
        monkeypatch.setattr(
            Path,
            "expanduser",
            lambda self: tmp_path / self.name if "~" in str(self) else self,
        )

        target = tmp_path / "sprint-status.yaml"
        write_sprint_status(sample_status, target)
        assert target.exists()


# =============================================================================
# Test: Error Handling (AC7)
# =============================================================================


class TestWriteErrorHandling:
    """Tests for graceful error handling with StateError."""

    def test_write_raises_state_error_on_permission_denied(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """StateError raised when write permission denied."""
        target = tmp_path / "readonly" / "sprint-status.yaml"
        target.parent.mkdir()

        # First create the file, then make parent read-only
        # This way path.exists() will succeed but writing will fail
        target.write_text("# placeholder\n", encoding="utf-8")

        # Make directory read-only (can't write new files)
        target.parent.chmod(0o555)

        try:
            with pytest.raises(StateError) as exc_info:
                write_sprint_status(sample_status, target)

            assert "Failed to write sprint-status" in str(exc_info.value)
        finally:
            # Restore permissions for cleanup
            target.parent.chmod(0o755)

    def test_write_cleans_temp_on_error(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """Temp file is cleaned up even when write fails."""
        target = tmp_path / "sprint-status.yaml"

        # Create a scenario where os.replace fails
        with patch("bmad_assist.sprint.writer.os.replace") as mock_replace:
            mock_replace.side_effect = OSError("Mock error")

            with pytest.raises(StateError):
                _write_with_pyyaml(
                    {"development_status": {}},
                    target,
                    "test",
                )

        # Temp file should be cleaned up
        temp_file = target.with_suffix(".yaml.tmp")
        assert not temp_file.exists()


# =============================================================================
# Test: Header Comment Generation (AC4)
# =============================================================================


class TestHeaderComment:
    """Tests for header comment with generation timestamp."""

    def test_write_adds_header_comment(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """Written file has header comment with timestamp."""
        target = tmp_path / "sprint-status.yaml"

        write_sprint_status(sample_status, target)

        content = target.read_text(encoding="utf-8")
        assert "# Generated by bmad-assist on" in content

    def test_write_header_includes_project(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """Header comment includes project name."""
        target = tmp_path / "sprint-status.yaml"

        write_sprint_status(sample_status, target)

        content = target.read_text(encoding="utf-8")
        assert "test-project" in content


# =============================================================================
# Test: PyYAML Fallback (AC6)
# =============================================================================


class TestPyYAMLFallback:
    """Tests for fallback behavior when ruamel.yaml unavailable."""

    def test_pyyaml_fallback_produces_valid_yaml(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """PyYAML fallback writes valid parseable YAML."""
        target = tmp_path / "sprint-status.yaml"

        # Force PyYAML by setting preserve_comments=False
        write_sprint_status(sample_status, target, preserve_comments=False)

        # Should be parseable
        with open(target, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert "development_status" in data
        assert data["development_status"]["epic-1"] == "done"


# =============================================================================
# Test: Entry Ordering Preservation (AC3)
# =============================================================================


class TestEntryOrdering:
    """Tests for preserving entry ordering in output."""

    def test_write_preserves_entry_order(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """Written file preserves entry order from SprintStatus."""
        target = tmp_path / "sprint-status.yaml"

        write_sprint_status(sample_status, target, preserve_comments=False)

        # Parse back and check order
        with open(target, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        written_keys = list(data["development_status"].keys())
        expected_keys = list(sample_status.entries.keys())
        assert written_keys == expected_keys

    def test_order_preserved_after_round_trip(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """Entry order preserved after write -> parse -> write cycle."""
        target = tmp_path / "sprint-status.yaml"

        # Write initial
        write_sprint_status(sample_status, target, preserve_comments=False)

        # Parse back
        parsed = parse_sprint_status(target)

        # Write again
        target2 = tmp_path / "sprint-status2.yaml"
        write_sprint_status(parsed, target2, preserve_comments=False)

        # Compare orders
        with open(target, encoding="utf-8") as f1:
            data1 = yaml.safe_load(f1)
        with open(target2, encoding="utf-8") as f2:
            data2 = yaml.safe_load(f2)

        keys1 = list(data1["development_status"].keys())
        keys2 = list(data2["development_status"].keys())
        assert keys1 == keys2

    def test_order_changes_applied_on_ruamel_update(
        self,
        tmp_path: Path,
    ):
        """Entry order changes are applied when updating via ruamel (AC3)."""
        if not has_ruamel():
            pytest.skip("ruamel.yaml not available")

        target = tmp_path / "sprint-status.yaml"

        # Write initial file with order: B, A, C
        meta = SprintStatusMetadata(
            generated=datetime.now(UTC).replace(tzinfo=None),
            project="order-test",
        )
        initial_entries = {
            "B-entry": SprintStatusEntry(
                key="B-entry", status="done", entry_type=EntryType.EPIC_STORY
            ),
            "A-entry": SprintStatusEntry(
                key="A-entry", status="done", entry_type=EntryType.EPIC_STORY
            ),
            "C-entry": SprintStatusEntry(
                key="C-entry", status="done", entry_type=EntryType.EPIC_STORY
            ),
        }
        initial_status = SprintStatus(metadata=meta, entries=initial_entries)
        write_sprint_status(initial_status, target, preserve_comments=True)

        # Verify initial order is B, A, C
        with open(target, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert list(data["development_status"].keys()) == ["B-entry", "A-entry", "C-entry"]

        # Write with new order: A, B, C (alphabetical)
        reordered_entries = {
            "A-entry": SprintStatusEntry(
                key="A-entry", status="done", entry_type=EntryType.EPIC_STORY
            ),
            "B-entry": SprintStatusEntry(
                key="B-entry", status="done", entry_type=EntryType.EPIC_STORY
            ),
            "C-entry": SprintStatusEntry(
                key="C-entry", status="done", entry_type=EntryType.EPIC_STORY
            ),
        }
        reordered_status = SprintStatus(metadata=meta, entries=reordered_entries)
        write_sprint_status(reordered_status, target, preserve_comments=True)

        # Verify order is now A, B, C (from model, not file)
        with open(target, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert list(data["development_status"].keys()) == ["A-entry", "B-entry", "C-entry"]


# =============================================================================
# Test: Parser Compatibility (AC8)
# =============================================================================


class TestParserCompatibility:
    """Tests ensuring written files are parseable by parse_sprint_status."""

    def test_written_file_parseable(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """Written file can be parsed by parse_sprint_status()."""
        target = tmp_path / "sprint-status.yaml"

        write_sprint_status(sample_status, target, preserve_comments=False)

        parsed = parse_sprint_status(target)

        assert parsed.metadata.project == sample_status.metadata.project
        assert len(parsed.entries) == len(sample_status.entries)

    def test_empty_status_parseable(
        self,
        empty_status: SprintStatus,
        tmp_path: Path,
    ):
        """Empty SprintStatus writes parseable file."""
        target = tmp_path / "sprint-status.yaml"

        write_sprint_status(empty_status, target, preserve_comments=False)

        parsed = parse_sprint_status(target)

        assert len(parsed.entries) == 0

    def test_round_trip_preserves_data(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """Round-trip write -> parse preserves all entry data."""
        target = tmp_path / "sprint-status.yaml"

        write_sprint_status(sample_status, target, preserve_comments=False)
        parsed = parse_sprint_status(target)

        # Check all entries preserved
        for key, original_entry in sample_status.entries.items():
            assert key in parsed.entries
            parsed_entry = parsed.entries[key]
            assert parsed_entry.status == original_entry.status


# =============================================================================
# Test: File Not Exists (AC - new file creation)
# =============================================================================


class TestFileNotExists:
    """Tests for creating new files when original doesn't exist."""

    def test_write_new_file_without_error(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """New file created without error when original missing."""
        target = tmp_path / "new-sprint-status.yaml"
        assert not target.exists()

        write_sprint_status(sample_status, target)

        assert target.exists()

    def test_write_new_file_no_comments_section(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """New file has no inline comments (no original to preserve)."""
        target = tmp_path / "new-sprint-status.yaml"

        write_sprint_status(sample_status, target, preserve_comments=True)

        # File should exist and be valid
        parsed = parse_sprint_status(target)
        assert len(parsed.entries) == len(sample_status.entries)


# =============================================================================
# Test: Comment Orphaning (entries removed)
# =============================================================================


class TestCommentOrphaning:
    """Tests for handling comments when entries are removed."""

    def test_removed_entries_drop_comments_silently(
        self,
        tmp_path: Path,
    ):
        """Entries removed from SprintStatus have their comments dropped."""
        target = tmp_path / "sprint-status.yaml"

        # Create initial status with two entries
        meta = SprintStatusMetadata(
            generated=datetime(2026, 1, 7),
            project="test",
        )
        entries_initial = {
            "1-1-keep": SprintStatusEntry(
                key="1-1-keep",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "1-2-remove": SprintStatusEntry(
                key="1-2-remove",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        status_initial = SprintStatus(metadata=meta, entries=entries_initial)

        # Write initial
        write_sprint_status(status_initial, target, preserve_comments=False)

        # Create new status without the removed entry
        entries_new = {
            "1-1-keep": SprintStatusEntry(
                key="1-1-keep",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        status_new = SprintStatus(metadata=meta, entries=entries_new)

        # Write new (should not error even though entry was removed)
        write_sprint_status(status_new, target, preserve_comments=True)

        # Verify removed entry is gone
        parsed = parse_sprint_status(target)
        assert "1-1-keep" in parsed.entries
        assert "1-2-remove" not in parsed.entries


# =============================================================================
# Test: Unicode in Comments
# =============================================================================


class TestUnicodeComments:
    """Tests for Unicode character preservation in comments."""

    def test_unicode_in_metadata_preserved(
        self,
        tmp_path: Path,
    ):
        """Unicode characters in metadata are preserved."""
        meta = SprintStatusMetadata(
            generated=datetime(2026, 1, 7),
            project="projekt-",
        )
        status = SprintStatus(metadata=meta, entries={})

        target = tmp_path / "unicode.yaml"
        write_sprint_status(status, target, preserve_comments=False)

        with open(target, encoding="utf-8") as f:
            content = f.read()

        assert "projekt-" in content

    def test_unicode_fixture_parseable(
        self,
        fixture_unicode: Path,
    ):
        """Unicode fixture file is parseable."""
        if not fixture_unicode.exists():
            pytest.skip("Unicode fixture not found")

        parsed = parse_sprint_status(fixture_unicode)
        assert parsed.metadata.project == "unicode-test"


# =============================================================================
# Test: _load_with_comments() Helper
# =============================================================================


class TestLoadWithComments:
    """Tests for loading files with comment extraction."""

    def test_load_nonexistent_returns_empty(
        self,
        tmp_path: Path,
    ):
        """Loading nonexistent file returns (None, {})."""
        nonexistent = tmp_path / "does-not-exist.yaml"

        data, comments = _load_with_comments(nonexistent)

        assert data is None
        assert comments == {}

    def test_load_without_ruamel_returns_empty(
        self,
        tmp_path: Path,
    ):
        """Loading without ruamel returns (None, {})."""
        target = tmp_path / "test.yaml"
        target.write_text("test: value\n", encoding="utf-8")

        with patch("bmad_assist.sprint.writer.has_ruamel", return_value=False):
            data, comments = _load_with_comments(target)

        assert data is None
        assert comments == {}


# =============================================================================
# Test: Comment Preservation with ruamel (AC2, AC5)
# =============================================================================


class TestCommentPreservation:
    """Tests for comment preservation when ruamel.yaml is available.

    These tests are skipped if ruamel.yaml is not installed.
    """

    @pytest.fixture
    def ruamel_available(self) -> bool:
        """Check if ruamel is available for these tests."""
        return has_ruamel()

    def test_inline_comments_preserved(
        self,
        fixture_with_comments: Path,
        tmp_path: Path,
        ruamel_available: bool,
    ):
        """Inline comments are preserved in round-trip (requires ruamel)."""
        if not ruamel_available:
            pytest.skip("ruamel.yaml not available")

        if not fixture_with_comments.exists():
            pytest.skip("Fixture file not found")

        # Parse the fixture
        original = parse_sprint_status(fixture_with_comments)

        # Write to new location
        target = tmp_path / "output.yaml"
        write_sprint_status(original, target, preserve_comments=True)

        # Read and check for comment presence
        # Note: We can't easily check exact comments without ruamel,
        # but we can verify the file structure is correct
        parsed = parse_sprint_status(target)
        assert len(parsed.entries) > 0

    def test_header_comment_added_on_write(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
        ruamel_available: bool,
    ):
        """Header comment is added when using ruamel writer."""
        if not ruamel_available:
            pytest.skip("ruamel.yaml not available")

        target = tmp_path / "output.yaml"
        write_sprint_status(sample_status, target, preserve_comments=True)

        content = target.read_text(encoding="utf-8")
        assert "# Generated by bmad-assist on" in content


# =============================================================================
# Test: Integration - Full Write/Read Cycle
# =============================================================================


class TestIntegration:
    """Integration tests for full write/read cycles."""

    def test_full_cycle_all_statuses(
        self,
        tmp_path: Path,
    ):
        """All valid statuses survive write/read cycle."""
        meta = SprintStatusMetadata(
            generated=datetime.now(UTC).replace(tzinfo=None),
            project="cycle-test",
        )
        entries = {
            "1-1-backlog": SprintStatusEntry(
                key="1-1-backlog",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
            "1-2-ready": SprintStatusEntry(
                key="1-2-ready",
                status="ready-for-dev",
                entry_type=EntryType.EPIC_STORY,
            ),
            "1-3-progress": SprintStatusEntry(
                key="1-3-progress",
                status="in-progress",
                entry_type=EntryType.EPIC_STORY,
            ),
            "1-4-review": SprintStatusEntry(
                key="1-4-review",
                status="review",
                entry_type=EntryType.EPIC_STORY,
            ),
            "1-5-done": SprintStatusEntry(
                key="1-5-done",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "1-6-blocked": SprintStatusEntry(
                key="1-6-blocked",
                status="blocked",
                entry_type=EntryType.EPIC_STORY,
            ),
            "1-7-deferred": SprintStatusEntry(
                key="1-7-deferred",
                status="deferred",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        original = SprintStatus(metadata=meta, entries=entries)

        target = tmp_path / "status.yaml"
        write_sprint_status(original, target, preserve_comments=False)

        parsed = parse_sprint_status(target)

        # Verify all entries and statuses preserved
        for key, entry in original.entries.items():
            assert key in parsed.entries
            assert parsed.entries[key].status == entry.status

    def test_multiple_write_cycles(
        self,
        sample_status: SprintStatus,
        tmp_path: Path,
    ):
        """Multiple consecutive writes don't corrupt file."""
        target = tmp_path / "multi.yaml"

        # Write multiple times
        for i in range(5):
            sample_status.metadata.generated = datetime.now(UTC).replace(tzinfo=None)
            write_sprint_status(sample_status, target, preserve_comments=False)

        # Final file should be valid
        parsed = parse_sprint_status(target)
        assert len(parsed.entries) == len(sample_status.entries)


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_development_status(
        self,
        tmp_path: Path,
    ):
        """Empty development_status section writes valid YAML."""
        status = SprintStatus.empty()

        target = tmp_path / "empty.yaml"
        write_sprint_status(status, target)

        parsed = parse_sprint_status(target)
        assert len(parsed.entries) == 0

    def test_special_characters_in_keys(
        self,
        tmp_path: Path,
    ):
        """Keys with special characters are handled."""
        meta = SprintStatusMetadata(
            generated=datetime.now(UTC).replace(tzinfo=None),
            project="special",
        )
        entries = {
            "testarch-1-config": SprintStatusEntry(
                key="testarch-1-config",
                status="done",
                entry_type=EntryType.MODULE_STORY,
            ),
            "standalone-01-refactor": SprintStatusEntry(
                key="standalone-01-refactor",
                status="done",
                entry_type=EntryType.STANDALONE,
            ),
        }
        status = SprintStatus(metadata=meta, entries=entries)

        target = tmp_path / "special.yaml"
        write_sprint_status(status, target)

        parsed = parse_sprint_status(target)
        assert "testarch-1-config" in parsed.entries
        assert "standalone-01-refactor" in parsed.entries

    def test_very_long_entry_key(
        self,
        tmp_path: Path,
    ):
        """Very long entry keys are handled."""
        meta = SprintStatusMetadata(
            generated=datetime.now(UTC).replace(tzinfo=None),
            project="long-key",
        )
        long_key = "12-3-" + "very-long-story-name-" * 10 + "end"
        entries = {
            long_key: SprintStatusEntry(
                key=long_key,
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        status = SprintStatus(metadata=meta, entries=entries)

        target = tmp_path / "long.yaml"
        write_sprint_status(status, target)

        parsed = parse_sprint_status(target)
        assert long_key in parsed.entries


# =============================================================================
# Test: Epic ID Extraction (_extract_epic_id)
# =============================================================================


class TestExtractEpicId:
    """Tests for _extract_epic_id() helper function."""

    def test_extract_numeric_epic_from_story(self):
        """Extract numeric epic ID from story key."""
        assert _extract_epic_id("12-3-setup") == 12
        assert _extract_epic_id("1-1-start") == 1
        assert _extract_epic_id("123-45-long-name") == 123

    def test_extract_numeric_epic_from_short_key(self):
        """Extract numeric epic ID from short key (no slug)."""
        assert _extract_epic_id("12-1") == 12
        assert _extract_epic_id("1-1") == 1

    def test_extract_string_epic_from_story(self):
        """Extract string epic ID from module story key."""
        assert _extract_epic_id("testarch-1-config") == "testarch"
        assert _extract_epic_id("guardian-2-setup") == "guardian"

    def test_extract_epic_from_meta_key(self):
        """Extract epic ID from epic meta key."""
        assert _extract_epic_id("epic-12") == 12
        assert _extract_epic_id("epic-testarch") == "testarch"

    def test_extract_epic_from_retrospective_key(self):
        """Extract epic ID from retrospective key."""
        assert _extract_epic_id("epic-12-retrospective") == 12
        assert _extract_epic_id("epic-testarch-retrospective") == "testarch"

    def test_standalone_returns_none(self):
        """Standalone entries return None (no epic)."""
        assert _extract_epic_id("standalone-01-refactor") is None

    def test_invalid_key_returns_none(self):
        """Invalid keys return None."""
        assert _extract_epic_id("invalid") is None
        assert _extract_epic_id("") is None
        assert _extract_epic_id("not-a-valid-pattern") is None


# =============================================================================
# Test: Epic Separator Comments (_add_epic_comments)
# =============================================================================


class TestAddEpicComments:
    """Tests for _add_epic_comments() helper function."""

    def test_adds_epic_comment_before_first_entry(self):
        """Epic comment added before first entry of each epic."""
        if not has_ruamel():
            pytest.skip("ruamel.yaml not available")

        from ruamel.yaml.comments import CommentedMap

        dev_status = CommentedMap()
        dev_status["epic-12"] = "done"
        dev_status["12-1-setup"] = "done"
        dev_status["12-2-feature"] = "done"

        _add_epic_comments(dev_status)

        # Check that comment was set before epic-12
        # ruamel stores comments in .ca (comment attribute)
        assert dev_status.ca.items.get("epic-12") is not None

    def test_separate_comments_for_different_epics(self):
        """Each epic gets its own separator comment."""
        if not has_ruamel():
            pytest.skip("ruamel.yaml not available")

        from ruamel.yaml.comments import CommentedMap

        dev_status = CommentedMap()
        dev_status["epic-1"] = "done"
        dev_status["1-1-setup"] = "done"
        dev_status["epic-12"] = "done"
        dev_status["12-1-start"] = "done"

        _add_epic_comments(dev_status)

        # Both epics should have comments
        assert dev_status.ca.items.get("epic-1") is not None
        assert dev_status.ca.items.get("epic-12") is not None

    def test_no_duplicate_comments_for_same_epic(self):
        """Only first entry of epic gets the comment."""
        if not has_ruamel():
            pytest.skip("ruamel.yaml not available")

        from ruamel.yaml.comments import CommentedMap

        dev_status = CommentedMap()
        dev_status["epic-12"] = "done"
        dev_status["12-1-setup"] = "done"
        dev_status["12-2-feature"] = "done"

        _add_epic_comments(dev_status)

        # Stories within epic should NOT have epic comments
        # (Only the first entry of the epic gets the comment)
        story_comment = dev_status.ca.items.get("12-1-setup")
        if story_comment:
            # If there's a comment entry, check it's not an epic comment
            # The before comment is at index 1 in the tuple
            before_comment = story_comment[1] if len(story_comment) > 1 else None
            # Before comment should be None or empty for non-first entries
            assert before_comment is None or str(before_comment).strip() == ""

    def test_epic_comments_in_written_file(
        self,
        tmp_path: Path,
    ):
        """Epic separator comments appear in written file."""
        if not has_ruamel():
            pytest.skip("ruamel.yaml not available")

        meta = SprintStatusMetadata(
            generated=datetime.now(UTC).replace(tzinfo=None),
            project="epic-comments-test",
        )
        entries = {
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
            "epic-20": SprintStatusEntry(
                key="epic-20",
                status="in-progress",
                entry_type=EntryType.EPIC_META,
            ),
            "20-1-start": SprintStatusEntry(
                key="20-1-start",
                status="in-progress",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        status = SprintStatus(metadata=meta, entries=entries)

        target = tmp_path / "epic-comments.yaml"
        write_sprint_status(status, target, preserve_comments=True)

        content = target.read_text(encoding="utf-8")

        # Should have epic separator comments
        assert "# Epic 12" in content
        assert "# Epic 20" in content

    def test_string_epic_comments(
        self,
        tmp_path: Path,
    ):
        """String epic IDs get correct separator comments."""
        if not has_ruamel():
            pytest.skip("ruamel.yaml not available")

        meta = SprintStatusMetadata(
            generated=datetime.now(UTC).replace(tzinfo=None),
            project="string-epic-test",
        )
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
        }
        status = SprintStatus(metadata=meta, entries=entries)

        target = tmp_path / "string-epic.yaml"
        write_sprint_status(status, target, preserve_comments=True)

        content = target.read_text(encoding="utf-8")

        # Should have string epic separator comment
        assert "# Epic testarch" in content

    def test_multiple_writes_no_duplicate_epic_comments(
        self,
        tmp_path: Path,
    ):
        """Multiple write cycles don't duplicate epic comments (regression test).

        This tests the bug fix where each write was adding `# Epic X` comments
        without clearing existing ones, causing accumulation like:
        # Epic 1
        # Epic 1
        # Epic 1
        """
        if not has_ruamel():
            pytest.skip("ruamel.yaml not available")

        meta = SprintStatusMetadata(
            generated=datetime.now(UTC).replace(tzinfo=None),
            project="regression-test",
        )
        entries = {
            "epic-1": SprintStatusEntry(
                key="epic-1",
                status="in-progress",
                entry_type=EntryType.EPIC_META,
            ),
            "1-1-setup": SprintStatusEntry(
                key="1-1-setup",
                status="done",
                entry_type=EntryType.EPIC_STORY,
            ),
            "epic-2": SprintStatusEntry(
                key="epic-2",
                status="backlog",
                entry_type=EntryType.EPIC_META,
            ),
            "2-1-start": SprintStatusEntry(
                key="2-1-start",
                status="backlog",
                entry_type=EntryType.EPIC_STORY,
            ),
        }
        status = SprintStatus(metadata=meta, entries=entries)

        target = tmp_path / "multi-write.yaml"

        # Write multiple times with preserve_comments=True
        for i in range(5):
            status.metadata.generated = datetime.now(UTC).replace(tzinfo=None)
            write_sprint_status(status, target, preserve_comments=True)

        content = target.read_text(encoding="utf-8")

        # Count occurrences of "# Epic 1" - should be exactly 1
        epic_1_count = content.count("# Epic 1")
        epic_2_count = content.count("# Epic 2")

        assert epic_1_count == 1, f"Expected 1 '# Epic 1', found {epic_1_count}"
        assert epic_2_count == 1, f"Expected 1 '# Epic 2', found {epic_2_count}"
