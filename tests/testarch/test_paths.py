"""Tests for TEA artifact path utilities."""

from pathlib import Path

import pytest

from bmad_assist.testarch.paths import (
    ARTIFACT_CONFIGS,
    VALID_ARTIFACT_TYPES,
    get_artifact_dir,
    get_artifact_patterns,
    normalize_story_id,
    validate_artifact_path,
)


class TestNormalizeStoryId:
    """Tests for normalize_story_id function (F7 Fix)."""

    def test_dot_format(self) -> None:
        """Test normalizing dotted story ID."""
        dotted, hyphen = normalize_story_id("25.1")
        assert dotted == "25.1"
        assert hyphen == "25-1"

    def test_hyphen_format(self) -> None:
        """Test normalizing hyphenated story ID."""
        dotted, hyphen = normalize_story_id("25-1")
        assert dotted == "25.1"
        assert hyphen == "25-1"

    def test_no_separator(self) -> None:
        """Test story ID without separator."""
        dotted, hyphen = normalize_story_id("251")
        assert dotted == "251"
        assert hyphen == "251"

    def test_none_returns_empty(self) -> None:
        """Test None returns empty strings."""
        dotted, hyphen = normalize_story_id(None)
        assert dotted == ""
        assert hyphen == ""

    def test_empty_returns_empty(self) -> None:
        """Test empty string returns empty strings."""
        dotted, hyphen = normalize_story_id("")
        assert dotted == ""
        assert hyphen == ""


class TestGetArtifactDir:
    """Tests for get_artifact_dir function."""

    def test_test_design_dir(self) -> None:
        """Test test-design subdirectory."""
        assert get_artifact_dir("test-design") == "test-designs"

    def test_atdd_dir(self) -> None:
        """Test ATDD subdirectory."""
        assert get_artifact_dir("atdd") == "atdd-checklists"

    def test_test_review_dir(self) -> None:
        """Test test-review subdirectory."""
        assert get_artifact_dir("test-review") == "test-reviews"

    def test_trace_dir(self) -> None:
        """Test trace subdirectory."""
        assert get_artifact_dir("trace") == "traceability"

    def test_unknown_returns_empty(self) -> None:
        """Test unknown artifact type returns empty string."""
        assert get_artifact_dir("unknown") == ""


class TestGetArtifactPatterns:
    """Tests for get_artifact_patterns function."""

    def test_test_design_patterns(self) -> None:
        """Test test-design pattern formatting."""
        patterns = get_artifact_patterns("test-design", epic_id=25)
        assert "test-design-epic-25.md" in patterns

    def test_atdd_patterns_with_dot_story(self) -> None:
        """Test ATDD patterns with dot format story ID."""
        patterns = get_artifact_patterns("atdd", epic_id=25, story_id="25.1")
        assert any("25.1" in p for p in patterns)
        assert any("25-1" in p for p in patterns)

    def test_atdd_patterns_with_hyphen_story(self) -> None:
        """Test ATDD patterns with hyphen format story ID."""
        patterns = get_artifact_patterns("atdd", epic_id=25, story_id="25-1")
        assert any("25.1" in p for p in patterns)
        assert any("25-1" in p for p in patterns)

    def test_string_epic_id(self) -> None:
        """Test pattern formatting with string epic ID (F2 Fix)."""
        patterns = get_artifact_patterns("test-design", epic_id="testarch")
        assert "test-design-epic-testarch.md" in patterns

    def test_int_epic_id(self) -> None:
        """Test pattern formatting with int epic ID (F2 Fix)."""
        patterns = get_artifact_patterns("test-design", epic_id=25)
        assert "test-design-epic-25.md" in patterns

    def test_invalid_artifact_type_raises(self) -> None:
        """Test invalid artifact type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_artifact_patterns("invalid-type", epic_id=25)
        assert "Invalid artifact type" in str(exc_info.value)


class TestValidateArtifactPath:
    """Tests for validate_artifact_path function (F17 Fix)."""

    def test_valid_path_within_base(self, tmp_path: Path) -> None:
        """Test valid path within base directory."""
        file_path = tmp_path / "artifacts" / "test.md"
        assert validate_artifact_path(file_path, tmp_path) is True

    def test_invalid_path_outside_base(self, tmp_path: Path) -> None:
        """Test path outside base directory is rejected."""
        outside_path = tmp_path.parent / "secrets" / "key.md"
        assert validate_artifact_path(outside_path, tmp_path) is False

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        """Test path traversal attempt is blocked."""
        traversal_path = tmp_path / "artifacts" / ".." / ".." / "secrets" / "key.md"
        assert validate_artifact_path(traversal_path, tmp_path) is False

    def test_same_as_base_is_valid(self, tmp_path: Path) -> None:
        """Test path equal to base is valid."""
        assert validate_artifact_path(tmp_path, tmp_path) is True


class TestArtifactConfigs:
    """Tests for artifact configuration constants."""

    def test_all_configs_have_subdir_and_patterns(self) -> None:
        """Test all configs have required structure."""
        for artifact_type, (subdir, patterns) in ARTIFACT_CONFIGS.items():
            assert isinstance(subdir, str)
            assert isinstance(patterns, list)
            assert len(patterns) > 0

    def test_valid_artifact_types_excludes_internal(self) -> None:
        """Test VALID_ARTIFACT_TYPES excludes internal types."""
        assert "test-design-system" not in VALID_ARTIFACT_TYPES
        assert "test-design" in VALID_ARTIFACT_TYPES
        assert "atdd" in VALID_ARTIFACT_TYPES
        assert "test-review" in VALID_ARTIFACT_TYPES
        assert "trace" in VALID_ARTIFACT_TYPES
