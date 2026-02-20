"""Tests for Evidence Score calculation module.

Tests cover:
- Severity and Verdict enums
- Score calculation with various findings
- Verdict threshold determination
- Report parsing (table and bullet formats)
- Finding deduplication
- Aggregate calculation across validators
- Context formatting for synthesis
- Exception handling for cache validation
"""

import pytest

from bmad_assist.validation.evidence_score import (
    AllValidatorsFailedError,
    CacheFormatError,
    CacheVersionError,
    EvidenceFinding,
    EvidenceScoreAggregate,
    EvidenceScoreReport,
    Severity,
    Verdict,
    aggregate_evidence_scores,
    calculate_evidence_score,
    determine_verdict,
    format_evidence_score_context,
    parse_evidence_findings,
)

# =============================================================================
# Enum Tests
# =============================================================================


class TestSeverityEnum:
    """Tests for Severity enum."""

    def test_severity_values(self) -> None:
        """Test all severity values exist."""
        assert Severity.CRITICAL.value == "CRITICAL"
        assert Severity.IMPORTANT.value == "IMPORTANT"
        assert Severity.MINOR.value == "MINOR"

    def test_severity_from_string(self) -> None:
        """Test creating severity from string."""
        assert Severity("CRITICAL") == Severity.CRITICAL
        assert Severity("IMPORTANT") == Severity.IMPORTANT
        assert Severity("MINOR") == Severity.MINOR


class TestVerdictEnum:
    """Tests for Verdict enum."""

    def test_verdict_values(self) -> None:
        """Test all verdict values exist."""
        assert Verdict.REJECT.value == "REJECT"
        assert Verdict.MAJOR_REWORK.value == "MAJOR_REWORK"
        assert Verdict.PASS.value == "PASS"
        assert Verdict.EXCELLENT.value == "EXCELLENT"

    def test_display_name_validation_context(self) -> None:
        """Test display names for validation context."""
        assert Verdict.REJECT.display_name("validation") == "REJECT"
        assert Verdict.MAJOR_REWORK.display_name("validation") == "MAJOR REWORK"
        assert Verdict.PASS.display_name("validation") == "READY"
        assert Verdict.EXCELLENT.display_name("validation") == "EXCELLENT"

    def test_display_name_code_review_context(self) -> None:
        """Test display names for code review context."""
        assert Verdict.REJECT.display_name("code_review") == "REJECT"
        assert Verdict.MAJOR_REWORK.display_name("code_review") == "MAJOR REWORK"
        assert Verdict.PASS.display_name("code_review") == "APPROVE"
        assert Verdict.EXCELLENT.display_name("code_review") == "EXEMPLARY"


# =============================================================================
# Score Calculation Tests
# =============================================================================


class TestCalculateEvidenceScore:
    """Tests for calculate_evidence_score function."""

    def test_empty_findings_zero_clean_passes(self) -> None:
        """Test score with no findings and no clean passes."""
        score = calculate_evidence_score([], 0)
        assert score == 0.0

    def test_single_critical_finding(self) -> None:
        """Test score with single CRITICAL finding (+3)."""
        findings = [
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Test critical",
                source="test.py:10",
                validator_id="Validator A",
            )
        ]
        score = calculate_evidence_score(findings, 0)
        assert score == 3.0

    def test_mixed_findings(self) -> None:
        """Test score with mixed severity findings."""
        findings = [
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Critical issue",
                source="test.py:10",
                validator_id="Validator A",
            ),
            EvidenceFinding(
                severity=Severity.IMPORTANT,
                score=1.0,
                description="Important issue",
                source="test.py:20",
                validator_id="Validator A",
            ),
            EvidenceFinding(
                severity=Severity.MINOR,
                score=0.3,
                description="Minor issue",
                source="test.py:30",
                validator_id="Validator A",
            ),
        ]
        # 3.0 + 1.0 + 0.3 = 4.3
        score = calculate_evidence_score(findings, 0)
        assert score == 4.3

    def test_clean_passes_reduce_score(self) -> None:
        """Test that CLEAN PASS categories reduce score."""
        findings = [
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Critical issue",
                source="test.py:10",
                validator_id="Validator A",
            )
        ]
        # 3.0 + (4 * -0.5) = 3.0 - 2.0 = 1.0
        score = calculate_evidence_score(findings, 4)
        assert score == 1.0

    def test_negative_score_possible(self) -> None:
        """Test that score can go negative with many clean passes."""
        # 0 findings + 10 clean passes = 10 * -0.5 = -5.0
        score = calculate_evidence_score([], 10)
        assert score == -5.0


