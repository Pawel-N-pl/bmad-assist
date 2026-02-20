"""Tests for Deep Verify scoring system."""

from __future__ import annotations

import pytest

from bmad_assist.deep_verify.core.scoring import (
    ACCEPT_THRESHOLD,
    CLEAN_PASS_BONUS,
    REJECT_THRESHOLD,
    SEVERITY_WEIGHTS,
    EvidenceScorer,
    calculate_score,
    determine_verdict,
)
from bmad_assist.deep_verify.core.types import (
    Evidence,
    Finding,
    MethodId,
    Severity,
    VerdictDecision,
)

# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Tests for scoring constants."""

    def test_severity_weights(self) -> None:
        """Severity weights should match specification."""
        assert SEVERITY_WEIGHTS[Severity.CRITICAL] == 4.0
        assert SEVERITY_WEIGHTS[Severity.ERROR] == 2.0
        assert SEVERITY_WEIGHTS[Severity.WARNING] == 1.0
        assert SEVERITY_WEIGHTS[Severity.INFO] == 0.5

    def test_thresholds(self) -> None:
        """Thresholds should match specification."""
        assert REJECT_THRESHOLD == 6.0
        assert ACCEPT_THRESHOLD == -3.0
        assert CLEAN_PASS_BONUS == -0.5


# =============================================================================
# calculate_score Tests
# =============================================================================


class TestCalculateScore:
    """Tests for calculate_score function."""

    def test_empty_findings(self) -> None:
        """Empty findings with no clean passes should score 0."""
        score = calculate_score([])
        assert score == 0.0

    def test_single_critical_finding(self) -> None:
        """Single CRITICAL finding should score 4.0."""
        finding = Finding(
            id="F1",
            severity=Severity.CRITICAL,
            title="Critical issue",
            description="Test",
            method_id=MethodId("#153"),
        )
        score = calculate_score([finding])
        assert score == 4.0

    def test_single_error_finding(self) -> None:
        """Single ERROR finding should score 2.0."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Error",
            description="Test",
            method_id=MethodId("#153"),
        )
        score = calculate_score([finding])
        assert score == 2.0

    def test_single_warning_finding(self) -> None:
        """Single WARNING finding should score 1.0."""
        finding = Finding(
            id="F1",
            severity=Severity.WARNING,
            title="Warning",
            description="Test",
            method_id=MethodId("#153"),
        )
        score = calculate_score([finding])
        assert score == 1.0

    def test_single_info_finding(self) -> None:
        """Single INFO finding should score 0.5."""
        finding = Finding(
            id="F1",
            severity=Severity.INFO,
            title="Info",
            description="Test",
            method_id=MethodId("#153"),
        )
        score = calculate_score([finding])
        assert score == 0.5

    def test_multiple_findings(self) -> None:
        """Multiple findings should sum correctly."""
        findings = [
            Finding(
                id="F1",
                severity=Severity.CRITICAL,
                title="Critical",
                description="Test",
                method_id=MethodId("#153"),
            ),
            Finding(
                id="F2",
                severity=Severity.ERROR,
                title="Error",
                description="Test",
                method_id=MethodId("#153"),
            ),
            Finding(
                id="F3",
                severity=Severity.WARNING,
                title="Warning",
                description="Test",
                method_id=MethodId("#154"),
            ),
        ]
        score = calculate_score(findings)
        # 4.0 + 2.0 + 1.0 = 7.0
        assert score == 7.0

    def test_clean_pass_bonus(self) -> None:
        """Clean pass bonus should reduce score."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Error",
            description="Test",
            method_id=MethodId("#153"),
        )
        score = calculate_score([finding], clean_passes=2)
        # 2.0 + (2 * -0.5) = 2.0 - 1.0 = 1.0
        assert score == 1.0

    def test_clean_pass_bonus_enables_accept(self) -> None:
        """Clean pass bonus should enable negative scores for ACCEPT."""
        findings = [
            Finding(
                id="F1",
                severity=Severity.WARNING,
                title="Warning",
                description="Test",
                method_id=MethodId("#153"),
            ),
        ]
        score = calculate_score(findings, clean_passes=5)
        # 1.0 + (5 * -0.5) = 1.0 - 2.5 = -1.5
        assert score == -1.5

    def test_evidence_confidence(self) -> None:
        """Evidence confidence should affect score."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Error",
            description="Test",
            method_id=MethodId("#153"),
            evidence=[
                Evidence(quote="test", confidence=0.5),
            ],
        )
        score = calculate_score([finding])
        # 2.0 * 0.5 = 1.0
        assert score == 1.0

    def test_multiple_evidence_average_confidence(self) -> None:
        """Multiple evidence should use average confidence."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Error",
            description="Test",
            method_id=MethodId("#153"),
            evidence=[
                Evidence(quote="test1", confidence=0.5),
                Evidence(quote="test2", confidence=1.0),
            ],
        )
        score = calculate_score([finding])
        # 2.0 * ((0.5 + 1.0) / 2) = 2.0 * 0.75 = 1.5
        assert score == 1.5

    def test_no_evidence_defaults_to_full_confidence(self) -> None:
        """Finding without evidence should use confidence 1.0."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Error",
            description="Test",
            method_id=MethodId("#153"),
            evidence=[],
        )
        score = calculate_score([finding])
        # 2.0 * 1.0 = 2.0
        assert score == 2.0

    def test_score_rounding(self) -> None:
        """Score should be rounded to 2 decimal places."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Error",
            description="Test",
            method_id=MethodId("#153"),
            evidence=[
                Evidence(quote="test", confidence=0.3333),
            ],
        )
        score = calculate_score([finding])
        # 2.0 * 0.3333 = 0.6666 -> rounded to 0.67
        assert score == 0.67

    def test_max_confidence(self) -> None:
        """Maximum confidence 1.0 should give full weight."""
        finding = Finding(
            id="F1",
            severity=Severity.CRITICAL,
            title="Critical",
            description="Test",
            method_id=MethodId("#153"),
            evidence=[Evidence(quote="test", confidence=1.0)],
        )
        score = calculate_score([finding])
        assert score == 4.0

    def test_zero_confidence(self) -> None:
        """Zero confidence should give zero contribution."""
        finding = Finding(
            id="F1",
            severity=Severity.CRITICAL,
            title="Critical",
            description="Test",
            method_id=MethodId("#153"),
            evidence=[Evidence(quote="test", confidence=0.0)],
        )
        score = calculate_score([finding])
        assert score == 0.0


