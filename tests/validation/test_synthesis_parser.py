"""Tests for synthesis metrics parser.

Story 13.6: Synthesizer Schema Integration
Tests cover:
- AC3: Synthesis output parser functionality
- AC4: Graceful parsing failures
- AC7: Quality field calculations
- AC8: Consensus field calculations
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture


class TestExtractSynthesisMetrics:
    """Test extract_synthesis_metrics function (AC3, AC4)."""

    @pytest.fixture
    def valid_json_output(self) -> str:
        """Create valid synthesis output with metrics JSON."""
        return """## Synthesis Summary

This is the synthesis report content.

## Issues Verified

Some verified issues here.

<!-- METRICS_JSON_START -->
{
  "quality": {
    "actionable_ratio": 0.85,
    "specificity_score": 0.75,
    "evidence_quality": 0.7,
    "follows_template": true,
    "internal_consistency": 0.9
  },
  "consensus": {
    "agreed_findings": 5,
    "unique_findings": 2,
    "disputed_findings": 1,
    "missed_findings": 0,
    "agreement_score": 0.625,
    "false_positive_count": 0
  }
}
<!-- METRICS_JSON_END -->

## Changes Applied

Final section.
"""

    def test_extracts_valid_metrics(self, valid_json_output: str) -> None:
        """Extracts metrics from valid synthesis output."""
        from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

        result = extract_synthesis_metrics(valid_json_output)

        assert result is not None
        assert result.quality is not None
        assert result.consensus is not None

        # Quality fields
        assert result.quality.actionable_ratio == 0.85
        assert result.quality.specificity_score == 0.75
        assert result.quality.evidence_quality == 0.7
        assert result.quality.follows_template is True
        assert result.quality.internal_consistency == 0.9

        # Consensus fields
        assert result.consensus.agreed_findings == 5
        assert result.consensus.unique_findings == 2
        assert result.consensus.disputed_findings == 1
        assert result.consensus.missed_findings == 0
        assert result.consensus.agreement_score == 0.625
        assert result.consensus.false_positive_count == 0

    def test_returns_none_when_markers_missing(self, caplog: LogCaptureFixture) -> None:
        """Returns None with warning when markers not found."""
        from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

        output_without_markers = """## Synthesis Summary

This is a synthesis report without metrics markers.
No JSON here.
"""

        with caplog.at_level(logging.WARNING):
            result = extract_synthesis_metrics(output_without_markers)

        assert result is None
        assert "Markers not found" in caplog.text

    def test_returns_none_on_invalid_json(self, caplog: LogCaptureFixture) -> None:
        """Returns None with warning when JSON is invalid."""
        from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

        output_with_bad_json = """## Synthesis Summary

<!-- METRICS_JSON_START -->
{ this is not: valid json, missing quotes }
<!-- METRICS_JSON_END -->
"""

        with caplog.at_level(logging.WARNING):
            result = extract_synthesis_metrics(output_with_bad_json)

        assert result is None
        assert "Invalid JSON" in caplog.text

    def test_returns_none_on_schema_validation_failure(self, caplog: LogCaptureFixture) -> None:
        """Returns None when Pydantic validation fails for both quality and consensus."""
        from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

        # Missing required fields in both quality and consensus
        output_with_invalid_schema = """## Synthesis Summary

<!-- METRICS_JSON_START -->
{
  "quality": {
    "actionable_ratio": "not_a_float"
  },
  "consensus": {
    "agreed_findings": "not_an_int"
  }
}
<!-- METRICS_JSON_END -->
"""

        with caplog.at_level(logging.WARNING):
            result = extract_synthesis_metrics(output_with_invalid_schema)

        # Both quality and consensus failed validation
        assert result is None
        assert "schema validation failed" in caplog.text.lower()

    def test_partial_extraction_quality_only(self, caplog: LogCaptureFixture) -> None:
        """Extracts quality when consensus validation fails."""
        from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

        output_quality_only = """## Synthesis Summary

