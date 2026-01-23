"""Tests for Story 22.7: Code Review Artifact Persistence.

Tests cover:
- AC #1: N individual report files are saved with correct naming
- AC #2: Individual reports use index-based role_id (a, b, c...)
- AC #3: Synthesis document and mapping are saved with correct format
- AC #4: Partial success handling (some validators fail)
- AC #5: Error handling and logging (I/O errors don't crash phase)
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.code_review.orchestrator import (
    CodeReviewError,
    CodeReviewPhaseResult,
    InsufficientReviewsError,
    _save_code_review_report,
    _save_code_review_mapping,
    load_reviews_for_synthesis,
    run_code_review_phase,
    save_reviews_for_synthesis,
)
from bmad_assist.core.config import Config, MultiProviderConfig, ProviderConfig
from bmad_assist.core.types import EpicId
from bmad_assist.validation.anonymizer import (
    AnonymizedValidation,
    AnonymizationMapping,
    ValidationOutput,
)
from bmad_assist.validation.evidence_score import (
    EvidenceScoreAggregate,
    Severity,
    Verdict,
)


# ============================================================================
# AC #1 & #2: Individual validator report saving with role_id
# ============================================================================


class TestIndividualReportSaving:
    """Test individual validator reports are saved with index-based role_id."""

    def test_report_naming_uses_role_id(self, tmp_path: Path) -> None:
        """Test AC #2: Individual reports use index-based role_id (a, b, c...).

        This prevents report overwriting when multiple reviewers use
        the same provider/model.
        """
        reviews_dir = tmp_path / "code-reviews"
        reviews_dir.mkdir(parents=True)

        # Create test outputs with same provider but different session IDs
        # (simulating 3 reviewers all using Claude Sonnet)
        base_timestamp = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)

        outputs = [
            ValidationOutput(
                provider="claude",
                model="sonnet-4",
                content="# Review by Claude A",
                timestamp=base_timestamp,
                duration_ms=1000,
                token_count=100,
                provider_session_id="session-a-123",
            ),
            ValidationOutput(
                provider="claude",
                model="sonnet-4",
                content="# Review by Claude B",
                timestamp=base_timestamp,
                duration_ms=1100,
                token_count=110,
                provider_session_id="session-b-456",
            ),
            ValidationOutput(
                provider="claude",
                model="sonnet-4",
                content="# Review by Claude C",
                timestamp=base_timestamp,
                duration_ms=1200,
                token_count=120,
                provider_session_id="session-c-789",
            ),
        ]

        # Save each report with different role_id
        saved_paths = []
        test_session_id = "test-session-abc123"
        for idx, output in enumerate(outputs):
            role_id = chr(ord("a") + idx)  # a, b, c...
            anonymized_id = f"Validator {chr(ord('A') + idx)}"
            path = _save_code_review_report(
                output=output,
                epic=22,
                story=7,
                reviews_dir=reviews_dir,
                role_id=role_id,
                session_id=test_session_id,
                anonymized_id=anonymized_id,
            )
            saved_paths.append(path)

        # Verify 3 separate files were created
        assert len(saved_paths) == 3

        # Verify filenames use role_id (a, b, c...)
        filenames = [p.name for p in saved_paths]
        assert "code-review-22-7-a-20260115T080000Z.md" in filenames
        assert "code-review-22-7-b-20260115T080000Z.md" in filenames
        assert "code-review-22-7-c-20260115T080000Z.md" in filenames

        # Verify files exist and are readable
        for path in saved_paths:
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "---" in content  # YAML frontmatter
            assert "role_id:" in content  # AC #2: role_id in frontmatter
            assert "session_id:" in content  # AC #3: session_id in frontmatter

    def test_all_n_validators_saved(self, tmp_path: Path) -> None:
        """Test AC #1: All N validators generate N separate report files."""
        reviews_dir = tmp_path / "code-reviews"
        reviews_dir.mkdir(parents=True)

        base_timestamp = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)

        # Simulate 6 reviewers
        outputs = []
        for idx in range(6):
            role_id = chr(ord("a") + idx)
            outputs.append(
                ValidationOutput(
                    provider=f"provider-{idx}",
                    model=f"model-{idx}",
                    content=f"# Review {idx}",
                    timestamp=base_timestamp,
                    duration_ms=1000,
                    token_count=100,
                    provider_session_id=f"session-{idx}",
                )
            )

        # Save all reports
        saved_files = []
        test_session_id = "test-session-6-validators"
        for idx, output in enumerate(outputs):
            role_id = chr(ord("a") + idx)
            path = _save_code_review_report(
                output=output,
                epic=22,
                story=7,
                reviews_dir=reviews_dir,
                role_id=role_id,
                session_id=test_session_id,
                anonymized_id=f"Validator {idx}",
            )
            saved_files.append(path.name)

        # Verify 6 files were created
        assert len(saved_files) == 6

        # Verify all files exist
        for filename in saved_files:
            assert (reviews_dir / filename).exists()

    def test_report_contains_full_markdown_content(self, tmp_path: Path) -> None:
        """Test AC #2: Report file contains complete markdown output."""
        reviews_dir = tmp_path / "code-reviews"
        reviews_dir.mkdir(parents=True)

        content = """# Code Review Report

## Findings

### Critical Issues
- Bug in src/file.py line 42

## Recommendations
- Fix the bug
"""

        output = ValidationOutput(
            provider="claude",
            model="sonnet-4",
            content=content,
            timestamp=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
            duration_ms=1000,
            token_count=100,
            provider_session_id="session-123",
        )

        path = _save_code_review_report(
            output=output,
            epic=22,
            story=7,
            reviews_dir=reviews_dir,
            role_id="a",
            session_id="test-session-content",
            anonymized_id="Validator A",
        )

        # Verify file contains full content
        file_content = path.read_text(encoding="utf-8")
        assert "## Findings" in file_content
        assert "Critical Issues" in file_content
        assert "Bug in src/file.py" in file_content


