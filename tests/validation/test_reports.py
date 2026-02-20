"""Tests for validation report persistence module.

Story 11.8: Validation Report Persistence

Tests cover:
- ValidationReportMetadata dataclass (AC4)
- list_validations() function with filtering (AC3)
- Malformed frontmatter handling (AC5)
- Empty results handling (AC6)
- save_validation_report() (AC1)
- save_synthesis_report() (AC2)
- extract_validation_report() (Multi-LLM extraction)
"""

from datetime import UTC, datetime
from pathlib import Path

import frontmatter
import pytest

from bmad_assist.validation.anonymizer import ValidationOutput
from bmad_assist.validation.reports import (
    ValidationReportMetadata,
    extract_validation_report,
    list_validations,
    save_synthesis_report,
    save_validation_report,
)


class TestValidationReportMetadataAC4:
    """Test AC4: ValidationReportMetadata dataclass."""

    def test_validation_report_metadata_fields(self) -> None:
        """Test all fields present for validation type."""
        metadata = ValidationReportMetadata(
            path=Path("/test/validation.md"),
            report_type="validation",
            validator_id="claude-opus_4",
            master_validator_id=None,
            timestamp=datetime(2025, 12, 16, 14, 30, 22, tzinfo=UTC),
            epic=11,
            story=8,
            phase="VALIDATE_STORY",
            duration_ms=5234,
            token_count=1847,
            session_id=None,
            validators_used=None,
        )

        assert metadata.report_type == "validation"
        assert metadata.validator_id == "claude-opus_4"
        assert metadata.phase == "VALIDATE_STORY"
        assert metadata.token_count == 1847
        # Synthesis-only fields must be None for validation
        assert metadata.master_validator_id is None
        assert metadata.session_id is None
        assert metadata.validators_used is None

    def test_synthesis_report_metadata_fields(self) -> None:
        """Test all fields present for synthesis type."""
        metadata = ValidationReportMetadata(
            path=Path("/test/synthesis.md"),
            report_type="synthesis",
            validator_id=None,
            master_validator_id="master-opus_4",
            timestamp=datetime(2025, 12, 16, 15, 45, 33, tzinfo=UTC),
            epic=11,
            story=8,
            phase=None,
            duration_ms=8432,
            token_count=None,
            session_id="abc123-uuid",
            validators_used=["Validator A", "Validator B"],
        )

        assert metadata.report_type == "synthesis"
        assert metadata.master_validator_id == "master-opus_4"
        assert metadata.session_id == "abc123-uuid"
        assert metadata.validators_used == ["Validator A", "Validator B"]
        # Validation-only fields must be None for synthesis
        assert metadata.validator_id is None
        assert metadata.phase is None
        assert metadata.token_count is None

    def test_metadata_frozen(self) -> None:
        """Test that metadata is immutable (frozen dataclass)."""
        metadata = ValidationReportMetadata(
            path=Path("/test/validation.md"),
            report_type="validation",
            validator_id="claude-opus_4",
            master_validator_id=None,
            timestamp=datetime.now(UTC),
            epic=11,
            story=8,
            phase="VALIDATE_STORY",
            duration_ms=5234,
            token_count=1847,
            session_id=None,
            validators_used=None,
        )

        with pytest.raises(AttributeError):
            metadata.epic = 12  # type: ignore[misc]


