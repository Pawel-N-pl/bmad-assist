"""Tests for Evidence Score integration with code review orchestrator.

Story: Evidence Score TIER 2 Python Calculator
Task 18: Code review orchestrator integration tests

Tests cover:
- Evidence Score data persistence in code review cache v2 format
- load_reviews_for_synthesis with Evidence Score
- Cache version validation for code review
"""

import json
from pathlib import Path

import pytest

from bmad_assist.code_review.orchestrator import (
    load_reviews_for_synthesis,
    save_reviews_for_synthesis,
)
from bmad_assist.validation.anonymizer import AnonymizedValidation
from bmad_assist.validation.evidence_score import (
    CacheVersionError,
    EvidenceScoreAggregate,
    Severity,
    Verdict,
)


class TestCodeReviewEvidenceScorePersistence:
    """Integration tests for Evidence Score in code review cache v2 format."""

    def _make_mock_evidence_aggregate(self) -> EvidenceScoreAggregate:
        """Create a mock EvidenceScoreAggregate for testing."""
        return EvidenceScoreAggregate(
            total_score=2.5,
            verdict=Verdict.PASS,
            per_validator_scores={"Reviewer A": 3.0, "Reviewer B": 2.0},
            per_validator_verdicts={
                "Reviewer A": Verdict.PASS,
                "Reviewer B": Verdict.PASS,
            },
            findings_by_severity={
                Severity.CRITICAL: 1,
                Severity.IMPORTANT: 2,
                Severity.MINOR: 1,
            },
            total_findings=4,
            total_clean_passes=6,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.5,
        )

    def test_evidence_score_saved_in_code_review_cache(self, tmp_path: Path) -> None:
        """Evidence Score aggregate is saved in code review cache v2 format."""
        from bmad_assist.core.paths import init_paths

        init_paths(tmp_path)

        reviews = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="# Code Review Report\n\nEvidence Score: 3.0",
                original_ref="ref-001",
            ),
        ]
        evidence = self._make_mock_evidence_aggregate()

        session_id = save_reviews_for_synthesis(
            anonymized=reviews,
            project_root=tmp_path,
            evidence_aggregate=evidence,
        )

        # Read cache directly
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_file = cache_dir / f"code-reviews-{session_id}.json"
        cache_data = json.loads(cache_file.read_text())

        assert cache_data["cache_version"] == 2
        assert "evidence_score" in cache_data
        assert cache_data["evidence_score"]["total_score"] == 2.5
        assert cache_data["evidence_score"]["verdict"] == "PASS"
        assert cache_data["evidence_score"]["consensus_ratio"] == 0.5

    def test_evidence_score_loaded_from_code_review_cache(self, tmp_path: Path) -> None:
        """Evidence Score is loaded from code review cache v2 format."""
        from bmad_assist.core.paths import init_paths

        init_paths(tmp_path)

        reviews = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="# Code Review",
                original_ref="ref-001",
            ),
        ]
        evidence = self._make_mock_evidence_aggregate()

        session_id = save_reviews_for_synthesis(
            anonymized=reviews,
            project_root=tmp_path,
            evidence_aggregate=evidence,
        )

        _, _, evidence_data = load_reviews_for_synthesis(session_id, tmp_path)

        assert evidence_data is not None
        assert evidence_data["total_score"] == 2.5
        assert evidence_data["verdict"] == "PASS"
        # Cache format uses per_validator with nested score/verdict
        assert evidence_data["per_validator"]["Reviewer A"]["score"] == 3.0
        assert evidence_data["per_validator"]["Reviewer B"]["score"] == 2.0

    def test_v1_cache_rejected_for_code_reviews(self, tmp_path: Path) -> None:
        """load_reviews_for_synthesis raises CacheVersionError for v1 cache."""
        from bmad_assist.core.paths import init_paths

        init_paths(tmp_path)

        # Manually create a v1 cache file (no cache_version field)
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        session_id = "test-v1-session"
        cache_file = cache_dir / f"code-reviews-{session_id}.json"

        v1_data = {
            "session_id": session_id,
            "validations": [
                {"validator_id": "Reviewer A", "content": "Test content", "original_ref": "ref-001"}
            ],
            # No cache_version = v1 format
        }
        cache_file.write_text(json.dumps(v1_data))

        with pytest.raises(CacheVersionError) as exc_info:
            load_reviews_for_synthesis(session_id, tmp_path)

        # Error message indicates version 2 required
        assert "version 2" in str(exc_info.value).lower()

    def test_v2_cache_missing_evidence_score_returns_none(
        self, tmp_path: Path
    ) -> None:
        """load_reviews_for_synthesis returns None evidence_score when v2 cache is missing it."""
        from bmad_assist.core.paths import init_paths

        init_paths(tmp_path)

        # Manually create a v2 cache file missing the evidence_score key
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        session_id = "test-v2-no-evidence-session"
        cache_file = cache_dir / f"code-reviews-{session_id}.json"

        v2_data_no_evidence = {
            "cache_version": 2,
            "session_id": session_id,
            "timestamp": "2026-01-22T10:00:00Z",
            "reviews": [
                {"reviewer_id": "Reviewer A", "content": "Test", "original_ref": "ref-001"}
            ],
            "failed_reviewers": [],
            # Missing evidence_score key - gracefully handled
        }
        cache_file.write_text(json.dumps(v2_data_no_evidence))

        reviews, failed, evidence_score = load_reviews_for_synthesis(session_id, tmp_path)

        assert len(reviews) == 1
        assert evidence_score is None


