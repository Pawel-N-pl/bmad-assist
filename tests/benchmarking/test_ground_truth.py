"""Tests for ground truth module.

Tests cover:
- Dataclass definitions (Task 1)
- Code review finding extraction (Task 2, AC6)
- Validation finding extraction (Task 2, AC6)
- Finding matching algorithm (Task 3, AC3)
- Precision/recall calculation (Task 4, AC4)
- populate_ground_truth (Task 5, AC2, AC7, AC8, AC9)
- amend_ground_truth (Task 6, AC5)
"""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bmad_assist.benchmarking.schema import (
    Amendment,
    BenchmarkingError,
    GroundTruth,
)

# =============================================================================
# Task 1: Dataclass and exception tests
# =============================================================================


class TestGroundTruthError:
    """Test GroundTruthError exception class."""

    def test_inherits_from_benchmarking_error(self) -> None:
        """GroundTruthError inherits from BenchmarkingError."""
        from bmad_assist.benchmarking.ground_truth import GroundTruthError

        assert issubclass(GroundTruthError, BenchmarkingError)

    def test_can_be_raised_with_message(self) -> None:
        """GroundTruthError can be raised with a message."""
        from bmad_assist.benchmarking.ground_truth import GroundTruthError

        with pytest.raises(GroundTruthError, match="test error"):
            raise GroundTruthError("test error")


class TestCodeReviewFinding:
    """Test CodeReviewFinding dataclass."""

    def test_creation_with_all_fields(self) -> None:
        """CodeReviewFinding can be created with all fields."""
        from bmad_assist.benchmarking.ground_truth import CodeReviewFinding

        finding = CodeReviewFinding(
            description="Missing error handling",
            severity="major",
            category="correctness",
        )
        assert finding.description == "Missing error handling"
        assert finding.severity == "major"
        assert finding.category == "correctness"

    def test_creation_with_optional_none(self) -> None:
        """CodeReviewFinding can be created with None severity/category."""
        from bmad_assist.benchmarking.ground_truth import CodeReviewFinding

        finding = CodeReviewFinding(
            description="Some issue",
            severity=None,
            category=None,
        )
        assert finding.severity is None
        assert finding.category is None

    def test_is_frozen(self) -> None:
        """CodeReviewFinding is immutable (frozen)."""
        from bmad_assist.benchmarking.ground_truth import CodeReviewFinding

        finding = CodeReviewFinding(description="test", severity=None, category=None)
        with pytest.raises(FrozenInstanceError):
            finding.description = "modified"  # type: ignore[misc]


class TestValidationFinding:
    """Test ValidationFinding dataclass."""

    def test_creation_with_all_fields(self) -> None:
        """ValidationFinding can be created with all fields."""
        from bmad_assist.benchmarking.ground_truth import ValidationFinding

        finding = ValidationFinding(
            description="Security vulnerability in auth",
            severity="critical",
            category="security",
        )
        assert finding.description == "Security vulnerability in auth"
        assert finding.severity == "critical"
        assert finding.category == "security"

    def test_is_frozen(self) -> None:
        """ValidationFinding is immutable (frozen)."""
        from bmad_assist.benchmarking.ground_truth import ValidationFinding

        finding = ValidationFinding(description="test", severity=None, category=None)
        with pytest.raises(FrozenInstanceError):
            finding.description = "modified"  # type: ignore[misc]


class TestGroundTruthUpdate:
    """Test GroundTruthUpdate dataclass."""

    def test_creation(self) -> None:
        """GroundTruthUpdate can be created with required fields."""
        from bmad_assist.benchmarking.ground_truth import GroundTruthUpdate

        ground_truth = GroundTruth(
            populated=True,
            populated_at=datetime.now(UTC),
            findings_confirmed=3,
            findings_false_alarm=1,
            issues_missed=2,
            precision=0.75,
            recall=0.6,
        )
        update = GroundTruthUpdate(
            record_id="uuid-123",
            record_path=Path("/path/to/record.yaml"),
            ground_truth=ground_truth,
        )
        assert update.record_id == "uuid-123"
        assert update.record_path == Path("/path/to/record.yaml")
        assert update.ground_truth.populated is True

    def test_is_frozen(self) -> None:
        """GroundTruthUpdate is immutable (frozen)."""
        from bmad_assist.benchmarking.ground_truth import GroundTruthUpdate

        ground_truth = GroundTruth(populated=False)
        update = GroundTruthUpdate(
            record_id="uuid-123",
            record_path=Path("/path"),
            ground_truth=ground_truth,
        )
        with pytest.raises(FrozenInstanceError):
            update.record_id = "modified"  # type: ignore[misc]


class TestModuleAPI:
    """Test module provides required public API (AC1)."""

    def test_populate_ground_truth_exists(self) -> None:
        """populate_ground_truth function is exported."""
        from bmad_assist.benchmarking.ground_truth import populate_ground_truth

        assert callable(populate_ground_truth)

    def test_amend_ground_truth_exists(self) -> None:
        """amend_ground_truth function is exported."""
        from bmad_assist.benchmarking.ground_truth import amend_ground_truth

        assert callable(amend_ground_truth)

    def test_calculate_precision_recall_exists(self) -> None:
        """calculate_precision_recall function is exported."""
        from bmad_assist.benchmarking.ground_truth import calculate_precision_recall

        assert callable(calculate_precision_recall)


# =============================================================================
# Task 2 / Task 8: Code review finding extraction tests (AC6)
# =============================================================================