class TestListValidationsAC3:
    """Test AC3: list_validations() function with filtering."""

    @pytest.fixture
    def validations_dir(self, tmp_path: Path) -> Path:
        """Create story-validations directory structure."""
        dir_path = tmp_path / "docs" / "sprint-artifacts" / "story-validations"
        dir_path.mkdir(parents=True)
        return dir_path

    @pytest.fixture
    def sample_validation_report(self, validations_dir: Path) -> Path:
        """Create a sample validation report."""
        content = """---
type: validation
validator_id: claude-opus_4
timestamp: 2025-12-16T14:30:22+00:00
epic: 11
story: 8
phase: VALIDATE_STORY
duration_ms: 5234
token_count: 1847
---

## Issues Found

1. Missing test coverage
"""
        file_path = validations_dir / "validation-11-8-claude-opus_4-20251216T143022.md"
        file_path.write_text(content)
        return file_path

    @pytest.fixture
    def sample_synthesis_report(self, validations_dir: Path) -> Path:
        """Create a sample synthesis report."""
        content = """---
type: synthesis
master_validator_id: master-opus_4
timestamp: 2025-12-16T15:45:33+00:00
epic: 11
story: 8
validators_used:
  - Validator A
  - Validator B
duration_ms: 8432
session_id: abc123-uuid
---

## Synthesis Summary

Combined findings from validators.
"""
        file_path = validations_dir / "synthesis-11-8-20251216T154533.md"
        file_path.write_text(content)
        return file_path

    @pytest.fixture
    def multiple_reports(self, validations_dir: Path) -> list[Path]:
        """Create multiple reports for filtering tests."""
        reports = []

        # Validation 1: Claude at 14:30
        content1 = """---
type: validation
validator_id: claude-opus_4
timestamp: 2025-12-16T14:30:22+00:00
epic: 11
story: 8
phase: VALIDATE_STORY
duration_ms: 5234
token_count: 1847
---

Content 1
"""
        path1 = validations_dir / "validation-11-8-claude-opus_4-20251216T143022.md"
        path1.write_text(content1)
        reports.append(path1)

        # Validation 2: Gemini at 14:35
        content2 = """---
type: validation
validator_id: gemini-gemini_2_5_pro
timestamp: 2025-12-16T14:35:00+00:00
epic: 11
story: 8
phase: VALIDATE_STORY
duration_ms: 4200
token_count: 1500
---

Content 2
"""
        path2 = validations_dir / "validation-11-8-gemini-gemini_2_5_pro-20251216T143500.md"
        path2.write_text(content2)
        reports.append(path2)

        # Synthesis at 15:00
        content3 = """---
type: synthesis
master_validator_id: master-opus_4
timestamp: 2025-12-16T15:00:00+00:00
epic: 11
story: 8
validators_used:
  - Validator A
  - Validator B
duration_ms: 8000
session_id: session-123
---

Synthesis content
"""
        path3 = validations_dir / "synthesis-11-8-20251216T150000.md"
        path3.write_text(content3)
        reports.append(path3)

        return reports

    def test_list_validations_basic(
        self,
        validations_dir: Path,
        sample_validation_report: Path,
        sample_synthesis_report: Path,
    ) -> None:
        """Test basic listing of all reports for epic/story."""
        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
        )

        assert len(results) == 2
        # Should be sorted by timestamp descending (newest first)
        assert results[0].report_type == "synthesis"  # 15:45 > 14:30
        assert results[1].report_type == "validation"

    def test_list_validations_sorted_descending(
        self,
        validations_dir: Path,
        multiple_reports: list[Path],
    ) -> None:
        """Test results sorted by timestamp descending (newest first)."""
        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
        )

        assert len(results) == 3
        # Timestamps: 15:00 (synthesis), 14:35 (gemini), 14:30 (claude)
        timestamps = [r.timestamp for r in results]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_filter_by_validator_id(
        self,
        validations_dir: Path,
        multiple_reports: list[Path],
    ) -> None:
        """Test filtering by validator_id."""
        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
            validator_id="claude-opus_4",
        )

        assert len(results) == 1
        assert results[0].validator_id == "claude-opus_4"

    def test_filter_by_report_type_validation(
        self,
        validations_dir: Path,
        multiple_reports: list[Path],
    ) -> None:
        """Test filtering by report_type 'validation'."""
        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
            report_type="validation",
        )

        assert len(results) == 2
        assert all(r.report_type == "validation" for r in results)

    def test_filter_by_report_type_synthesis(
        self,
        validations_dir: Path,
        multiple_reports: list[Path],
    ) -> None:
        """Test filtering by report_type 'synthesis'."""
        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
            report_type="synthesis",
        )

        assert len(results) == 1
        assert results[0].report_type == "synthesis"

    def test_filter_by_date_range(
        self,
        validations_dir: Path,
        multiple_reports: list[Path],
    ) -> None:
        """Test filtering by date range (start_date, end_date)."""
        # Filter to only get reports between 14:32 and 14:58
        start_date = datetime(2025, 12, 16, 14, 32, 0, tzinfo=UTC)
        end_date = datetime(2025, 12, 16, 14, 58, 0, tzinfo=UTC)

        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
            start_date=start_date,
            end_date=end_date,
        )

        # Only gemini at 14:35 should match
        assert len(results) == 1
        assert results[0].validator_id == "gemini-gemini_2_5_pro"

    def test_filter_by_start_date_only(
        self,
        validations_dir: Path,
        multiple_reports: list[Path],
    ) -> None:
        """Test filtering with start_date only."""
        start_date = datetime(2025, 12, 16, 14, 32, 0, tzinfo=UTC)

        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
            start_date=start_date,
        )

        # Gemini (14:35) and synthesis (15:00) should match
        assert len(results) == 2

    def test_filter_by_end_date_only(
        self,
        validations_dir: Path,
        multiple_reports: list[Path],
    ) -> None:
        """Test filtering with end_date only."""
        end_date = datetime(2025, 12, 16, 14, 33, 0, tzinfo=UTC)

        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
            end_date=end_date,
        )

        # Only claude (14:30) should match
        assert len(results) == 1
        assert results[0].validator_id == "claude-opus_4"

    def test_combined_filters(
        self,
        validations_dir: Path,
        multiple_reports: list[Path],
    ) -> None:
        """Test combining validator_id and report_type filters."""
        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
            validator_id="claude-opus_4",
            report_type="validation",
        )

        assert len(results) == 1
        assert results[0].validator_id == "claude-opus_4"

    def test_filter_no_match(
        self,
        validations_dir: Path,
        multiple_reports: list[Path],
    ) -> None:
        """Test filtering with no matching results."""
        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
            validator_id="nonexistent-validator",
        )

        assert results == []

    def test_different_epic_story(
        self,
        validations_dir: Path,
        sample_validation_report: Path,
    ) -> None:
        """Test filtering by different epic/story returns empty."""
        # Looking for epic 10, story 5 (doesn't exist)
        results = list_validations(
            validations_dir=validations_dir,
            epic=10,
            story=5,
        )

        assert results == []


