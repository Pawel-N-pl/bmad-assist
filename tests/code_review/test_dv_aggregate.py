"""Tests for _aggregate_dv_results() in code review orchestrator."""

from pathlib import Path

import pytest

from bmad_assist.code_review.orchestrator import _aggregate_dv_results
from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    DeepVerifyValidationResult,
    DomainConfidence,
    Finding,
    MethodId,
    Severity,
    VerdictDecision,
)


@pytest.fixture
def finding_security():
    """A security finding."""
    return Finding(
        id="F1",
        severity=Severity.CRITICAL,
        title="SQL Injection",
        description="Unsanitized input",
        method_id=MethodId("#201"),
        domain=ArtifactDomain.SECURITY,
        evidence=[],
    )


@pytest.fixture
def finding_api():
    """An API finding."""
    return Finding(
        id="F2",
        severity=Severity.WARNING,
        title="Missing validation",
        description="No input validation",
        method_id=MethodId("#153"),
        domain=ArtifactDomain.API,
        evidence=[],
    )


@pytest.fixture
def dv_result_reject(finding_security):
    """A REJECT DV result."""
    return DeepVerifyValidationResult(
        findings=[finding_security],
        domains_detected=[
            DomainConfidence(domain=ArtifactDomain.SECURITY, confidence=0.9, signals=["auth"]),
        ],
        methods_executed=[MethodId("#201")],
        verdict=VerdictDecision.REJECT,
        score=8.5,
        duration_ms=3000,
        error=None,
    )


@pytest.fixture
def dv_result_accept(finding_api):
    """An ACCEPT DV result."""
    return DeepVerifyValidationResult(
        findings=[finding_api],
        domains_detected=[
            DomainConfidence(domain=ArtifactDomain.API, confidence=0.7, signals=["rest"]),
        ],
        methods_executed=[MethodId("#153")],
        verdict=VerdictDecision.ACCEPT,
        score=2.0,
        duration_ms=2000,
        error=None,
    )


@pytest.fixture
def dv_result_uncertain():
    """An UNCERTAIN DV result with no findings."""
    return DeepVerifyValidationResult(
        findings=[],
        domains_detected=[],
        methods_executed=[MethodId("#100")],
        verdict=VerdictDecision.UNCERTAIN,
        score=5.0,
        duration_ms=1500,
        error=None,
    )


class TestAggregateDvResults:
    """Tests for _aggregate_dv_results helper."""

    def test_multiple_files_aggregated(self, dv_result_reject, dv_result_accept):
        """Multiple file results are combined correctly."""
        batch_result = {
            Path("/src/file0.py"): dv_result_reject,
            Path("/src/file1.py"): dv_result_accept,
        }

        aggregated = _aggregate_dv_results(batch_result)

        assert aggregated is not None
        # Findings from both results combined
        assert len(aggregated.findings) == 2
        # Domains from both
        assert len(aggregated.domains_detected) == 2
        # Methods merged (unique set)
        method_ids = {str(m) for m in aggregated.methods_executed}
        assert "#201" in method_ids
        assert "#153" in method_ids
        # Duration summed
        assert aggregated.duration_ms == 5000
        # Worst verdict wins (REJECT > ACCEPT)
        assert aggregated.verdict == VerdictDecision.REJECT
        # Min score
        assert aggregated.score == 2.0

    def test_empty_results(self):
        """Empty results dict → returns None."""
        aggregated = _aggregate_dv_results({})

        assert aggregated is None

    def test_worst_verdict_reject_wins(
        self, dv_result_reject, dv_result_accept, dv_result_uncertain
    ):
        """REJECT beats UNCERTAIN and ACCEPT."""
        batch_result = {
            Path("/src/file0.py"): dv_result_accept,
            Path("/src/file1.py"): dv_result_uncertain,
            Path("/src/file2.py"): dv_result_reject,
        }

        aggregated = _aggregate_dv_results(batch_result)

        assert aggregated is not None
        assert aggregated.verdict == VerdictDecision.REJECT

    def test_uncertain_beats_accept(self, dv_result_accept, dv_result_uncertain):
        """UNCERTAIN beats ACCEPT."""
        batch_result = {
            Path("/src/file0.py"): dv_result_accept,
            Path("/src/file1.py"): dv_result_uncertain,
        }

        aggregated = _aggregate_dv_results(batch_result)

        assert aggregated is not None
        assert aggregated.verdict == VerdictDecision.UNCERTAIN

    def test_single_result(self, dv_result_accept):
        """Single result passes through."""
        batch_result = {
            Path("/src/file0.py"): dv_result_accept,
        }

        aggregated = _aggregate_dv_results(batch_result)

        assert aggregated is not None
        assert aggregated.verdict == VerdictDecision.ACCEPT
        assert len(aggregated.findings) == 1
        assert aggregated.score == 2.0
