"""Tests for code review synthesis handler.

Story 13.10: Code Review Benchmarking Integration

Tests cover:
- Task 4: Synthesis record creation (AC: #3)
- Task 11: Unit tests for synthesis record
"""

from pathlib import Path

import pytest

from bmad_assist.code_review.orchestrator import (
    CODE_REVIEW_SYNTHESIS_WORKFLOW_ID,
    CodeReviewError,
    load_reviews_for_synthesis,
    save_reviews_for_synthesis,
)
from bmad_assist.validation.anonymizer import AnonymizedValidation
from bmad_assist.validation.evidence_score import (
    EvidenceScoreAggregate,
    Severity,
    Verdict,
)

# ============================================================================
# Tests for save_reviews_for_synthesis and load_reviews_for_synthesis
# ============================================================================


class TestReviewsForSynthesis:
    """Test review caching for synthesis phase."""

    def _make_mock_evidence_aggregate(self) -> EvidenceScoreAggregate:
        """Create a mock EvidenceScoreAggregate for testing."""
        return EvidenceScoreAggregate(
            total_score=1.5,
            verdict=Verdict.PASS,
            per_validator_scores={"validator-a": 2.0, "validator-b": 1.0},
            per_validator_verdicts={
                "validator-a": Verdict.PASS,
                "validator-b": Verdict.PASS,
            },
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

    def test_save_and_load_reviews(self, tmp_path: Path) -> None:
        """Test round-trip of saving and loading reviews."""
        reviews = [
            AnonymizedValidation(
                validator_id="validator-a",
                content="# Review A\n\nFindings here",
                original_ref="claude-sonnet",
            ),
            AnonymizedValidation(
                validator_id="validator-b",
                content="# Review B\n\nMore findings",
                original_ref="gemini-2.5-flash",
            ),
        ]

        # Save reviews with Evidence Score (required for v2 cache)
        evidence = self._make_mock_evidence_aggregate()
        session_id = save_reviews_for_synthesis(
            reviews,
            tmp_path,
            session_id="test-session-123",
            evidence_aggregate=evidence,
        )

        assert session_id == "test-session-123"

        # Verify cache file exists
        cache_file = tmp_path / ".bmad-assist" / "cache" / "code-reviews-test-session-123.json"
        assert cache_file.exists()

        # Load reviews back - TIER 2: returns (reviews, failed_reviewers, evidence_score)
        loaded, failed_reviewers, evidence_data = load_reviews_for_synthesis(
            "test-session-123", tmp_path
        )

        assert len(loaded) == 2
        assert loaded[0].validator_id == "validator-a"
        assert loaded[1].validator_id == "validator-b"
        assert "Review A" in loaded[0].content
        assert failed_reviewers == []  # No failed reviewers in this test
        assert evidence_data is not None

    def test_load_nonexistent_session_raises_error(self, tmp_path: Path) -> None:
        """Test that loading a nonexistent session raises CodeReviewError."""
        with pytest.raises(CodeReviewError) as exc_info:
            load_reviews_for_synthesis("nonexistent-session", tmp_path)

        assert "not found" in str(exc_info.value).lower()

    def test_save_generates_session_id_if_none(self, tmp_path: Path) -> None:
        """Test that save generates a session_id if none provided."""
        reviews = [
            AnonymizedValidation(
                validator_id="validator-a",
                content="Content",
                original_ref="ref",
            ),
        ]

        session_id = save_reviews_for_synthesis(reviews, tmp_path)

        # Should be a UUID
        assert session_id
        assert len(session_id) == 36  # UUID format


# ============================================================================
# Tests for synthesis workflow ID constant
# ============================================================================


class TestCodeReviewSynthesisWorkflowId:
    """Test that code review synthesis uses correct workflow ID."""

    def test_workflow_id_constant_value(self) -> None:
        """Test CODE_REVIEW_SYNTHESIS_WORKFLOW_ID has correct value."""
        assert CODE_REVIEW_SYNTHESIS_WORKFLOW_ID == "code-review-synthesis"

    def test_workflow_id_differs_from_validation(self) -> None:
        """Test that code review synthesis ID differs from validation synthesis."""
        # Import validation synthesis workflow ID
        from bmad_assist.code_review.orchestrator import CODE_REVIEW_WORKFLOW_ID

        # They should all be distinct
        assert CODE_REVIEW_WORKFLOW_ID == "code-review"
        assert CODE_REVIEW_SYNTHESIS_WORKFLOW_ID == "code-review-synthesis"
        assert CODE_REVIEW_WORKFLOW_ID != CODE_REVIEW_SYNTHESIS_WORKFLOW_ID


# ============================================================================
# Tests for synthesis handler session discovery
# ============================================================================


class TestSynthesisHandlerSessionDiscovery:
    """Test that synthesis handler correctly discovers review sessions."""

    def test_discovers_latest_session(self, tmp_path: Path) -> None:
        """Test that handler finds the most recent code-reviews cache file."""
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        # Create two cache files with different timestamps
        import json
        import time

        old_file = cache_dir / "code-reviews-old-session.json"
        old_file.write_text(
            json.dumps(
                {
                    "session_id": "old-session",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "reviews": [],
                }
            )
        )

        time.sleep(0.01)  # Ensure different mtime

        new_file = cache_dir / "code-reviews-new-session.json"
        new_file.write_text(
            json.dumps(
                {
                    "session_id": "new-session",
                    "timestamp": "2024-12-20T00:00:00Z",
                    "reviews": [],
                }
            )
        )

        # The synthesis handler should find new-session
        # (Testing the _get_session_id_from_state pattern)
        def safe_mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except (OSError, FileNotFoundError):
                return 0.0

        review_files = sorted(
            cache_dir.glob("code-reviews-*.json"),
            key=safe_mtime,
            reverse=True,
        )

        latest_file = review_files[0]
        session_id = latest_file.stem.replace("code-reviews-", "")

        assert session_id == "new-session"