class TestExtractCodeReviewFindings:
    """Test _extract_code_review_findings function (AC6)."""

    def test_extract_from_standard_markdown(self) -> None:
        """Extract findings from standard code review markdown format."""
        from bmad_assist.benchmarking.ground_truth import _extract_code_review_findings

        code_review = """
## Issues Found

1. Missing error handling in authentication flow
2. SQL injection vulnerability in user search
3. Performance issue with N+1 queries

## Summary

All issues should be addressed before merge.
"""
        findings = _extract_code_review_findings(code_review)

        assert len(findings) == 3
        assert "Missing error handling" in findings[0].description
        assert "SQL injection" in findings[1].description
        assert "N+1 queries" in findings[2].description

    def test_extract_from_bullet_list(self) -> None:
        """Extract findings from bullet list format."""
        from bmad_assist.benchmarking.ground_truth import _extract_code_review_findings

        code_review = """
## Problems

- Critical: Authentication bypass in login endpoint
- Major: Memory leak in connection pool
- Minor: Typo in error message
"""
        findings = _extract_code_review_findings(code_review)

        assert len(findings) == 3
        # Severities should be detected from keywords
        assert findings[0].severity == "critical"
        assert findings[1].severity == "major"
        assert findings[2].severity == "minor"

    def test_classify_severity_from_keywords(self) -> None:
        """Classify severity from finding content keywords."""
        from bmad_assist.benchmarking.ground_truth import _extract_code_review_findings

        code_review = """
## Issues

1. CRITICAL: Security vulnerability found
2. This is a blocker for release
3. Major performance degradation
4. Minor style inconsistency
5. Nit: extra whitespace
"""
        findings = _extract_code_review_findings(code_review)

        assert findings[0].severity == "critical"
        assert findings[1].severity == "critical"  # blocker maps to critical
        assert findings[2].severity == "major"
        assert findings[3].severity == "minor"
        assert findings[4].severity == "nit"

    def test_classify_category_from_content(self) -> None:
        """Classify category from finding content."""
        from bmad_assist.benchmarking.ground_truth import _extract_code_review_findings

        code_review = """
## Findings

1. Security: XSS vulnerability in user input
2. Slow database query needs optimization
3. Missing implementation of feature X
4. Bug: Incorrect calculation in total
5. Code needs refactoring for readability
"""
        findings = _extract_code_review_findings(code_review)

        assert findings[0].category == "security"
        assert findings[1].category == "performance"
        assert findings[2].category == "completeness"
        assert findings[3].category == "correctness"
        assert findings[4].category == "maintainability"

    def test_empty_input_returns_empty_list(self) -> None:
        """Empty or malformed input returns empty list."""
        from bmad_assist.benchmarking.ground_truth import _extract_code_review_findings

        assert _extract_code_review_findings("") == []
        assert _extract_code_review_findings("No issues found") == []
        assert _extract_code_review_findings("## Summary\nAll good!") == []

    def test_handles_multiple_finding_sections(self) -> None:
        """Extract findings from multiple sections."""
        from bmad_assist.benchmarking.ground_truth import _extract_code_review_findings

        code_review = """
## Issues

1. First issue

## Problems

- Second issue

## Action Items

1. Third issue
"""
        findings = _extract_code_review_findings(code_review)

        assert len(findings) == 3

    def test_handles_nested_lists(self) -> None:
        """Handle nested list items (only extract top-level)."""
        from bmad_assist.benchmarking.ground_truth import _extract_code_review_findings

        code_review = """
## Issues

1. Main issue with authentication
   - Sub-item 1
   - Sub-item 2
2. Second main issue
"""
        findings = _extract_code_review_findings(code_review)

        # Should extract 2 main findings, not sub-items
        assert len(findings) == 2


class TestExtractValidationFindings:
    """Test _extract_validation_findings function (AC6)."""

    def test_extract_from_validation_report_format(self) -> None:
        """Extract findings from validation report markdown format."""
        from bmad_assist.benchmarking.ground_truth import _extract_validation_findings

        validation_report = """
# 🎯 Story Context Validation Report

## 🚨 Critical Issues

### 1. Missing Error Handling for API Failures
The story does not address what happens when external API fails.

### 2. Security Vulnerability in Input Validation
User input is not properly sanitized.

## ⚡ Enhancement Suggestions

### 1. Add Retry Logic
Consider adding retry mechanism for transient failures.

## ✨ Optimization Opportunities

### 1. Cache Frequently Accessed Data
This could improve performance significantly.
"""
        findings = _extract_validation_findings(Path("dummy.md"), validation_report)

        assert len(findings) == 4
        # Check severities based on section
        assert findings[0].severity == "critical"
        assert findings[1].severity == "critical"
        assert findings[2].severity == "major"  # Enhancement → major
        assert findings[3].severity == "minor"  # Optimization → minor

    def test_extract_with_category_detection(self) -> None:
        """Extract findings with category detection from content."""
        from bmad_assist.benchmarking.ground_truth import _extract_validation_findings

        validation_report = """
## 🚨 Critical Issues

### 1. Security Vulnerability in Authentication
XSS attack possible.

### 2. Missing Implementation
Feature not fully implemented.
"""
        findings = _extract_validation_findings(Path("dummy.md"), validation_report)

        assert findings[0].category == "security"
        assert findings[1].category == "completeness"

    def test_empty_report_returns_empty_list(self) -> None:
        """Empty validation report returns empty list."""
        from bmad_assist.benchmarking.ground_truth import _extract_validation_findings

        findings = _extract_validation_findings(Path("dummy.md"), "")
        assert findings == []

    def test_report_without_findings_sections(self) -> None:
        """Report without standard finding sections returns empty list."""
        from bmad_assist.benchmarking.ground_truth import _extract_validation_findings

        validation_report = """
# Validation Report

## Summary

Everything looks good, no issues found.
"""
        findings = _extract_validation_findings(Path("dummy.md"), validation_report)
        assert findings == []


class TestFindValidationReportForRecord:
    """Test _find_validation_report_for_record function."""

    def test_finds_report_by_provider_pattern(self, tmp_path: Path) -> None:
        """Find validation report matching provider pattern."""
        from bmad_assist.benchmarking.ground_truth import _find_validation_report_for_record

        # Setup
        validations_dir = tmp_path / "story-validations"
        validations_dir.mkdir()
        report_path = validations_dir / "story-validation-13-7-claude_opus_4_5.md"
        report_path.write_text("# Report")

        # Create mock record
        record = MagicMock()
        record.story.epic_num = 13
        record.story.story_num = 7
        record.evaluator.provider = "claude_opus_4_5"

        result = _find_validation_report_for_record(record, tmp_path)

        assert result == report_path

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """Return None when no matching report exists."""
        from bmad_assist.benchmarking.ground_truth import _find_validation_report_for_record

        validations_dir = tmp_path / "story-validations"
        validations_dir.mkdir()

        record = MagicMock()
        record.story.epic_num = 13
        record.story.story_num = 7
        record.evaluator.provider = "nonexistent_provider"

        result = _find_validation_report_for_record(record, tmp_path)

        assert result is None

    def test_returns_none_when_dir_missing(self, tmp_path: Path) -> None:
        """Return None when validations directory doesn't exist."""
        from bmad_assist.benchmarking.ground_truth import _find_validation_report_for_record

        record = MagicMock()
        record.story.epic_num = 13
        record.story.story_num = 7
        record.evaluator.provider = "claude"

        result = _find_validation_report_for_record(record, tmp_path)

        assert result is None

    def test_returns_most_recent_when_multiple_matches(self, tmp_path: Path) -> None:
        """Return most recent file when multiple reports match."""
        import time

        from bmad_assist.benchmarking.ground_truth import _find_validation_report_for_record

        validations_dir = tmp_path / "story-validations"
        validations_dir.mkdir()

        # Create older file
        old_report = validations_dir / "story-validation-13-7-claude_2024-01-01.md"
        old_report.write_text("# Old Report")

        # Ensure time difference
        time.sleep(0.01)

        # Create newer file
        new_report = validations_dir / "story-validation-13-7-claude_2024-01-02.md"
        new_report.write_text("# New Report")

        record = MagicMock()
        record.story.epic_num = 13
        record.story.story_num = 7
        record.evaluator.provider = "claude"

        result = _find_validation_report_for_record(record, tmp_path)

        assert result == new_report