class TestDetermineVerdict:
    """Tests for determine_verdict function."""

    def test_reject_threshold(self) -> None:
        """Test REJECT verdict for score >= 6."""
        assert determine_verdict(6.0) == Verdict.REJECT
        assert determine_verdict(10.0) == Verdict.REJECT
        assert determine_verdict(100.0) == Verdict.REJECT

    def test_major_rework_threshold(self) -> None:
        """Test MAJOR_REWORK verdict for score 4-5.9."""
        assert determine_verdict(4.0) == Verdict.MAJOR_REWORK
        assert determine_verdict(5.0) == Verdict.MAJOR_REWORK
        assert determine_verdict(5.9) == Verdict.MAJOR_REWORK

    def test_pass_threshold(self) -> None:
        """Test PASS verdict for score -2.9 to 3.9."""
        assert determine_verdict(3.9) == Verdict.PASS
        assert determine_verdict(0.0) == Verdict.PASS
        assert determine_verdict(-2.9) == Verdict.PASS

    def test_excellent_threshold(self) -> None:
        """Test EXCELLENT verdict for score <= -3."""
        assert determine_verdict(-3.0) == Verdict.EXCELLENT
        assert determine_verdict(-5.0) == Verdict.EXCELLENT
        assert determine_verdict(-10.0) == Verdict.EXCELLENT


# =============================================================================
# Parsing Tests
# =============================================================================


class TestParseEvidenceFindings:
    """Tests for parse_evidence_findings function."""

    def test_parse_table_format(self) -> None:
        """Test parsing Evidence Score table format."""
        content = """
## Evidence Score Summary

| Severity | Description | Source | Score |
|----------|-------------|--------|-------|
| 🔴 CRITICAL | Missing input validation | auth.py:45 | +3 |
| 🟠 IMPORTANT | No error handling | api.py:100 | +1 |
| 🟡 MINOR | Inconsistent naming | utils.py:20 | +0.3 |

| 🟢 CLEAN PASS | 5 |

### Evidence Score: 4.3
"""
        report = parse_evidence_findings(content, "Validator A")
        assert report is not None
        assert len(report.findings) == 3
        assert report.clean_passes == 5
        # 3.0 + 1.0 + 0.3 + (5 * -0.5) = 4.3 - 2.5 = 1.8
        assert report.total_score == 1.8

    def test_parse_bullet_format(self) -> None:
        """Test parsing Evidence Score bullet format."""
        content = """
## Findings

- 🔴 **CRITICAL** (+3): SQL injection vulnerability [db.py:50]
- 🟠 **IMPORTANT** (+1): Missing rate limiting [api.py:30]
- 🟡 **MINOR** (+0.3): Unused import

CLEAN PASS: 2
"""
        report = parse_evidence_findings(content, "Validator B")
        assert report is not None
        assert len(report.findings) == 3
        assert report.clean_passes == 2
        # 3.0 + 1.0 + 0.3 + (2 * -0.5) = 4.3 - 1.0 = 3.3
        assert report.total_score == 3.3

    def test_parse_no_findings_returns_none(self) -> None:
        """Test that report with no parseable data returns None."""
        content = """
This is a validation report without any Evidence Score format.

Just plain text without structured findings.
"""
        report = parse_evidence_findings(content, "Validator C")
        assert report is None

    def test_parse_only_clean_passes(self) -> None:
        """Test parsing report with only CLEAN PASS count."""
        content = """
## Evidence Score

No issues found!

| 🟢 CLEAN PASS | 8 |

Evidence Score: -4.0
"""
        report = parse_evidence_findings(content, "Validator D")
        assert report is not None
        assert len(report.findings) == 0
        assert report.clean_passes == 8
        assert report.total_score == -4.0
        assert report.verdict == Verdict.EXCELLENT