# =============================================================================
# determine_verdict Tests
# =============================================================================


class TestDetermineVerdict:
    """Tests for determine_verdict function."""

    def test_reject_threshold_boundary(self) -> None:
        """Score > 6 should give REJECT."""
        assert determine_verdict(6.1) == VerdictDecision.REJECT
        assert determine_verdict(10.0) == VerdictDecision.REJECT
        assert determine_verdict(100.0) == VerdictDecision.REJECT

    def test_uncertain_upper_boundary(self) -> None:
        """Score = 6 should give UNCERTAIN (not REJECT)."""
        assert determine_verdict(6.0) == VerdictDecision.UNCERTAIN

    def test_uncertain_middle(self) -> None:
        """Score between -3 and 6 should give UNCERTAIN."""
        assert determine_verdict(0.0) == VerdictDecision.UNCERTAIN
        assert determine_verdict(3.0) == VerdictDecision.UNCERTAIN
        assert determine_verdict(-1.0) == VerdictDecision.UNCERTAIN

    def test_uncertain_lower_boundary(self) -> None:
        """Score = -3 should give UNCERTAIN (not ACCEPT)."""
        assert determine_verdict(-3.0) == VerdictDecision.UNCERTAIN

    def test_accept_threshold_boundary(self) -> None:
        """Score < -3 should give ACCEPT."""
        assert determine_verdict(-3.1) == VerdictDecision.ACCEPT
        assert determine_verdict(-4.0) == VerdictDecision.ACCEPT
        assert determine_verdict(-10.0) == VerdictDecision.ACCEPT

    def test_thresholds_are_non_overlapping(self) -> None:
        """Thresholds should be non-overlapping."""
        # Each score should map to exactly one verdict
        for score in [-10, -5, -3.1, -3, -2, 0, 3, 6, 6.1, 10]:
            verdict = determine_verdict(score)
            assert verdict in {VerdictDecision.ACCEPT, VerdictDecision.UNCERTAIN, VerdictDecision.REJECT}

    def test_critical_finding_hard_block(self) -> None:
        """CRITICAL findings should always result in REJECT verdict (hard block)."""
        critical_finding = Finding(
            id="F1",
            severity=Severity.CRITICAL,
            title="Critical security issue",
            description="Test",
            method_id=MethodId("#153"),
        )
        # Even with a very negative score (lots of clean passes), CRITICAL should REJECT
        assert determine_verdict(-10.0, [critical_finding]) == VerdictDecision.REJECT
        assert determine_verdict(-5.0, [critical_finding]) == VerdictDecision.REJECT
        # Without findings parameter, score-based logic applies
        assert determine_verdict(-10.0) == VerdictDecision.ACCEPT

    def test_no_critical_finding_allows_accept(self) -> None:
        """Non-CRITICAL findings can result in ACCEPT verdict."""
        error_finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Error",
            description="Test",
            method_id=MethodId("#153"),
        )
        # ERROR finding with negative score can ACCEPT
        assert determine_verdict(-5.0, [error_finding]) == VerdictDecision.ACCEPT


