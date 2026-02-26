"""Tests for schema-tolerant sprint-status parser.

Tests cover:
- FormatVariant enum values
- Format detection heuristics with edge cases
- Full format parsing (production sprint-status files)
- Hybrid format parsing (epics as dict list)
- Array format parsing (epics as int array)
- Minimal format parsing (empty epics array)
- Error handling (missing files, malformed YAML, type errors)
- Entry classification integration
- Metadata extraction and datetime parsing
"""

import logging
from datetime import datetime
from pathlib import Path
from textwrap import dedent

import pytest

from bmad_assist.core.exceptions import ParserError
from bmad_assist.sprint import (
    EntryType,
    FormatVariant,
    detect_format,
    parse_sprint_status,
)


class TestFormatVariant:
    """Tests for FormatVariant enum."""

    def test_format_variant_has_all_values(self):
        """AC1: FormatVariant enum has all 5 required values."""
        expected_values = {"full", "hybrid", "array", "minimal", "unknown"}
        actual_values = {v.value for v in FormatVariant}
        assert actual_values == expected_values

    def test_format_variant_enum_members(self):
        """AC1: Verify enum member names match expected."""
        assert FormatVariant.FULL.value == "full"
        assert FormatVariant.HYBRID.value == "hybrid"
        assert FormatVariant.ARRAY.value == "array"
        assert FormatVariant.MINIMAL.value == "minimal"
        assert FormatVariant.UNKNOWN.value == "unknown"


class TestDetectFormatFull:
    """Tests for FULL format detection (AC2, AC3)."""

    def test_detect_full_format_with_dev_status(self):
        """FULL: No epics key, has development_status dict."""
        data = {
            "generated": "2026-01-07",
            "project": "test-project",
            "development_status": {"1-1-story": "done"},
        }
        assert detect_format(data) == FormatVariant.FULL

    def test_detect_full_format_minimal_metadata(self):
        """FULL: Only development_status present."""
        data = {"development_status": {"epic-1": "done"}}
        assert detect_format(data) == FormatVariant.FULL

    def test_detect_full_format_empty_dev_status(self):
        """FULL: development_status is empty dict."""
        data = {"development_status": {}}
        assert detect_format(data) == FormatVariant.FULL


class TestDetectFormatHybrid:
    """Tests for HYBRID format detection (AC2, AC4)."""

    def test_detect_hybrid_format_with_epic_dicts(self):
        """HYBRID: epics is list of dicts with 'id' key."""
        data = {
            "epics": [{"id": 1, "title": "Epic One", "status": "in-progress"}],
            "development_status": {},
        }
        assert detect_format(data) == FormatVariant.HYBRID

    def test_detect_hybrid_format_multiple_epics(self):
        """HYBRID: Multiple epics in list."""
        data = {
            "epics": [
                {"id": 1, "title": "Epic One"},
                {"id": 2, "title": "Epic Two"},
            ],
        }
        assert detect_format(data) == FormatVariant.HYBRID


class TestDetectFormatArray:
    """Tests for ARRAY format detection (AC2, AC5)."""

    def test_detect_array_format_with_integers(self):
        """ARRAY: epics is list of integers."""
        data = {"epics": [1, 2, 3], "development_status": {}}
        assert detect_format(data) == FormatVariant.ARRAY

    def test_detect_array_format_with_strings(self):
        """ARRAY: epics is list of strings."""
        data = {"epics": ["1", "2", "testarch"]}
        assert detect_format(data) == FormatVariant.ARRAY


class TestDetectFormatMinimal:
    """Tests for MINIMAL format detection (AC2, AC6)."""

    def test_detect_minimal_format_empty_epics(self):
        """MINIMAL: epics is empty list."""
        data = {"epics": [], "current_epic": 1, "current_story": 1}
        assert detect_format(data) == FormatVariant.MINIMAL

    def test_detect_minimal_format_only_epics_empty(self):
        """MINIMAL: Just empty epics array."""
        data = {"epics": []}
        assert detect_format(data) == FormatVariant.MINIMAL