<!-- METRICS_JSON_START -->
{
  "quality": {
    "actionable_ratio": 0.8,
    "specificity_score": 0.7,
    "evidence_quality": 0.6,
    "follows_template": true,
    "internal_consistency": 0.85
  },
  "consensus": {
    "agreed_findings": "invalid_type"
  }
}
<!-- METRICS_JSON_END -->
"""

        with caplog.at_level(logging.WARNING):
            result = extract_synthesis_metrics(output_quality_only)

        assert result is not None
        assert result.quality is not None
        assert result.quality.actionable_ratio == 0.8
        assert result.consensus is None
        assert "Consensus schema validation failed" in caplog.text

    def test_partial_extraction_consensus_only(self, caplog: LogCaptureFixture) -> None:
        """Extracts consensus when quality validation fails."""
        from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

        output_consensus_only = """## Synthesis Summary

<!-- METRICS_JSON_START -->
{
  "quality": {
    "actionable_ratio": "invalid_type"
  },
  "consensus": {
    "agreed_findings": 3,
    "unique_findings": 1,
    "disputed_findings": 0,
    "missed_findings": 0,
    "agreement_score": 0.75,
    "false_positive_count": 0
  }
}
<!-- METRICS_JSON_END -->
"""

        with caplog.at_level(logging.WARNING):
            result = extract_synthesis_metrics(output_consensus_only)

        assert result is not None
        assert result.quality is None
        assert result.consensus is not None
        assert result.consensus.agreed_findings == 3
        assert "Quality schema validation failed" in caplog.text


class TestQualityFieldRanges:
    """Test quality field value ranges (AC7)."""

    def test_quality_values_in_valid_range(self) -> None:
        """Quality float fields are in 0.0-1.0 range."""
        from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

        output = """
<!-- METRICS_JSON_START -->
{
  "quality": {
    "actionable_ratio": 0.0,
    "specificity_score": 1.0,
    "evidence_quality": 0.5,
    "follows_template": false,
    "internal_consistency": 0.99
  },
  "consensus": {
    "agreed_findings": 0,
    "unique_findings": 0,
    "disputed_findings": 0,
    "missed_findings": 0,
    "agreement_score": 1.0,
    "false_positive_count": 0
  }
}
<!-- METRICS_JSON_END -->
"""

        result = extract_synthesis_metrics(output)

        assert result is not None
        assert result.quality is not None
        assert 0.0 <= result.quality.actionable_ratio <= 1.0
        assert 0.0 <= result.quality.specificity_score <= 1.0
        assert 0.0 <= result.quality.evidence_quality <= 1.0
        assert 0.0 <= result.quality.internal_consistency <= 1.0


class TestConsensusFieldValues:
    """Test consensus field value calculations (AC8)."""

    def test_agreement_score_calculation(self) -> None:
        """Agreement score = agreed / (agreed + unique + disputed)."""
        from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

        # 5 / (5 + 2 + 1) = 0.625
        output = """
<!-- METRICS_JSON_START -->
{
  "quality": {
    "actionable_ratio": 0.5,
    "specificity_score": 0.5,
    "evidence_quality": 0.5,
    "follows_template": true,
    "internal_consistency": 0.5
  },
  "consensus": {
    "agreed_findings": 5,
    "unique_findings": 2,
    "disputed_findings": 1,
    "missed_findings": 0,
    "agreement_score": 0.625,
    "false_positive_count": 0
  }
}
<!-- METRICS_JSON_END -->
"""

        result = extract_synthesis_metrics(output)

        assert result is not None
        assert result.consensus is not None
        assert result.consensus.agreement_score == 0.625
        assert result.consensus.agreed_findings == 5
        assert result.consensus.unique_findings == 2
        assert result.consensus.disputed_findings == 1

    def test_zero_findings_edge_case(self) -> None:
        """When no findings, agreement_score should be 1.0."""
        from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

        output = """
<!-- METRICS_JSON_START -->
{
  "quality": {
    "actionable_ratio": 1.0,
    "specificity_score": 1.0,
    "evidence_quality": 1.0,
    "follows_template": true,
    "internal_consistency": 1.0
  },
  "consensus": {
    "agreed_findings": 0,
    "unique_findings": 0,
    "disputed_findings": 0,
    "missed_findings": 0,
    "agreement_score": 1.0,
    "false_positive_count": 0
  }
}
<!-- METRICS_JSON_END -->
"""

        result = extract_synthesis_metrics(output)

        assert result is not None
        assert result.consensus is not None
        assert result.consensus.agreement_score == 1.0

    def test_post_hoc_fields_zero(self) -> None:
        """missed_findings and false_positive_count should be 0 from synthesizer."""
        from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

        output = """