# ============================================================================
# AC #3: Synthesis document and mapping saving
# ============================================================================


class TestSynthesisAndMappingSaving:
    """Test synthesis document and mapping are saved correctly."""

    def test_synthesis_document_saved_with_timestamp(self, tmp_path: Path) -> None:
        """Test AC #3: Synthesis document saved with timestamp in filename."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        # Create a mock handler
        handler = MagicMock(spec=CodeReviewSynthesisHandler)
        handler.project_path = tmp_path

        reviews_dir = tmp_path / "code-reviews"
        reviews_dir.mkdir(parents=True)

        # Call _save_synthesis_report
        CodeReviewSynthesisHandler._save_synthesis_report(
            handler,
            content="# Synthesis Report\n\n## Consensus\nAll agreed",
            master_reviewer_id="master-opus",
            session_id="test-session-123",
            reviewers_used=["Validator A", "Validator B"],
            epic=22,
            story=7,
            duration_ms=5000,
            reviews_dir=reviews_dir,
        )

        # Verify file was created with timestamp
        synthesis_files = list(reviews_dir.glob("synthesis-22-7-*.md"))
        assert len(synthesis_files) == 1

        synthesis_file = synthesis_files[0]
        # Filename should match pattern: synthesis-{epic}-{story}-{timestamp}.md
        assert synthesis_file.name.startswith("synthesis-22-7-")
        assert synthesis_file.name.endswith(".md")

        # Verify content
        content = synthesis_file.read_text(encoding="utf-8")
        assert "## Consensus" in content
        assert "---" in content  # YAML frontmatter

    def test_mapping_saved_with_correct_prefix(self, tmp_path: Path) -> None:
        """Test AC #3: Mapping saved with code-review-mapping prefix."""
        mapping = AnonymizationMapping(
            session_id="test-session-456",
            timestamp=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
            mapping={
                "Validator A": {
                    "provider": "claude",
                    "model": "sonnet-4",
                    "role_id": "a",
                    "provider_session_id": "session-a",
                },
                "Validator B": {
                    "provider": "gemini",
                    "model": "gemini-2.5-flash",
                    "role_id": "b",
                    "provider_session_id": "session-b",
                },
            },
        )

        path = _save_code_review_mapping(mapping, tmp_path)

        # Verify file path
        assert path.name == "code-review-mapping-test-session-456.json"
        assert path.exists()

        # Verify content
        content = json.loads(path.read_text(encoding="utf-8"))
        assert content["session_id"] == "test-session-456"
        assert "Validator A" in content["mapping"]
        assert "Validator B" in content["mapping"]
        # Verify role_id is in mapping
        assert content["mapping"]["Validator A"]["role_id"] == "a"
        assert content["mapping"]["Validator B"]["role_id"] == "b"

    def test_synthesis_includes_anonymized_references(self, tmp_path: Path) -> None:
        """Test AC #3: Synthesis includes anonymized validator references."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = MagicMock(spec=CodeReviewSynthesisHandler)
        handler.project_path = tmp_path

        reviews_dir = tmp_path / "code-reviews"
        reviews_dir.mkdir(parents=True)

        CodeReviewSynthesisHandler._save_synthesis_report(
            handler,
            content="# Synthesis\n\nValidator A found issues. Validator B agreed.",
            master_reviewer_id="master-opus",
            session_id="test-session-789",
            reviewers_used=["Validator A", "Validator B"],
            epic=22,
            story=7,
            duration_ms=5000,
            reviews_dir=reviews_dir,
        )

        # Load and verify frontmatter
        synthesis_file = list(reviews_dir.glob("synthesis-*.md"))[0]
        content = synthesis_file.read_text(encoding="utf-8")

        # Should have anonymized references in frontmatter
        assert "reviewers_used:" in content
        assert "Validator A" in content
        assert "Validator B" in content


# ============================================================================
# AC #4: Partial success handling
# ============================================================================


class TestPartialSuccessHandling:
    """Test partial success scenarios (some validators fail)."""

    def test_only_successful_validators_save_reports(self, tmp_path: Path) -> None:
        """Test AC #4: Only successful validators' reports are persisted."""
        # This is tested at integration level in test_orchestrator.py
        # Here we verify the data flow
        reviews_dir = tmp_path / "code-reviews"
        reviews_dir.mkdir(parents=True)

        # Simulate 2 successful, 1 failed
        successful_outputs = [
            ValidationOutput(
                provider="claude",
                model="sonnet-4",
                content="# Review A",
                timestamp=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
                duration_ms=1000,
                token_count=100,
                provider_session_id="session-a",
            ),
            ValidationOutput(
                provider="gemini",
                model="gemini-2.5-flash",
                content="# Review B",
                timestamp=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
                duration_ms=1100,
                token_count=110,
                provider_session_id="session-b",
            ),
        ]

        # Save reports for only successful validators
        saved_files = []
        test_session_id = "test-session-partial"
        for idx, output in enumerate(successful_outputs):
            role_id = chr(ord("a") + idx)
            path = _save_code_review_report(
                output=output,
                epic=22,
                story=7,
                reviews_dir=reviews_dir,
                role_id=role_id,
                session_id=test_session_id,
                anonymized_id=f"Validator {idx}",
            )
            saved_files.append(path)

        # Verify only 2 files were saved (not 3)
        assert len(saved_files) == 2
        assert all(p.exists() for p in saved_files)

    def test_synthesis_includes_failed_reviewer_metadata(self, tmp_path: Path) -> None:
        """Test AC #4: Synthesis includes failed reviewers in frontmatter."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = MagicMock(spec=CodeReviewSynthesisHandler)
        handler.project_path = tmp_path

        reviews_dir = tmp_path / "code-reviews"
        reviews_dir.mkdir(parents=True)

        failed_reviewers = ["claude-sonnet-timeout", "gpt-4-error"]

        CodeReviewSynthesisHandler._save_synthesis_report(
            handler,
            content="# Synthesis\n\n## Consensus\n2 reviewers agreed.",
            master_reviewer_id="master-opus",
            session_id="test-session-failed",
            reviewers_used=["Validator A", "Validator B"],
            epic=22,
            story=7,
            duration_ms=5000,
            reviews_dir=reviews_dir,
            failed_reviewers=failed_reviewers,
        )

        # Verify failed reviewers in frontmatter
        synthesis_file = list(reviews_dir.glob("synthesis-*.md"))[0]
        content = synthesis_file.read_text(encoding="utf-8")

        assert "failed_reviewers:" in content
        assert "claude-sonnet-timeout" in content
        assert "gpt-4-error" in content

    def _make_mock_evidence_aggregate(self) -> EvidenceScoreAggregate:
        """Create a mock EvidenceScoreAggregate for testing."""
        return EvidenceScoreAggregate(
            total_score=1.5,
            verdict=Verdict.PASS,
            per_validator_scores={"validator-a": 1.5},
            per_validator_verdicts={"validator-a": Verdict.PASS},
            findings_by_severity={
                Severity.CRITICAL: 0,
                Severity.IMPORTANT: 1,
                Severity.MINOR: 0,
            },
            total_findings=1,
            total_clean_passes=3,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.0,
        )

    def test_save_and_load_with_failed_reviewers(self, tmp_path: Path) -> None:
        """Test AC #4: save_reviews_for_synthesis includes failed_reviewers."""
        reviews = [
            AnonymizedValidation(
                validator_id="validator-a",
                content="# Review A",
                original_ref="claude-sonnet",
            ),
        ]

        failed_reviewers = ["gemini-flash-timeout"]
        evidence = self._make_mock_evidence_aggregate()

        # Save with failed reviewers and evidence score (v2 cache)
        session_id = save_reviews_for_synthesis(
            reviews,
            tmp_path,
            session_id="test-partial-success",
            failed_reviewers=failed_reviewers,
            evidence_aggregate=evidence,
        )

        # Load and verify failed reviewers are preserved
        # TIER 2: returns (reviews, failed_reviewers, evidence_score)
        loaded, loaded_failed, evidence_data = load_reviews_for_synthesis(session_id, tmp_path)

        assert len(loaded) == 1
        assert loaded[0].validator_id == "validator-a"
        assert loaded_failed == failed_reviewers
        assert evidence_data is not None