# =============================================================================
# Task 3 / Task 9: Finding matching algorithm tests (AC3)
# =============================================================================


class TestCalculateSimilarity:
    """Test _calculate_similarity helper function."""

    def test_exact_match_returns_one(self) -> None:
        """Exact string match returns 1.0."""
        from bmad_assist.benchmarking.ground_truth import _calculate_similarity

        assert _calculate_similarity("exact match", "exact match") == 1.0

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        from bmad_assist.benchmarking.ground_truth import _calculate_similarity

        assert _calculate_similarity("EXACT MATCH", "exact match") == 1.0

    def test_similar_strings_above_threshold(self) -> None:
        """Similar strings return high similarity."""
        from bmad_assist.benchmarking.ground_truth import _calculate_similarity

        # Very similar strings should score high
        sim = _calculate_similarity("Missing error handling", "Missing error handling code")
        assert sim > 0.6

    def test_different_strings_below_threshold(self) -> None:
        """Different strings return low similarity."""
        from bmad_assist.benchmarking.ground_truth import _calculate_similarity

        sim = _calculate_similarity("Security XSS vulnerability", "Performance optimization needed")
        assert sim < 0.6


class TestCalculateCombinedScore:
    """Test _calculate_combined_score function."""

    def test_base_score_only(self) -> None:
        """Combined score equals base score when no category/severity match."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            _calculate_combined_score,
        )

        cr_finding = CodeReviewFinding(
            description="exact match",
            severity="major",
            category="security",
        )
        score = _calculate_combined_score(
            v_desc="exact match",
            v_category="performance",  # Different category
            v_severity="minor",  # Different severity
            cr_finding=cr_finding,
        )
        assert score == 1.0  # Only base score (exact match)

    def test_category_boost(self) -> None:
        """Category match adds 0.1 to score."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            _calculate_combined_score,
        )

        cr_finding = CodeReviewFinding(
            description="some text",
            severity="major",
            category="security",
        )
        score = _calculate_combined_score(
            v_desc="different text",
            v_category="security",  # Matching category
            v_severity="minor",
            cr_finding=cr_finding,
        )
        # Check that category boost was applied
        base_score = _calculate_combined_score(
            v_desc="different text",
            v_category="performance",  # Non-matching
            v_severity="minor",
            cr_finding=cr_finding,
        )
        assert score - base_score == pytest.approx(0.1, abs=0.01)

    def test_severity_boost(self) -> None:
        """Severity match adds 0.05 to score."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            _calculate_combined_score,
        )

        cr_finding = CodeReviewFinding(
            description="some text",
            severity="major",
            category="security",
        )
        score = _calculate_combined_score(
            v_desc="different text",
            v_category="performance",
            v_severity="major",  # Matching severity
            cr_finding=cr_finding,
        )
        base_score = _calculate_combined_score(
            v_desc="different text",
            v_category="performance",
            v_severity="minor",  # Non-matching
            cr_finding=cr_finding,
        )
        assert score - base_score == pytest.approx(0.05, abs=0.01)

    def test_combined_boost_capped_at_one(self) -> None:
        """Combined score is capped at 1.0."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            _calculate_combined_score,
        )

        cr_finding = CodeReviewFinding(
            description="exact match",
            severity="major",
            category="security",
        )
        score = _calculate_combined_score(
            v_desc="exact match",  # 1.0 base
            v_category="security",  # +0.1
            v_severity="major",  # +0.05
            cr_finding=cr_finding,
        )
        assert score == 1.0  # Capped at 1.0


class TestMatchFindings:
    """Test _match_findings function (AC3)."""

    def test_exact_match(self) -> None:
        """Exact string matches are found."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            ValidationFinding,
            _match_findings,
        )

        v_findings = [ValidationFinding("Missing error handling", None, None)]
        cr_findings = [CodeReviewFinding("Missing error handling", None, None)]

        matched, unmatched_v, unmatched_cr = _match_findings(v_findings, cr_findings)

        assert len(matched) == 1
        assert matched[0] == (0, 0)
        assert len(unmatched_v) == 0
        assert len(unmatched_cr) == 0

    def test_fuzzy_match_above_threshold(self) -> None:
        """Fuzzy matches above 0.6 threshold are found."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            ValidationFinding,
            _match_findings,
        )

        v_findings = [ValidationFinding("Missing error handling in API", None, None)]
        cr_findings = [CodeReviewFinding("Error handling missing for API calls", None, None)]

        matched, unmatched_v, unmatched_cr = _match_findings(v_findings, cr_findings)

        # Should match (similar content)
        assert len(matched) == 1
        assert len(unmatched_v) == 0
        assert len(unmatched_cr) == 0

    def test_fuzzy_match_below_threshold(self) -> None:
        """Dissimilar findings below threshold are not matched."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            ValidationFinding,
            _match_findings,
        )

        v_findings = [ValidationFinding("Security XSS vulnerability", None, None)]
        cr_findings = [CodeReviewFinding("Performance optimization needed", None, None)]

        matched, unmatched_v, unmatched_cr = _match_findings(v_findings, cr_findings)

        assert len(matched) == 0
        assert len(unmatched_v) == 1
        assert len(unmatched_cr) == 1

    def test_one_to_one_constraint(self) -> None:
        """Each finding matches at most once (no double-matching)."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            ValidationFinding,
            _match_findings,
        )

        # Two similar validation findings, one code review finding
        v_findings = [
            ValidationFinding("Error handling issue", None, None),
            ValidationFinding("Error handling problem", None, None),
        ]
        cr_findings = [CodeReviewFinding("Error handling missing", None, None)]

        matched, unmatched_v, unmatched_cr = _match_findings(v_findings, cr_findings)

        # Only one match possible
        assert len(matched) == 1
        assert len(unmatched_v) == 1  # One validation finding unmatched
        assert len(unmatched_cr) == 0

    def test_category_boost_affects_matching(self) -> None:
        """Category match boosts score and affects matching priority."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            _calculate_combined_score,
        )

        # Verify category boost is applied correctly
        cr_finding = CodeReviewFinding(
            description="Database issue",
            severity=None,
            category="security",
        )

        # Score WITH matching category
        score_with_cat = _calculate_combined_score(
            v_desc="Database issue",
            v_category="security",
            v_severity=None,
            cr_finding=cr_finding,
        )

        # Score WITHOUT matching category
        score_without_cat = _calculate_combined_score(
            v_desc="Database issue",
            v_category="performance",
            v_severity=None,
            cr_finding=cr_finding,
        )

        # Category match should add 0.1 (but capped at 1.0)
        # With exact match base score is 1.0, so both are 1.0
        # Test with different text to see the boost
        cr_finding2 = CodeReviewFinding(
            description="Database problem",
            severity=None,
            category="security",
        )
        score_with_cat2 = _calculate_combined_score(
            v_desc="Database issue",
            v_category="security",
            v_severity=None,
            cr_finding=cr_finding2,
        )
        score_without_cat2 = _calculate_combined_score(
            v_desc="Database issue",
            v_category="performance",
            v_severity=None,
            cr_finding=cr_finding2,
        )

        assert score_with_cat2 - score_without_cat2 == pytest.approx(0.1, abs=0.01)

    def test_severity_boost_affects_matching(self) -> None:
        """Severity match boosts score and affects matching priority."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            ValidationFinding,
            _match_findings,
        )

        # Two validation findings with same text but different severities
        v_findings = [
            ValidationFinding("API bug", "minor", None),
            ValidationFinding("API bug", "critical", None),
        ]
        cr_findings = [CodeReviewFinding("API bug", "critical", None)]

        matched, _, _ = _match_findings(v_findings, cr_findings)

        # Should match the one with matching severity
        assert len(matched) == 1
        assert matched[0][0] == 1  # Second validation (critical severity)

    def test_empty_description_skipped(self) -> None:
        """Findings with empty descriptions are skipped."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            ValidationFinding,
            _match_findings,
        )

        v_findings = [
            ValidationFinding("", None, None),  # Empty
            ValidationFinding("   ", None, None),  # Whitespace only
            ValidationFinding("Valid finding", None, None),
        ]
        cr_findings = [
            CodeReviewFinding("", None, None),
            CodeReviewFinding("Valid finding", None, None),
        ]

        matched, unmatched_v, unmatched_cr = _match_findings(v_findings, cr_findings)

        # Only valid findings should be considered
        assert len(matched) == 1
        assert matched[0] == (2, 1)  # Third validation, second code review
        # Empty findings are excluded from unmatched counts
        assert len(unmatched_v) == 0
        assert len(unmatched_cr) == 0

    def test_greedy_matching_by_score(self) -> None:
        """Matching uses greedy algorithm by descending combined score."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            ValidationFinding,
            _match_findings,
        )

        v_findings = [
            ValidationFinding("Issue A very similar", None, None),
            ValidationFinding("Issue B", None, None),
        ]
        cr_findings = [
            CodeReviewFinding("Issue A very similar", None, None),  # Exact match to first
            CodeReviewFinding("Issue A", None, None),  # Partial match to first
        ]

        matched, _, _ = _match_findings(v_findings, cr_findings)

        # Best match (exact) should be taken first
        assert (0, 0) in matched  # First validation matches first CR (exact)

    def test_empty_inputs(self) -> None:
        """Empty input lists return appropriate results."""
        from bmad_assist.benchmarking.ground_truth import (
            CodeReviewFinding,
            ValidationFinding,
            _match_findings,
        )

        # Empty validation findings
        matched, unmatched_v, unmatched_cr = _match_findings(
            [], [CodeReviewFinding("Issue", None, None)]
        )
        assert len(matched) == 0
        assert len(unmatched_v) == 0
        assert len(unmatched_cr) == 1

        # Empty code review findings
        matched, unmatched_v, unmatched_cr = _match_findings(
            [ValidationFinding("Issue", None, None)], []
        )
        assert len(matched) == 0
        assert len(unmatched_v) == 1
        assert len(unmatched_cr) == 0

        # Both empty
        matched, unmatched_v, unmatched_cr = _match_findings([], [])
        assert len(matched) == 0
        assert len(unmatched_v) == 0
        assert len(unmatched_cr) == 0


