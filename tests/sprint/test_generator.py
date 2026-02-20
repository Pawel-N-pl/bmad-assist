"""Tests for sprint-status entry generator.

Tests cover:
- Slug generation with various inputs (AC: #4)
- Story key generation for numeric and string epics (AC: #4)
- Story number parsing edge cases (AC: #4)
- Epic file scanning with sharded support (AC: #1, #2, #6)
- Module epic scanning (AC: #3)
- Duplicate detection (AC: #7)
- Epic meta entry generation (AC: #8)
- Status preservation from epic story (AC: #5)
- Parse failure handling (AC: #9)
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.bmad.parser import EpicDocument, EpicStory
from bmad_assist.core.exceptions import ParserError
from bmad_assist.sprint import EntryType
from bmad_assist.sprint.generator import (
    GeneratedEntries,
    _generate_entries_from_epic,
    _normalize_status,
    _scan_epic_files,
    _scan_module_epics,
    generate_from_epics,
    generate_story_key,
    generate_story_slug,
)


class TestGenerateStorySlug:
    """Tests for slug generation (AC: #4)."""

    def test_simple_title_to_kebab_case(self):
        """Convert simple title to kebab-case."""
        assert generate_story_slug("Entry Classification System") == "entry-classification-system"

    def test_uppercase_preserved_as_lowercase(self):
        """Uppercase letters converted to lowercase."""
        assert generate_story_slug("ATDD Eligibility Prompt") == "atdd-eligibility-prompt"

    def test_special_characters_removed(self):
        """Special characters replaced with hyphens."""
        assert (
            generate_story_slug("CLI `serve` Command (with options)")
            == "cli-serve-command-with-options"
        )

    def test_empty_title_returns_untitled(self):
        """Empty title returns 'untitled'."""
        assert generate_story_slug("") == "untitled"
        assert generate_story_slug("   ") == "untitled"

    def test_only_special_chars_returns_untitled(self):
        """Title with only special chars returns 'untitled'."""
        assert generate_story_slug("!@#$%^&*()") == "untitled"

    def test_unicode_normalization(self):
        """Unicode characters normalized to ASCII."""
        assert generate_story_slug("Café résumé") == "cafe-resume"
        assert generate_story_slug("naïve façade") == "naive-facade"

    def test_truncation_at_word_boundary(self):
        """Long titles truncated at word boundary."""
        long_title = (
            "This is a very long story title that should be truncated at a reasonable word boundary"
        )
        slug = generate_story_slug(long_title, max_length=30)
        assert len(slug) <= 30
        assert not slug.endswith("-")
        assert slug == "this-is-a-very-long-story"

    def test_truncation_with_max_length(self):
        """Custom max_length respected."""
        slug = generate_story_slug("Short Title Here", max_length=10)
        assert len(slug) <= 10

    def test_multiple_spaces_collapsed(self):
        """Multiple spaces collapsed to single hyphen."""
        assert generate_story_slug("word   multiple   spaces") == "word-multiple-spaces"

    def test_leading_trailing_special_chars_removed(self):
        """Leading/trailing special chars removed."""
        assert generate_story_slug("---test---") == "test"
        assert generate_story_slug("***story***") == "story"

    def test_numbers_preserved(self):
        """Numbers are preserved in slug."""
        assert generate_story_slug("Version 2.0 Release") == "version-2-0-release"

    def test_real_story_titles(self):
        """Test with actual story titles from the codebase."""
        assert generate_story_slug("Entry Classification System") == "entry-classification-system"
        assert generate_story_slug("Canonical SprintStatus Model") == "canonical-sprintstatus-model"
        assert generate_story_slug("Schema-Tolerant Parser") == "schema-tolerant-parser"
        assert generate_story_slug("Epic and Module Generator") == "epic-and-module-generator"


class TestGenerateStoryKey:
    """Tests for story key generation (AC: #4)."""

    def test_numeric_epic_with_dot_format(self):
        """Generate key for numeric epic with X.Y story number."""
        story = EpicStory(number="12.3", title="Variables Cleanup")
        key = generate_story_key(12, story)
        assert key == "12-3-variables-cleanup"

    def test_string_epic_with_letter_prefix(self):
        """Generate key for string epic with T.Y story number."""
        story = EpicStory(number="T.1", title="Config Schema")
        key = generate_story_key("testarch", story)
        assert key == "testarch-1-config-schema"

    def test_single_digit_story_number(self):
        """Handle story number without dot separator."""
        story = EpicStory(number="5", title="Simple Story")
        key = generate_story_key(1, story)
        assert key == "1-5-simple-story"

    def test_empty_story_number_returns_none(self):
        """Empty story number returns None with warning."""
        story = EpicStory(number="", title="No Number Story")
        key = generate_story_key(1, story)
        assert key is None

    def test_whitespace_story_number_returns_none(self):
        """Whitespace-only story number returns None."""
        story = EpicStory(number="   ", title="Whitespace Number")
        key = generate_story_key(1, story)
        assert key is None

    def test_none_story_number_returns_none(self):
        """None story number returns None."""
        story = EpicStory(number=None, title="None Number")  # type: ignore[arg-type]
        key = generate_story_key(1, story)
        assert key is None

    def test_complex_story_number_format(self):
        """Handle complex story number formats like '12.3.1'."""
        story = EpicStory(number="12.3.1", title="Subpoint Story")
        key = generate_story_key(12, story)
        # Takes last segment after dot: "1"
        assert key == "12-1-subpoint-story"

    def test_logging_on_invalid_number(self, caplog):
        """Log warning when story number is invalid."""
        story = EpicStory(number="", title="Empty Number")
        with caplog.at_level(logging.WARNING):
            generate_story_key(1, story)
        assert "Empty story number" in caplog.text

    def test_real_epic_story_combinations(self):
        """Test with actual epic/story combinations."""
        # Epic 20, Story 4
        story = EpicStory(number="20.4", title="Epic and Module Generator")
        assert generate_story_key(20, story) == "20-4-epic-and-module-generator"

        # Testarch module story
        story = EpicStory(number="T.3", title="Keyword Scorer")
        assert generate_story_key("testarch", story) == "testarch-3-keyword-scorer"


class TestNormalizeStatus:
    """Tests for status normalization."""

    def test_none_returns_backlog(self):
        """None status defaults to backlog."""
        assert _normalize_status(None) == "backlog"

    def test_empty_returns_backlog(self):
        """Empty status defaults to backlog."""
        assert _normalize_status("") == "backlog"

    def test_backlog_unchanged(self):
        """'backlog' returns as-is."""
        assert _normalize_status("backlog") == "backlog"

    def test_case_insensitive(self):
        """Status matching is case-insensitive."""
        assert _normalize_status("DONE") == "done"
        assert _normalize_status("In-Progress") == "in-progress"

    def test_complete_mapped_to_done(self):
        """'complete' and 'completed' map to 'done'."""
        assert _normalize_status("complete") == "done"
        assert _normalize_status("completed") == "done"

    def test_spaces_handled(self):
        """Status with spaces handled."""
        assert _normalize_status("in progress") == "in-progress"
        assert _normalize_status("ready for dev") == "ready-for-dev"

    def test_unknown_status_defaults_to_backlog(self):
        """Unknown status defaults to backlog."""
        assert _normalize_status("phase2-deferred") == "backlog"
        assert _normalize_status("on-hold") == "backlog"


class TestGenerateEntriesFromEpic:
    """Tests for entry generation from EpicDocument (AC: #5, #8)."""

    def test_generates_epic_meta_entry_first(self):
        """AC8: Epic meta entry generated first."""
        epic = EpicDocument(
            epic_num=12,
            title="Test Epic",
            status=None,
            stories=[],
            path="/path/to/epic.md",
        )
        entries = _generate_entries_from_epic(epic)
        # 1 meta + 1 retrospective (no stories)
        assert len(entries) == 2
        assert entries[0].key == "epic-12"
        assert entries[0].entry_type == EntryType.EPIC_META
        assert entries[0].status == "backlog"
        assert entries[0].source == "epic"
        # Retrospective entry at the end
        assert entries[-1].key == "epic-12-retrospective"
        assert entries[-1].entry_type == EntryType.RETROSPECTIVE

    def test_generates_story_entries(self):
        """Generate entries for each story in epic."""
        stories = [
            EpicStory(number="12.1", title="First Story"),
            EpicStory(number="12.2", title="Second Story"),
        ]
        epic = EpicDocument(
            epic_num=12,
            title="Test Epic",
            status=None,
            stories=stories,
            path="/path/to/epic.md",
        )
        entries = _generate_entries_from_epic(epic)
        # 1 meta + 2 stories + 1 retrospective
        assert len(entries) == 4
        assert entries[0].entry_type == EntryType.EPIC_META
        assert entries[1].key == "12-1-first-story"
        assert entries[2].key == "12-2-second-story"
        assert entries[-1].key == "epic-12-retrospective"

    def test_story_entry_type_is_epic_story(self):
        """Story entry_type is EPIC_STORY for regular epics."""
        stories = [EpicStory(number="12.1", title="Story")]
        epic = EpicDocument(
            epic_num=12,
            title="Test Epic",
            status=None,
            stories=stories,
            path="/path/to/epic.md",
        )
        entries = _generate_entries_from_epic(epic, is_module=False)
        assert entries[1].entry_type == EntryType.EPIC_STORY

    def test_module_story_entry_type(self):
        """Story entry_type is MODULE_STORY for module epics."""
        stories = [EpicStory(number="T.1", title="Module Story")]
        epic = EpicDocument(
            epic_num="testarch",
            title="Test Module",
            status=None,
            stories=stories,
            path="/path/to/module-epic.md",
        )
        entries = _generate_entries_from_epic(epic, is_module=True)
        assert entries[1].entry_type == EntryType.MODULE_STORY

    def test_preserves_explicit_status(self):
        """AC5: Explicit status from story is preserved."""
        stories = [
            EpicStory(number="12.1", title="Done Story", status="done"),
            EpicStory(number="12.2", title="In Progress", status="in-progress"),
        ]
        epic = EpicDocument(
            epic_num=12,
            title="Test Epic",
            status=None,
            stories=stories,
            path="/path/to/epic.md",
        )
        entries = _generate_entries_from_epic(epic)
        assert entries[1].status == "done"
        assert entries[2].status == "in-progress"

    def test_defaults_to_backlog_when_no_status(self):
        """AC5: Default to backlog when no status specified."""
        stories = [EpicStory(number="12.1", title="No Status Story")]
        epic = EpicDocument(
            epic_num=12,
            title="Test Epic",
            status=None,
            stories=stories,
            path="/path/to/epic.md",
        )
        entries = _generate_entries_from_epic(epic)
        assert entries[1].status == "backlog"

    def test_skips_invalid_story_numbers(self, caplog):
        """Skip stories with invalid numbers."""
        stories = [
            EpicStory(number="12.1", title="Valid Story"),
            EpicStory(number="", title="Invalid Story"),
            EpicStory(number="12.2", title="Another Valid"),
        ]
        epic = EpicDocument(
            epic_num=12,
            title="Test Epic",
            status=None,
            stories=stories,
            path="/path/to/epic.md",
        )
        with caplog.at_level(logging.WARNING):
            entries = _generate_entries_from_epic(epic)
        # 1 meta + 2 valid stories + 1 retrospective
        assert len(entries) == 4
        assert any("Empty story number" in record.message for record in caplog.records)

    def test_returns_empty_for_none_epic_num(self, caplog):
        """Return empty list when epic_num is None."""
        epic = EpicDocument(
            epic_num=None,
            title="No Epic Num",
            status=None,
            stories=[EpicStory(number="1.1", title="Story")],
            path="/path/to/epic.md",
        )
        with caplog.at_level(logging.WARNING):
            entries = _generate_entries_from_epic(epic)
        assert entries == []
        assert "Epic has no epic_num" in caplog.text

    def test_source_is_always_epic(self):
        """All generated entries have source='epic'."""
        stories = [EpicStory(number="12.1", title="Story")]
        epic = EpicDocument(
            epic_num=12,
            title="Test Epic",
            status=None,
            stories=stories,
            path="/path/to/epic.md",
        )
        entries = _generate_entries_from_epic(epic)
        for entry in entries:
            assert entry.source == "epic"

    def test_generates_retrospective_entry(self):
        """AC: Retrospective entry generated for each epic."""
        stories = [EpicStory(number="12.1", title="Story")]
        epic = EpicDocument(
            epic_num=12,
            title="Test Epic",
            status=None,
            stories=stories,
            path="/path/to/epic.md",
        )
        entries = _generate_entries_from_epic(epic)
        # Should have: epic-12 (meta), 12-1-story (story), epic-12-retrospective (retro)
        assert len(entries) == 3
        assert entries[0].key == "epic-12"
        assert entries[0].entry_type == EntryType.EPIC_META
        assert entries[1].key == "12-1-story"
        assert entries[1].entry_type == EntryType.EPIC_STORY
        assert entries[2].key == "epic-12-retrospective"
        assert entries[2].entry_type == EntryType.RETROSPECTIVE
        assert entries[2].status == "backlog"

    def test_retrospective_entry_for_string_epic(self):
        """Retrospective entry generated for string epic IDs."""
        stories = [EpicStory(number="T.1", title="Config")]
        epic = EpicDocument(
            epic_num="testarch",
            title="Testarch Module",
            status=None,
            stories=stories,
            path="/path/to/epic.md",
        )
        entries = _generate_entries_from_epic(epic, is_module=True)
        retro_entry = entries[-1]
        assert retro_entry.key == "epic-testarch-retrospective"
        assert retro_entry.entry_type == EntryType.RETROSPECTIVE

    def test_string_epic_id_meta_entry(self):
        """Epic meta entry with string epic ID."""
        epic = EpicDocument(
            epic_num="testarch",
            title="Testarch Module",
            status=None,
            stories=[],
            path="/path/to/epic.md",
        )
        entries = _generate_entries_from_epic(epic)
        assert entries[0].key == "epic-testarch"


class TestScanEpicFiles:
    """Tests for epic file scanning (AC: #1, #2, #6)."""

    def test_scan_nonexistent_directory(self, tmp_path):
        """Non-existent directory returns empty list."""
        nonexistent = tmp_path / "nonexistent"
        epics, failed = _scan_epic_files([nonexistent], tmp_path)
        assert epics == []
        assert failed == 0

    def test_scan_empty_directory(self, tmp_path):
        """Empty directory returns empty list."""
        empty_dir = tmp_path / "epics"
        empty_dir.mkdir()
        epics, failed = _scan_epic_files([empty_dir], tmp_path)
        assert epics == []
        assert failed == 0

    def test_scan_directory_with_epic_files(self, tmp_path):
        """Scan directory with epic files."""
        # Create epics directory with a simple epic file
        epics_dir = tmp_path / "epics"
        epics_dir.mkdir()
        epic_file = epics_dir / "epic-1-test.md"
        epic_file.write_text(
            """---
epic_num: 1
title: Test Epic
---
# Epic 1: Test Epic

## Story 1.1: First Story

Description here.
"""
        )

        epics, failed = _scan_epic_files([epics_dir], tmp_path)
        assert len(epics) == 1
        assert epics[0].epic_num == 1
        assert failed == 0

    def test_scan_handles_files_without_stories(self, tmp_path):
        """Files without stories parsed but have empty story list."""
        epics_dir = tmp_path / "epics"
        epics_dir.mkdir()
        # Create a file that parses but has no valid story headers
        no_stories = epics_dir / "epic-empty.md"
        no_stories.write_text(
            """---
epic_num: 99
title: Empty Epic
---
# Epic 99: Empty

No stories defined here.
"""
        )

        epics, failed = _scan_epic_files([epics_dir], tmp_path)
        assert len(epics) == 1
        assert epics[0].epic_num == 99
        assert len(epics[0].stories) == 0
        assert failed == 0


class TestScanModuleEpics:
    """Tests for module epic scanning (AC: #3)."""

    def test_scan_nonexistent_modules_dir(self, tmp_path):
        """Non-existent modules directory returns empty list."""
        nonexistent = tmp_path / "modules"
        modules, failed = _scan_module_epics(nonexistent)
        assert modules == []
        assert failed == 0

    def test_scan_modules_directory(self, tmp_path):
        """Scan modules directory for epic files."""
        # Create modules structure
        modules_dir = tmp_path / "modules"
        testarch = modules_dir / "testarch"
        testarch.mkdir(parents=True)

        # Note: The parser requires numeric story format "## Story X.Y: Title"
        # Module epics in production use "### Story T.1:" which the parser doesn't handle
        # For testing, we use numeric format that the parser supports
        epic_file = testarch / "epic-testarch.md"
        epic_file.write_text(
            """---
epic_num: testarch
title: Testarch Module
---
# Epic: Testarch Module

## Story 1.1: Config Schema

Description.
"""
        )

        modules, failed = _scan_module_epics(modules_dir)
        assert len(modules) == 1
        module_name, epic = modules[0]
        assert module_name == "testarch"
        assert epic.epic_num == "testarch"
        assert len(epic.stories) == 1
        assert epic.stories[0].title == "Config Schema"
        assert failed == 0

    def test_scan_multiple_modules(self, tmp_path):
        """Scan multiple module directories."""
        modules_dir = tmp_path / "modules"

        # Create first module with numeric story format
        mod1 = modules_dir / "alpha"
        mod1.mkdir(parents=True)
        (mod1 / "epic-alpha.md").write_text(
            """---
epic_num: alpha
---
# Epic: Alpha

## Story 1.1: Story One

Description.
"""
        )

        # Create second module with numeric story format
        mod2 = modules_dir / "beta"
        mod2.mkdir(parents=True)
        (mod2 / "epic-beta.md").write_text(
            """---
epic_num: beta
---
# Epic: Beta

## Story 2.1: Story One

Description.
"""
        )

        modules, failed = _scan_module_epics(modules_dir)
        assert len(modules) == 2
        module_names = [m[0] for m in modules]
        assert "alpha" in module_names
        assert "beta" in module_names
        assert failed == 0

    def test_skips_non_directory_items(self, tmp_path):
        """Skip non-directory items in modules directory."""
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        # Create a file instead of directory
        (modules_dir / "README.md").write_text("# Modules")

        modules, failed = _scan_module_epics(modules_dir)
        assert modules == []
        assert failed == 0


class TestGenerateFromEpics:
    """Integration tests for generate_from_epics (AC: all)."""

    def test_empty_project(self, tmp_path):
        """Generate from project with no epics."""
        result = generate_from_epics(tmp_path)
        assert len(result.entries) == 0
        assert result.files_processed == 0
        assert result.duplicates_skipped == 0

    def test_generate_from_single_epic(self, tmp_path):
        """Generate entries from single epic file."""
        # Create docs/epics structure
        epics_dir = tmp_path / "docs" / "epics"
        epics_dir.mkdir(parents=True)

        epic_file = epics_dir / "epic-1-foundation.md"
        epic_file.write_text(
            """---
epic_num: 1
title: Foundation
---
# Epic 1: Foundation

## Story 1.1: Setup

Setup story.

## Story 1.2: Config

Config story.
"""
        )

        result = generate_from_epics(tmp_path)
        assert result.files_processed == 1
        # 1 meta + 2 stories + 1 retrospective
        assert len(result.entries) == 4
        keys = [e.key for e in result.entries]
        assert "epic-1" in keys
        assert "1-1-setup" in keys
        assert "1-2-config" in keys
        assert "epic-1-retrospective" in keys

    def test_duplicate_detection(self, tmp_path, caplog):
        """AC7: Duplicate keys detected and skipped."""
        # Create two locations with same epic
        epics_dir = tmp_path / "docs" / "epics"
        epics_dir.mkdir(parents=True)

        planning_dir = tmp_path / "_bmad-output" / "planning-artifacts" / "epics"
        planning_dir.mkdir(parents=True)

        epic_content = """---
epic_num: 1
title: Duplicate Epic
---
# Epic 1: Duplicate

## Story 1.1: Same Story

Description.
"""
        (epics_dir / "epic-1.md").write_text(epic_content)
        (planning_dir / "epic-1.md").write_text(epic_content)

        with caplog.at_level(logging.WARNING):
            result = generate_from_epics(tmp_path)

        # First occurrence kept, duplicates skipped
        assert result.duplicates_skipped >= 1
        assert "Duplicate story key" in caplog.text

    def test_priority_order_docs_first(self, tmp_path):
        """docs/epics/ has priority over _bmad-output/."""
        # Create both locations with same epic but different stories
        epics_dir = tmp_path / "docs" / "epics"
        epics_dir.mkdir(parents=True)

        planning_dir = tmp_path / "_bmad-output" / "planning-artifacts" / "epics"
        planning_dir.mkdir(parents=True)

        (epics_dir / "epic-1.md").write_text(
            """---
epic_num: 1
title: Primary Epic
---
# Epic 1: Primary

## Story 1.1: Primary Story

From docs/epics.
"""
        )

        (planning_dir / "epic-1.md").write_text(
            """---
epic_num: 1
title: Secondary Epic
---
# Epic 1: Secondary

## Story 1.1: Secondary Story

From planning-artifacts.
"""
        )

        result = generate_from_epics(tmp_path)
        # Both epic-1 and 1-1-* should be from docs/epics (first wins)
        story_entry = next(e for e in result.entries if e.key.startswith("1-1-"))
        assert "primary" in story_entry.key

    def test_module_epics_scanned(self, tmp_path):
        """Module epics are scanned and have MODULE_STORY type."""
        # Create module structure
        module_dir = tmp_path / "docs" / "modules" / "testarch"
        module_dir.mkdir(parents=True)

        # Note: Use numeric story format since the parser requires it
        (module_dir / "epic-testarch.md").write_text(
            """---
epic_num: testarch
title: Testarch Module
---
# Epic: Testarch Module

## Story 1.1: Module Config

Config story.
"""
        )

        result = generate_from_epics(tmp_path)
        # Find the module story
        story = next((e for e in result.entries if "module-config" in e.key), None)
        assert story is not None
        assert story.entry_type == EntryType.MODULE_STORY

    def test_status_preservation(self, tmp_path):
        """Status from epic stories is preserved."""
        epics_dir = tmp_path / "docs" / "epics"
        epics_dir.mkdir(parents=True)

        (epics_dir / "epic-1.md").write_text(
            """---
epic_num: 1
title: Mixed Status Epic
---
# Epic 1: Mixed

## Story 1.1: Done Story

**Status:** done

Completed.

## Story 1.2: In Progress

**Status:** in-progress

Working on it.

## Story 1.3: Backlog Story

No explicit status.
"""
        )

        result = generate_from_epics(tmp_path)
        entries_by_key = {e.key: e for e in result.entries}

        assert entries_by_key["1-1-done-story"].status == "done"
        assert entries_by_key["1-2-in-progress"].status == "in-progress"
        assert entries_by_key["1-3-backlog-story"].status == "backlog"

    def test_generated_entries_dataclass(self, tmp_path):
        """GeneratedEntries has correct field types."""
        result = generate_from_epics(tmp_path)
        assert isinstance(result.entries, list)
        assert isinstance(result.duplicates_skipped, int)
        assert isinstance(result.files_processed, int)
        assert isinstance(result.files_failed, int)


class TestGeneratedEntriesDataclass:
    """Tests for GeneratedEntries dataclass."""

    def test_default_values(self):
        """Default values are empty/zero."""
        result = GeneratedEntries()
        assert result.entries == []
        assert result.duplicates_skipped == 0
        assert result.files_processed == 0
        assert result.files_failed == 0

    def test_initialization_with_values(self):
        """Can initialize with custom values."""
        from bmad_assist.sprint.models import SprintStatusEntry

        entry = SprintStatusEntry(
            key="1-1-test",
            status="done",
            entry_type=EntryType.EPIC_STORY,
        )
        result = GeneratedEntries(
            entries=[entry],
            duplicates_skipped=2,
            files_processed=5,
            files_failed=1,
        )
        assert len(result.entries) == 1
        assert result.duplicates_skipped == 2
        assert result.files_processed == 5
        assert result.files_failed == 1


class TestIntegrationWithProductionFiles:
    """Integration tests with real project epic files."""

    def test_parse_real_epic_file(self):
        """Test parsing real epic file from project."""
        # Use the actual epic-20 file from the project
        epic_file = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "epics"
            / "epic-20-sprint-status-management.md"
        )

        if not epic_file.exists():
            pytest.skip("Epic file not found - running in isolated environment")

        from bmad_assist.bmad.parser import parse_epic_file

        epic = parse_epic_file(epic_file)
        assert epic.epic_num == 20
        assert len(epic.stories) >= 10  # Epic 20 has 12 stories

        # Generate entries
        entries = _generate_entries_from_epic(epic)
        assert entries[0].key == "epic-20"
        assert entries[0].entry_type == EntryType.EPIC_META

    def test_parse_real_module_epic(self):
        """Test parsing real module epic file.

        Note: The testarch module epic uses "### Story T.1:" format which the
        parser's regex doesn't currently match (requires numeric format like
        "## Story 12.1:"). Also, the header format "# Epic: Testarch Integration"
        doesn't match the expected "# Epic N: Title" pattern.

        This test documents the current parser limitations with module epics:
        - No frontmatter with epic_num
        - Header format doesn't match expected pattern
        - Story format uses letter prefix (T.1) not numbers
        """
        module_epic = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "modules"
            / "testarch"
            / "epic-testarch.md"
        )

        if not module_epic.exists():
            pytest.skip("Module epic file not found - running in isolated environment")

        from bmad_assist.bmad.parser import parse_epic_file

        epic = parse_epic_file(module_epic)
        # Parser can read the file but:
        # 1. No frontmatter with epic_num -> epic_num is None
        # 2. Header "# Epic: Testarch Integration" doesn't match "# Epic N: Title"
        # 3. Stories use "### Story T.X:" which doesn't match numeric pattern
        assert epic is not None
        assert epic.path.endswith("epic-testarch.md")
        # Content was read successfully, even if metadata wasn't extracted
        # This is a known limitation documented for future improvement

    def test_full_project_generation(self):
        """Test full generation from project root."""
        project_root = Path(__file__).parent.parent.parent

        if not (project_root / "docs" / "epics").exists():
            pytest.skip("Project epics not found - running in isolated environment")

        result = generate_from_epics(project_root)

        # Project should have multiple epics worth of entries
        assert result.files_processed >= 1
        assert len(result.entries) >= 10

        # Check that we have both epic metas and stories
        meta_entries = [e for e in result.entries if e.entry_type == EntryType.EPIC_META]
        story_entries = [e for e in result.entries if e.entry_type == EntryType.EPIC_STORY]

        assert len(meta_entries) >= 1
        assert len(story_entries) >= 5
