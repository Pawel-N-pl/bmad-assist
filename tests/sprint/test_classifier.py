"""Tests for sprint-status entry classifier.

Tests cover:
- EntryType enum values and semantics
- classify_entry function with all pattern types
- Edge cases and priority handling
- Configurable module prefixes
- Invalid input handling
"""

import logging

import pytest

from bmad_assist.sprint import EntryType, classify_entry
from bmad_assist.sprint.classifier import DEFAULT_MODULE_PREFIXES


class TestEntryType:
    """Tests for EntryType enum."""

    def test_entry_type_has_all_required_values(self):
        """AC1: EntryType enum has all 6 required values."""
        expected_values = {
            "epic_story",
            "module_story",
            "standalone",
            "epic_meta",
            "retro",
            "hardening",
            "unknown",
        }
        actual_values = {e.value for e in EntryType}
        assert actual_values == expected_values

    def test_entry_type_enum_members(self):
        """AC1: Verify enum member names match expected."""
        assert EntryType.EPIC_STORY.value == "epic_story"
        assert EntryType.MODULE_STORY.value == "module_story"
        assert EntryType.STANDALONE.value == "standalone"
        assert EntryType.EPIC_META.value == "epic_meta"
        assert EntryType.RETROSPECTIVE.value == "retro"
        assert EntryType.HARDENING.value == "hardening"
        assert EntryType.UNKNOWN.value == "unknown"


class TestClassifyEntryStandalone:
    """Tests for standalone pattern classification (AC3)."""

    @pytest.mark.parametrize(
        "key",
        [
            "standalone-01-reconciler-refactoring",
            "standalone-02-sharded-docs",
            "standalone-foo-bar",
            "standalone-x",
            "standalone-123",
        ],
    )
    def test_standalone_patterns_classified_correctly(self, key: str):
        """AC3: standalone-* patterns correctly identified as STANDALONE."""
        assert classify_entry(key) == EntryType.STANDALONE

    def test_standalone_prefix_case_insensitive(self):
        """Verify standalone matching is case-insensitive."""
        assert classify_entry("STANDALONE-01-test") == EntryType.STANDALONE
        assert classify_entry("Standalone-02-test") == EntryType.STANDALONE


class TestClassifyEntryModuleStory:
    """Tests for module story pattern classification (AC4)."""

    def test_default_module_prefixes_includes_testarch(self):
        """Verify default module prefixes contain testarch."""
        assert "testarch" in DEFAULT_MODULE_PREFIXES

    def test_default_module_prefixes_is_immutable(self):
        """Verify default module prefixes is immutable (tuple, not list)."""
        assert isinstance(DEFAULT_MODULE_PREFIXES, tuple)

    @pytest.mark.parametrize(
        "key",
        [
            "testarch-1-configuration-schema",
            "testarch-2-test-design",
            "testarch-10-advanced-feature",
        ],
    )
    def test_testarch_patterns_classified_as_module_story(self, key: str):
        """AC4: testarch-* patterns classified as MODULE_STORY with default prefixes."""
        assert classify_entry(key) == EntryType.MODULE_STORY

    @pytest.mark.parametrize(
        "key,prefixes",
        [
            ("guardian-1-anomaly-detection", ["guardian"]),
            ("prompts-3-template-engine", ["prompts"]),
            ("custom-5-feature", ["custom", "another"]),
        ],
    )
    def test_custom_module_prefixes(self, key: str, prefixes: list[str]):
        """AC4: Custom module prefixes correctly classify entries."""
        assert classify_entry(key, module_prefixes=prefixes) == EntryType.MODULE_STORY

    def test_module_prefix_case_insensitive(self):
        """Verify module prefix matching is case-insensitive."""
        assert classify_entry("TESTARCH-1-config") == EntryType.MODULE_STORY
        assert classify_entry("Testarch-2-test") == EntryType.MODULE_STORY


class TestClassifyEntryEpicMeta:
    """Tests for epic meta pattern classification (AC5)."""

    @pytest.mark.parametrize(
        "key",
        [
            "epic-1",
            "epic-12",
            "epic-100",
            "epic-testarch",
            "epic-guardian",
            "epic-foo-bar",
        ],
    )
    def test_epic_meta_patterns_classified_correctly(self, key: str):
        """AC5: epic-{id} patterns classified as EPIC_META."""
        assert classify_entry(key) == EntryType.EPIC_META

    def test_epic_meta_case_insensitive(self):
        """Verify epic-{id} matching is case-insensitive."""
        assert classify_entry("EPIC-12") == EntryType.EPIC_META
        assert classify_entry("Epic-testarch") == EntryType.EPIC_META


