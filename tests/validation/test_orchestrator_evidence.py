"""Tests for Evidence Score integration with validation orchestrator.

Story: Evidence Score TIER 2 Python Calculator
Task 17: Validation orchestrator integration tests

Tests cover:
- parse_evidence_findings integration with validator output
- aggregate_evidence_scores calculation with multiple validators
- Evidence Score data persistence in cache v2 format
- format_evidence_score_context for synthesis prompt
"""

import json
from pathlib import Path

import pytest

from bmad_assist.validation.anonymizer import AnonymizedValidation
from bmad_assist.validation.evidence_score import (
    EvidenceFinding,
    EvidenceScoreAggregate,
    EvidenceScoreReport,
    Severity,
    Verdict,
    aggregate_evidence_scores,
    format_evidence_score_context,
    parse_evidence_findings,
)
from bmad_assist.validation.orchestrator import (
    load_validations_for_synthesis,
    save_validations_for_synthesis,
)


class TestParseEvidenceFindingsIntegration:
    """Integration tests for parsing Evidence Score from validator output."""

    def test_parses_full_validation_report(self) -> None:
        """Parse Evidence Score from a complete validation report."""
        content = """# Story Context Validation Report

## Executive Summary

Story validated against INVEST criteria.

## Evidence Score Summary

| Severity | Description | Source | Score |
|----------|-------------|--------|-------|
| 🔴 CRITICAL | Missing acceptance criteria for error handling | Story:AC3 | +3 |
| 🔴 CRITICAL | Scope boundary unclear between modules | Story:AC1 | +3 |
| 🟠 IMPORTANT | No performance requirements specified | Story:NFR | +1 |
| 🟡 MINOR | Typo in task description | Story:Tasks | +0.3 |

| 🟢 CLEAN PASS | 4 |

### Evidence Score: 5.3

| Score | Verdict |
|-------|---------|
| **5.3** | **MAJOR REWORK** |

## Detailed Findings

### AC1: Data Processing
🟢 CLEAN PASS - Well-defined acceptance criteria
"""
        report = parse_evidence_findings(content, "Validator A")

        assert report is not None
        assert len(report.findings) == 4
        assert report.clean_passes == 4
        # 3 + 3 + 1 + 0.3 + (4 * -0.5) = 7.3 - 2.0 = 5.3
        assert report.total_score == pytest.approx(5.3, abs=0.01)
        assert report.verdict == Verdict.MAJOR_REWORK

    def test_parses_clean_validation_report(self) -> None:
        """Parse Evidence Score from a clean validation report with no issues."""
        content = """# Story Context Validation Report

## Evidence Score Summary

No issues found during validation.

| Severity | Description | Source | Score |
|----------|-------------|--------|-------|
| 🟢 CLEAN PASS | 8 |

### Evidence Score: -4.0

| Score | Verdict |
|-------|---------|
| **-4.0** | **EXCELLENT** |
"""
        report = parse_evidence_findings(content, "Validator B")

        assert report is not None
        assert len(report.findings) == 0
        assert report.clean_passes == 8
        # 8 * -0.5 = -4.0
        assert report.total_score == -4.0
        assert report.verdict == Verdict.EXCELLENT

    def test_returns_none_for_non_evidence_report(self) -> None:
        """Returns None when content has no Evidence Score format."""
        content = """# Story Validation

This is a legacy format validation report.

## Issues Found

- Issue 1: Something wrong
- Issue 2: Another problem

Final Score: 6/10
"""
        report = parse_evidence_findings(content, "Validator C")
        assert report is None


class TestAggregateEvidenceScoresIntegration:
    """Integration tests for aggregating Evidence Scores across validators."""

    def test_aggregates_multiple_validators_with_consensus(self) -> None:
        """Aggregate scores from multiple validators finding similar issues."""
        # Validator A: Critical issue + 2 clean passes
        # Note: Use very similar descriptions to ensure deduplication (ratio >= 0.85)
        findings_a = (
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Missing input validation",
                source="auth.py:45",
                validator_id="Validator A",
            ),
        )
        report_a = EvidenceScoreReport(
            validator_id="Validator A",
            findings=findings_a,
            clean_passes=2,
            total_score=2.0,  # 3.0 - 1.0
            verdict=Verdict.PASS,
        )

        # Validator B: Same critical issue (identical wording) + 1 clean pass
        findings_b = (
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Missing input validation",
                source="auth.py:45",
                validator_id="Validator B",
            ),
        )
        report_b = EvidenceScoreReport(
            validator_id="Validator B",
            findings=findings_b,
            clean_passes=1,
            total_score=2.5,  # 3.0 - 0.5
            verdict=Verdict.PASS,
        )

        aggregate = aggregate_evidence_scores([report_a, report_b])

        assert aggregate.total_score == pytest.approx(2.2, abs=0.1)  # Average
        assert aggregate.verdict == Verdict.PASS
        assert aggregate.total_findings == 1  # Deduplicated
        assert len(aggregate.consensus_findings) == 1  # Both agree
        assert aggregate.consensus_ratio == 1.0

    def test_aggregates_with_unique_findings(self) -> None:
        """Aggregate scores when validators find different issues."""
        findings_a = (
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="SQL injection vulnerability",
                source="db.py:100",
                validator_id="Validator A",
            ),
        )
        report_a = EvidenceScoreReport(
            validator_id="Validator A",
            findings=findings_a,
            clean_passes=3,
            total_score=1.5,
            verdict=Verdict.PASS,
        )

        findings_b = (
            EvidenceFinding(
                severity=Severity.IMPORTANT,
                score=1.0,
                description="Missing rate limiting",
                source="api.py:50",
                validator_id="Validator B",
            ),
        )
        report_b = EvidenceScoreReport(
            validator_id="Validator B",
            findings=findings_b,
            clean_passes=4,
            total_score=-1.0,
            verdict=Verdict.PASS,
        )

        aggregate = aggregate_evidence_scores([report_a, report_b])

        assert aggregate.total_findings == 2  # Both unique
        assert len(aggregate.unique_findings) == 2
        assert len(aggregate.consensus_findings) == 0
        assert aggregate.consensus_ratio == 0.0


