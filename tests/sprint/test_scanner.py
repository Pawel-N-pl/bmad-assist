"""Tests for the artifact scanner and index module."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from bmad_assist.sprint.scanner import (
    CODE_REVIEW_PATTERN,
    LEGACY_REVIEW_PATTERN,
    LEGACY_VALIDATION_PATTERN,
    NEW_VALIDATION_PATTERN,
    RETRO_PATTERN,
    STORY_FILENAME_PATTERN,
    SYNTHESIS_PATTERN,
    ArtifactIndex,
    CodeReviewArtifact,
    RetrospectiveArtifact,
    StoryArtifact,
    ValidationArtifact,
    _extract_story_status,
    _get_artifact_locations,
    _normalize_story_key,
    _parse_epic_id,
    _scan_code_reviews,
    _scan_retrospectives,
    _scan_stories,
    _scan_validations,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a temporary project structure with artifacts."""
    # New location: _bmad-output/implementation-artifacts/
    new_base = tmp_path / "_bmad-output" / "implementation-artifacts"

    # Stories
    stories_dir = new_base / "stories"
    stories_dir.mkdir(parents=True)
    (stories_dir / "20-1-entry-classification-system.md").write_text(
        "# Story 20.1\n\nStatus: done\n\nSome content..."
    )
    (stories_dir / "20-2-canonical-model.md").write_text(
        "# Story 20.2\n\nStatus: in-progress\n\nSome content..."
    )
    (stories_dir / "testarch-1-config.md").write_text(
        "# Story testarch.1\n\nStatus: review\n\nSome content..."
    )
    (stories_dir / "20-3-parser.md").write_text(
        "# Story 20.3\n\nNo status field here\n\nSome content..."
    )

    # Code reviews
    reviews_dir = new_base / "code-reviews"
    reviews_dir.mkdir()
    (reviews_dir / "synthesis-20-1-20260107_1234.md").write_text("# Synthesis")
    (reviews_dir / "code-review-20-1-validator_a-20260107_1230.md").write_text("# Validator A")
    (reviews_dir / "code-review-20-1-validator_b-20260107_1231.md").write_text("# Validator B")
    (reviews_dir / "code-review-1-4-master-20251209-233000.md").write_text("# Master")

    # Validations
    validations_dir = new_base / "story-validations"
    validations_dir.mkdir()
    (validations_dir / "synthesis-20-1-20260107T154829.md").write_text("# Validation Synthesis")
    # New format: single letter role_id
    (validations_dir / "validation-20-1-c-20260107T154039.md").write_text("# Validator C")

    # Retrospectives
    retros_dir = new_base / "retrospectives"
    retros_dir.mkdir()
    (retros_dir / "epic-12-retro-20260105.md").write_text("# Epic 12 Retrospective")
    (retros_dir / "epic-testarch-retro-20260105.md").write_text("# Testarch Retrospective")

    return tmp_path


@pytest.fixture
def temp_project_legacy(tmp_path: Path) -> Path:
    """Create a temporary project with legacy artifact locations."""
    # Legacy location: docs/sprint-artifacts/
    legacy_base = tmp_path / "docs" / "sprint-artifacts"

    # Stories
    stories_dir = legacy_base / "stories"
    stories_dir.mkdir(parents=True)
    (stories_dir / "1-1-setup.md").write_text("# Story 1.1\n\nStatus: done\n")

    # Code reviews
    reviews_dir = legacy_base / "code-reviews"
    reviews_dir.mkdir()
    (reviews_dir / "code-review-1-1-master-20251209.md").write_text("# Master Review")

    # Validations
    validations_dir = legacy_base / "story-validations"
    validations_dir.mkdir()
    (validations_dir / "story-validation-1-1-master-20251209-151848.md").write_text(
        "# Legacy Validation"
    )

    return tmp_path


@pytest.fixture
def temp_project_both(tmp_path: Path) -> Path:
    """Create a project with both legacy and new artifact locations."""
    # Legacy
    legacy_base = tmp_path / "docs" / "sprint-artifacts"
    (legacy_base / "stories").mkdir(parents=True)
    (legacy_base / "stories" / "1-1-setup.md").write_text("# Story 1.1\n\nStatus: backlog\n")

    # New (takes precedence)
    new_base = tmp_path / "_bmad-output" / "implementation-artifacts"
    (new_base / "stories").mkdir(parents=True)
    (new_base / "stories" / "1-1-setup.md").write_text(
        "# Story 1.1\n\nStatus: done\n"
    )  # Different status

    return tmp_path