class TestDetectFormatEdgeCases:
    """Tests for edge cases in format detection (AC2)."""

    def test_detect_unknown_epics_is_string(self):
        """UNKNOWN: epics is string, not list."""
        data = {"epics": "invalid"}
        assert detect_format(data) == FormatVariant.UNKNOWN

    def test_detect_unknown_epics_is_dict(self):
        """UNKNOWN: epics is dict, not list."""
        data = {"epics": {"1": "Epic One"}}
        assert detect_format(data) == FormatVariant.UNKNOWN

    def test_detect_unknown_epics_is_integer(self):
        """UNKNOWN: epics is integer, not list."""
        data = {"epics": 42}
        assert detect_format(data) == FormatVariant.UNKNOWN

    def test_detect_unknown_both_keys_missing(self):
        """UNKNOWN: Neither epics nor development_status."""
        data = {"project": "test"}
        assert detect_format(data) == FormatVariant.UNKNOWN

    def test_detect_unknown_dev_status_is_list(self):
        """UNKNOWN: development_status is list, not dict."""
        data = {"development_status": ["1-1-story"]}
        assert detect_format(data) == FormatVariant.UNKNOWN

    def test_detect_unknown_empty_data(self):
        """UNKNOWN: Empty dict."""
        assert detect_format({}) == FormatVariant.UNKNOWN

    def test_detect_unknown_none_data(self):
        """UNKNOWN: None data treated as empty."""
        # This would require special handling in caller
        # detect_format expects dict, so test empty dict
        assert detect_format({}) == FormatVariant.UNKNOWN

    def test_detect_unknown_epics_with_mixed_types(self):
        """UNKNOWN: epics has mixed int/dict types."""
        data = {"epics": [1, {"id": 2}]}
        # First element is int, but second is dict - fails array check
        assert detect_format(data) == FormatVariant.UNKNOWN

    def test_detect_unknown_epics_list_of_dicts_without_id(self):
        """UNKNOWN: epics is list of dicts but no 'id' key."""
        data = {"epics": [{"title": "Epic"}]}
        assert detect_format(data) == FormatVariant.UNKNOWN


