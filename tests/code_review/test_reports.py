"""Tests for code review report persistence.

Tests cover:
- _save_code_review_report() (AC1)
"""

from datetime import UTC, datetime
from pathlib import Path

import frontmatter
import pytest

from bmad_assist.code_review.orchestrator import _save_code_review_report
from bmad_assist.validation.anonymizer import ValidationOutput


class TestSaveCodeReviewReport:
    """Test saving code review reports with frontmatter."""

    @pytest.fixture
    def reviews_dir(self, tmp_path: Path) -> Path:
        """Create code-reviews directory structure."""
        dir_path = tmp_path / "docs" / "sprint-artifacts" / "code-reviews"
        dir_path.mkdir(parents=True)
        return dir_path

    @pytest.fixture
    def sample_validation_output(self) -> ValidationOutput:
        """Sample ValidationOutput for testing."""
        return ValidationOutput(
            provider="gemini",
            model="gemini-1.5-pro",
            content="## Code Review\n\nLooks good.",
            timestamp=datetime.now(UTC),
            duration_ms=1234,
            token_count=500,
        )

    def test_save_code_review_report_frontmatter(
        self,
        reviews_dir: Path,
        sample_validation_output: ValidationOutput,
    ) -> None:
        """Test YAML frontmatter excludes provider/model to preserve anonymization."""
        result_path = _save_code_review_report(
            output=sample_validation_output,
            epic=12,
            story=5,
            reviews_dir=reviews_dir,
            role_id="a",
            session_id="test-session-id",
            anonymized_id="Validator A",
        )

        with open(result_path, encoding="utf-8") as f:
            post = frontmatter.load(f)

        metadata = post.metadata

        assert metadata["type"] == "code-review"
        assert metadata["role_id"] == "a"
        assert metadata["reviewer_id"] == "Validator A"
        assert "provider" not in metadata  # Excluded to preserve anonymization
        assert "model" not in metadata
        assert "timestamp" in metadata
        assert metadata["epic"] == 12
        assert metadata["story"] == 5
        assert metadata["phase"] == "CODE_REVIEW"