# ============================================================================
# Tests: Regex Patterns
# ============================================================================


class TestStoryFilenamePattern:
    """Tests for STORY_FILENAME_PATTERN regex."""

    def test_standard_numeric_epic(self) -> None:
        """Test standard numeric epic story filename."""
        match = STORY_FILENAME_PATTERN.match("20-1-entry-classification-system.md")
        assert match is not None
        assert match.group("epic") == "20"
        assert match.group("story") == "1"
        assert match.group("slug") == "entry-classification-system"

    def test_string_epic(self) -> None:
        """Test string epic story filename."""
        match = STORY_FILENAME_PATTERN.match("testarch-1-config.md")
        assert match is not None
        assert match.group("epic") == "testarch"
        assert match.group("story") == "1"
        assert match.group("slug") == "config"

    def test_standalone_epic(self) -> None:
        """Test standalone story filename."""
        match = STORY_FILENAME_PATTERN.match("standalone-01-reconciler-refactoring.md")
        assert match is not None
        assert match.group("epic") == "standalone"
        assert match.group("story") == "01"
        assert match.group("slug") == "reconciler-refactoring"

    def test_no_match_invalid_format(self) -> None:
        """Test that invalid formats don't match."""
        assert STORY_FILENAME_PATTERN.match("readme.md") is None
        assert STORY_FILENAME_PATTERN.match("index.md") is None
        assert STORY_FILENAME_PATTERN.match("20.md") is None


class TestSynthesisPattern:
    """Tests for SYNTHESIS_PATTERN regex."""

    def test_synthesis_with_timestamp(self) -> None:
        """Test synthesis filename with timestamp."""
        match = SYNTHESIS_PATTERN.match("synthesis-20-1-20260107_1234.md")
        assert match is not None
        assert match.group("epic") == "20"
        assert match.group("story") == "1"
        assert match.group("timestamp") == "20260107_1234"

    def test_synthesis_with_t_timestamp(self) -> None:
        """Test synthesis filename with T-format timestamp."""
        match = SYNTHESIS_PATTERN.match("synthesis-20-1-20260107T154829.md")
        assert match is not None
        assert match.group("timestamp") == "20260107T154829"

    def test_synthesis_without_timestamp(self) -> None:
        """Test synthesis filename without timestamp."""
        match = SYNTHESIS_PATTERN.match("synthesis-20-4.md")
        assert match is not None
        assert match.group("epic") == "20"
        assert match.group("story") == "4"
        assert match.group("timestamp") is None

    def test_synthesis_string_epic(self) -> None:
        """Test synthesis with string epic."""
        match = SYNTHESIS_PATTERN.match("synthesis-testarch-2-20260104_1857.md")
        assert match is not None
        assert match.group("epic") == "testarch"
        assert match.group("story") == "2"


class TestCodeReviewPattern:
    """Tests for CODE_REVIEW_PATTERN regex (new format with role_id)."""

    def test_code_review_new_format(self) -> None:
        """Test new code review filename with single letter role_id."""
        match = CODE_REVIEW_PATTERN.match("code-review-22-11-a-20260115T155525Z.md")
        assert match is not None
        assert match.group("epic") == "22"
        assert match.group("story") == "11"
        assert match.group("role_id") == "a"
        assert match.group("timestamp") == "20260115T155525Z"

    def test_code_review_without_z_suffix(self) -> None:
        """Test code review filename without Z suffix in timestamp."""
        match = CODE_REVIEW_PATTERN.match("code-review-20-4-g-20260107T173800.md")
        assert match is not None
        assert match.group("epic") == "20"
        assert match.group("story") == "4"
        assert match.group("role_id") == "g"