class TestCodeReviewCacheWithFailedReviewers:
    """Tests for failed reviewer tracking with Evidence Score in cache."""

    def _make_mock_evidence_aggregate(self) -> EvidenceScoreAggregate:
        """Create a mock EvidenceScoreAggregate for testing."""
        return EvidenceScoreAggregate(
            total_score=1.5,
            verdict=Verdict.PASS,
            per_validator_scores={"Reviewer A": 1.5},
            per_validator_verdicts={"Reviewer A": Verdict.PASS},
            findings_by_severity={
                Severity.CRITICAL: 0,
                Severity.IMPORTANT: 1,
                Severity.MINOR: 1,
            },
            total_findings=2,
            total_clean_passes=4,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.0,
        )

    def test_failed_reviewers_with_evidence_score(self, tmp_path: Path) -> None:
        """Failed reviewers and Evidence Score coexist in cache v2."""
        from bmad_assist.core.paths import init_paths

        init_paths(tmp_path)

        reviews = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="# Code Review",
                original_ref="ref-001",
            ),
        ]
        failed_reviewers = ["Reviewer B", "Reviewer C"]
        evidence = self._make_mock_evidence_aggregate()

        session_id = save_reviews_for_synthesis(
            anonymized=reviews,
            project_root=tmp_path,
            failed_reviewers=failed_reviewers,
            evidence_aggregate=evidence,
        )

        loaded_reviews, loaded_failed, evidence_data = load_reviews_for_synthesis(
            session_id, tmp_path
        )

        # All data preserved
        assert len(loaded_reviews) == 1
        assert loaded_failed == ["Reviewer B", "Reviewer C"]
        assert evidence_data is not None
        assert evidence_data["total_score"] == 1.5


class TestCodeReviewEvidenceScoreRoundtrip:
    """End-to-end tests for Evidence Score in code review workflow."""

    def test_full_cache_roundtrip(self, tmp_path: Path) -> None:
        """Test Evidence Score persists through code review cache save/load cycle."""
        from bmad_assist.core.paths import init_paths

        init_paths(tmp_path)

        # Create realistic Evidence Score aggregate
        aggregate = EvidenceScoreAggregate(
            total_score=-1.5,
            verdict=Verdict.PASS,
            per_validator_scores={
                "Reviewer A": -1.0,
                "Reviewer B": -2.0,
            },
            per_validator_verdicts={
                "Reviewer A": Verdict.PASS,
                "Reviewer B": Verdict.PASS,
            },
            findings_by_severity={
                Severity.CRITICAL: 0,
                Severity.IMPORTANT: 0,
                Severity.MINOR: 2,
            },
            total_findings=2,
            total_clean_passes=6,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.0,
        )

        # Save to cache
        reviews = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="Code looks good",
                original_ref="ref-001",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="Minor style issues",
                original_ref="ref-002",
            ),
        ]
        session_id = save_reviews_for_synthesis(
            anonymized=reviews,
            project_root=tmp_path,
            evidence_aggregate=aggregate,
        )

        # Load from cache
        _, _, evidence_data = load_reviews_for_synthesis(session_id, tmp_path)

        # Verify data survived roundtrip
        assert evidence_data is not None
        assert evidence_data["total_score"] == -1.5
        assert evidence_data["verdict"] == "PASS"
        assert evidence_data["total_findings"] == 2
        assert evidence_data["findings_summary"]["CRITICAL"] == 0
        assert evidence_data["findings_summary"]["MINOR"] == 2
        assert evidence_data["findings_summary"]["CLEAN_PASS"] == 6