<!-- METRICS_JSON_START -->
{
  "quality": {
    "actionable_ratio": 0.5,
    "specificity_score": 0.5,
    "evidence_quality": 0.5,
    "follows_template": true,
    "internal_consistency": 0.5
  },
  "consensus": {
    "agreed_findings": 3,
    "unique_findings": 1,
    "disputed_findings": 0,
    "missed_findings": 0,
    "agreement_score": 0.75,
    "false_positive_count": 0
  }
}
<!-- METRICS_JSON_END -->
"""

        result = extract_synthesis_metrics(output)

        assert result is not None
        assert result.consensus is not None
        # These are POST_HOC fields - should be 0 from synthesizer
        assert result.consensus.missed_findings == 0
        assert result.consensus.false_positive_count == 0


class TestSynthesisMetricsDataclass:
    """Test SynthesisMetrics dataclass."""

    def test_dataclass_is_frozen(self) -> None:
        """SynthesisMetrics is immutable (frozen)."""
        from bmad_assist.validation.synthesis_parser import SynthesisMetrics

        metrics = SynthesisMetrics(quality=None, consensus=None)

        with pytest.raises(AttributeError):
            metrics.quality = None  # type: ignore[misc]

    def test_dataclass_allows_both_none(self) -> None:
        """SynthesisMetrics allows both fields to be None."""
        from bmad_assist.validation.synthesis_parser import SynthesisMetrics

        metrics = SynthesisMetrics(quality=None, consensus=None)

        assert metrics.quality is None
        assert metrics.consensus is None


class TestLoggingExcerpt:
    """Test logging includes output excerpt (AC4)."""

    def test_log_includes_output_excerpt_on_missing_markers(
        self, caplog: LogCaptureFixture
    ) -> None:
        """Log includes first 500 chars when markers missing."""
        from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

        output = "A" * 600  # More than 500 chars

        with caplog.at_level(logging.WARNING):
            extract_synthesis_metrics(output)

        # Check log message includes excerpt
        assert "Markers not found" in caplog.text
        # Excerpt should be truncated to ~500 chars
        assert "A" * 500 in caplog.text


class TestCreateSynthesizerRecord:
    """Test create_synthesizer_record function (AC5, AC6)."""

    @pytest.fixture
    def valid_synthesis_output(self) -> str:
        """Create valid synthesis output with metrics JSON."""
        return """## Synthesis Summary

5 issues verified, 2 false positives dismissed, 3 changes applied.