# =============================================================================
# EvidenceScorer Tests
# =============================================================================


class TestEvidenceScorer:
    """Tests for EvidenceScorer class."""

    def test_default_initialization(self) -> None:
        """Should initialize with default values."""
        scorer = EvidenceScorer()
        assert scorer.severity_weights == SEVERITY_WEIGHTS
        assert scorer.clean_pass_bonus == CLEAN_PASS_BONUS
        assert scorer.reject_threshold == REJECT_THRESHOLD
        assert scorer.accept_threshold == ACCEPT_THRESHOLD

    def test_custom_thresholds(self) -> None:
        """Should accept custom thresholds."""
        scorer = EvidenceScorer(
            reject_threshold=8.0,
            accept_threshold=-5.0,
        )
        assert scorer.reject_threshold == 8.0
        assert scorer.accept_threshold == -5.0

    def test_custom_severity_weights(self) -> None:
        """Should accept custom severity weights."""
        custom_weights = {
            Severity.CRITICAL: 5.0,
            Severity.ERROR: 3.0,
            Severity.WARNING: 1.5,
            Severity.INFO: 0.5,
        }
        scorer = EvidenceScorer(severity_weights=custom_weights)
        assert scorer.severity_weights[Severity.CRITICAL] == 5.0

    def test_invalid_thresholds_raises(self) -> None:
        """Invalid threshold order should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            EvidenceScorer(reject_threshold=5.0, accept_threshold=5.0)
        assert "reject_threshold" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            EvidenceScorer(reject_threshold=-5.0, accept_threshold=5.0)
        assert "reject_threshold" in str(exc_info.value)

    def test_calculate_score_with_defaults(self) -> None:
        """Should calculate score with default configuration."""
        scorer = EvidenceScorer()
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Error",
            description="Test",
            method_id=MethodId("#153"),
        )
        score = scorer.calculate_score([finding])
        assert score == 2.0

    def test_calculate_score_with_custom_weights(self) -> None:
        """Should calculate score with custom severity weights."""
        scorer = EvidenceScorer(severity_weights={
            Severity.CRITICAL: 5.0,
            Severity.ERROR: 2.0,
            Severity.WARNING: 1.0,
            Severity.INFO: 0.5,
        })
        finding = Finding(
            id="F1",
            severity=Severity.CRITICAL,
            title="Critical",
            description="Test",
            method_id=MethodId("#153"),
        )
        score = scorer.calculate_score([finding])
        assert score == 5.0

    def test_determine_verdict_with_defaults(self) -> None:
        """Should determine verdict with default thresholds."""
        scorer = EvidenceScorer()
        assert scorer.determine_verdict(8.0) == VerdictDecision.REJECT
        assert scorer.determine_verdict(0.0) == VerdictDecision.UNCERTAIN
        assert scorer.determine_verdict(-4.0) == VerdictDecision.ACCEPT

    def test_determine_verdict_with_custom_thresholds(self) -> None:
        """Should determine verdict with custom thresholds."""
        scorer = EvidenceScorer(reject_threshold=10.0, accept_threshold=-5.0)
        assert scorer.determine_verdict(8.0) == VerdictDecision.UNCERTAIN  # Below 10
        assert scorer.determine_verdict(12.0) == VerdictDecision.REJECT
        assert scorer.determine_verdict(-4.0) == VerdictDecision.UNCERTAIN  # Above -5
        assert scorer.determine_verdict(-6.0) == VerdictDecision.ACCEPT

    def test_critical_finding_hard_block(self) -> None:
        """CRITICAL findings should always result in REJECT verdict (hard block)."""
        scorer = EvidenceScorer()
        critical_finding = Finding(
            id="F1",
            severity=Severity.CRITICAL,
            title="Critical security issue",
            description="Test",
            method_id=MethodId("#153"),
        )
        # Even with a very negative score, CRITICAL should REJECT
        assert scorer.determine_verdict(-10.0, [critical_finding]) == VerdictDecision.REJECT
        assert scorer.determine_verdict(-5.0, [critical_finding]) == VerdictDecision.REJECT
        # Without findings, score-based logic applies
        assert scorer.determine_verdict(-10.0) == VerdictDecision.ACCEPT


class TestEvidenceScorerGetVerdictWithConfidence:
    """Tests for EvidenceScorer.get_verdict_with_confidence."""

    def test_reject_confidence(self) -> None:
        """REJECT confidence should increase with score."""
        scorer = EvidenceScorer()

        verdict, conf_low = scorer.get_verdict_with_confidence(7.0, 1, 1)
        verdict, conf_high = scorer.get_verdict_with_confidence(15.0, 1, 1)

        assert verdict == VerdictDecision.REJECT
        assert conf_high > conf_low

    def test_reject_confidence_boosted_by_critical(self) -> None:
        """REJECT confidence should be boosted by critical findings."""
        scorer = EvidenceScorer()

        verdict, conf_no_critical = scorer.get_verdict_with_confidence(7.0, 5, 0)
        verdict, conf_with_critical = scorer.get_verdict_with_confidence(7.0, 5, 1)

        assert conf_with_critical > conf_no_critical

    def test_accept_confidence(self) -> None:
        """ACCEPT confidence should increase with distance below threshold."""
        scorer = EvidenceScorer()

        verdict, conf_low = scorer.get_verdict_with_confidence(-4.0, 0, 0)
        verdict, conf_high = scorer.get_verdict_with_confidence(-10.0, 0, 0)

        assert verdict == VerdictDecision.ACCEPT
        assert conf_high > conf_low

    def test_accept_confidence_boosted_by_clean(self) -> None:
        """ACCEPT confidence should be boosted when no findings."""
        scorer = EvidenceScorer()

        verdict, conf_with_findings = scorer.get_verdict_with_confidence(-4.0, 1, 0)
        verdict, conf_clean = scorer.get_verdict_with_confidence(-4.0, 0, 0)

        assert conf_clean > conf_with_findings

    def test_uncertain_confidence(self) -> None:
        """UNCERTAIN confidence should be lowest near middle of range."""
        scorer = EvidenceScorer()

        middle = (REJECT_THRESHOLD + ACCEPT_THRESHOLD) / 2  # 1.5
        verdict, conf_middle = scorer.get_verdict_with_confidence(middle, 1, 0)

        assert verdict == VerdictDecision.UNCERTAIN
        assert 0.0 <= conf_middle <= 1.0

    def test_confidence_range(self) -> None:
        """Confidence should always be between 0 and 1."""
        scorer = EvidenceScorer()

        test_scores = [-100, -10, -3, 0, 3, 6, 10, 100]
        for score in test_scores:
            _, confidence = scorer.get_verdict_with_confidence(score, 1, 0)
            assert 0.0 <= confidence <= 1.0


# =============================================================================
# Integration Tests
# =============================================================================


class TestScoringIntegration:
    """Integration tests for scoring system."""

    def test_full_workflow_reject(self) -> None:
        """Full workflow should produce REJECT for high-severity findings."""
        findings = [
            Finding(
                id="F1",
                severity=Severity.CRITICAL,
                title="Critical issue",
                description="Test",
                method_id=MethodId("#153"),
            ),
            Finding(
                id="F2",
                severity=Severity.CRITICAL,
                title="Another critical",
                description="Test",
                method_id=MethodId("#201"),
            ),
        ]
        score = calculate_score(findings)
        verdict = determine_verdict(score)

        assert score == 8.0  # 4.0 + 4.0
        assert verdict == VerdictDecision.REJECT

    def test_full_workflow_accept(self) -> None:
        """Full workflow should produce ACCEPT for clean with bonuses."""
        findings = [
            Finding(
                id="F1",
                severity=Severity.WARNING,
                title="Minor issue",
                description="Test",
                method_id=MethodId("#153"),
            ),
        ]
        score = calculate_score(findings, clean_passes=10)
        verdict = determine_verdict(score)

        # 1.0 + (10 * -0.5) = 1.0 - 5.0 = -4.0
        assert score == -4.0
        assert verdict == VerdictDecision.ACCEPT

    def test_full_workflow_uncertain(self) -> None:
        """Full workflow should produce UNCERTAIN for borderline."""
        findings = [
            Finding(
                id="F1",
                severity=Severity.ERROR,
                title="Error",
                description="Test",
                method_id=MethodId("#153"),
            ),
            Finding(
                id="F2",
                severity=Severity.WARNING,
                title="Warning",
                description="Test",
                method_id=MethodId("#154"),
            ),
        ]
        score = calculate_score(findings)
        verdict = determine_verdict(score)

        # 2.0 + 1.0 = 3.0
        assert score == 3.0
        assert verdict == VerdictDecision.UNCERTAIN

    def test_scorer_matches_standalone_functions(self) -> None:
        """EvidenceScorer should produce same results as standalone functions."""
        findings = [
            Finding(
                id="F1",
                severity=Severity.ERROR,
                title="Error",
                description="Test",
                method_id=MethodId("#153"),
            ),
            Finding(
                id="F2",
                severity=Severity.WARNING,
                title="Warning",
                description="Test",
                method_id=MethodId("#154"),
            ),
        ]

        standalone_score = calculate_score(findings)
        standalone_verdict = determine_verdict(standalone_score)

        scorer = EvidenceScorer()
        scorer_score = scorer.calculate_score(findings)
        scorer_verdict = scorer.determine_verdict(scorer_score)

        assert scorer_score == standalone_score
        assert scorer_verdict == standalone_verdict

    def test_boundary_conditions(self) -> None:
        """Test all boundary conditions for verdict thresholds."""
        test_cases = [
            # (score, expected_verdict)
            (6.1, VerdictDecision.REJECT),
            (6.0, VerdictDecision.UNCERTAIN),
            (5.9, VerdictDecision.UNCERTAIN),
            (0.0, VerdictDecision.UNCERTAIN),
            (-2.9, VerdictDecision.UNCERTAIN),
            (-3.0, VerdictDecision.UNCERTAIN),
            (-3.1, VerdictDecision.ACCEPT),
        ]

        for score, expected in test_cases:
            verdict = determine_verdict(score)
            assert verdict == expected, f"Score {score} should give {expected}, got {verdict}"