class TestParseFullFormat:
    """Tests for Full format parsing (AC3, AC10, AC11)."""

    def test_parse_full_format_basic(self, tmp_path):
        """Parse basic Full format file."""
        content = dedent("""
            generated: 2026-01-07
            project: test-project
            development_status:
              1-1-setup: done
              1-2-config: in-progress
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert len(status.entries) == 2
        assert status.entries["1-1-setup"].status == "done"
        assert status.entries["1-2-config"].status == "in-progress"
        assert status.metadata.project == "test-project"

    def test_parse_full_format_with_all_metadata(self, tmp_path):
        """Parse Full format with all metadata fields."""
        content = dedent("""
            generated: 2026-01-07T10:30:00
            project: bmad-assist
            project_key: bmad
            tracking_system: file-system
            story_location: _bmad-output/stories
            development_status:
              epic-12: done
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert status.metadata.project == "bmad-assist"
        assert status.metadata.project_key == "bmad"
        assert status.metadata.tracking_system == "file-system"
        assert status.metadata.story_location == "_bmad-output/stories"

    def test_parse_full_format_entry_classification(self, tmp_path):
        """AC11: Entries have correct entry_type and source."""
        content = dedent("""
            development_status:
              epic-12: done
              12-1-story: done
              standalone-01-fix: done
              testarch-1-config: done
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert status.entries["epic-12"].entry_type == EntryType.EPIC_META
        assert status.entries["12-1-story"].entry_type == EntryType.EPIC_STORY
        assert status.entries["standalone-01-fix"].entry_type == EntryType.STANDALONE
        assert status.entries["testarch-1-config"].entry_type == EntryType.MODULE_STORY

        # All should have source="sprint-status"
        for entry in status.entries.values():
            assert entry.source == "sprint-status"

    def test_parse_full_format_comment_is_none(self, tmp_path):
        """AC7: Comment field is None for all entries."""
        content = dedent("""
            development_status:
              # This is a YAML comment
              1-1-story: done  # inline comment
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert status.entries["1-1-story"].comment is None


class TestParseHybridFormat:
    """Tests for Hybrid format parsing (AC4)."""

    def test_parse_hybrid_format_basic(self, tmp_path):
        """Parse basic Hybrid format file."""
        content = dedent("""
            epics:
              - id: 1
                title: Config Parser
                status: in-progress
              - id: 2
                title: Widgets
                status: backlog
            development_status:
              1-1-define-schema: done
              1-2-implement-parser: review
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        # Check epic entries
        assert "epic-1" in status.entries
        assert status.entries["epic-1"].status == "in-progress"
        assert status.entries["epic-1"].entry_type == EntryType.EPIC_META

        assert "epic-2" in status.entries
        assert status.entries["epic-2"].status == "backlog"

        # Check story entries
        assert "1-1-define-schema" in status.entries
        assert status.entries["1-1-define-schema"].status == "done"

    def test_parse_hybrid_format_preserves_order(self, tmp_path):
        """Hybrid format preserves entry order (epics first, then stories)."""
        content = dedent("""
            epics:
              - id: 1
                status: done
            development_status:
              1-1-first: done
              1-2-second: done
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)
        keys = list(status.entries.keys())

        assert keys[0] == "epic-1"
        assert keys[1] == "1-1-first"
        assert keys[2] == "1-2-second"


class TestParseArrayFormat:
    """Tests for Array format parsing (AC5)."""

    def test_parse_array_format_integers(self, tmp_path):
        """Parse Array format with integer epic IDs."""
        content = dedent("""
            epics: [1, 2, 3]
            development_status:
              1-1-story: done
              2-1-story: review
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        # Check epic placeholder entries
        assert "epic-1" in status.entries
        assert status.entries["epic-1"].status == "backlog"  # Default status
        assert "epic-2" in status.entries
        assert "epic-3" in status.entries

        # Check story entries
        assert status.entries["1-1-story"].status == "done"
        assert status.entries["2-1-story"].status == "review"

    def test_parse_array_format_strings(self, tmp_path):
        """Parse Array format with string epic IDs."""
        content = dedent("""
            epics: ["testarch", "guardian"]
            development_status:
              testarch-1-config: done
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert "epic-testarch" in status.entries
        assert "epic-guardian" in status.entries


class TestParseMinimalFormat:
    """Tests for Minimal format parsing (AC6)."""

    def test_parse_minimal_format_empty_epics(self, tmp_path):
        """Parse Minimal format with empty epics array."""
        content = dedent("""
            epics: []
            current_epic: 1
            current_story: 1
            phase: documentation
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert len(status.entries) == 0
        assert status.metadata.generated is not None

    def test_parse_minimal_format_with_dev_status(self, tmp_path):
        """Minimal format can have development_status."""
        content = dedent("""
            epics: []
            development_status:
              standalone-01-fix: done
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert len(status.entries) == 1
        assert "standalone-01-fix" in status.entries


class TestErrorHandling:
    """Tests for error handling (AC8)."""

    def test_file_not_found_raises_parser_error(self, tmp_path):
        """AC8: FileNotFoundError raises ParserError with path."""
        path = tmp_path / "nonexistent.yaml"

        with pytest.raises(ParserError) as exc_info:
            parse_sprint_status(path)

        assert "not found" in str(exc_info.value)
        assert "nonexistent.yaml" in str(exc_info.value)

    def test_malformed_yaml_returns_empty(self, tmp_path, caplog):
        """AC8: YAML parse error returns SprintStatus.empty() with warning."""
        content = "invalid: yaml: :::malformed["
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        with caplog.at_level(logging.WARNING):
            status = parse_sprint_status(path)

        assert len(status.entries) == 0
        assert "Failed to parse" in caplog.text

    def test_empty_file_returns_empty(self, tmp_path, caplog):
        """AC8: Empty file returns SprintStatus.empty() with INFO log."""
        path = tmp_path / "sprint-status.yaml"
        path.write_text("")

        with caplog.at_level(logging.INFO):
            status = parse_sprint_status(path)

        assert len(status.entries) == 0
        assert "empty" in caplog.text.lower()

    def test_missing_dev_status_returns_empty_entries(self, tmp_path):
        """AC8: Missing development_status returns empty entries dict."""
        content = dedent("""
            generated: 2026-01-07
            project: test
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert len(status.entries) == 0

    def test_dev_status_is_list_returns_empty(self, tmp_path, caplog):
        """AC8: development_status as list returns empty entries with warning."""
        content = dedent("""
            development_status:
              - 1-1-story
              - 1-2-story
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        with caplog.at_level(logging.WARNING):
            status = parse_sprint_status(path)

        assert len(status.entries) == 0
        assert "expected dict" in caplog.text.lower()

    def test_invalid_generated_datetime_uses_fallback(self, tmp_path, caplog):
        """AC8: Invalid generated datetime logs warning, uses now() fallback."""
        content = dedent("""
            generated: not-a-date
            development_status:
              1-1-story: done
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        from datetime import UTC

        before = datetime.now(UTC).replace(tzinfo=None)

        with caplog.at_level(logging.WARNING):
            status = parse_sprint_status(path)

        after = datetime.now(UTC).replace(tzinfo=None)

        assert status.metadata.generated is not None
        # Should be between before and after
        assert before <= status.metadata.generated <= after
        assert "Could not parse" in caplog.text


class TestMetadataExtraction:
    """Tests for metadata extraction."""

    def test_parse_iso_datetime(self, tmp_path):
        """Parse ISO format datetime."""
        content = dedent("""
            generated: 2026-01-07T10:30:00
            development_status: {}
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert status.metadata.generated.year == 2026
        assert status.metadata.generated.month == 1
        assert status.metadata.generated.day == 7
        assert status.metadata.generated.hour == 10
        assert status.metadata.generated.minute == 30

    def test_parse_date_only(self, tmp_path):
        """Parse date-only format (YAML date type)."""
        content = dedent("""
            generated: 2026-01-07
            development_status: {}
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert status.metadata.generated.year == 2026
        assert status.metadata.generated.month == 1
        assert status.metadata.generated.day == 7

    def test_missing_generated_uses_now(self, tmp_path):
        """Missing generated field uses current time."""
        from datetime import UTC

        content = "development_status: {}"
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        before = datetime.now(UTC).replace(tzinfo=None)
        status = parse_sprint_status(path)
        after = datetime.now(UTC).replace(tzinfo=None)

        assert before <= status.metadata.generated <= after


class TestStatusNormalization:
    """Tests for status value normalization."""

    @pytest.mark.parametrize(
        "raw_status,expected",
        [
            ("done", "done"),
            ("DONE", "done"),
            ("Done", "done"),
            ("in-progress", "in-progress"),
            ("in_progress", "in-progress"),
            ("inprogress", "in-progress"),
            ("IN-PROGRESS", "in-progress"),
            ("ready-for-dev", "ready-for-dev"),
            ("ready_for_dev", "ready-for-dev"),
            ("readyfordev", "ready-for-dev"),
            ("review", "review"),
            ("backlog", "backlog"),
            ("blocked", "blocked"),
            ("deferred", "deferred"),
            # Legacy aliases
            ("drafted", "backlog"),
            ("completed", "done"),
        ],
    )
    def test_status_normalization(self, tmp_path, raw_status, expected):
        """Status values are normalized to canonical form."""
        content = f"""
development_status:
  1-1-story: {raw_status}
"""
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert status.entries["1-1-story"].status == expected

    def test_unknown_status_defaults_to_backlog(self, tmp_path, caplog):
        """Unknown status values default to backlog with warning."""
        content = dedent("""
            development_status:
              1-1-story: unknown-status
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        with caplog.at_level(logging.WARNING):
            status = parse_sprint_status(path)

        assert status.entries["1-1-story"].status == "backlog"
        assert "Invalid status" in caplog.text


class TestRealFixtures:
    """Tests using real fixture files."""

    def test_parse_production_sprint_status(self):
        """Parse production sprint-status.yaml (Full format)."""
        path = Path("_bmad-output/implementation-artifacts/sprint-status.yaml")
        if not path.exists():
            pytest.skip("Production sprint-status.yaml not found")

        status = parse_sprint_status(path)

        # Should have entries
        assert len(status.entries) > 0

        # Should have metadata
        assert status.metadata.project == "bmad-assist"

        # Check some known entries exist
        assert "epic-testarch" in status.entries or "epic-12" in status.entries

    def test_parse_cli_dashboard_fixture(self):
        """Parse cli-dashboard fixture (Hybrid format)."""
        path = Path("tests/fixtures/sprint/sprint-status-cli-dashboard.yaml")
        if not path.exists():
            pytest.skip("cli-dashboard fixture not found")

        status = parse_sprint_status(path)

        # Should have epic entries from hybrid format
        assert "epic-1" in status.entries

        # Should have story entries
        assert any("define" in key for key in status.entries)

    def test_parse_test_data_gen_fixture(self):
        """Parse test-data-gen fixture (Array format)."""
        path = Path("tests/fixtures/sprint/sprint-status-test-data-gen.yaml")
        if not path.exists():
            pytest.skip("test-data-gen fixture not found")

        status = parse_sprint_status(path)

        # Should have epic placeholder entries
        assert "epic-1" in status.entries

        # Should have story entries
        assert len(status.entries) > 5

    def test_parse_webhook_relay_fixture(self):
        """Parse webhook-relay fixture (Minimal format)."""
        path = Path("tests/fixtures/sprint/sprint-status-webhook-relay.yaml")
        if not path.exists():
            pytest.skip("webhook-relay fixture not found")

        status = parse_sprint_status(path)

        # Minimal format has empty entries
        assert len(status.entries) == 0

    def test_parse_auth_service_fixture(self):
        """Parse auth-service fixture (Minimal format)."""
        path = Path("tests/fixtures/sprint/sprint-status-auth-service.yaml")
        if not path.exists():
            pytest.skip("auth-service fixture not found")

        status = parse_sprint_status(path)

        # Minimal format has empty entries
        assert len(status.entries) == 0


class TestHelperIntegration:
    """Tests for SprintStatus helper method integration."""

    def test_get_stories_for_epic_with_parsed_data(self, tmp_path):
        """get_stories_for_epic works with parsed data."""
        content = dedent("""
            development_status:
              epic-12: done
              12-1-setup: done
              12-2-config: review
              12-3-deploy: in-progress
              13-1-other: done
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)
        stories = status.get_stories_for_epic(12)

        assert len(stories) == 3
        keys = [s.key for s in stories]
        assert "12-1-setup" in keys
        assert "12-2-config" in keys
        assert "12-3-deploy" in keys
        assert "13-1-other" not in keys

    def test_get_epic_status_with_parsed_data(self, tmp_path):
        """get_epic_status works with parsed data."""
        content = dedent("""
            development_status:
              epic-12: done
              epic-13: in-progress
              12-1-story: done
        """)
        path = tmp_path / "sprint-status.yaml"
        path.write_text(content)

        status = parse_sprint_status(path)

        assert status.get_epic_status(12) == "done"
        assert status.get_epic_status(13) == "in-progress"
        assert status.get_epic_status(99) is None