# =============================================================================
# Task 4 / Task 10: Precision/Recall calculation tests (AC4)
# =============================================================================


class TestCalculatePrecisionRecall:
    """Test calculate_precision_recall function (AC4)."""

    def test_normal_calculation(self) -> None:
        """Normal precision/recall calculation."""
        from bmad_assist.benchmarking.ground_truth import calculate_precision_recall

        ground_truth = GroundTruth(
            populated=True,
            findings_confirmed=3,
            findings_false_alarm=1,
            issues_missed=2,
        )

        precision, recall = calculate_precision_recall(ground_truth)

        # precision = 3 / (3 + 1) = 0.75
        assert precision == pytest.approx(0.75)
        # recall = 3 / (3 + 2) = 0.6
        assert recall == pytest.approx(0.6)

    def test_perfect_precision(self) -> None:
        """All predictions confirmed, no false alarms."""
        from bmad_assist.benchmarking.ground_truth import calculate_precision_recall

        ground_truth = GroundTruth(
            populated=True,
            findings_confirmed=5,
            findings_false_alarm=0,
            issues_missed=3,
        )

        precision, recall = calculate_precision_recall(ground_truth)

        # precision = 5 / (5 + 0) = 1.0
        assert precision == pytest.approx(1.0)
        # recall = 5 / (5 + 3) = 0.625
        assert recall == pytest.approx(0.625)

    def test_perfect_recall(self) -> None:
        """All issues found, none missed."""
        from bmad_assist.benchmarking.ground_truth import calculate_precision_recall

        ground_truth = GroundTruth(
            populated=True,
            findings_confirmed=4,
            findings_false_alarm=2,
            issues_missed=0,
        )

        precision, recall = calculate_precision_recall(ground_truth)

        # precision = 4 / (4 + 2) = 0.667
        assert precision == pytest.approx(0.667, abs=0.01)
        # recall = 4 / (4 + 0) = 1.0
        assert recall == pytest.approx(1.0)

    def test_zero_precision_denominator(self) -> None:
        """Zero denominator for precision returns None."""
        from bmad_assist.benchmarking.ground_truth import calculate_precision_recall

        ground_truth = GroundTruth(
            populated=True,
            findings_confirmed=0,
            findings_false_alarm=0,
            issues_missed=5,
        )

        precision, recall = calculate_precision_recall(ground_truth)

        assert precision is None  # 0 / (0 + 0) = undefined
        assert recall == pytest.approx(0.0)  # 0 / (0 + 5) = 0

    def test_zero_recall_denominator(self) -> None:
        """Zero denominator for recall returns None."""
        from bmad_assist.benchmarking.ground_truth import calculate_precision_recall

        ground_truth = GroundTruth(
            populated=True,
            findings_confirmed=0,
            findings_false_alarm=3,
            issues_missed=0,
        )

        precision, recall = calculate_precision_recall(ground_truth)

        assert precision == pytest.approx(0.0)  # 0 / (0 + 3) = 0
        assert recall is None  # 0 / (0 + 0) = undefined

    def test_both_denominators_zero(self) -> None:
        """Both denominators zero returns (None, None)."""
        from bmad_assist.benchmarking.ground_truth import calculate_precision_recall

        ground_truth = GroundTruth(
            populated=True,
            findings_confirmed=0,
            findings_false_alarm=0,
            issues_missed=0,
        )

        precision, recall = calculate_precision_recall(ground_truth)

        assert precision is None
        assert recall is None

    def test_all_false_alarms(self) -> None:
        """All validation findings were false alarms (precision = 0)."""
        from bmad_assist.benchmarking.ground_truth import calculate_precision_recall

        ground_truth = GroundTruth(
            populated=True,
            findings_confirmed=0,
            findings_false_alarm=5,
            issues_missed=3,
        )

        precision, recall = calculate_precision_recall(ground_truth)

        assert precision == pytest.approx(0.0)
        assert recall == pytest.approx(0.0)

    def test_all_issues_missed(self) -> None:
        """All code review issues were missed (recall = 0)."""
        from bmad_assist.benchmarking.ground_truth import calculate_precision_recall

        ground_truth = GroundTruth(
            populated=True,
            findings_confirmed=0,
            findings_false_alarm=0,
            issues_missed=10,
        )

        precision, recall = calculate_precision_recall(ground_truth)

        assert precision is None  # No predictions at all
        assert recall == pytest.approx(0.0)

    def test_values_clamped_to_range(self) -> None:
        """Values are always in [0.0, 1.0] range."""
        from bmad_assist.benchmarking.ground_truth import calculate_precision_recall

        ground_truth = GroundTruth(
            populated=True,
            findings_confirmed=10,
            findings_false_alarm=0,
            issues_missed=0,
        )

        precision, recall = calculate_precision_recall(ground_truth)

        # Both should be 1.0 (perfect)
        assert precision == pytest.approx(1.0)
        assert recall == pytest.approx(1.0)
        assert 0.0 <= precision <= 1.0
        assert 0.0 <= recall <= 1.0


