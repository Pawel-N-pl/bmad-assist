"""Tests for code review custom metrics.

Story 13.10: Code Review Benchmarking Integration

Tests cover:
- Task 5: Phase-specific custom metrics (AC: #5)
- Task 12: Unit tests for custom metrics
"""

from pathlib import Path

from bmad_assist.code_review.orchestrator import (
    _extract_code_review_custom_metrics,
    _extract_code_review_report,
)

# ============================================================================
# Tests for custom metrics extraction (AC: #5)
# ============================================================================


class TestExtractCodeReviewCustomMetrics:
    """Test extraction of code review specific metrics."""

    def test_extracts_file_count_from_file_list(self, tmp_path: Path) -> None:
        """Test extraction of file count from story File List section."""
        story_file = tmp_path / "test-story.md"
        story_file.write_text("""# Story 13.10

## File List

- `src/bmad_assist/code_review/__init__.py`
- `src/bmad_assist/code_review/orchestrator.py`
- `tests/code_review/test_orchestrator.py`
- `tests/code_review/test_custom_metrics.py`

## Acceptance Criteria

- AC1: Test passes
""")

        metrics = _extract_code_review_custom_metrics(story_file)

        assert metrics["phase"] == "code-review"
        assert metrics["file_count"] == 4

    def test_handles_missing_file_list(self, tmp_path: Path) -> None:
        """Test graceful handling of missing File List section."""
        story_file = tmp_path / "test-story.md"
        story_file.write_text("""# Story 13.10

## Acceptance Criteria

- AC1: Test passes
""")

        metrics = _extract_code_review_custom_metrics(story_file)

        assert metrics["phase"] == "code-review"
        assert metrics["file_count"] is None

    def test_handles_nonexistent_file(self, tmp_path: Path) -> None:
        """Test graceful handling of nonexistent story file."""
        story_file = tmp_path / "nonexistent.md"

        metrics = _extract_code_review_custom_metrics(story_file)

        assert metrics["phase"] == "code-review"
        assert metrics["file_count"] is None

    def test_handles_empty_file_list(self, tmp_path: Path) -> None:
        """Test handling of empty File List section."""
        story_file = tmp_path / "test-story.md"
        story_file.write_text("""# Story 13.10

## File List

(No files modified)

## Acceptance Criteria

- AC1: Test passes
""")

        metrics = _extract_code_review_custom_metrics(story_file)

        assert metrics["phase"] == "code-review"
        # Empty file list should result in None or 0
        assert metrics["file_count"] in (None, 0)

    def test_h3_file_list_header(self, tmp_path: Path) -> None:
        """### File List is detected for metric extraction."""
        story_file = tmp_path / "test-story.md"
        story_file.write_text("""# Story 13.10

### File List

- `src/bmad_assist/code_review/__init__.py`
- `src/bmad_assist/code_review/orchestrator.py`
- `tests/code_review/test_orchestrator.py`

### Acceptance Criteria

- AC1: Test passes
""")

        metrics = _extract_code_review_custom_metrics(story_file)

        assert metrics["phase"] == "code-review"
        assert metrics["file_count"] == 3

    def test_filters_directories_from_count(self, tmp_path: Path) -> None:
        """Test that directories are filtered from file count."""
        story_file = tmp_path / "test-story.md"
        story_file.write_text("""# Story 13.10

## File List

- `src/bmad_assist/code_review/` (directory)
- `src/bmad_assist/code_review/__init__.py`
- `tests/code_review/` (directory)
- `tests/code_review/test_orchestrator.py`

## Acceptance Criteria

- AC1: Test passes
""")

        metrics = _extract_code_review_custom_metrics(story_file)

        # Should only count files with extensions, not directories
        assert metrics["file_count"] == 2


# ============================================================================
# Tests for report extraction
# ============================================================================


class TestExtractCodeReviewReport:
    """Test extraction of code review report from raw output."""

    def test_extracts_with_markers(self) -> None:
        """Test extraction using start/end markers."""
        raw_output = """Some preamble text

<!-- CODE_REVIEW_REPORT_START -->
# Code Review Report

## Findings

1. Issue found
2. Another issue
<!-- CODE_REVIEW_REPORT_END -->

Some trailing text
"""
        extracted = _extract_code_review_report(raw_output)

        assert "# Code Review Report" in extracted
        assert "Issue found" in extracted
        assert "preamble" not in extracted
        assert "trailing" not in extracted

    def test_extracts_with_header_fallback(self) -> None:
        """Test extraction using header when no markers present."""
        raw_output = """Some preamble

# Review

## Findings

- Issue 1
- Issue 2
"""
        extracted = _extract_code_review_report(raw_output)

        assert "# Review" in extracted
        assert "Issue 1" in extracted
        assert "preamble" not in extracted

    def test_extracts_code_review_header(self) -> None:
        """Test extraction with 'Code Review' header."""
        raw_output = """# Code Review

## Summary

Looks good overall
"""
        extracted = _extract_code_review_report(raw_output)

        assert "# Code Review" in extracted
        assert "Looks good" in extracted

    def test_returns_raw_on_no_match(self) -> None:
        """Test that raw output is returned when no patterns match."""
        raw_output = "Just some plain text without any headers"

        extracted = _extract_code_review_report(raw_output)

        assert extracted == raw_output.strip()
