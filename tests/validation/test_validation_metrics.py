"""Tests for deterministic validation metrics extraction.

Tests cover:
- Per-validator metrics extraction from markdown
- Aggregate metrics calculation
- Formatted output generation
- Evidence Score integration
"""

import pytest

from bmad_assist.validation.validation_metrics import (
    AggregateMetrics,
    ValidatorMetrics,
    calculate_aggregate_metrics,
    extract_validator_metrics,
    format_deterministic_metrics_header,
)


class TestExtractValidatorMetrics:
    """Tests for extract_validator_metrics function."""

    def test_extracts_issue_counts_from_table(self) -> None:
        """Extracts critical/enhancement/optimization counts from Issues Overview."""
        content = """
# Validation Report

## Executive Summary

### Issues Overview

| Category | Found |
|----------|-------|
| 🚨 Critical Issues | 4 |
| ⚡ Enhancements | 5 |
| ✨ Optimizations | 3 |
| 🤖 LLM Optimizations | 2 |
"""
        metrics = extract_validator_metrics(content, "Validator A")

        assert metrics.critical_count == 4
        assert metrics.enhancement_count == 5
        assert metrics.optimization_count == 3
        assert metrics.llm_optimization_count == 2
        assert metrics.total_findings == 14

    def test_extracts_evidence_score_from_heading(self) -> None:
        """Extracts Evidence Score from heading format."""
        content = """
### Evidence Score: 4.5

| Score | Verdict |
|-------|---------|
| **4.5** | **MAJOR REWORK** |
"""
        metrics = extract_validator_metrics(content, "Validator A")

        assert metrics.evidence_score == 4.5
        assert metrics.verdict == "MAJOR REWORK"

    def test_extracts_evidence_score_findings(self) -> None:
        """Extracts Evidence Score finding counts (Deep Verify format)."""
        content = """
## Evidence Score Summary

| Severity | Count |
|----------|-------|
| 🔴 CRITICAL | 2 |
| 🟠 IMPORTANT | 3 |
| 🟡 MINOR | 5 |
| 🟢 CLEAN PASS | 4 |
"""
        metrics = extract_validator_metrics(content, "Validator A")

        assert metrics.critical_finding_count == 2
        assert metrics.important_finding_count == 3
        assert metrics.minor_finding_count == 5
        assert metrics.clean_pass_count == 4
        assert metrics.total_evidence_findings == 10  # 2 + 3 + 5

    def test_counts_invest_violations(self) -> None:
        """Counts bullet points in INVEST Violations section."""
        content = """
### INVEST Violations

- **[5/10] Independent:** CTA target is not fully specified
- **[4/10] Negotiable:** Overly prescriptive about implementation
- **[4/10] Estimable:** Scope boundary is blurred

### Acceptance Criteria Issues
"""
        metrics = extract_validator_metrics(content, "Validator A")

        assert metrics.invest_violations == 3

    def test_handles_missing_sections(self) -> None:
        """Returns zeros for missing sections."""
        content = "# Empty report"
        metrics = extract_validator_metrics(content, "Validator A")

        assert metrics.critical_count == 0
        assert metrics.enhancement_count == 0
        assert metrics.evidence_score is None
        assert metrics.verdict is None

    def test_preserves_validator_id(self) -> None:
        """Preserves validator ID in output."""
        metrics = extract_validator_metrics("", "Validator B")
        assert metrics.validator_id == "Validator B"