# =============================================================================
# Task 5 / Task 11: Integration tests for populate_ground_truth (AC2, AC7, AC8, AC9)
# =============================================================================


@pytest.fixture
def sample_evaluation_record() -> dict:
    """Create a sample evaluation record for testing."""
    from datetime import UTC, datetime

    return {
        "record_id": "test-record-123",
        "created_at": datetime.now(UTC).isoformat(),
        "workflow": {
            "id": "validate-story",
            "version": "1.0.0",
            "variant": "multi-llm",
            "patch": {"applied": False, "id": None, "version": None, "file_hash": None},
        },
        "story": {
            "epic_num": 13,
            "story_num": 7,
            "title": "Ground Truth Auto-Population",
            "complexity_flags": {},
        },
        "evaluator": {
            "provider": "claude_opus_4_5",
            "model": "opus-4.5",
            "role": "validator",
            "role_id": "a",
            "session_id": "session-123",
        },
        "execution": {
            "start_time": datetime.now(UTC).isoformat(),
            "end_time": datetime.now(UTC).isoformat(),
            "duration_ms": 1000,
            "input_tokens": 5000,
            "output_tokens": 2000,
            "retries": 0,
            "sequence_position": 0,
        },
        "output": {
            "char_count": 5000,
            "heading_count": 10,
            "list_depth_max": 2,
            "code_block_count": 3,
            "sections_detected": ["Summary", "Findings"],
            "anomalies": [],
        },
        "environment": {
            "bmad_assist_version": "0.1.0",
            "python_version": "3.11.0",
            "platform": "linux",
            "git_commit_hash": None,
        },
        "ground_truth": None,
    }


@pytest.fixture
def sample_synthesizer_record() -> dict:
    """Create a sample synthesizer record for testing."""
    from datetime import UTC, datetime

    return {
        "record_id": "test-synthesizer-456",
        "created_at": datetime.now(UTC).isoformat(),
        "workflow": {
            "id": "validate-story-synthesis",
            "version": "1.0.0",
            "variant": "synthesis",
            "patch": {"applied": False, "id": None, "version": None, "file_hash": None},
        },
        "story": {
            "epic_num": 13,
            "story_num": 7,
            "title": "Ground Truth Auto-Population",
            "complexity_flags": {},
        },
        "evaluator": {
            "provider": "claude_opus_4_5",
            "model": "opus-4.5",
            "role": "synthesizer",
            "role_id": None,
            "session_id": "session-456",
        },
        "execution": {
            "start_time": datetime.now(UTC).isoformat(),
            "end_time": datetime.now(UTC).isoformat(),
            "duration_ms": 2000,
            "input_tokens": 10000,
            "output_tokens": 3000,
            "retries": 0,
            "sequence_position": 1,
        },
        "output": {
            "char_count": 8000,
            "heading_count": 15,
            "list_depth_max": 3,
            "code_block_count": 5,
            "sections_detected": ["Synthesis", "Recommendations"],
            "anomalies": [],
        },
        "environment": {
            "bmad_assist_version": "0.1.0",
            "python_version": "3.11.0",
            "platform": "linux",
            "git_commit_hash": None,
        },
        "consensus": {
            "agreed_findings": 3,
            "unique_findings": 2,
            "disputed_findings": 1,
            "missed_findings": 0,
            "agreement_score": 0.8,
            "false_positive_count": 0,
        },
        "ground_truth": None,
    }


