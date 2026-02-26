"""Golden test suite for Deep Verify.

These tests verify exact expected output for select artifacts.
Golden tests run with standard pytest and fail if output doesn't match exactly.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from bmad_assist.deep_verify.core.engine import DeepVerifyEngine
from bmad_assist.deep_verify.core.types import VerdictDecision
from bmad_assist.deep_verify.metrics.corpus_loader import (
    CorpusLoader,
    GoldenCase,
    GoldenTolerance,
)

# Mark all tests in this module as slow (real LLM calls, 20-27s each)
pytestmark = pytest.mark.slow


# Load all golden cases
def load_golden_cases() -> list[GoldenCase]:
    """Load all golden test cases from corpus."""
    loader = CorpusLoader()
    return loader.load_all_golden_cases()


def assert_verdict_matches(actual, expected: GoldenCase) -> None:
    """Assert that actual verdict matches expected within tolerance.

    Args:
        actual: Actual verdict from verification.
        expected: Expected golden case.

    Raises:
        AssertionError: If verdict doesn't match within tolerance.

    """
    tolerance: GoldenTolerance = expected.tolerance

    # Check decision matches
    assert actual.decision == expected.expected_verdict.decision, (
        f"Decision mismatch: {actual.decision} != {expected.expected_verdict.decision}"
    )

    # Check score within tolerance
    assert math.isclose(
        actual.score,
        expected.expected_verdict.score,
        abs_tol=tolerance.score,
    ), (
        f"Score mismatch: {actual.score} != {expected.expected_verdict.score} "
        f"(tolerance: ±{tolerance.score})"
    )

    # Check number of findings
    assert len(actual.findings) == len(expected.expected_verdict.findings), (
        f"Finding count mismatch: {len(actual.findings)} != {len(expected.expected_verdict.findings)}"
    )

    # Check domains detected
    expected_domains = {d.domain for d in expected.expected_verdict.domains_detected}
    actual_domains = {d.domain for d in actual.domains_detected}
    assert expected_domains == actual_domains, (
        f"Domain mismatch: {actual_domains} != {expected_domains}"
    )

    # Check confidence within tolerance for each domain
    for expected_dc in expected.expected_verdict.domains_detected:
        matching = [d for d in actual.domains_detected if d.domain == expected_dc.domain]
        if matching:
            actual_dc = matching[0]
            assert math.isclose(
                actual_dc.confidence,
                expected_dc.confidence,
                abs_tol=tolerance.confidence,
            ), (
                f"Domain confidence mismatch for {expected_dc.domain}: "
                f"{actual_dc.confidence} != {expected_dc.confidence} "
                f"(tolerance: ±{tolerance.confidence})"
            )


# Load golden cases at module level for parametrize
golden_cases = load_golden_cases()


@pytest.mark.asyncio
@pytest.mark.parametrize("golden_case", golden_cases, ids=lambda c: c.artifact_id)
async def test_golden_verdict(golden_case: GoldenCase) -> None:
    """Test that verification produces expected verdict for golden case.

    Args:
        golden_case: Golden test case with expected output.

    """
    # Load the artifact content
    loader = CorpusLoader()
    label = loader.load_label(
        loader.corpus_path / "labels" / f"{golden_case.artifact_id}.yaml"
    )
    content = loader.load_artifact_content(label)

    # Run verification
    project_root = Path(".")
    engine = DeepVerifyEngine(project_root=project_root)
    verdict = await engine.verify(content)

    # Assert verdict matches expected
    assert_verdict_matches(verdict, golden_case)


@pytest.mark.asyncio
async def test_golden_verdict_reject() -> None:
    """Test that golden-01 produces REJECT verdict (has race condition)."""
    loader = CorpusLoader()
    label = loader.load_label(loader.corpus_path / "labels" / "golden-01.yaml")
    content = loader.load_artifact_content(label)

    project_root = Path(".")
    engine = DeepVerifyEngine(project_root=project_root)
    verdict = await engine.verify(content)

    # golden-01 has a race condition, should be REJECT
    assert verdict.decision == VerdictDecision.REJECT
    assert len(verdict.findings) > 0


@pytest.mark.asyncio
async def test_golden_verdict_accept() -> None:
    """Test that clean artifacts produce ACCEPT verdict."""
    # Use golden-02 which has no findings
    loader = CorpusLoader()
    label = loader.load_label(loader.corpus_path / "labels" / "golden-02.yaml")
    content = loader.load_artifact_content(label)

    project_root = Path(".")
    engine = DeepVerifyEngine(project_root=project_root)
    verdict = await engine.verify(content)

    # Clean artifact should be ACCEPT
    assert verdict.decision == VerdictDecision.ACCEPT