class TestEvidenceScoreCachePersistence:
    """Integration tests for Evidence Score in cache v2 format."""

    def _make_mock_evidence_aggregate(self) -> EvidenceScoreAggregate:
        """Create a mock EvidenceScoreAggregate for testing."""
        return EvidenceScoreAggregate(
            total_score=3.5,
            verdict=Verdict.PASS,
            per_validator_scores={"Validator A": 4.0, "Validator B": 3.0},
            per_validator_verdicts={
                "Validator A": Verdict.MAJOR_REWORK,
                "Validator B": Verdict.PASS,
            },
            findings_by_severity={
                Severity.CRITICAL: 2,
                Severity.IMPORTANT: 1,
                Severity.MINOR: 0,
            },
            total_findings=3,
            total_clean_passes=5,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.67,
        )

    def test_evidence_score_persisted_in_cache(self, tmp_path: Path) -> None:
        """Evidence Score aggregate is saved in cache v2 format."""
        from bmad_assist.core.paths import init_paths

        init_paths(tmp_path)

        validations = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="# Validation Report\n\nEvidence Score: 4.0",
                original_ref="ref-001",
            ),
        ]
        evidence = self._make_mock_evidence_aggregate()

        session_id = save_validations_for_synthesis(
            anonymized=validations,
            project_root=tmp_path,
            evidence_aggregate=evidence,
        )

        # Read cache directly
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_file = cache_dir / f"validations-{session_id}.json"
        cache_data = json.loads(cache_file.read_text())

        assert cache_data["cache_version"] == 3
        assert "evidence_score" in cache_data
        assert cache_data["evidence_score"]["total_score"] == 3.5
        assert cache_data["evidence_score"]["verdict"] == "PASS"
        assert cache_data["evidence_score"]["consensus_ratio"] == 0.67

    def test_evidence_score_loaded_from_cache(self, tmp_path: Path) -> None:
        """Evidence Score is loaded from cache v2 format."""
        from bmad_assist.core.paths import init_paths

        init_paths(tmp_path)

        validations = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="# Report",
                original_ref="ref-001",
            ),
        ]
        evidence = self._make_mock_evidence_aggregate()

        session_id = save_validations_for_synthesis(
            anonymized=validations,
            project_root=tmp_path,
            evidence_aggregate=evidence,
        )

        _, _, evidence_data, _ = load_validations_for_synthesis(
            session_id, tmp_path
        )

        assert evidence_data is not None
        assert evidence_data["total_score"] == 3.5
        assert evidence_data["verdict"] == "PASS"
        # Cache format uses per_validator with nested score/verdict
        assert evidence_data["per_validator"]["Validator A"]["score"] == 4.0
        assert evidence_data["per_validator"]["Validator B"]["score"] == 3.0

    def test_v2_cache_missing_evidence_score_raises_format_error(
        self, tmp_path: Path
    ) -> None:
        """load_validations_for_synthesis raises CacheFormatError when v2 cache missing evidence_score."""
        from bmad_assist.core.paths import init_paths

        init_paths(tmp_path)

        # Manually create a v2 cache file missing the evidence_score key
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        session_id = "test-v2-malformed-session"
        cache_file = cache_dir / f"validations-{session_id}.json"

        malformed_v2_data = {
            "cache_version": 2,  # Claims to be v2
            "session_id": session_id,
            "timestamp": "2026-01-22T10:00:00Z",
            "validations": [
                {"validator_id": "Validator A", "content": "Test", "original_ref": "ref-001"}
            ],
            # Missing evidence_score key - should still load with warning
        }
        cache_file.write_text(json.dumps(malformed_v2_data))

        # Should succeed with None evidence_score (backward compatible)
        validations, failed_validators, evidence_score, _ = load_validations_for_synthesis(
            session_id, tmp_path
        )

        assert len(validations) == 1
        assert validations[0].validator_id == "Validator A"
        assert failed_validators == []
        assert evidence_score is None  # Missing evidence_score returns None