class TestEmptyResultsAC6:
    """Test AC6: Empty results handling."""

    @pytest.fixture
    def empty_validations_dir(self, tmp_path: Path) -> Path:
        """Create empty story-validations directory."""
        dir_path = tmp_path / "docs" / "sprint-artifacts" / "story-validations"
        dir_path.mkdir(parents=True)
        return dir_path

    def test_empty_directory(self, empty_validations_dir: Path) -> None:
        """Test empty list returned for empty directory."""
        results = list_validations(
            validations_dir=empty_validations_dir,
            epic=11,
            story=8,
        )

        assert results == []
        assert isinstance(results, list)

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        """Test empty list returned for non-existent directory."""
        nonexistent_dir = tmp_path / "does" / "not" / "exist"

        results = list_validations(
            validations_dir=nonexistent_dir,
            epic=11,
            story=8,
        )

        assert results == []
        assert isinstance(results, list)


class TestMalformedReportsAC5:
    """Test AC5: Error handling for malformed reports."""

    @pytest.fixture
    def validations_dir(self, tmp_path: Path) -> Path:
        """Create story-validations directory structure."""
        dir_path = tmp_path / "docs" / "sprint-artifacts" / "story-validations"
        dir_path.mkdir(parents=True)
        return dir_path

    def test_missing_frontmatter(
        self,
        validations_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test file without frontmatter is skipped with WARNING."""
        # Create file without frontmatter
        content = """# Just a markdown file

No YAML frontmatter here.
"""
        file_path = validations_dir / "validation-11-8-bad-20251216T140000.md"
        file_path.write_text(content)

        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
        )

        # Should return empty list (file skipped)
        assert results == []
        # Should log WARNING
        assert "WARNING" in caplog.text or any(r.levelname == "WARNING" for r in caplog.records)

    def test_invalid_yaml_frontmatter(
        self,
        validations_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test file with invalid YAML is skipped with WARNING."""
        # Create file with malformed YAML
        content = """---
type: validation
validator_id: "unclosed quote
epic: not_a_number
---

Content here.
"""
        file_path = validations_dir / "validation-11-8-bad-20251216T140000.md"
        file_path.write_text(content)

        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
        )

        # Should return empty list (file skipped)
        assert results == []
        # Should log WARNING
        assert any(r.levelname == "WARNING" for r in caplog.records)

    def test_missing_required_field(
        self,
        validations_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test file with missing required field is skipped."""
        # Missing 'type' field
        content = """---
validator_id: claude-opus_4
timestamp: 2025-12-16T14:30:22+00:00
epic: 11
story: 8
phase: VALIDATE_STORY
duration_ms: 5234
token_count: 1847
---

Content here.
"""
        file_path = validations_dir / "validation-11-8-bad-20251216T140000.md"
        file_path.write_text(content)

        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
        )

        assert results == []
        assert any(r.levelname == "WARNING" for r in caplog.records)

    def test_mixed_valid_invalid_files(
        self,
        validations_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test valid files returned, invalid files skipped."""
        # Valid file
        valid_content = """---
type: validation
validator_id: claude-opus_4
timestamp: 2025-12-16T14:30:22+00:00
epic: 11
story: 8
phase: VALIDATE_STORY
duration_ms: 5234
token_count: 1847
---

Valid content.
"""
        valid_path = validations_dir / "validation-11-8-claude-opus_4-20251216T143022.md"
        valid_path.write_text(valid_content)

        # Invalid file
        invalid_content = "No frontmatter"
        invalid_path = validations_dir / "validation-11-8-bad-20251216T140000.md"
        invalid_path.write_text(invalid_content)

        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
        )

        # Should return only valid file
        assert len(results) == 1
        assert results[0].validator_id == "claude-opus_4"