class TestLegacyReviewPattern:
    """Tests for LEGACY_REVIEW_PATTERN regex."""

    def test_legacy_master_review(self) -> None:
        """Test legacy master code review filename."""
        match = LEGACY_REVIEW_PATTERN.match("code-review-1-4-master-20251209-233000.md")
        assert match is not None
        assert match.group("epic") == "1"
        assert match.group("story") == "4"
        assert match.group("reviewer") == "master"
        assert match.group("timestamp") == "20251209-233000"

    def test_legacy_standalone_review(self) -> None:
        """Test legacy standalone code review filename."""
        match = LEGACY_REVIEW_PATTERN.match("code-review-standalone-01-master-20251210.md")
        assert match is not None
        assert match.group("epic") == "standalone"
        assert match.group("story") == "01"


class TestNewValidationPattern:
    """Tests for NEW_VALIDATION_PATTERN regex (role_id format)."""

    def test_new_validation_role_id(self) -> None:
        """Test new format validation filename with single letter role_id."""
        match = NEW_VALIDATION_PATTERN.match("validation-22-11-a-20260115T155525Z.md")
        assert match is not None
        assert match.group("epic") == "22"
        assert match.group("story") == "11"
        assert match.group("role_id") == "a"
        assert match.group("timestamp") == "20260115T155525Z"

    def test_new_validation_another_role(self) -> None:
        """Test validation with another role_id letter."""
        match = NEW_VALIDATION_PATTERN.match("validation-20-5-h-20260107T175546.md")
        assert match is not None
        assert match.group("epic") == "20"
        assert match.group("story") == "5"
        assert match.group("role_id") == "h"
        assert match.group("timestamp") == "20260107T175546"


class TestLegacyValidationPattern:
    """Tests for LEGACY_VALIDATION_PATTERN regex."""

    def test_legacy_validation(self) -> None:
        """Test legacy validation filename."""
        match = LEGACY_VALIDATION_PATTERN.match("story-validation-1-4-master-20251209.md")
        assert match is not None
        assert match.group("epic") == "1"
        assert match.group("story") == "4"
        assert match.group("reviewer") == "master"


class TestRetroPattern:
    """Tests for RETRO_PATTERN regex."""

    def test_numeric_epic_retro(self) -> None:
        """Test retrospective with numeric epic."""
        match = RETRO_PATTERN.match("epic-15-retro-20260106.md")
        assert match is not None
        assert match.group("epic_id") == "15"
        assert match.group("timestamp") == "20260106"

    def test_string_epic_retro(self) -> None:
        """Test retrospective with string epic."""
        match = RETRO_PATTERN.match("epic-testarch-retro-20260105.md")
        assert match is not None
        assert match.group("epic_id") == "testarch"

    def test_retrospective_spelling(self) -> None:
        """Test 'retrospective' spelling variant."""
        match = RETRO_PATTERN.match("epic-5-retrospective.md")
        assert match is not None
        assert match.group("epic_id") == "5"

    def test_retro_no_timestamp(self) -> None:
        """Test retrospective without timestamp."""
        match = RETRO_PATTERN.match("epic-2-retro.md")
        assert match is not None
        assert match.group("epic_id") == "2"
        assert match.group("timestamp") is None


# ============================================================================
# Tests: Helper Functions
# ============================================================================


class TestNormalizeStoryKey:
    """Tests for _normalize_story_key function."""

    def test_full_key_to_short(self) -> None:
        """Test converting full key with slug to short key."""
        assert _normalize_story_key("20-1-entry-classification-system") == "20-1"

    def test_short_key_unchanged(self) -> None:
        """Test that short key remains unchanged."""
        assert _normalize_story_key("20-1") == "20-1"

    def test_string_epic(self) -> None:
        """Test string epic key normalization."""
        assert _normalize_story_key("testarch-1-config") == "testarch-1"

    def test_standalone_key(self) -> None:
        """Test standalone story key normalization."""
        assert _normalize_story_key("standalone-01-reconciler-refactoring") == "standalone-01"