# ============================================================================
# AC #5: Error handling and logging
# ============================================================================


class TestErrorHandlingAndLogging:
    """Test error handling and logging (AC #5)."""

    def test_report_save_failure_logs_warning(self, tmp_path: Path, caplog) -> None:
        """Test AC #5: Report save failure logs warning but doesn't crash."""
        # Create read-only directory to trigger write error
        reviews_dir = tmp_path / "readonly" / "code-reviews"
        reviews_dir.mkdir(parents=True)

        # Make directory read-only
        import os
        import stat

        original_mode = reviews_dir.stat().st_mode
        reviews_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # Read and execute only

        try:
            output = ValidationOutput(
                provider="claude",
                model="sonnet-4",
                content="# Review",
                timestamp=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
                duration_ms=1000,
                token_count=100,
                provider_session_id="session-123",
            )

            # This should log a warning and re-raise OSError
            with caplog.at_level(logging.WARNING):
                with pytest.raises(OSError):
                    _save_code_review_report(
                        output=output,
                        epic=22,
                        story=7,
                        reviews_dir=reviews_dir,
                        role_id="a",
                        session_id="test-session-error",
                        anonymized_id="Validator A",
                    )

            # Verify warning was logged
            assert any(
                "Failed to save code review report" in record.message for record in caplog.records
            )

        finally:
            # Restore permissions for cleanup
            reviews_dir.chmod(original_mode)

    def test_missing_directory_created_automatically(self, tmp_path: Path) -> None:
        """Test AC #5: Missing code-reviews directory is created automatically."""
        reviews_dir = tmp_path / "code-reviews"

        # Don't create directory - _save_code_review_report should create it
        assert not reviews_dir.exists()

        output = ValidationOutput(
            provider="claude",
            model="sonnet-4",
            content="# Review",
            timestamp=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
            duration_ms=1000,
            token_count=100,
            provider_session_id="session-123",
        )

        # This should create the directory automatically
        path = _save_code_review_report(
            output=output,
            epic=22,
            story=7,
            reviews_dir=reviews_dir,
            role_id="a",
            session_id="test-session-mkdir",
            anonymized_id="Validator A",
        )

        # Verify directory was created and file exists
        assert reviews_dir.exists()
        assert path.exists()

    def test_atomic_write_prevents_partial_files(self, tmp_path: Path) -> None:
        """Test AC #5: Atomic write pattern (temp file + rename)."""
        reviews_dir = tmp_path / "code-reviews"
        reviews_dir.mkdir(parents=True)

        output = ValidationOutput(
            provider="claude",
            model="sonnet-4",
            content="# Review",
            timestamp=datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC),
            duration_ms=1000,
            token_count=100,
            provider_session_id="session-123",
        )

        path = _save_code_review_report(
            output=output,
            epic=22,
            story=7,
            reviews_dir=reviews_dir,
            role_id="a",
            session_id="test-session-atomic",
            anonymized_id="Validator A",
        )

        # Verify final file exists
        assert path.exists()

        # Verify no temp file remains
        temp_files = list(reviews_dir.glob("*.md.tmp"))
        assert len(temp_files) == 0