class TestCalculateAggregateMetrics:
    """Tests for calculate_aggregate_metrics function."""

    def test_calculates_evidence_score_statistics(self) -> None:
        """Calculates min/max/avg/stdev for Evidence Scores."""
        validators = [
            ValidatorMetrics("A", evidence_score=2.0),
            ValidatorMetrics("B", evidence_score=4.0),
            ValidatorMetrics("C", evidence_score=6.0),
        ]

        aggregate = calculate_aggregate_metrics(validators)

        assert aggregate.evidence_score_min == 2.0
        assert aggregate.evidence_score_max == 6.0
        assert abs(aggregate.evidence_score_avg - 4.0) < 0.1  # type: ignore[operator]
        assert aggregate.evidence_score_stdev is not None

    def test_sums_category_totals(self) -> None:
        """Sums findings across all validators."""
        validators = [
            ValidatorMetrics("A", critical_count=4, enhancement_count=5),
            ValidatorMetrics("B", critical_count=2, enhancement_count=3),
        ]

        aggregate = calculate_aggregate_metrics(validators)

        assert aggregate.total_critical == 6
        assert aggregate.total_enhancement == 8
        assert aggregate.total_findings == 14

    def test_sums_evidence_score_findings(self) -> None:
        """Sums Evidence Score findings across all validators."""
        validators = [
            ValidatorMetrics(
                "A",
                critical_finding_count=2,
                important_finding_count=3,
                minor_finding_count=1,
                clean_pass_count=4,
            ),
            ValidatorMetrics(
                "B",
                critical_finding_count=1,
                important_finding_count=2,
                minor_finding_count=2,
                clean_pass_count=3,
            ),
        ]

        aggregate = calculate_aggregate_metrics(validators)

        assert aggregate.total_critical_findings == 3
        assert aggregate.total_important_findings == 5
        assert aggregate.total_minor_findings == 3
        assert aggregate.total_clean_passes == 7
        assert aggregate.total_evidence_findings == 11  # 3 + 5 + 3

    def test_counts_validators_with_findings(self) -> None:
        """Counts how many validators found issues in each category."""
        validators = [
            ValidatorMetrics("A", critical_count=4),
            ValidatorMetrics("B", critical_count=0),
            ValidatorMetrics("C", critical_count=2),
        ]

        aggregate = calculate_aggregate_metrics(validators)

        assert aggregate.validators_with_critical == 2

    def test_counts_validators_with_evidence_findings(self) -> None:
        """Counts how many validators found Evidence Score findings."""
        validators = [
            ValidatorMetrics("A", critical_finding_count=2, important_finding_count=0),
            ValidatorMetrics("B", critical_finding_count=0, important_finding_count=3),
            ValidatorMetrics("C", critical_finding_count=1, important_finding_count=2),
        ]

        aggregate = calculate_aggregate_metrics(validators)

        assert aggregate.validators_with_critical_findings == 2
        assert aggregate.validators_with_important_findings == 2

    def test_handles_empty_list(self) -> None:
        """Returns empty aggregate for no validators."""
        aggregate = calculate_aggregate_metrics([])

        assert aggregate.validator_count == 0
        assert aggregate.evidence_score_avg is None

    def test_handles_single_validator(self) -> None:
        """Handles single validator (no stdev possible)."""
        validators = [ValidatorMetrics("A", evidence_score=3.5)]

        aggregate = calculate_aggregate_metrics(validators)

        assert aggregate.validator_count == 1
        assert aggregate.evidence_score_avg == 3.5
        assert aggregate.evidence_score_stdev is None


class TestFormatDeterministicMetricsHeader:
    """Tests for format_deterministic_metrics_header function."""

    def test_includes_markers(self) -> None:
        """Output includes start/end markers."""
        aggregate = AggregateMetrics(validator_count=2)
        header = format_deterministic_metrics_header(aggregate)

        assert "<!-- DETERMINISTIC_METRICS_START -->" in header
        assert "<!-- DETERMINISTIC_METRICS_END -->" in header

    def test_includes_summary_table(self) -> None:
        """Output includes summary table with validator count."""
        aggregate = AggregateMetrics(
            validator_count=4,
            evidence_score_avg=3.5,
            total_evidence_findings=12,
        )
        header = format_deterministic_metrics_header(aggregate)

        assert "| Validators | 4 |" in header
        assert "Evidence Score (avg) | 3.50" in header
        assert "| Total findings | 12 |" in header

    def test_includes_evidence_score_breakdown(self) -> None:
        """Output includes Evidence Score findings by severity table."""
        aggregate = AggregateMetrics(
            validator_count=3,
            total_critical_findings=6,
            total_important_findings=4,
            total_minor_findings=2,
            total_clean_passes=5,
            validators_with_critical_findings=2,
            validators_with_important_findings=3,
        )
        header = format_deterministic_metrics_header(aggregate)

        assert "| 🔴 CRITICAL | +3 | 6 | 2/3 |" in header
        assert "| 🟠 IMPORTANT | +1 | 4 | 3/3 |" in header
        assert "| 🟡 MINOR | +0.3 | 2 | - |" in header
        assert "| 🟢 CLEAN PASS | -0.5 | 5 | - |" in header

    def test_includes_per_validator_breakdown(self) -> None:
        """Output includes per-validator Evidence Score table."""
        validators = [
            ValidatorMetrics(
                "Validator A",
                critical_finding_count=2,
                important_finding_count=1,
                minor_finding_count=0,
                clean_pass_count=3,
                evidence_score=4.5,
                verdict="MAJOR REWORK",
            ),
            ValidatorMetrics(
                "Validator B",
                critical_finding_count=0,
                important_finding_count=2,
                minor_finding_count=1,
                clean_pass_count=5,
                evidence_score=-0.2,
                verdict="READY",
            ),
        ]
        aggregate = calculate_aggregate_metrics(validators)
        header = format_deterministic_metrics_header(aggregate)

        assert "| Validator A | 4.50 | 2 | 1 | 0 | 3 | MAJOR REWORK |" in header
        assert "| Validator B | -0.20 | 0 | 2 | 1 | 5 | READY |" in header