class TestExtractStoryStatus:
    """Tests for _extract_story_status function."""

    def test_status_extracted(self) -> None:
        """Test that status is extracted correctly."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"# Story 20.1\n\nStatus: done\n\nSome content...")
            f.flush()
            path = Path(f.name)
            assert _extract_story_status(path) == "done"
            path.unlink()

    def test_status_in_progress(self) -> None:
        """Test in-progress status extraction."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"# Story\n\nStatus: in-progress\n")
            f.flush()
            path = Path(f.name)
            assert _extract_story_status(path) == "in-progress"
            path.unlink()

    def test_no_status_returns_none(self) -> None:
        """Test that missing status returns None."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"# Story\n\nNo status field here")
            f.flush()
            path = Path(f.name)
            assert _extract_story_status(path) is None
            path.unlink()

    def test_case_insensitive(self) -> None:
        """Test that status matching is case insensitive."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"# Story\n\nSTATUS: DONE\n")
            f.flush()
            path = Path(f.name)
            # Returns lowercase
            assert _extract_story_status(path) == "done"
            path.unlink()

    def test_nonexistent_file_returns_none(self) -> None:
        """Test that nonexistent file returns None."""
        assert _extract_story_status(Path("/nonexistent/path.md")) is None


class TestParseEpicId:
    """Tests for _parse_epic_id function."""

    def test_numeric_epic(self) -> None:
        """Test numeric epic ID parsing."""
        assert _parse_epic_id("12") == 12
        assert isinstance(_parse_epic_id("12"), int)

    def test_string_epic(self) -> None:
        """Test string epic ID parsing."""
        assert _parse_epic_id("testarch") == "testarch"
        assert isinstance(_parse_epic_id("testarch"), str)


class TestGetArtifactLocations:
    """Tests for _get_artifact_locations function."""

    def test_new_location_only(self, temp_project: Path) -> None:
        """Test when only new location exists."""
        locations = _get_artifact_locations(temp_project)
        # 2 locations: stories/ subdirectory + base implementation-artifacts/
        assert len(locations["stories"]) == 2
        assert "stories" in str(locations["stories"][0])
        assert "implementation-artifacts" in str(locations["stories"][1])

    def test_legacy_location_only(self, temp_project_legacy: Path) -> None:
        """Test when only legacy location exists."""
        locations = _get_artifact_locations(temp_project_legacy)
        assert len(locations["stories"]) == 1
        assert "sprint-artifacts" in str(locations["stories"][0])

    def test_both_locations(self, temp_project_both: Path) -> None:
        """Test when both locations exist."""
        locations = _get_artifact_locations(temp_project_both)
        # 3 locations: legacy stories/ + new stories/ + base implementation-artifacts/
        assert len(locations["stories"]) == 3
        # Legacy first, new subdirectory second, base last (new takes precedence)
        assert "sprint-artifacts" in str(locations["stories"][0])
        assert "stories" in str(locations["stories"][1])
        assert "implementation-artifacts" in str(locations["stories"][2])

    def test_empty_project(self, tmp_path: Path) -> None:
        """Test with empty project."""
        locations = _get_artifact_locations(tmp_path)
        assert locations["stories"] == []
        assert locations["code_reviews"] == []
        assert locations["validations"] == []
        assert locations["retrospectives"] == []


# ============================================================================
# Tests: Individual Scanners
# ============================================================================


class TestScanStories:
    """Tests for _scan_stories function."""

    def test_scan_stories(self, temp_project: Path) -> None:
        """Test scanning story files."""
        stories_dir = temp_project / "_bmad-output" / "implementation-artifacts" / "stories"
        stories = _scan_stories([stories_dir])

        assert len(stories) == 4
        assert "20-1-entry-classification-system" in stories
        assert stories["20-1-entry-classification-system"].status == "done"
        assert stories["20-2-canonical-model"].status == "in-progress"
        assert stories["testarch-1-config"].status == "review"
        assert stories["20-3-parser"].status is None

    def test_scan_skips_readme(self, tmp_path: Path) -> None:
        """Test that README.md is skipped."""
        stories_dir = tmp_path / "stories"
        stories_dir.mkdir()
        (stories_dir / "README.md").write_text("# README")
        (stories_dir / "20-1-test.md").write_text("# Story\n\nStatus: done")

        stories = _scan_stories([stories_dir])
        assert "README" not in str(stories)
        assert len(stories) == 1