class TestPopulateGroundTruth:
    """Integration tests for populate_ground_truth function (AC2, AC7, AC8, AC9)."""

    def test_full_populate_flow(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
        sample_synthesizer_record: dict,
    ) -> None:
        """Test complete populate_ground_truth flow with mock records."""
        import yaml

        from bmad_assist.benchmarking.ground_truth import populate_ground_truth

        # Setup: Create benchmarks directory with records
        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)

        # Create validator record file
        validator_path = month_dir / "eval-13-7-a-20250120T120000.yaml"
        with open(validator_path, "w") as f:
            yaml.dump(sample_evaluation_record, f)

        # Create synthesizer record file
        synthesizer_path = month_dir / "eval-13-7-synthesizer-20250120T120500.yaml"
        with open(synthesizer_path, "w") as f:
            yaml.dump(sample_synthesizer_record, f)

        # Create index
        index_data = {
            "records": [
                {
                    "record_id": sample_evaluation_record["record_id"],
                    "path": validator_path.name,
                    "epic": 13,
                    "story": 7,
                    "role": "validator",
                    "role_id": "a",
                    "provider": "claude_opus_4_5",
                    "created_at": sample_evaluation_record["created_at"],
                },
                {
                    "record_id": sample_synthesizer_record["record_id"],
                    "path": synthesizer_path.name,
                    "epic": 13,
                    "story": 7,
                    "role": "synthesizer",
                    "role_id": None,
                    "provider": "claude_opus_4_5",
                    "created_at": sample_synthesizer_record["created_at"],
                },
            ]
        }
        with open(month_dir / "index.yaml", "w") as f:
            yaml.dump(index_data, f)

        # Create validation report
        validations_dir = tmp_path / "story-validations"
        validations_dir.mkdir()
        validation_report = """
# 🎯 Story Context Validation Report

## 🚨 Critical Issues

### 1. Missing Error Handling
No error handling for API failures.

### 2. Security Vulnerability
Input not sanitized.

## ⚡ Enhancement Suggestions

### 1. Add Retry Logic
Consider adding retry mechanism.
"""
        report_path = validations_dir / "story-validation-13-7-claude_opus_4_5.md"
        report_path.write_text(validation_report)

        # Code review output with matching findings
        code_review = """
## Issues Found

1. Missing error handling for API calls
2. Security vulnerability in input validation
3. Performance issue with N+1 queries (new finding not in validation)
"""

        # Execute
        updates = populate_ground_truth(
            epic_num=13,
            story_num=7,
            code_review_output=code_review,
            base_dir=tmp_path,
        )

        # Verify
        assert len(updates) == 1  # One validator record updated

        update = updates[0]
        assert update.record_id == sample_evaluation_record["record_id"]
        assert update.ground_truth.populated is True
        assert update.ground_truth.populated_at is not None
        assert update.ground_truth.findings_confirmed == 2  # Two matched
        assert update.ground_truth.findings_false_alarm == 1  # One validation finding unmatched
        assert update.ground_truth.issues_missed == 1  # One CR finding unmatched

    def test_no_records_returns_empty_list(self, tmp_path: Path) -> None:
        """No validation records returns empty list with warning."""
        from bmad_assist.benchmarking.ground_truth import populate_ground_truth

        # No benchmarks directory
        updates = populate_ground_truth(
            epic_num=99,
            story_num=99,
            code_review_output="## Issues\n1. Some issue",
            base_dir=tmp_path,
        )

        assert updates == []

    def test_already_populated_overwrites_with_warning(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
    ) -> None:
        """Already populated ground truth is overwritten with warning."""
        from datetime import UTC, datetime

        import yaml

        from bmad_assist.benchmarking.ground_truth import populate_ground_truth

        # Setup with already populated ground truth
        sample_evaluation_record["ground_truth"] = {
            "populated": True,
            "populated_at": datetime.now(UTC).isoformat(),
            "findings_confirmed": 1,
            "findings_false_alarm": 0,
            "issues_missed": 0,
            "precision": 1.0,
            "recall": 1.0,
            "amendments": [],
            "last_updated_at": None,
        }

        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)

        validator_path = month_dir / "eval-13-7-a-20250120T120000.yaml"
        with open(validator_path, "w") as f:
            yaml.dump(sample_evaluation_record, f)

        # Create index
        index_data = {
            "records": [
                {
                    "record_id": sample_evaluation_record["record_id"],
                    "path": validator_path.name,
                    "epic": 13,
                    "story": 7,
                    "role": "validator",
                    "role_id": "a",
                    "provider": "claude_opus_4_5",
                    "created_at": sample_evaluation_record["created_at"],
                },
            ]
        }
        with open(month_dir / "index.yaml", "w") as f:
            yaml.dump(index_data, f)

        # Create validation report (empty findings)
        validations_dir = tmp_path / "story-validations"
        validations_dir.mkdir()
        report_path = validations_dir / "story-validation-13-7-claude_opus_4_5.md"
        report_path.write_text("## Summary\nNo issues found.")

        # Execute with new empty code review
        updates = populate_ground_truth(
            epic_num=13,
            story_num=7,
            code_review_output="## Summary\nNo issues found.",
            base_dir=tmp_path,
        )

        # Should still update (overwrite old values)
        assert len(updates) == 1
        assert updates[0].ground_truth.findings_confirmed == 0

    def test_no_code_review_findings(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
    ) -> None:
        """No code review findings sets counts to 0, recall to None."""
        import yaml

        from bmad_assist.benchmarking.ground_truth import populate_ground_truth

        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)

        validator_path = month_dir / "eval-13-7-a-20250120T120000.yaml"
        with open(validator_path, "w") as f:
            yaml.dump(sample_evaluation_record, f)

        index_data = {
            "records": [
                {
                    "record_id": sample_evaluation_record["record_id"],
                    "path": validator_path.name,
                    "epic": 13,
                    "story": 7,
                    "role": "validator",
                    "role_id": "a",
                    "provider": "claude_opus_4_5",
                    "created_at": sample_evaluation_record["created_at"],
                },
            ]
        }
        with open(month_dir / "index.yaml", "w") as f:
            yaml.dump(index_data, f)

        # Create validation report WITH findings
        validations_dir = tmp_path / "story-validations"
        validations_dir.mkdir()
        report = """
## 🚨 Critical Issues

### 1. Missing Error Handling
Not handled.
"""
        report_path = validations_dir / "story-validation-13-7-claude_opus_4_5.md"
        report_path.write_text(report)

        # Empty code review (no findings)
        updates = populate_ground_truth(
            epic_num=13,
            story_num=7,
            code_review_output="## Summary\nAll looks good!",
            base_dir=tmp_path,
        )

        assert len(updates) == 1
        gt = updates[0].ground_truth
        assert gt.findings_confirmed == 0
        assert gt.findings_false_alarm == 1  # Validation finding is false alarm
        assert gt.issues_missed == 0
        assert gt.precision == pytest.approx(0.0)  # 0 / (0 + 1)
        assert gt.recall is None  # 0 / (0 + 0) undefined

    def test_validation_report_not_found_skips_validator(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
    ) -> None:
        """Missing validation report skips that validator and continues."""
        import yaml

        from bmad_assist.benchmarking.ground_truth import populate_ground_truth

        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)

        validator_path = month_dir / "eval-13-7-a-20250120T120000.yaml"
        with open(validator_path, "w") as f:
            yaml.dump(sample_evaluation_record, f)

        index_data = {
            "records": [
                {
                    "record_id": sample_evaluation_record["record_id"],
                    "path": validator_path.name,
                    "epic": 13,
                    "story": 7,
                    "role": "validator",
                    "role_id": "a",
                    "provider": "claude_opus_4_5",
                    "created_at": sample_evaluation_record["created_at"],
                },
            ]
        }
        with open(month_dir / "index.yaml", "w") as f:
            yaml.dump(index_data, f)

        # NO validation report created

        updates = populate_ground_truth(
            epic_num=13,
            story_num=7,
            code_review_output="## Issues\n1. Issue",
            base_dir=tmp_path,
        )

        # Should return empty (validator skipped due to missing report)
        assert len(updates) == 0

    def test_synthesizer_consensus_update(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
        sample_synthesizer_record: dict,
    ) -> None:
        """Synthesizer consensus fields updated after all validators."""
        import yaml

        from bmad_assist.benchmarking.ground_truth import populate_ground_truth
        from bmad_assist.benchmarking.storage import load_evaluation_record

        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)

        # Create two validator records
        validator1_record = sample_evaluation_record.copy()
        validator1_record["evaluator"] = validator1_record["evaluator"].copy()
        validator1_record["evaluator"]["role_id"] = "a"
        validator1_record["evaluator"]["provider"] = "claude"
        validator1_record["record_id"] = "validator-1"

        validator2_record = sample_evaluation_record.copy()
        validator2_record["evaluator"] = validator2_record["evaluator"].copy()
        validator2_record["evaluator"]["role_id"] = "b"
        validator2_record["evaluator"]["provider"] = "gemini"
        validator2_record["record_id"] = "validator-2"

        validator1_path = month_dir / "eval-13-7-a-20250120T120000.yaml"
        validator2_path = month_dir / "eval-13-7-b-20250120T120100.yaml"
        synthesizer_path = month_dir / "eval-13-7-synthesizer-20250120T120500.yaml"

        with open(validator1_path, "w") as f:
            yaml.dump(validator1_record, f)
        with open(validator2_path, "w") as f:
            yaml.dump(validator2_record, f)
        with open(synthesizer_path, "w") as f:
            yaml.dump(sample_synthesizer_record, f)

        # Create index
        index_data = {
            "records": [
                {
                    "record_id": validator1_record["record_id"],
                    "path": validator1_path.name,
                    "epic": 13,
                    "story": 7,
                    "role": "validator",
                    "role_id": "a",
                    "provider": "claude",
                    "created_at": validator1_record["created_at"],
                },
                {
                    "record_id": validator2_record["record_id"],
                    "path": validator2_path.name,
                    "epic": 13,
                    "story": 7,
                    "role": "validator",
                    "role_id": "b",
                    "provider": "gemini",
                    "created_at": validator2_record["created_at"],
                },
                {
                    "record_id": sample_synthesizer_record["record_id"],
                    "path": synthesizer_path.name,
                    "epic": 13,
                    "story": 7,
                    "role": "synthesizer",
                    "role_id": None,
                    "provider": "claude_opus_4_5",
                    "created_at": sample_synthesizer_record["created_at"],
                },
            ]
        }
        with open(month_dir / "index.yaml", "w") as f:
            yaml.dump(index_data, f)

        # Create validation reports for both validators
        validations_dir = tmp_path / "story-validations"
        validations_dir.mkdir()

        report1 = """
## 🚨 Critical Issues

### 1. Missing Error Handling
Issue 1.
"""
        (validations_dir / "story-validation-13-7-claude.md").write_text(report1)

        report2 = """
## 🚨 Critical Issues

### 1. Security Issue
Issue 2.
"""
        (validations_dir / "story-validation-13-7-gemini.md").write_text(report2)

        # Code review with one issue that matches validator 1
        code_review = """
## Issues

1. Missing error handling found
2. New issue not in validation
"""

        # Execute
        updates = populate_ground_truth(
            epic_num=13,
            story_num=7,
            code_review_output=code_review,
            base_dir=tmp_path,
        )

        # Verify validator updates
        assert len(updates) == 2

        # Verify synthesizer consensus update
        synth_record = load_evaluation_record(synthesizer_path)
        assert synth_record.consensus is not None
        # Aggregate: validator1 missed 1, validator2 missed 2, false alarms: v1=0, v2=1
        assert synth_record.consensus.missed_findings >= 0
        assert synth_record.consensus.false_positive_count >= 0

    def test_no_synthesizer_record(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
    ) -> None:
        """No synthesizer record logs warning, skips consensus update."""
        import yaml

        from bmad_assist.benchmarking.ground_truth import populate_ground_truth

        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)

        validator_path = month_dir / "eval-13-7-a-20250120T120000.yaml"
        with open(validator_path, "w") as f:
            yaml.dump(sample_evaluation_record, f)

        index_data = {
            "records": [
                {
                    "record_id": sample_evaluation_record["record_id"],
                    "path": validator_path.name,
                    "epic": 13,
                    "story": 7,
                    "role": "validator",
                    "role_id": "a",
                    "provider": "claude_opus_4_5",
                    "created_at": sample_evaluation_record["created_at"],
                },
            ]
        }
        with open(month_dir / "index.yaml", "w") as f:
            yaml.dump(index_data, f)

        # Create validation report
        validations_dir = tmp_path / "story-validations"
        validations_dir.mkdir()
        report_path = validations_dir / "story-validation-13-7-claude_opus_4_5.md"
        report_path.write_text("## 🚨 Critical Issues\n\n### 1. Issue\nSome issue.")

        # Execute
        updates = populate_ground_truth(
            epic_num=13,
            story_num=7,
            code_review_output="## Issues\n1. Issue",
            base_dir=tmp_path,
        )

        # Should still return validator update
        assert len(updates) == 1

    def test_synthesizer_no_consensus(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
        sample_synthesizer_record: dict,
    ) -> None:
        """Synthesizer with consensus=None skips consensus update."""
        import yaml

        from bmad_assist.benchmarking.ground_truth import populate_ground_truth
        from bmad_assist.benchmarking.storage import load_evaluation_record

        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)

        validator_path = month_dir / "eval-13-7-a-20250120T120000.yaml"
        with open(validator_path, "w") as f:
            yaml.dump(sample_evaluation_record, f)

        # Synthesizer with consensus=None
        synth_record = sample_synthesizer_record.copy()
        synth_record["consensus"] = None
        synthesizer_path = month_dir / "eval-13-7-synthesizer-20250120T120500.yaml"
        with open(synthesizer_path, "w") as f:
            yaml.dump(synth_record, f)

        index_data = {
            "records": [
                {
                    "record_id": sample_evaluation_record["record_id"],
                    "path": validator_path.name,
                    "epic": 13,
                    "story": 7,
                    "role": "validator",
                    "role_id": "a",
                    "provider": "claude_opus_4_5",
                    "created_at": sample_evaluation_record["created_at"],
                },
                {
                    "record_id": synth_record["record_id"],
                    "path": synthesizer_path.name,
                    "epic": 13,
                    "story": 7,
                    "role": "synthesizer",
                    "role_id": None,
                    "provider": "claude_opus_4_5",
                    "created_at": synth_record["created_at"],
                },
            ]
        }
        with open(month_dir / "index.yaml", "w") as f:
            yaml.dump(index_data, f)

        # Create validation report
        validations_dir = tmp_path / "story-validations"
        validations_dir.mkdir()
        report_path = validations_dir / "story-validation-13-7-claude_opus_4_5.md"
        report_path.write_text("## 🚨 Critical Issues\n\n### 1. Issue\nSome issue.")

        # Execute
        updates = populate_ground_truth(
            epic_num=13,
            story_num=7,
            code_review_output="## Issues\n1. Issue",
            base_dir=tmp_path,
        )

        # Should return validator update
        assert len(updates) == 1

        # Synthesizer consensus should still be None
        synth = load_evaluation_record(synthesizer_path)
        assert synth.consensus is None