class TestFormatEvidenceScoreContextIntegration:
    """Integration tests for formatting Evidence Score context for synthesis."""

    def test_format_validation_context(self) -> None:
        """Format Evidence Score context for validation synthesis."""
        aggregate = EvidenceScoreAggregate(
            total_score=5.5,
            verdict=Verdict.MAJOR_REWORK,
            per_validator_scores={
                "Validator A": 6.0,
                "Validator B": 5.0,
            },
            per_validator_verdicts={
                "Validator A": Verdict.REJECT,
                "Validator B": Verdict.MAJOR_REWORK,
            },
            findings_by_severity={
                Severity.CRITICAL: 3,
                Severity.IMPORTANT: 2,
                Severity.MINOR: 1,
            },
            total_findings=6,
            total_clean_passes=2,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.5,
        )

        context = format_evidence_score_context(aggregate, "validation")

        assert "<!-- PRE-CALCULATED EVIDENCE SCORE" in context
        assert "**Total Score** | 5.5" in context
        assert "**Verdict** | MAJOR REWORK" in context
        assert "CRITICAL findings | 3" in context
        assert "Consensus ratio | 50%" in context

    def test_format_code_review_context(self) -> None:
        """Format Evidence Score context for code review synthesis."""
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

        context = format_evidence_score_context(aggregate, "code_review")

        # Code review uses different display names
        assert "**Verdict** | EXEMPLARY" in context
        assert "CLEAN PASS categories | 8" in context


class TestEndToEndEvidenceScoreFlow:
    """End-to-end tests for Evidence Score calculation flow."""

    def test_full_flow_from_content_to_synthesis_context(self) -> None:
        """Test complete flow from validator content to synthesis context."""
        # Step 1: Parse validator outputs
        # Note: Use identical critical finding descriptions to ensure consensus detection
        validator_a_content = """
## Evidence Score Summary

| Severity | Description | Source | Score |
|----------|-------------|--------|-------|
| 🔴 CRITICAL | SQL injection vulnerability | auth.py:50 | +3 |
| 🟠 IMPORTANT | Missing error handling | api.py:100 | +1 |

| 🟢 CLEAN PASS | 3 |

### Evidence Score: 2.5
"""
        validator_b_content = """
## Evidence Score Summary

| Severity | Description | Source | Score |
|----------|-------------|--------|-------|
| 🔴 CRITICAL | SQL injection vulnerability | auth.py:50 | +3 |
| 🟡 MINOR | Inconsistent naming | utils.py:20 | +0.3 |

| 🟢 CLEAN PASS | 5 |

### Evidence Score: 0.8
"""
        report_a = parse_evidence_findings(validator_a_content, "Validator A")
        report_b = parse_evidence_findings(validator_b_content, "Validator B")

        assert report_a is not None
        assert report_b is not None

        # Step 2: Aggregate scores
        aggregate = aggregate_evidence_scores([report_a, report_b])

        # Verify aggregation
        assert aggregate.total_score == pytest.approx(1.65, abs=0.1)  # Average
        assert aggregate.verdict == Verdict.PASS
        # 3 unique findings total: SQL injection (consensus), error handling (unique), naming (unique)
        assert aggregate.total_findings == 3
        assert len(aggregate.consensus_findings) == 1  # SQL injection found by both

        # Step 3: Format for synthesis
        context = format_evidence_score_context(aggregate, "validation")

        # Verify context contains key information
        assert "PRE-CALCULATED EVIDENCE SCORE" in context
        assert "READY" in context  # PASS verdict -> READY for validation
        assert "Consensus ratio" in context

    def test_full_flow_with_cache_roundtrip(self, tmp_path: Path) -> None:
        """Test Evidence Score persists through cache save/load cycle."""
        from bmad_assist.core.paths import init_paths

        init_paths(tmp_path)

        # Create test data
        findings = (
            EvidenceFinding(
                severity=Severity.CRITICAL,
                score=3.0,
                description="Test issue",
                source="test.py:1",
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

        # Save to cache
        validations = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Test content",
                original_ref="ref-001",
            ),
        ]
        session_id = save_validations_for_synthesis(
            anonymized=validations,
            project_root=tmp_path,
            evidence_aggregate=aggregate,
        )

        # Load from cache
        _, _, evidence_data, _ = load_validations_for_synthesis(session_id, tmp_path)

        # Verify data survived roundtrip
        assert evidence_data is not None
        assert evidence_data["total_score"] == 2.0
        assert evidence_data["verdict"] == "PASS"
        assert evidence_data["total_findings"] == 1