<!-- METRICS_JSON_START -->
{
  "quality": {
    "actionable_ratio": 0.8,
    "specificity_score": 0.75,
    "evidence_quality": 0.7,
    "follows_template": true,
    "internal_consistency": 0.9
  },
  "consensus": {
    "agreed_findings": 4,
    "unique_findings": 1,
    "disputed_findings": 0,
    "missed_findings": 0,
    "agreement_score": 0.8,
    "false_positive_count": 2
  }
}
<!-- METRICS_JSON_END -->
"""

    @pytest.fixture
    def sample_workflow_info(self) -> WorkflowInfo:
        """Sample workflow info."""
        from bmad_assist.benchmarking import PatchInfo, WorkflowInfo

        return WorkflowInfo(
            id="validate-story-synthesis",
            version="1.0.0",
            variant="default",
            patch=PatchInfo(applied=True),
        )

    @pytest.fixture
    def sample_story_info(self) -> StoryInfo:
        """Sample story info."""
        from bmad_assist.benchmarking import StoryInfo

        return StoryInfo(
            epic_num=13,
            story_num=6,
            title="Synthesizer Schema Integration",
            complexity_flags={},
        )

    def test_creates_record_with_synthesizer_role(
        self,
        valid_synthesis_output: str,
        sample_workflow_info: WorkflowInfo,
        sample_story_info: StoryInfo,
    ) -> None:
        """Creates LLMEvaluationRecord with role=SYNTHESIZER."""
        from datetime import UTC, datetime

        from bmad_assist.benchmarking import EvaluatorRole
        from bmad_assist.validation.benchmarking_integration import (
            create_synthesizer_record,
        )

        start_time = datetime(2025, 12, 20, 10, 0, 0, tzinfo=UTC)
        end_time = datetime(2025, 12, 20, 10, 1, 0, tzinfo=UTC)

        record = create_synthesizer_record(
            synthesis_output=valid_synthesis_output,
            workflow_info=sample_workflow_info,
            story_info=sample_story_info,
            provider="claude",
            model="opus-4",
            start_time=start_time,
            end_time=end_time,
            input_tokens=5000,
            output_tokens=2000,
            validator_count=4,
        )

        assert record.evaluator.role == EvaluatorRole.SYNTHESIZER
        assert record.evaluator.role_id is None  # CRITICAL: synthesizer has no role_id

    def test_populates_quality_and_consensus(
        self,
        valid_synthesis_output: str,
        sample_workflow_info: WorkflowInfo,
        sample_story_info: StoryInfo,
    ) -> None:
        """Populates quality and consensus from extracted metrics."""
        from datetime import UTC, datetime

        from bmad_assist.validation.benchmarking_integration import (
            create_synthesizer_record,
        )

        start_time = datetime.now(UTC)
        end_time = datetime.now(UTC)

        record = create_synthesizer_record(
            synthesis_output=valid_synthesis_output,
            workflow_info=sample_workflow_info,
            story_info=sample_story_info,
            provider="claude",
            model="opus-4",
            start_time=start_time,
            end_time=end_time,
            input_tokens=5000,
            output_tokens=2000,
            validator_count=4,
        )

        assert record.quality is not None
        assert record.quality.actionable_ratio == 0.8
        assert record.consensus is not None
        assert record.consensus.agreed_findings == 4

    def test_handles_extraction_failure(
        self,
        sample_workflow_info: WorkflowInfo,
        sample_story_info: StoryInfo,
    ) -> None:
        """Returns None for quality/consensus when extraction fails."""
        from datetime import UTC, datetime

        from bmad_assist.validation.benchmarking_integration import (
            create_synthesizer_record,
        )

        # Output without metrics markers
        bad_output = "## Synthesis Summary\n\nNo metrics here."

        start_time = datetime.now(UTC)
        end_time = datetime.now(UTC)

        record = create_synthesizer_record(
            synthesis_output=bad_output,
            workflow_info=sample_workflow_info,
            story_info=sample_story_info,
            provider="claude",
            model="opus-4",
            start_time=start_time,
            end_time=end_time,
            input_tokens=5000,
            output_tokens=500,
            validator_count=4,
        )

        # Record should still be created, just with None metrics
        assert record is not None
        assert record.quality is None
        assert record.consensus is None

    def test_calculates_duration_from_times(
        self,
        valid_synthesis_output: str,
        sample_workflow_info: WorkflowInfo,
        sample_story_info: StoryInfo,
    ) -> None:
        """Calculates duration_ms from start and end times."""
        from datetime import UTC, datetime

        from bmad_assist.validation.benchmarking_integration import (
            create_synthesizer_record,
        )

        start_time = datetime(2025, 12, 20, 10, 0, 0, tzinfo=UTC)
        end_time = datetime(2025, 12, 20, 10, 0, 30, tzinfo=UTC)  # 30 seconds later

        record = create_synthesizer_record(
            synthesis_output=valid_synthesis_output,
            workflow_info=sample_workflow_info,
            story_info=sample_story_info,
            provider="claude",
            model="opus-4",
            start_time=start_time,
            end_time=end_time,
            input_tokens=5000,
            output_tokens=2000,
            validator_count=4,
        )

        assert record.execution.duration_ms == 30000  # 30 seconds in ms

    def test_sequence_position_is_validator_count(
        self,
        valid_synthesis_output: str,
        sample_workflow_info: WorkflowInfo,
        sample_story_info: StoryInfo,
    ) -> None:
        """Synthesizer runs after all validators, so sequence_position = validator_count."""
        from datetime import UTC, datetime

        from bmad_assist.validation.benchmarking_integration import (
            create_synthesizer_record,
        )

        start_time = datetime.now(UTC)
        end_time = datetime.now(UTC)

        record = create_synthesizer_record(
            synthesis_output=valid_synthesis_output,
            workflow_info=sample_workflow_info,
            story_info=sample_story_info,
            provider="claude",
            model="opus-4",
            start_time=start_time,
            end_time=end_time,
            input_tokens=5000,
            output_tokens=2000,
            validator_count=4,  # 4 validators ran before synthesizer
        )

        assert record.execution.sequence_position == 4


# Type hints for fixtures
if TYPE_CHECKING:
    from bmad_assist.benchmarking import StoryInfo, WorkflowInfo