class TestClassifyEntryRetrospective:
    """Tests for retrospective pattern classification."""

    @pytest.mark.parametrize(
        "key",
        [
            "epic-12-retrospective",
            "epic-1-retrospective",
            "epic-testarch-retrospective",
        ],
    )
    def test_epic_retrospective_patterns(self, key: str):
        """Retrospective entries ending with -retrospective classified correctly."""
        assert classify_entry(key) == EntryType.RETROSPECTIVE

    def test_retrospective_suffix_has_highest_priority(self):
        """Edge case: -retrospective suffix wins over other patterns."""
        # Would match standalone- prefix but -retrospective has priority
        assert classify_entry("standalone-retrospective") == EntryType.RETROSPECTIVE

        # Would match testarch- module prefix but -retrospective has priority
        assert classify_entry("testarch-retrospective") == EntryType.RETROSPECTIVE


class TestClassifyEntryHardening:
    """Tests for hardening pattern classification."""

    @pytest.mark.parametrize(
        "key",
        [
            "epic-12-hardening",
            "epic-1-hardening",
            "epic-testarch-hardening",
        ],
    )
    def test_epic_hardening_patterns(self, key: str):
        """Hardening entries ending with -hardening classified correctly."""
        assert classify_entry(key) == EntryType.HARDENING

    def test_hardening_suffix_has_high_priority(self):
        """Edge case: -hardening suffix wins over other patterns."""
        # Would match standalone- prefix but -hardening has priority
        assert classify_entry("standalone-hardening") == EntryType.HARDENING

        # Would match testarch- module prefix but -hardening has priority
        assert classify_entry("testarch-hardening") == EntryType.HARDENING


class TestClassifyEntryEpicStory:
    """Tests for epic story pattern classification (AC2)."""

    @pytest.mark.parametrize(
        "key",
        [
            "1-1-story-name",
            "12-3-another-story",
            "100-99-long-slug-name",
            "1-1-x",
        ],
    )
    def test_numeric_epic_id_story_patterns(self, key: str):
        """AC2: {numeric_id}-{story_num}-{slug} classified as EPIC_STORY."""
        assert classify_entry(key) == EntryType.EPIC_STORY

    @pytest.mark.parametrize(
        "key",
        [
            "auth-1-login",
            "api-2-endpoints",
            "ui-10-dashboard",
            "core-module-5-feature",
        ],
    )
    def test_string_epic_id_story_patterns(self, key: str):
        """AC2: {string_id}-{story_num}-{slug} classified as EPIC_STORY."""
        assert classify_entry(key) == EntryType.EPIC_STORY

    def test_story_pattern_case_insensitive(self):
        """Verify story pattern matching is case-insensitive."""
        assert classify_entry("AUTH-1-Login") == EntryType.EPIC_STORY
        assert classify_entry("12-3-MyStory") == EntryType.EPIC_STORY


class TestClassifyEntryUnknown:
    """Tests for unknown pattern classification (AC7, AC8)."""

    @pytest.mark.parametrize(
        "key",
        [
            "random-string",
            "12-3",  # Missing slug
            "no-match-here",
            "123",
            "abc",
            "some_underscore_key",
        ],
    )
    def test_unknown_patterns_return_unknown(self, key: str):
        """AC7: Unknown patterns default to UNKNOWN."""
        assert classify_entry(key) == EntryType.UNKNOWN

    def test_empty_string_returns_unknown_with_warning(self, caplog):
        """AC8: Empty string returns UNKNOWN with logged warning."""
        with caplog.at_level(logging.WARNING):
            result = classify_entry("")

        assert result == EntryType.UNKNOWN
        assert "empty/whitespace" in caplog.text

    def test_whitespace_only_returns_unknown_with_warning(self, caplog):
        """AC8: Whitespace-only string returns UNKNOWN with logged warning."""
        with caplog.at_level(logging.WARNING):
            result = classify_entry("   ")

        assert result == EntryType.UNKNOWN
        assert "empty/whitespace" in caplog.text

    def test_none_like_falsy_returns_unknown(self, caplog):
        """AC8: Falsy-like None string returns UNKNOWN with warning."""
        with caplog.at_level(logging.WARNING):
            # Empty after strip
            result = classify_entry("\t\n")

        assert result == EntryType.UNKNOWN
        assert "empty/whitespace" in caplog.text