class TestScanCodeReviews:
    """Tests for _scan_code_reviews function."""

    def test_scan_code_reviews(self, temp_project: Path) -> None:
        """Test scanning code review files."""
        reviews_dir = temp_project / "_bmad-output" / "implementation-artifacts" / "code-reviews"
        reviews = _scan_code_reviews([reviews_dir])

        # Should have two story keys: 20-1 and 1-4
        assert "20-1" in reviews
        assert "1-4" in reviews

        # 20-1 should have 3 reviews (synthesis + 2 validators)
        assert len(reviews["20-1"]) == 3

        # Check synthesis is marked correctly
        synthesis_reviews = [r for r in reviews["20-1"] if r.is_synthesis]
        assert len(synthesis_reviews) == 1
        assert synthesis_reviews[0].is_master is True

        # Check validator is marked correctly
        validator_reviews = [r for r in reviews["20-1"] if r.reviewer == "validator_a"]
        assert len(validator_reviews) == 1
        assert validator_reviews[0].is_master is False

        # Check legacy master review
        assert len(reviews["1-4"]) == 1
        assert reviews["1-4"][0].is_master is True


class TestScanValidations:
    """Tests for _scan_validations function."""

    def test_scan_validations(self, temp_project: Path) -> None:
        """Test scanning validation files."""
        validations_dir = (
            temp_project / "_bmad-output" / "implementation-artifacts" / "story-validations"
        )
        validations = _scan_validations([validations_dir])

        assert "20-1" in validations
        assert len(validations["20-1"]) == 2

        # Check synthesis
        synthesis = [v for v in validations["20-1"] if v.is_synthesis]
        assert len(synthesis) == 1

        # Check validator (new format uses single letter role_id)
        validators = [v for v in validations["20-1"] if not v.is_synthesis]
        assert len(validators) == 1
        assert validators[0].reviewer == "c"  # Single letter role_id


class TestScanRetrospectives:
    """Tests for _scan_retrospectives function."""

    def test_scan_retrospectives(self, temp_project: Path) -> None:
        """Test scanning retrospective files."""
        retros_dir = temp_project / "_bmad-output" / "implementation-artifacts" / "retrospectives"
        retros = _scan_retrospectives([retros_dir])

        assert len(retros) == 2
        assert "12" in retros
        assert "testarch" in retros

        assert retros["12"].epic_id == 12
        assert retros["testarch"].epic_id == "testarch"
        assert retros["12"].timestamp == "20260105"


# ============================================================================
# Tests: ArtifactIndex
# ============================================================================


class TestArtifactIndexScan:
    """Tests for ArtifactIndex.scan() class method."""

    def test_scan_creates_index(self, temp_project: Path) -> None:
        """Test that scan creates a populated index."""
        index = ArtifactIndex.scan(temp_project)

        assert len(index.story_files) == 4
        assert len(index.code_reviews) == 2
        assert len(index.validations) == 1
        assert len(index.retrospectives) == 2
        assert isinstance(index.scan_time, datetime)

    def test_new_location_takes_precedence(self, temp_project_both: Path) -> None:
        """Test that new location overwrites legacy."""
        index = ArtifactIndex.scan(temp_project_both)

        # Should have status "done" from new location, not "backlog" from legacy
        assert index.get_story_status("1-1-setup") == "done"

    def test_empty_project(self, tmp_path: Path) -> None:
        """Test scanning empty project."""
        index = ArtifactIndex.scan(tmp_path)

        assert len(index.story_files) == 0
        assert len(index.code_reviews) == 0
        assert len(index.validations) == 0
        assert len(index.retrospectives) == 0