class TestIntegration:
    """Integration tests with real validation report content."""

    def test_full_extraction_pipeline_evidence_score(self) -> None:
        """Tests full extraction from Evidence Score format content."""
        # Note: CRITICAL_FINDING_PATTERN expects format: | 🔴 CRITICAL | <count> |
        # Evidence Score detailed findings are parsed by evidence_score.py module
        content_a = """
# Story Context Validation Report

## Evidence Score Summary

| Severity | Count |
|----------|-------|
| 🔴 CRITICAL | 2 |
| 🟠 IMPORTANT | 1 |
| 🟡 MINOR | 1 |
| 🟢 CLEAN PASS | 2 |

### Evidence Score: 7.3

| Score | Verdict |
|-------|---------|
| **7.3** | **REJECT** |
"""
        content_b = """
# Story Context Validation Report

## Evidence Score Summary

| Severity | Count |
|----------|-------|
| 🔴 CRITICAL | 0 |
| 🟠 IMPORTANT | 1 |
| 🟡 MINOR | 1 |
| 🟢 CLEAN PASS | 6 |

### Evidence Score: -1.7

| Score | Verdict |
|-------|---------|
| **-1.7** | **READY** |
"""
        # Extract individual metrics
        metrics_a = extract_validator_metrics(content_a, "Validator A")
        metrics_b = extract_validator_metrics(content_b, "Validator B")

        assert metrics_a.evidence_score == 7.3
        assert metrics_a.critical_finding_count == 2
        assert metrics_a.important_finding_count == 1
        assert metrics_a.verdict == "REJECT"

        assert metrics_b.evidence_score == -1.7
        assert metrics_b.critical_finding_count == 0
        assert metrics_b.important_finding_count == 1
        assert metrics_b.verdict == "READY"

        # Calculate aggregate
        aggregate = calculate_aggregate_metrics([metrics_a, metrics_b])

        assert aggregate.validator_count == 2
        assert aggregate.evidence_score_avg == 2.8  # (7.3 + -1.7) / 2
        assert aggregate.total_critical_findings == 2
        assert aggregate.total_important_findings == 2
        assert aggregate.validators_with_critical_findings == 1

        # Format header
        header = format_deterministic_metrics_header(aggregate)

        assert "## Validation Metrics (Deterministic)" in header
        assert "| Validators | 2 |" in header
        assert "| 🔴 CRITICAL | +3 | 2 | 1/2 |" in header

    def test_legacy_format_still_works(self) -> None:
        """Tests that legacy format (old validation reports) still works."""
        content = """
# 🎯 Story Context Validation Report

## Executive Summary

### 🎯 Story Quality Verdict

| Final Score | Verdict |
|-------------|---------|
| **6/10** | **MAJOR REWORK** |

### Issues Overview

| Category | Found |
|----------|-------|
| 🚨 Critical Issues | 4 |
| ⚡ Enhancements | 5 |
| ✨ Optimizations | 3 |
| 🤖 LLM Optimizations | 3 |

### INVEST Violations

- **[5/10] Independent:** Issue 1
- **[4/10] Negotiable:** Issue 2
"""
        metrics = extract_validator_metrics(content, "Validator A")

        # Legacy counts should still work
        assert metrics.critical_count == 4
        assert metrics.enhancement_count == 5
        assert metrics.optimization_count == 3
        assert metrics.llm_optimization_count == 3
        assert metrics.total_findings == 15
        assert metrics.invest_violations == 2