class TestClassifyEntryEdgeCases:
    """Tests for edge cases and pattern priority."""

    def test_epic_testarch_is_epic_meta_not_module(self):
        """Edge case: epic-testarch should be EPIC_META, not MODULE_STORY."""
        # The epic- prefix marks it as epic meta, even though "testarch" is a module prefix
        assert classify_entry("epic-testarch") == EntryType.EPIC_META

    def test_retrospective_wins_over_standalone(self):
        """Edge case: -retrospective suffix wins over standalone- prefix."""
        assert classify_entry("standalone-retrospective") == EntryType.RETROSPECTIVE

    def test_retrospective_wins_over_module(self):
        """Edge case: -retrospective suffix wins over module prefix."""
        assert classify_entry("testarch-retrospective") == EntryType.RETROSPECTIVE

    def test_retrospective_wins_over_epic_meta(self):
        """Edge case: epic-12-retrospective is RETROSPECTIVE not EPIC_META."""
        assert classify_entry("epic-12-retrospective") == EntryType.RETROSPECTIVE

    def test_hardening_wins_over_epic_meta(self):
        """Edge case: epic-12-hardening is HARDENING not EPIC_META."""
        assert classify_entry("epic-12-hardening") == EntryType.HARDENING

    def test_story_pattern_requires_slug(self):
        """Edge case: {id}-{num} without slug is UNKNOWN."""
        assert classify_entry("12-3") == EntryType.UNKNOWN

    def test_module_prefix_not_story_pattern(self):
        """Edge case: testarch-1 without slug is MODULE_STORY (prefix match)."""
        # testarch-1 matches module prefix pattern
        assert classify_entry("testarch-1") == EntryType.MODULE_STORY

    def test_whitespace_trimmed_before_classification(self):
        """Edge case: Leading/trailing whitespace is trimmed."""
        assert classify_entry("  12-3-story  ") == EntryType.EPIC_STORY
        assert classify_entry("\tepic-12\n") == EntryType.EPIC_META


class TestClassifyEntryModulePrefixConfiguration:
    """Tests for module prefix configuration (AC6)."""

    def test_empty_prefix_list_no_module_matches(self):
        """AC6: Empty prefix list means no MODULE_STORY matches."""
        result = classify_entry("testarch-1-config", module_prefixes=[])
        # Without testarch in prefixes, this could match story pattern
        # testarch-1-config: testarch is epic_id, 1 is story_num, config is slug
        assert result == EntryType.EPIC_STORY

    def test_custom_prefix_replaces_default(self):
        """AC6: Custom prefixes replace defaults entirely."""
        # With only "guardian" prefix, "testarch-1-config" is not MODULE_STORY
        result = classify_entry("testarch-1-config", module_prefixes=["guardian"])
        # It matches the story pattern instead
        assert result == EntryType.EPIC_STORY

        # But guardian-1-detect is MODULE_STORY
        result = classify_entry("guardian-1-detect", module_prefixes=["guardian"])
        assert result == EntryType.MODULE_STORY

    def test_multiple_prefixes_all_work(self):
        """AC6: Multiple prefixes all match MODULE_STORY."""
        prefixes = ["testarch", "guardian", "prompts"]

        assert classify_entry("testarch-1-a", module_prefixes=prefixes) == EntryType.MODULE_STORY
        assert classify_entry("guardian-2-b", module_prefixes=prefixes) == EntryType.MODULE_STORY
        assert classify_entry("prompts-3-c", module_prefixes=prefixes) == EntryType.MODULE_STORY


class TestClassifyEntryImportFromPackage:
    """Tests for public API imports."""

    def test_entry_type_importable_from_sprint(self):
        """EntryType is importable from bmad_assist.sprint."""
        from bmad_assist.sprint import EntryType as ImportedEntryType

        assert ImportedEntryType is EntryType

    def test_classify_entry_importable_from_sprint(self):
        """classify_entry is importable from bmad_assist.sprint."""
        from bmad_assist.sprint import classify_entry as imported_classify

        assert imported_classify is classify_entry