# =============================================================================
# Aggregation Tests
# =============================================================================


class TestAggregateEvidenceScores:
    """Tests for aggregate_evidence_scores function."""

    def test_single_report_aggregate(self) -> None:
        """Test aggregation with single report."""
        findings = (
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Test critical",
                source="test.py:10",
                validator_id="Validator A",
            ),
        )
        report = EvidenceScoreReport(
            validator_id="Validator A",
            findings=findings,
            clean_passes=2,
            total_score=2.0,
            verdict=Verdict.PASS,
        )

        aggregate = aggregate_evidence_scores([report])

        assert aggregate.total_score == 2.0
        assert aggregate.verdict == Verdict.PASS
        assert aggregate.per_validator_scores == {"Validator A": 2.0}
        assert aggregate.total_findings == 1
        assert aggregate.consensus_ratio == 0.0  # Single validator = no consensus

    def test_multiple_reports_with_consensus(self) -> None:
        """Test aggregation with multiple reports having consensus findings."""
        # Both validators report similar critical issue
        findings_a = (
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Missing input validation",
                source="auth.py:45",
                validator_id="Validator A",
            ),
        )
        findings_b = (
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Missing input validation in auth",
                source="auth.py:45",
                validator_id="Validator B",
            ),
        )

        report_a = EvidenceScoreReport(
            validator_id="Validator A",
            findings=findings_a,
            clean_passes=2,
            total_score=2.0,
            verdict=Verdict.PASS,
        )
        report_b = EvidenceScoreReport(
            validator_id="Validator B",
            findings=findings_b,
            clean_passes=1,
            total_score=2.5,
            verdict=Verdict.PASS,
        )

        aggregate = aggregate_evidence_scores([report_a, report_b])

        assert aggregate.total_score == 2.2  # Average of 2.0 and 2.5 = 2.25, rounded to 2.2
        assert aggregate.total_findings == 1  # Deduplicated
        assert len(aggregate.consensus_findings) == 1  # Both validators agree
        assert len(aggregate.unique_findings) == 0
        assert aggregate.consensus_ratio == 1.0

    def test_empty_reports_raises_error(self) -> None:
        """Test that empty reports list raises AllValidatorsFailedError."""
        with pytest.raises(AllValidatorsFailedError):
            aggregate_evidence_scores([])

    def test_consensus_with_fuzzy_match_and_severity_replacement(self) -> None:
        """Test that consensus tracking survives severity replacement.

        When two findings are fuzzy-matched (similar but not identical descriptions)
        and the second has higher severity, the replacement must update consensus
        tracking to use the new finding's normalized_description.

        Regression test for bug where consensus_counts used old key but deduped
        list contained new finding with different normalized_description.
        """
        # Validator A: MINOR finding
        # SequenceMatcher ratio for "missing input validation" vs "missing input validation in auth"
        # is 2*24/(24+32) = 48/56 = 0.857 > 0.85 threshold
        findings_a = (
            EvidenceFinding(
                severity=Severity.MINOR,
                score=0.3,
                description="Missing input validation",  # Shorter version
                source="auth.py:45",
                validator_id="Validator A",
            ),
        )
        # Validator B: CRITICAL finding with similar but longer description
        findings_b = (
            EvidenceFinding(
                severity=Severity.CRITICAL,  # Higher severity - triggers replacement
                score=3.0,
                description="Missing input validation in auth",  # Similar but different
                source="auth.py:45",
                validator_id="Validator B",
            ),
        )

        report_a = EvidenceScoreReport(
            validator_id="Validator A",
            findings=findings_a,
            clean_passes=2,
            total_score=-0.7,  # 0.3 + (2 * -0.5) = 0.3 - 1.0 = -0.7
            verdict=Verdict.PASS,
        )
        report_b = EvidenceScoreReport(
            validator_id="Validator B",
            findings=findings_b,
            clean_passes=1,
            total_score=2.5,  # 3.0 + (1 * -0.5) = 3.0 - 0.5 = 2.5
            verdict=Verdict.PASS,
        )

        aggregate = aggregate_evidence_scores([report_a, report_b])

        # Key assertions:
        # 1. Findings should be deduplicated (fuzzy match)
        assert aggregate.total_findings == 1

        # 2. The CRITICAL finding should be kept (higher severity)
        assert aggregate.findings_by_severity[Severity.CRITICAL] == 1
        assert aggregate.findings_by_severity[Severity.MINOR] == 0

        # 3. CRITICAL: Consensus tracking must work after replacement
        # Both validators found the same issue, so it's consensus (not unique)
        assert len(aggregate.consensus_findings) == 1
        assert len(aggregate.unique_findings) == 0
        assert aggregate.consensus_ratio == 1.0

        # 4. The consensus finding should be the CRITICAL one
        assert aggregate.consensus_findings[0].severity == Severity.CRITICAL