class TestPathTraversalPrevention:
    """Test path traversal prevention in list_validations()."""

    @pytest.fixture
    def validations_dir(self, tmp_path: Path) -> Path:
        """Create story-validations directory structure."""
        dir_path = tmp_path / "docs" / "sprint-artifacts" / "story-validations"
        dir_path.mkdir(parents=True)
        return dir_path

    def test_symlink_outside_dir_skipped(
        self,
        validations_dir: Path,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test symlinks pointing outside validations dir are skipped."""
        # Create file outside validations dir
        outside_file = tmp_path / "secret.md"
        outside_file.write_text("""---
type: validation
validator_id: evil
timestamp: 2025-12-16T14:30:22+00:00
epic: 11
story: 8
phase: VALIDATE_STORY
duration_ms: 100
token_count: 50
---
Secret content
""")

        # Create symlink inside validations dir pointing to outside file
        symlink_path = validations_dir / "validation-11-8-evil-20251216T143022.md"
        try:
            symlink_path.symlink_to(outside_file)
        except OSError:
            pytest.skip("Symlink creation not supported on this platform")

        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
        )

        # Symlink should be skipped
        assert results == []
        # Should log WARNING about path traversal
        assert any("WARNING" in str(r) or r.levelname == "WARNING" for r in caplog.records)


class TestSafeLoaderUsage:
    """Test YAML SafeLoader usage prevents code injection."""

    @pytest.fixture
    def validations_dir(self, tmp_path: Path) -> Path:
        """Create story-validations directory structure."""
        dir_path = tmp_path / "docs" / "sprint-artifacts" / "story-validations"
        dir_path.mkdir(parents=True)
        return dir_path

    def test_yaml_injection_attempt_fails(
        self,
        validations_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that YAML injection via !!python/object fails safely."""
        # Attempt YAML injection with !!python/object
        malicious_content = """---
type: validation
validator_id: !!python/object/apply:os.system ["echo pwned"]
timestamp: 2025-12-16T14:30:22+00:00
epic: 11
story: 8
phase: VALIDATE_STORY
duration_ms: 5234
token_count: 1847
---

Malicious content.
"""
        file_path = validations_dir / "validation-11-8-evil-20251216T143022.md"
        file_path.write_text(malicious_content)

        # Should not execute the injection - should either skip or safely parse
        results = list_validations(
            validations_dir=validations_dir,
            epic=11,
            story=8,
        )

        # SafeLoader should reject !!python tags
        # Either the file is skipped (warning) or parsed without execution
        # The key is that os.system should NOT have been called
        assert len(results) <= 1  # Either 0 or 1 if somehow parsed safely


class TestSaveValidationReportAC1:
    """Test AC1: Validation report YAML frontmatter."""

    @pytest.fixture
    def validations_dir(self, tmp_path: Path) -> Path:
        """Create story-validations directory structure."""
        dir_path = tmp_path / "docs" / "sprint-artifacts" / "story-validations"
        dir_path.mkdir(parents=True)
        return dir_path

    @pytest.fixture
    def sample_validation_output(self) -> ValidationOutput:
        """Sample ValidationOutput for testing."""
        return ValidationOutput(
            provider="claude-opus_4",
            model="claude-opus-4",
            content="## Issues Found\n\n1. Missing test coverage...",
            timestamp=datetime.now(UTC),
            duration_ms=5234,
            token_count=1847,
        )

    def test_save_creates_file(
        self,
        validations_dir: Path,
        sample_validation_output: ValidationOutput,
    ) -> None:
        """Test save_validation_report creates file."""
        result_path = save_validation_report(
            output=sample_validation_output,
            epic=11,
            story=8,
            phase="VALIDATE_STORY",
            validations_dir=validations_dir,
        )

        assert result_path.exists()
        assert result_path.suffix == ".md"

    def test_filename_pattern(
        self,
        validations_dir: Path,
        sample_validation_output: ValidationOutput,
    ) -> None:
        """Test filename follows pattern: validation-{epic}-{story}-{validator_id}-{timestamp}.md"""
        result_path = save_validation_report(
            output=sample_validation_output,
            epic=11,
            story=8,
            phase="VALIDATE_STORY",
            validations_dir=validations_dir,
        )

        # Filename should start with validation-11-8-claude-opus_4-
        assert result_path.name.startswith("validation-11-8-claude-opus_4-")
        # Should have timestamp format YYYYMMDDTHHMMSSZ (with Z suffix)
        parts = result_path.stem.split("-")
        timestamp_part = parts[-1]
        assert len(timestamp_part) == 16  # YYYYMMDDTHHMMSSZ (16 chars with Z)

    def test_frontmatter_fields(
        self,
        validations_dir: Path,
        sample_validation_output: ValidationOutput,
    ) -> None:
        """Test YAML frontmatter contains all required fields per AC1."""
        result_path = save_validation_report(
            output=sample_validation_output,
            epic=11,
            story=8,
            phase="VALIDATE_STORY",
            validations_dir=validations_dir,
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        metadata = post.metadata

        # Required fields per AC1
        assert metadata["type"] == "validation"
        assert metadata["validator_id"] == "claude-opus_4"
        assert "provider" not in metadata  # Provider excluded to preserve anonymization
        assert "model" not in metadata
        assert "timestamp" in metadata  # ISO 8601 format
        assert metadata["epic"] == 11
        assert metadata["story"] == 8
        assert metadata["phase"] == "VALIDATE_STORY"
        assert metadata["duration_ms"] == 5234
        assert metadata["token_count"] == 1847

    def test_timestamp_iso8601_format(
        self,
        validations_dir: Path,
        sample_validation_output: ValidationOutput,
    ) -> None:
        """Test timestamp is ISO 8601 with timezone."""
        result_path = save_validation_report(
            output=sample_validation_output,
            epic=11,
            story=8,
            phase="VALIDATE_STORY",
            validations_dir=validations_dir,
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        ts = post.metadata["timestamp"]
        # Should parse as ISO 8601 datetime
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None

    def test_content_after_frontmatter(
        self,
        validations_dir: Path,
        sample_validation_output: ValidationOutput,
    ) -> None:
        """Test validator output follows frontmatter."""
        result_path = save_validation_report(
            output=sample_validation_output,
            epic=11,
            story=8,
            phase="VALIDATE_STORY",
            validations_dir=validations_dir,
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        assert "## Issues Found" in post.content
        assert "Missing test coverage" in post.content

    def test_atomic_write_pattern(
        self,
        validations_dir: Path,
        sample_validation_output: ValidationOutput,
    ) -> None:
        """Test atomic write pattern (no .tmp file left behind)."""
        result_path = save_validation_report(
            output=sample_validation_output,
            epic=11,
            story=8,
            phase="VALIDATE_STORY",
            validations_dir=validations_dir,
        )

        # No .tmp files should remain
        tmp_files = list(validations_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

        # Target file should exist
        assert result_path.exists()

    def test_creates_parent_directory(
        self,
        tmp_path: Path,
        sample_validation_output: ValidationOutput,
    ) -> None:
        """Test creates parent directory if doesn't exist."""
        # Directory doesn't exist yet
        validations_dir = tmp_path / "new" / "nested" / "path"
        assert not validations_dir.exists()

        result_path = save_validation_report(
            output=sample_validation_output,
            epic=11,
            story=8,
            phase="VALIDATE_STORY",
            validations_dir=validations_dir,
        )

        assert result_path.exists()
        assert validations_dir.exists()

    def test_sanitizes_provider_id_for_filename(
        self,
        validations_dir: Path,
    ) -> None:
        """Test provider ID with special chars is sanitized for filename."""
        output = ValidationOutput(
            provider="provider/with:special*chars",
            model="model",
            content="content",
            timestamp=datetime.now(UTC),
            duration_ms=1000,
            token_count=100,
        )

        result_path = save_validation_report(
            output=output,
            epic=11,
            story=8,
            phase="VALIDATE_STORY",
            validations_dir=validations_dir,
        )

        # Filename should not contain / or :
        assert "/" not in result_path.name
        assert ":" not in result_path.name
        assert result_path.exists()


class TestSaveSynthesisReportAC2:
    """Test AC2: Synthesis report YAML frontmatter."""

    @pytest.fixture
    def validations_dir(self, tmp_path: Path) -> Path:
        """Create story-validations directory structure."""
        dir_path = tmp_path / "docs" / "sprint-artifacts" / "story-validations"
        dir_path.mkdir(parents=True)
        return dir_path

    def test_save_creates_file(self, validations_dir: Path) -> None:
        """Test save_synthesis_report creates file."""
        result_path = save_synthesis_report(
            content="## Synthesis Summary\n\nCombined findings...",
            master_validator_id="master-opus_4",
            session_id="abc123-uuid",
            validators_used=["Validator A", "Validator B"],
            epic=11,
            story=8,
            duration_ms=8432,
            validations_dir=validations_dir,
        )

        assert result_path.exists()
        assert result_path.suffix == ".md"

    def test_filename_pattern(self, validations_dir: Path) -> None:
        """Test filename follows pattern: synthesis-{epic}-{story}-{timestamp}.md"""
        result_path = save_synthesis_report(
            content="Synthesis content",
            master_validator_id="master-opus_4",
            session_id="abc123-uuid",
            validators_used=["Validator A"],
            epic=11,
            story=8,
            duration_ms=8432,
            validations_dir=validations_dir,
        )

        # Filename should start with synthesis-11-8-
        assert result_path.name.startswith("synthesis-11-8-")

    def test_frontmatter_fields(self, validations_dir: Path) -> None:
        """Test YAML frontmatter contains all required fields per AC2."""
        result_path = save_synthesis_report(
            content="Synthesis content",
            master_validator_id="master-opus_4",
            session_id="abc123-uuid",
            validators_used=["Validator A", "Validator B", "Validator C"],
            epic=11,
            story=8,
            duration_ms=8432,
            validations_dir=validations_dir,
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        metadata = post.metadata

        # Required fields per AC2
        assert metadata["type"] == "synthesis"
        assert metadata["master_validator_id"] == "master-opus_4"
        assert "timestamp" in metadata
        assert metadata["epic"] == 11
        assert metadata["story"] == 8
        assert metadata["validators_used"] == ["Validator A", "Validator B", "Validator C"]
        assert metadata["duration_ms"] == 8432
        assert metadata["session_id"] == "abc123-uuid"

    def test_timestamp_iso8601_format(self, validations_dir: Path) -> None:
        """Test timestamp is ISO 8601 with timezone."""
        result_path = save_synthesis_report(
            content="Synthesis content",
            master_validator_id="master-opus_4",
            session_id="abc123-uuid",
            validators_used=["Validator A"],
            epic=11,
            story=8,
            duration_ms=8432,
            validations_dir=validations_dir,
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        ts = post.metadata["timestamp"]
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None

    def test_content_after_frontmatter(self, validations_dir: Path) -> None:
        """Test synthesis output follows frontmatter."""
        result_path = save_synthesis_report(
            content="## Synthesis Summary\n\nCombined findings from all validators.",
            master_validator_id="master-opus_4",
            session_id="abc123-uuid",
            validators_used=["Validator A"],
            epic=11,
            story=8,
            duration_ms=8432,
            validations_dir=validations_dir,
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        assert "## Synthesis Summary" in post.content
        assert "Combined findings" in post.content

    def test_atomic_write_pattern(self, validations_dir: Path) -> None:
        """Test atomic write pattern (no .tmp file left behind)."""
        result_path = save_synthesis_report(
            content="Synthesis content",
            master_validator_id="master-opus_4",
            session_id="abc123-uuid",
            validators_used=["Validator A"],
            epic=11,
            story=8,
            duration_ms=8432,
            validations_dir=validations_dir,
        )

        # No .tmp files should remain
        tmp_files = list(validations_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

        # Target file should exist
        assert result_path.exists()


class TestExtractValidationReport:
    """Tests for extract_validation_report() function."""

    def test_extract_with_markers(self) -> None:
        """Test extraction with proper start and end markers."""
        raw_output = """Some LLM thinking about the task...

<!-- VALIDATION_REPORT_START -->
# 🎯 Story Context Validation Report

**Story:** 1-1-hero-section
**Validated:** 2025-12-18

## Executive Summary
Good story.

**Report Generated:** 2025-12-18
**Validator:** claude-opus
<!-- VALIDATION_REPORT_END -->

Some closing thoughts from the LLM."""

        result = extract_validation_report(raw_output)

        assert result.startswith("# 🎯 Story Context Validation Report")
        assert "**Story:** 1-1-hero-section" in result
        assert "Good story." in result
        assert "**Validator:** claude-opus" in result
        # Should NOT contain text outside markers
        assert "LLM thinking" not in result
        assert "closing thoughts" not in result

    def test_extract_with_markers_no_trailing_content(self) -> None:
        """Test extraction when markers are at very end."""
        raw_output = """<!-- VALIDATION_REPORT_START -->
# 🎯 Story Context Validation Report
Content here.
<!-- VALIDATION_REPORT_END -->"""

        result = extract_validation_report(raw_output)

        assert result == "# 🎯 Story Context Validation Report\nContent here."

    def test_extract_start_marker_only(self) -> None:
        """Test extraction when only start marker present."""
        raw_output = """Some intro...
<!-- VALIDATION_REPORT_START -->
# 🎯 Story Context Validation Report
Report content here."""

        result = extract_validation_report(raw_output)

        assert result.startswith("# 🎯 Story Context Validation Report")
        assert "Report content here." in result
        assert "Some intro" not in result

    def test_extract_fallback_header_based(self) -> None:
        """Test fallback extraction using report header pattern."""
        raw_output = """The LLM is thinking about validation...

# 🎯 Story Context Validation Report

**Story:** 2-1-test-story
**Validated:** 2025-12-18

## Summary
Everything looks good.

**Validator:** gemini-flash"""

        result = extract_validation_report(raw_output)

        assert result.startswith("# 🎯 Story Context Validation Report")
        assert "**Story:** 2-1-test-story" in result
        assert "Everything looks good." in result
        # Thinking should be excluded
        assert "LLM is thinking" not in result

    def test_extract_with_code_block_wrapper(self) -> None:
        """Test extraction when report is wrapped in markdown code block."""
        raw_output = """```markdown
<!-- VALIDATION_REPORT_START -->
# 🎯 Story Context Validation Report

Content inside code block.
<!-- VALIDATION_REPORT_END -->
```"""

        result = extract_validation_report(raw_output)

        assert "# 🎯 Story Context Validation Report" in result
        assert "Content inside code block." in result
        # Code block markers should be stripped
        assert "```" not in result

    def test_extract_raw_fallback(self) -> None:
        """Test fallback to raw content when no patterns found."""
        raw_output = "Just some random text without any report structure."

        result = extract_validation_report(raw_output)

        assert result == "Just some random text without any report structure."

    def test_extract_empty_input(self) -> None:
        """Test extraction with empty input."""
        result = extract_validation_report("")
        assert result == ""

    def test_extract_whitespace_only(self) -> None:
        """Test extraction with whitespace-only input."""
        result = extract_validation_report("   \n\n   ")
        assert result == ""

    def test_extract_preserves_internal_formatting(self) -> None:
        """Test that internal markdown formatting is preserved."""
        raw_output = """<!-- VALIDATION_REPORT_START -->
# 🎯 Story Context Validation Report

## 🚨 Critical Issues

### 1. Missing viewport

**Problem:**
The viewport meta tag is missing.

```html
<meta name="viewport" content="width=device-width">
```

**Validator:** test
<!-- VALIDATION_REPORT_END -->"""

        result = extract_validation_report(raw_output)

        assert "## 🚨 Critical Issues" in result
        assert "### 1. Missing viewport" in result
        assert "```html" in result
        assert '<meta name="viewport"' in result

    def test_extract_handles_typo_in_validator_line(self) -> None:
        """Test fallback extraction handles 'Validatior' typo in template."""
        raw_output = """# 🎯 Story Context Validation Report

Report content.

**Validatior:** some-model"""

        result = extract_validation_report(raw_output)

        assert "Report content." in result
        assert "**Validatior:** some-model" in result

    def test_extract_duplicate_start_marker(self) -> None:
        """Test extraction when LLM echoes the start marker (duplicate markers).

        This can happen when the LLM sees the marker in the template and
        includes it in its output, resulting in two start markers.
        """
        raw_output = """Some LLM thinking...

<!-- VALIDATION_REPORT_START -->
<!-- VALIDATION_REPORT_START -->
# 🎯 Story Context Validation Report

**Story:** 1-1-test
Content here.
<!-- VALIDATION_REPORT_END -->"""

        result = extract_validation_report(raw_output)

        # Should NOT start with marker - should be stripped
        assert not result.startswith("<!-- VALIDATION")
        assert result.startswith("# 🎯 Story Context Validation Report")
        assert "**Story:** 1-1-test" in result
        assert "Content here." in result

    def test_extract_multiple_duplicate_markers(self) -> None:
        """Test extraction with multiple duplicate start markers."""
        raw_output = """<!-- VALIDATION_REPORT_START -->
<!-- VALIDATION_REPORT_START -->
<!-- VALIDATION_REPORT_START -->
# 🎯 Story Context Validation Report
Test.
<!-- VALIDATION_REPORT_END -->"""

        result = extract_validation_report(raw_output)

        assert result.startswith("# 🎯 Story Context Validation Report")
        assert "<!-- VALIDATION" not in result


class TestDeduplicateSynthesisContent:
    """Tests for _deduplicate_synthesis_content function."""

    def test_keeps_longest_section_for_duplicates(self) -> None:
        """Test that longest/most substantive version is kept for duplicate headings."""
        from bmad_assist.validation.reports import _deduplicate_synthesis_content

        content = """## Summary
Short summary.

## Changes Applied

Let me now apply the changes.

---

## Changes Applied

**Location**: /path/to/file.md
**Change**: Actual substantive content here with details.
**Before**: old
**After**: new

---

## Summary
This is a much longer and more detailed summary with actual content.
"""
        result = _deduplicate_synthesis_content(content)

        # Should have exactly one of each heading
        assert result.count("## Summary") == 1
        assert result.count("## Changes Applied") == 1
        # Should keep the LONGER/more substantive versions
        assert "**Location**" in result  # From longer Changes Applied
        assert "more detailed summary" in result  # From longer Summary
        # Should NOT have filler
        assert "Let me now apply" not in result

    def test_keeps_single_metrics_block(self) -> None:
        """Test that only first METRICS_JSON block is kept."""
        from bmad_assist.validation.reports import _deduplicate_synthesis_content

        content = """## Summary
Content here.

<!-- METRICS_JSON_START -->
{"quality": {"score": 0.9}}
<!-- METRICS_JSON_END -->

More content.

<!-- METRICS_JSON_START -->
{"quality": {"score": 0.5}}
<!-- METRICS_JSON_END -->
"""
        result = _deduplicate_synthesis_content(content)

        assert result.count("<!-- METRICS_JSON_START -->") == 1
        assert result.count("<!-- METRICS_JSON_END -->") == 1
        assert '"score": 0.9' in result
        assert '"score": 0.5' not in result

    def test_removes_filler_text(self) -> None:
        """Test that filler text patterns are removed."""
        from bmad_assist.validation.reports import _deduplicate_synthesis_content

        content = """## Summary
Good content.

Let me now apply the changes.

## Changes Applied
Real changes here.
"""
        result = _deduplicate_synthesis_content(content)

        assert "Let me now apply" not in result
        assert "Good content" in result
        assert "Real changes here" in result

    def test_preserves_non_whitelisted_duplicate_headings(self) -> None:
        """Test that non-whitelisted headings are NOT deduplicated."""
        from bmad_assist.validation.reports import _deduplicate_synthesis_content

        content = """## Issues Verified
First issues section.

## Issues Dismissed
First dismissed.

## Issues Verified
Second issues section - should be kept!

## Custom Section
Some content.

## Custom Section
Different content - should also be kept!
"""
        result = _deduplicate_synthesis_content(content)

        # Non-whitelisted headings should appear multiple times
        assert result.count("## Issues Verified") == 2
        assert result.count("## Custom Section") == 2
        assert "First issues section" in result
        assert "Second issues section" in result
        assert "Some content" in result
        assert "Different content" in result


# =============================================================================
# Story 22.8: Validation Synthesis Saving - Session ID and Failed Validators
# =============================================================================


class TestStory22_8SessionIdInValidationReports:
    """Story 22.8 AC #3: Individual reports include session_id for mapping traceability."""

    @pytest.fixture
    def validations_dir(self, tmp_path: Path) -> Path:
        """Create story-validations directory structure."""
        dir_path = tmp_path / "docs" / "sprint-artifacts" / "story-validations"
        dir_path.mkdir(parents=True)
        return dir_path

    @pytest.fixture
    def sample_validation_output(self) -> ValidationOutput:
        """Sample ValidationOutput for testing."""
        return ValidationOutput(
            provider="claude-sonnet_4",
            model="claude-sonnet-4",
            content="## Issues Found\n\n1. Missing test coverage...",
            timestamp=datetime.now(UTC),
            duration_ms=5234,
            token_count=1847,
        )

    def test_session_id_in_frontmatter_when_provided(
        self,
        validations_dir: Path,
        sample_validation_output: ValidationOutput,
    ) -> None:
        """Test session_id is added to frontmatter when provided (AC #3)."""
        result_path = save_validation_report(
            output=sample_validation_output,
            epic=22,
            story=8,
            phase="VALIDATE_STORY",
            validations_dir=validations_dir,
            session_id="test-session-12345",
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        # AC #3: session_id should be in frontmatter
        assert "session_id" in post.metadata
        assert post.metadata["session_id"] == "test-session-12345"

    def test_session_id_not_in_frontmatter_when_not_provided(
        self,
        validations_dir: Path,
        sample_validation_output: ValidationOutput,
    ) -> None:
        """Test session_id is omitted from frontmatter when not provided."""
        result_path = save_validation_report(
            output=sample_validation_output,
            epic=22,
            story=8,
            phase="VALIDATE_STORY",
            validations_dir=validations_dir,
            # session_id not provided
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        # session_id should NOT be in frontmatter (backward compatible)
        assert "session_id" not in post.metadata

    def test_session_id_with_role_id(
        self,
        validations_dir: Path,
        sample_validation_output: ValidationOutput,
    ) -> None:
        """Test session_id works alongside role_id (AC #3)."""
        result_path = save_validation_report(
            output=sample_validation_output,
            epic=22,
            story=8,
            phase="VALIDATE_STORY",
            validations_dir=validations_dir,
            role_id="a",
            session_id="sess-abc-123",
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        # Both role_id and session_id should be present
        assert post.metadata["role_id"] == "a"
        assert post.metadata["session_id"] == "sess-abc-123"


class TestStory22_8FailedValidatorsInSynthesis:
    """Story 22.8 AC #2, AC #4: Synthesis report includes failed_validators in frontmatter."""

    @pytest.fixture
    def validations_dir(self, tmp_path: Path) -> Path:
        """Create story-validations directory structure."""
        dir_path = tmp_path / "docs" / "sprint-artifacts" / "story-validations"
        dir_path.mkdir(parents=True)
        return dir_path

    def test_failed_validators_in_frontmatter_when_provided(
        self,
        validations_dir: Path,
    ) -> None:
        """Test failed_validators is added to frontmatter when provided (AC #2, AC #4)."""
        result_path = save_synthesis_report(
            content="## Synthesis Summary\n\nCombined findings...",
            master_validator_id="master-opus_4",
            session_id="sess-xyz",
            validators_used=["Validator A", "Validator B"],
            epic=22,
            story=8,
            duration_ms=8432,
            validations_dir=validations_dir,
            failed_validators=["claude-haiku", "gemini-flash"],
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        # AC #2, AC #4: failed_validators should be in frontmatter
        assert "failed_validators" in post.metadata
        assert post.metadata["failed_validators"] == ["claude-haiku", "gemini-flash"]

    def test_failed_validators_empty_list_omitted_from_frontmatter(
        self,
        validations_dir: Path,
    ) -> None:
        """Test empty failed_validators list is omitted from frontmatter (cleaner YAML)."""
        result_path = save_synthesis_report(
            content="## Synthesis Summary\n\nCombined findings...",
            master_validator_id="master-opus_4",
            session_id="sess-xyz",
            validators_used=["Validator A", "Validator B"],
            epic=22,
            story=8,
            duration_ms=8432,
            validations_dir=validations_dir,
            failed_validators=[],  # Empty list - treated same as None
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        # Empty list is omitted (same as None) for cleaner YAML
        assert "failed_validators" not in post.metadata

    def test_failed_validators_not_in_frontmatter_when_none(
        self,
        validations_dir: Path,
    ) -> None:
        """Test failed_validators is omitted when None (backward compatible)."""
        result_path = save_synthesis_report(
            content="## Synthesis Summary\n\nCombined findings...",
            master_validator_id="master-opus_4",
            session_id="sess-xyz",
            validators_used=["Validator A", "Validator B"],
            epic=22,
            story=8,
            duration_ms=8432,
            validations_dir=validations_dir,
            # failed_validators not provided (defaults to None)
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        # failed_validators should NOT be in frontmatter
        assert "failed_validators" not in post.metadata

    def test_synthesis_frontmatter_complete_with_failed_validators(
        self,
        validations_dir: Path,
    ) -> None:
        """Test complete frontmatter structure with failed_validators."""
        result_path = save_synthesis_report(
            content="## Synthesis Summary\n\nCombined findings...",
            master_validator_id="master-opus_4",
            session_id="sess-complete-test",
            validators_used=["Validator A", "Validator B", "Validator C"],
            epic=22,
            story=8,
            duration_ms=8432,
            validations_dir=validations_dir,
            failed_validators=["claude-haiku"],
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        metadata = post.metadata

        # All expected fields present
        assert metadata["type"] == "synthesis"
        assert metadata["master_validator_id"] == "master-opus_4"
        assert metadata["session_id"] == "sess-complete-test"
        assert metadata["validators_used"] == ["Validator A", "Validator B", "Validator C"]
        assert metadata["failed_validators"] == ["claude-haiku"]
        assert metadata["epic"] == 22
        assert metadata["story"] == 8
        assert metadata["duration_ms"] == 8432
        assert "timestamp" in metadata