class TestArtifactIndexQueryMethods:
    """Tests for ArtifactIndex query methods."""

    @pytest.fixture
    def index(self, temp_project: Path) -> ArtifactIndex:
        """Create index from temp project."""
        return ArtifactIndex.scan(temp_project)

    def test_has_story_file_full_key(self, index: ArtifactIndex) -> None:
        """Test has_story_file with full key."""
        assert index.has_story_file("20-1-entry-classification-system") is True
        assert index.has_story_file("nonexistent-99-foo") is False

    def test_has_story_file_short_key(self, index: ArtifactIndex) -> None:
        """Test has_story_file with short key."""
        assert index.has_story_file("20-1") is True
        assert index.has_story_file("99-99") is False

    def test_get_story_status_full_key(self, index: ArtifactIndex) -> None:
        """Test get_story_status with full key."""
        assert index.get_story_status("20-1-entry-classification-system") == "done"
        assert index.get_story_status("20-2-canonical-model") == "in-progress"

    def test_get_story_status_short_key(self, index: ArtifactIndex) -> None:
        """Test get_story_status with short key."""
        assert index.get_story_status("20-1") == "done"
        assert index.get_story_status("testarch-1") == "review"

    def test_get_story_status_none(self, index: ArtifactIndex) -> None:
        """Test get_story_status returns None for missing status."""
        # 20-3-parser has no Status field
        assert index.get_story_status("20-3-parser") is None
        # Nonexistent story
        assert index.get_story_status("99-99") is None

    def test_has_master_review(self, index: ArtifactIndex) -> None:
        """Test has_master_review query."""
        assert index.has_master_review("20-1") is True  # Has synthesis
        assert index.has_master_review("1-4") is True  # Has legacy master
        assert index.has_master_review("99-99") is False

    def test_has_any_review(self, index: ArtifactIndex) -> None:
        """Test has_any_review query."""
        assert index.has_any_review("20-1") is True
        assert index.has_any_review("1-4") is True
        assert index.has_any_review("99-99") is False

    def test_get_code_reviews(self, index: ArtifactIndex) -> None:
        """Test get_code_reviews query."""
        reviews = index.get_code_reviews("20-1")
        assert len(reviews) == 3

        reviews_nonexistent = index.get_code_reviews("99-99")
        assert reviews_nonexistent == []

    def test_has_validation(self, index: ArtifactIndex) -> None:
        """Test has_validation query."""
        assert index.has_validation("20-1") is True
        assert index.has_validation("99-99") is False

    def test_get_validations(self, index: ArtifactIndex) -> None:
        """Test get_validations query."""
        validations = index.get_validations("20-1")
        assert len(validations) == 2

        validations_nonexistent = index.get_validations("99-99")
        assert validations_nonexistent == []

    def test_has_retrospective(self, index: ArtifactIndex) -> None:
        """Test has_retrospective query."""
        assert index.has_retrospective(12) is True
        assert index.has_retrospective("testarch") is True
        assert index.has_retrospective(99) is False

    def test_get_retrospective(self, index: ArtifactIndex) -> None:
        """Test get_retrospective query."""
        retro = index.get_retrospective(12)
        assert retro is not None
        assert retro.epic_id == 12
        assert retro.timestamp == "20260105"

        retro_testarch = index.get_retrospective("testarch")
        assert retro_testarch is not None
        assert retro_testarch.epic_id == "testarch"

        retro_nonexistent = index.get_retrospective(99)
        assert retro_nonexistent is None


class TestArtifactIndexRepr:
    """Tests for ArtifactIndex __repr__."""

    def test_repr(self, temp_project: Path) -> None:
        """Test __repr__ output."""
        index = ArtifactIndex.scan(temp_project)
        repr_str = repr(index)

        assert "ArtifactIndex" in repr_str
        assert "stories=4" in repr_str
        assert "code_reviews=2" in repr_str
        assert "validations=1" in repr_str
        assert "retrospectives=2" in repr_str


# ============================================================================
# Tests: Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.skipif(os.geteuid() == 0, reason="Root ignores permissions")
    def test_permission_error_handled(self, tmp_path: Path) -> None:
        """Test that permission errors are handled gracefully."""
        stories_dir = tmp_path / "stories"
        stories_dir.mkdir()
        story_file = stories_dir / "20-1-test.md"
        story_file.write_text("# Story\n\nStatus: done")

        # Make file unreadable
        story_file.chmod(0o000)

        try:
            stories = _scan_stories([stories_dir])
            # Should have entry with None status due to read error
            assert "20-1-test" in stories
            assert stories["20-1-test"].status is None
        finally:
            # Restore permissions for cleanup
            story_file.chmod(0o644)

    def test_empty_status_value(self, tmp_path: Path) -> None:
        """Test handling of empty status value."""
        stories_dir = tmp_path / "stories"
        stories_dir.mkdir()
        (stories_dir / "20-1-test.md").write_text("# Story\n\nStatus:\n")

        stories = _scan_stories([stories_dir])
        assert stories["20-1-test"].status is None

    def test_unicode_in_story_content(self, tmp_path: Path) -> None:
        """Test handling of unicode characters in story content."""
        stories_dir = tmp_path / "stories"
        stories_dir.mkdir()
        (stories_dir / "20-1-test.md").write_text(
            "# Story with émojis 🎉\n\nStatus: done\n\nContent with ñ"
        )

        stories = _scan_stories([stories_dir])
        assert stories["20-1-test"].status == "done"

    def test_nonexistent_directory(self) -> None:
        """Test scanning nonexistent directory."""
        stories = _scan_stories([Path("/nonexistent/path")])
        assert stories == {}