# =============================================================================
# Format Context Tests
# =============================================================================


class TestFormatEvidenceScoreContext:
    """Tests for format_evidence_score_context function."""

    def test_format_validation_context(self) -> None:
        """Test formatting for validation synthesis context."""
        aggregate = EvidenceScoreAggregate(
            total_score=2.5,
            verdict=Verdict.PASS,
            per_validator_scores={"Validator A": 3.0, "Validator B": 2.0},
            per_validator_verdicts={
                "Validator A": Verdict.PASS,
                "Validator B": Verdict.PASS,
            },
            findings_by_severity={
                Severity.CRITICAL: 1,
                Severity.IMPORTANT: 2,
                Severity.MINOR: 1,
            },
            total_findings=4,
            total_clean_passes=3,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.5,
        )

        output = format_evidence_score_context(aggregate, "validation")

        assert "<!-- PRE-CALCULATED EVIDENCE SCORE" in output
        assert "**Total Score** | 2.5" in output
        assert "**Verdict** | READY" in output  # PASS -> READY for validation
        assert "CRITICAL findings | 1" in output
        assert "IMPORTANT findings | 2" in output
        assert "Consensus ratio | 50%" in output

    def test_format_code_review_context(self) -> None:
        """Test formatting for code review synthesis context."""
        aggregate = EvidenceScoreAggregate(
            total_score=-3.5,
            verdict=Verdict.EXCELLENT,
            per_validator_scores={"Reviewer A": -3.5},
            per_validator_verdicts={"Reviewer A": Verdict.EXCELLENT},
            findings_by_severity={
                Severity.CRITICAL: 0,
                Severity.IMPORTANT: 0,
                Severity.MINOR: 1,
            },
            total_findings=1,
            total_clean_passes=8,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.0,
        )

        output = format_evidence_score_context(aggregate, "code_review")

        assert "**Verdict** | EXEMPLARY" in output  # EXCELLENT -> EXEMPLARY for code review
        assert "CLEAN PASS categories | 8" in output


# =============================================================================
# Exception Tests
# =============================================================================


class TestCacheVersionError:
    """Tests for CacheVersionError exception."""

    def test_missing_version_message(self) -> None:
        """Test error message when version is missing."""
        error = CacheVersionError(found_version=None, required_version=2)
        assert "v2 required" in str(error)
        assert "missing" in str(error).lower()

    def test_old_version_message(self) -> None:
        """Test error message when version is too old."""
        error = CacheVersionError(found_version=1, required_version=2)
        assert "v2 required" in str(error)
        assert "1" in str(error)

    def test_custom_message(self) -> None:
        """Test custom error message."""
        error = CacheVersionError(
            found_version=1,
            required_version=2,
            message="Custom error message",
        )
        assert str(error) == "Custom error message"


class TestCacheFormatError:
    """Tests for CacheFormatError exception."""

    def test_error_message(self) -> None:
        """Test error message content."""
        error = CacheFormatError("Missing required key")
        assert "Missing required key" in str(error)


class TestAllValidatorsFailedError:
    """Tests for AllValidatorsFailedError exception."""

    def test_error_message(self) -> None:
        """Test error message content."""
        error = AllValidatorsFailedError("All validators failed")
        assert "All validators failed" in str(error)