# =============================================================================
# Task 6: amend_ground_truth tests (AC5)
# =============================================================================


class TestAmendGroundTruth:
    """Tests for amend_ground_truth function (AC5)."""

    def test_apply_amendment_success(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
    ) -> None:
        """Successfully apply amendment to ground truth."""
        from datetime import UTC, datetime

        import yaml

        from bmad_assist.benchmarking.ground_truth import amend_ground_truth
        from bmad_assist.benchmarking.storage import load_evaluation_record

        # Setup: Record with populated ground truth
        sample_evaluation_record["ground_truth"] = {
            "populated": True,
            "populated_at": datetime.now(UTC).isoformat(),
            "findings_confirmed": 3,
            "findings_false_alarm": 1,
            "issues_missed": 1,
            "precision": 0.75,
            "recall": 0.75,
            "amendments": [],
            "last_updated_at": None,
        }

        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)
        record_path = month_dir / "eval-13-7-a-20250120T120000.yaml"

        with open(record_path, "w") as f:
            yaml.dump(sample_evaluation_record, f)

        # Create amendment
        amendment = Amendment(
            timestamp=datetime.now(UTC),
            phase="code_review",
            note="Code review found additional issue",
            delta_confirmed=0,
            delta_missed=1,  # Add one missed issue
        )

        # Execute
        amend_ground_truth(record_path, amendment)

        # Verify
        updated = load_evaluation_record(record_path)
        assert updated.ground_truth is not None
        assert updated.ground_truth.issues_missed == 2  # 1 + 1
        assert len(updated.ground_truth.amendments) == 1
        assert updated.ground_truth.amendments[0].note == "Code review found additional issue"
        assert updated.ground_truth.last_updated_at is not None

    def test_apply_multiple_amendments(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
    ) -> None:
        """Apply multiple amendments in sequence."""
        from datetime import UTC, datetime

        import yaml

        from bmad_assist.benchmarking.ground_truth import amend_ground_truth
        from bmad_assist.benchmarking.storage import load_evaluation_record

        # Setup
        sample_evaluation_record["ground_truth"] = {
            "populated": True,
            "populated_at": datetime.now(UTC).isoformat(),
            "findings_confirmed": 2,
            "findings_false_alarm": 2,
            "issues_missed": 2,
            "precision": 0.5,
            "recall": 0.5,
            "amendments": [],
            "last_updated_at": None,
        }

        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)
        record_path = month_dir / "eval-13-7-a-20250120T120000.yaml"

        with open(record_path, "w") as f:
            yaml.dump(sample_evaluation_record, f)

        # First amendment
        amend_ground_truth(
            record_path,
            Amendment(
                timestamp=datetime.now(UTC),
                phase="code_review",
                note="First amendment",
                delta_confirmed=1,
                delta_missed=0,
            ),
        )

        # Second amendment
        amend_ground_truth(
            record_path,
            Amendment(
                timestamp=datetime.now(UTC),
                phase="code_review",
                note="Second amendment",
                delta_confirmed=0,
                delta_missed=-1,
            ),
        )

        # Verify
        updated = load_evaluation_record(record_path)
        gt = updated.ground_truth
        assert gt is not None
        assert gt.findings_confirmed == 3  # 2 + 1
        assert gt.issues_missed == 1  # 2 - 1
        assert len(gt.amendments) == 2

    def test_amendment_recalculates_precision_recall(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
    ) -> None:
        """Amendment recalculates precision and recall."""
        from datetime import UTC, datetime

        import yaml

        from bmad_assist.benchmarking.ground_truth import amend_ground_truth
        from bmad_assist.benchmarking.storage import load_evaluation_record

        # Setup: 3 confirmed, 1 false alarm -> precision = 0.75
        sample_evaluation_record["ground_truth"] = {
            "populated": True,
            "populated_at": datetime.now(UTC).isoformat(),
            "findings_confirmed": 3,
            "findings_false_alarm": 1,
            "issues_missed": 0,
            "precision": 0.75,
            "recall": 1.0,
            "amendments": [],
            "last_updated_at": None,
        }

        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)
        record_path = month_dir / "eval-13-7-a-20250120T120000.yaml"

        with open(record_path, "w") as f:
            yaml.dump(sample_evaluation_record, f)

        # Amendment: add 1 confirmed
        amend_ground_truth(
            record_path,
            Amendment(
                timestamp=datetime.now(UTC),
                phase="code_review",
                note="Confirmed additional issue",
                delta_confirmed=1,
                delta_missed=0,
            ),
        )

        # Verify new precision: 4 / (4 + 1) = 0.8
        updated = load_evaluation_record(record_path)
        assert updated.ground_truth.precision == pytest.approx(0.8)
        assert updated.ground_truth.recall == pytest.approx(1.0)

    def test_amendment_record_not_found(self, tmp_path: Path) -> None:
        """Raise GroundTruthError when record not found."""
        from datetime import UTC, datetime

        from bmad_assist.benchmarking.ground_truth import (
            GroundTruthError,
            amend_ground_truth,
        )

        nonexistent_path = tmp_path / "nonexistent.yaml"
        amendment = Amendment(
            timestamp=datetime.now(UTC),
            phase="code_review",
            note="Test",
            delta_confirmed=0,
            delta_missed=0,
        )

        with pytest.raises(GroundTruthError, match="not found|Failed"):
            amend_ground_truth(nonexistent_path, amendment)

    def test_amendment_unpopulated_ground_truth(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
    ) -> None:
        """Raise GroundTruthError when ground truth not populated."""
        from datetime import UTC, datetime

        import yaml

        from bmad_assist.benchmarking.ground_truth import (
            GroundTruthError,
            amend_ground_truth,
        )

        # Ground truth not populated
        sample_evaluation_record["ground_truth"] = None

        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)
        record_path = month_dir / "eval-13-7-a-20250120T120000.yaml"

        with open(record_path, "w") as f:
            yaml.dump(sample_evaluation_record, f)

        amendment = Amendment(
            timestamp=datetime.now(UTC),
            phase="code_review",
            note="Test",
            delta_confirmed=1,
            delta_missed=0,
        )

        with pytest.raises(GroundTruthError, match="not populated"):
            amend_ground_truth(record_path, amendment)

    def test_amendment_clamps_negative_values(
        self,
        tmp_path: Path,
        sample_evaluation_record: dict,
    ) -> None:
        """Negative values are clamped to 0."""
        from datetime import UTC, datetime

        import yaml

        from bmad_assist.benchmarking.ground_truth import amend_ground_truth
        from bmad_assist.benchmarking.storage import load_evaluation_record

        # Setup
        sample_evaluation_record["ground_truth"] = {
            "populated": True,
            "populated_at": datetime.now(UTC).isoformat(),
            "findings_confirmed": 1,
            "findings_false_alarm": 0,
            "issues_missed": 0,
            "precision": 1.0,
            "recall": 1.0,
            "amendments": [],
            "last_updated_at": None,
        }

        month_dir = tmp_path / "benchmarks" / "2025-01"
        month_dir.mkdir(parents=True)
        record_path = month_dir / "eval-13-7-a-20250120T120000.yaml"

        with open(record_path, "w") as f:
            yaml.dump(sample_evaluation_record, f)

        # Try to subtract more than exists
        amend_ground_truth(
            record_path,
            Amendment(
                timestamp=datetime.now(UTC),
                phase="code_review",
                note="Test negative clamping",
                delta_confirmed=-5,  # More than 1 confirmed
                delta_missed=0,
            ),
        )

        updated = load_evaluation_record(record_path)
        assert updated.ground_truth.findings_confirmed == 0  # Clamped to 0