# ============================================================================
# Tests: Real Project Integration (if available)
# ============================================================================


class TestRealProjectIntegration:
    """Integration tests using real project artifacts."""

    @pytest.fixture
    def real_project_root(self) -> Path:
        """Get the real project root path."""
        # This assumes tests are run from the project root
        return Path(__file__).parent.parent.parent

    def test_scan_real_project(self, real_project_root: Path) -> None:
        """Test scanning the real bmad-assist project."""
        target_dir = real_project_root / "_bmad-output" / "implementation-artifacts" / "stories"
        # Skip if not in the real project or empty
        if not target_dir.exists() or not any(target_dir.iterdir()):
            pytest.skip("Real project artifacts not available")

        index = ArtifactIndex.scan(real_project_root)

        # Should find at least some artifacts
        assert len(index.story_files) > 0

    def test_query_real_story(self, real_project_root: Path) -> None:
        """Test querying a real story."""
        target_dir = real_project_root / "_bmad-output" / "implementation-artifacts" / "stories"
        if not target_dir.exists() or not any(target_dir.iterdir()):
            pytest.skip("Real project artifacts not available")

        index = ArtifactIndex.scan(real_project_root)

        # Story 20-1 should exist and have status
        if index.has_story_file("20-1"):
            status = index.get_story_status("20-1")
            # Status should be a valid value or None
            assert status is None or status in (
                "backlog",
                "ready-for-dev",
                "in-progress",
                "review",
                "done",
                "blocked",
                "deferred",
            )

    def test_query_real_retrospective(self, real_project_root: Path) -> None:
        """Test querying real retrospectives."""
        target_dir = real_project_root / "_bmad-output" / "implementation-artifacts" / "retrospectives"
        if not target_dir.exists() or not any(target_dir.iterdir()):
            pytest.skip("Real project artifacts not available")

        index = ArtifactIndex.scan(real_project_root)

        # Should find testarch retrospective if it exists
        if index.has_retrospective("testarch"):
            retro = index.get_retrospective("testarch")
            assert retro is not None
            assert retro.epic_id == "testarch"


# ============================================================================
# Tests: Dataclass Instances
# ============================================================================


class TestDataclasses:
    """Tests for artifact dataclass instances."""

    def test_story_artifact_frozen(self) -> None:
        """Test that StoryArtifact is frozen (immutable)."""
        artifact = StoryArtifact(
            path=Path("/test/story.md"),
            story_key="20-1-test",
            status="done",
        )
        with pytest.raises(AttributeError):
            artifact.status = "changed"  # type: ignore[misc]

    def test_code_review_artifact_frozen(self) -> None:
        """Test that CodeReviewArtifact is frozen."""
        artifact = CodeReviewArtifact(
            path=Path("/test/review.md"),
            story_key="20-1",
            reviewer="master",
            is_synthesis=False,
            is_master=True,
            timestamp="20260107",
        )
        with pytest.raises(AttributeError):
            artifact.is_master = False  # type: ignore[misc]

    def test_validation_artifact_frozen(self) -> None:
        """Test that ValidationArtifact is frozen."""
        artifact = ValidationArtifact(
            path=Path("/test/validation.md"),
            story_key="20-1",
            reviewer="master",
            is_synthesis=False,
            timestamp="20260107",
        )
        with pytest.raises(AttributeError):
            artifact.is_synthesis = True  # type: ignore[misc]

    def test_retrospective_artifact_frozen(self) -> None:
        """Test that RetrospectiveArtifact is frozen."""
        artifact = RetrospectiveArtifact(
            path=Path("/test/retro.md"),
            epic_id=12,
            timestamp="20260107",
        )
        with pytest.raises(AttributeError):
            artifact.epic_id = 99  # type: ignore[misc]
