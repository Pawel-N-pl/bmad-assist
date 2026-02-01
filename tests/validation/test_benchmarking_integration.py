"""Tests for benchmarking integration with validation orchestrator.

Story 13.4: Orchestrator Integration
Tests cover:
- AC1: Deterministic metrics collection on validator success
- AC2: Parallel extraction after validation
- AC3: Record finalization and merging
- AC4: Workflow variant support
- AC5: Record return for storage
- AC6: Error handling and partial results
- AC7: Integration with existing orchestrator
"""

from __future__ import annotations

import asyncio
import platform
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bmad_assist.benchmarking import (
    CollectorContext,
    DeterministicMetrics,
    EnvironmentInfo,
    EvaluatorInfo,
    EvaluatorRole,
    ExecutionTelemetry,
    LLMEvaluationRecord,
    MetricsExtractionError,
    PatchInfo,
    StoryInfo,
    WorkflowInfo,
)
from bmad_assist.benchmarking.collector import (
    LinguisticMetrics,
    ReasoningSignals,
    StructureMetrics,
)
from bmad_assist.validation.anonymizer import ValidationOutput


class TestHelperFunctions:
    """Test helper functions for benchmarking integration."""

    @pytest.fixture
    def sample_validation_output(self) -> ValidationOutput:
        """Create sample validation output for testing."""
        return ValidationOutput(
            provider="claude-sonnet",
            model="sonnet-4",
            content="# Validation Report\n\nTest content with findings.",
            timestamp=datetime.now(UTC),
            duration_ms=5000,
            token_count=500,
            provider_session_id="session-123-abc",
        )

    @pytest.fixture
    def sample_deterministic_metrics(self) -> DeterministicMetrics:
        """Create sample deterministic metrics for testing."""
        structure = StructureMetrics(
            char_count=1000,
            heading_count=5,
            list_depth_max=2,
            code_block_count=3,
            sections_detected=("Summary", "Findings", "Recommendations"),
        )
        linguistic = LinguisticMetrics(
            avg_sentence_length=15.5,
            vocabulary_richness=0.65,
            flesch_reading_ease=45.0,
            vague_terms_count=2,
        )
        reasoning = ReasoningSignals(
            cites_prd=True,
            cites_architecture=True,
            cites_story_sections=True,
            uses_conditionals=True,
            uncertainty_phrases_count=1,
            confidence_phrases_count=3,
        )
        return DeterministicMetrics(
            structure=structure,
            linguistic=linguistic,
            reasoning=reasoning,
            collected_at=datetime.now(UTC),
        )


class TestCreateCollectorContext:
    """Test _create_collector_context helper function."""

    def test_creates_context_with_story_info(self) -> None:
        """Creates CollectorContext with story epic and number."""
        from bmad_assist.validation.benchmarking_integration import (
            _create_collector_context,
        )

        timestamp = datetime.now(UTC)
        context = _create_collector_context(
            story_epic=13,
            story_num=4,
            timestamp=timestamp,
        )

        assert context.story_epic == 13
        assert context.story_num == 4
        assert context.timestamp == timestamp


class TestParseRoleId:
    """Test _parse_role_id helper function with fallback logic (Story 22.5)."""

    def test_valid_anonymous_ids_parse_correctly(self) -> None:
        """Valid anonymized IDs ('Validator A', 'Validator B') parse correctly."""
        from bmad_assist.validation.benchmarking_integration import (
            _parse_role_id,
        )

        assert _parse_role_id("Validator A", 0, EvaluatorRole.VALIDATOR) == "a"
        assert _parse_role_id("Validator B", 1, EvaluatorRole.VALIDATOR) == "b"
        assert _parse_role_id("Validator Z", 25, EvaluatorRole.VALIDATOR) == "z"

    def test_case_insensitive_parsing(self) -> None:
        """Case-insensitive parsing ('VALIDATOR A' -> 'a', 'validator a' -> 'a')."""
        from bmad_assist.validation.benchmarking_integration import (
            _parse_role_id,
        )

        assert _parse_role_id("VALIDATOR A", 0, EvaluatorRole.VALIDATOR) == "a"
        assert _parse_role_id("validator a", 0, EvaluatorRole.VALIDATOR) == "a"
        assert _parse_role_id("VaLiDaToR A", 0, EvaluatorRole.VALIDATOR) == "a"

    def test_empty_string_generates_fallback(self) -> None:
        """Empty string generates valid fallback based on sequence_position."""
        from bmad_assist.validation.benchmarking_integration import (
            _parse_role_id,
        )

        assert _parse_role_id("", 0, EvaluatorRole.VALIDATOR) == "a"
        assert _parse_role_id("", 1, EvaluatorRole.VALIDATOR) == "b"
        assert _parse_role_id("", 25, EvaluatorRole.VALIDATOR) == "z"

    def test_whitespace_only_string_generates_fallback(self) -> None:
        """Whitespace-only string generates valid fallback based on sequence_position."""
        from bmad_assist.validation.benchmarking_integration import (
            _parse_role_id,
        )

        assert _parse_role_id("   ", 0, EvaluatorRole.VALIDATOR) == "a"
        assert _parse_role_id("\t\t", 1, EvaluatorRole.VALIDATOR) == "b"
        assert _parse_role_id("\n", 2, EvaluatorRole.VALIDATOR) == "c"

    def test_none_value_generates_fallback(self) -> None:
        """None value generates valid fallback based on sequence_position."""
        from bmad_assist.validation.benchmarking_integration import (
            _parse_role_id,
        )

        assert _parse_role_id(None, 0, EvaluatorRole.VALIDATOR) == "a"
        assert _parse_role_id(None, 1, EvaluatorRole.VALIDATOR) == "b"
        assert _parse_role_id(None, 10, EvaluatorRole.VALIDATOR) == "k"

    def test_malformed_identifier_uses_fallback(self) -> None:
        """Malformed identifier (e.g., 'gemini-gemini-3-pro-preview') uses fallback."""
        from bmad_assist.validation.benchmarking_integration import (
            _parse_role_id,
        )

        assert _parse_role_id("gemini-gemini-3-pro-preview", 0, EvaluatorRole.VALIDATOR) == "a"
        assert _parse_role_id("multi-word-identifier", 1, EvaluatorRole.VALIDATOR) == "b"
        assert _parse_role_id("12345", 2, EvaluatorRole.VALIDATOR) == "c"

    def test_single_word_without_space_uses_fallback(self) -> None:
        """Single word without space (e.g., 'Unknown') uses fallback."""
        from bmad_assist.validation.benchmarking_integration import (
            _parse_role_id,
        )

        assert _parse_role_id("Unknown", 0, EvaluatorRole.VALIDATOR) == "a"
        assert _parse_role_id("Invalid", 1, EvaluatorRole.VALIDATOR) == "b"
        assert _parse_role_id("ABC", 2, EvaluatorRole.VALIDATOR) == "c"

    def test_position_wraps_modulo_26(self) -> None:
        """sequence_position 0 -> 'a', 1 -> 'b', 25 -> 'z', 26 -> 'a', 27 -> 'b' (wraps)."""
        from bmad_assist.validation.benchmarking_integration import (
            _parse_role_id,
        )

        # Normal range
        assert _parse_role_id(None, 0, EvaluatorRole.VALIDATOR) == "a"
        assert _parse_role_id(None, 1, EvaluatorRole.VALIDATOR) == "b"
        assert _parse_role_id(None, 25, EvaluatorRole.VALIDATOR) == "z"

        # Wrapping: 26 -> 'a', 27 -> 'b', 52 -> 'a'
        assert _parse_role_id(None, 26, EvaluatorRole.VALIDATOR) == "a"
        assert _parse_role_id(None, 27, EvaluatorRole.VALIDATOR) == "b"
        assert _parse_role_id(None, 52, EvaluatorRole.VALIDATOR) == "a"

    def test_synthesizer_role_always_returns_none(self) -> None:
        """SYNTHESIZER role always gets role_id=None regardless of anonymized_id."""
        from bmad_assist.validation.benchmarking_integration import (
            _parse_role_id,
        )

        assert _parse_role_id("Validator A", 0, EvaluatorRole.SYNTHESIZER) is None
        assert _parse_role_id(None, 0, EvaluatorRole.SYNTHESIZER) is None
        assert _parse_role_id("   ", 1, EvaluatorRole.SYNTHESIZER) is None

    def test_master_role_always_returns_none(self) -> None:
        """MASTER role always gets role_id=None regardless of anonymized_id."""
        from bmad_assist.validation.benchmarking_integration import (
            _parse_role_id,
        )

        assert _parse_role_id("Validator A", 0, EvaluatorRole.MASTER) is None
        assert _parse_role_id(None, 0, EvaluatorRole.MASTER) is None
        assert _parse_role_id("Invalid", 1, EvaluatorRole.MASTER) is None

    def test_pydantic_validation_succeeds_for_all_validators(self) -> None:
        """Pydantic validation succeeds for all VALIDATOR role test cases."""
        from bmad_assist.benchmarking import EvaluatorInfo
        from bmad_assist.validation.benchmarking_integration import (
            _parse_role_id,
        )

        test_cases = [
            ("Validator A", 0),
            ("VALIDATOR B", 1),
            ("", 2),
            ("   ", 3),
            (None, 4),
            ("gemini-gemini-3-pro-preview", 5),
            ("Unknown", 6),
        ]

        for anonymized_id, pos in test_cases:
            role_id = _parse_role_id(anonymized_id, pos, EvaluatorRole.VALIDATOR)
            # Should not raise ValidationError
            info = EvaluatorInfo(
                provider="test",
                model="test",
                role=EvaluatorRole.VALIDATOR,
                role_id=role_id,
                session_id="test",
            )
            assert info.role_id is not None
            assert len(info.role_id) == 1
            assert "a" <= info.role_id <= "z"

    def test_pydantic_validation_rejects_invalid_inputs(self) -> None:
        """Pydantic validation rejects non-ASCII, uppercase, multi-char, numbers.

        Story 22.5 synthesis fix: Validator accepts only ASCII lowercase a-z.
        Unicode lowercase letters (ä, é, ñ) must be rejected to prevent data corruption.
        """
        from pydantic import ValidationError

        from bmad_assist.benchmarking import EvaluatorInfo

        invalid_cases = [
            "ä",  # Unicode lowercase (German umlaut)
            "é",  # Unicode lowercase (French accent)
            "ñ",  # Unicode lowercase (Spanish tilde)
            "ø",  # Unicode lowercase (Nordic)
            "A",  # Uppercase
            "Z",  # Uppercase
            "1",  # Number
            "-",  # Symbol
            "ab",  # Multi-char
            "",  # Empty string
        ]

        for invalid_id in invalid_cases:
            with pytest.raises(ValidationError, match="role_id must be single lowercase"):
                EvaluatorInfo(
                    provider="test",
                    model="test",
                    role=EvaluatorRole.VALIDATOR,
                    role_id=invalid_id,
                    session_id="test",
                )


class TestCreateEvaluatorInfo:
    """Test _create_evaluator_info helper function."""

    @pytest.fixture
    def sample_output(self) -> ValidationOutput:
        """Sample validation output."""
        return ValidationOutput(
            provider="claude",
            model="sonnet-4",
            content="test",
            timestamp=datetime.now(UTC),
            duration_ms=1000,
            token_count=100,
            provider_session_id="session-abc",
        )

    def test_uses_provider_model_directly(self, sample_output: ValidationOutput) -> None:
        """Uses provider and model directly from ValidationOutput."""
        from bmad_assist.validation.benchmarking_integration import (
            _create_evaluator_info,
        )

        info = _create_evaluator_info(
            validation_output=sample_output,
            role=EvaluatorRole.VALIDATOR,
            anonymized_id="Validator A",
            sequence_position=0,
        )

        assert info.provider == "claude"
        assert info.model == "sonnet-4"

    def test_derives_role_id_from_anonymized(self, sample_output: ValidationOutput) -> None:
        """Derives role_id from anonymized ID: 'Validator A' -> 'a'."""
        from bmad_assist.validation.benchmarking_integration import (
            _create_evaluator_info,
        )

        info = _create_evaluator_info(
            validation_output=sample_output,
            role=EvaluatorRole.VALIDATOR,
            anonymized_id="Validator B",
            sequence_position=1,
        )

        assert info.role_id == "b"

    def test_assigns_session_id(self, sample_output: ValidationOutput) -> None:
        """Assigns session_id from validation output."""
        from bmad_assist.validation.benchmarking_integration import (
            _create_evaluator_info,
        )

        info = _create_evaluator_info(
            validation_output=sample_output,
            role=EvaluatorRole.VALIDATOR,
            anonymized_id="Validator A",
            sequence_position=0,
        )

        assert info.session_id == "session-abc"

    def test_handles_provider_without_dash(self) -> None:
        """Handles provider without dash (uses model field)."""
        from bmad_assist.validation.benchmarking_integration import (
            _create_evaluator_info,
        )

        output = ValidationOutput(
            provider="gemini",
            model="gemini-2.0-flash",
            content="test",
            timestamp=datetime.now(UTC),
            duration_ms=1000,
            token_count=100,
            provider_session_id=None,
        )

        info = _create_evaluator_info(
            validation_output=output,
            role=EvaluatorRole.VALIDATOR,
            anonymized_id="Validator C",
            sequence_position=2,
        )

        assert info.provider == "gemini"
        assert info.model == "gemini-2.0-flash"
        assert info.role_id == "c"


class TestCreateExecutionTelemetry:
    """Test _create_execution_telemetry helper function."""

    def test_calculates_end_time(self) -> None:
        """Calculates end_time from timestamp + duration."""
        from bmad_assist.validation.benchmarking_integration import (
            _create_execution_telemetry,
        )

        start = datetime(2025, 12, 20, 10, 0, 0, tzinfo=UTC)
        output = ValidationOutput(
            provider="claude-sonnet",
            model="sonnet-4",
            content="test",
            timestamp=start,
            duration_ms=5000,
            token_count=500,
            provider_session_id=None,
        )

        telemetry = _create_execution_telemetry(output, sequence_position=0)

        assert telemetry.start_time == start
        assert telemetry.end_time == start + timedelta(milliseconds=5000)
        assert telemetry.duration_ms == 5000
        assert telemetry.output_tokens == 500
        assert telemetry.sequence_position == 0


class TestCreateEnvironmentInfo:
    """Test _create_environment_info helper function."""

    def test_captures_version_info(self) -> None:
        """Captures bmad-assist and Python version."""
        from bmad_assist.validation.benchmarking_integration import (
            _create_environment_info,
        )

        info = _create_environment_info()

        from bmad_assist import __version__

        assert info.bmad_assist_version == __version__
        assert (
            info.python_version
            == f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
        assert info.platform == platform.system()


class TestCreateWorkflowInfo:
    """Test _create_workflow_info helper function."""

    def test_creates_workflow_info_with_variant(self) -> None:
        """Creates WorkflowInfo with workflow variant."""
        from bmad_assist.validation.benchmarking_integration import (
            _create_workflow_info,
        )

        info = _create_workflow_info(
            workflow_id="validate-story",
            variant="experiment-a",
            patch_applied=True,
            patch_path=Path("/path/to/patch.yaml"),
        )

        assert info.id == "validate-story"
        assert info.variant == "experiment-a"
        assert info.patch.applied is True

    def test_default_variant(self) -> None:
        """Default variant is 'default'."""
        from bmad_assist.validation.benchmarking_integration import (
            _create_workflow_info,
        )

        info = _create_workflow_info(
            workflow_id="validate-story",
            variant="default",
            patch_applied=False,
        )

        assert info.variant == "default"
        assert info.patch.applied is False


class TestCreateStoryInfo:
    """Test _create_story_info helper function."""

    def test_creates_story_info(self) -> None:
        """Creates StoryInfo with epic, num, title, and complexity flags."""
        from bmad_assist.validation.benchmarking_integration import (
            _create_story_info,
        )

        complexity = {"has_ui": True, "has_api": False}
        info = _create_story_info(
            epic_num=13,
            story_num=4,
            title="Orchestrator Integration",
            complexity_flags=complexity,
        )

        assert info.epic_num == 13
        assert info.story_num == 4
        assert info.title == "Orchestrator Integration"
        assert info.complexity_flags == {"has_ui": True, "has_api": False}


class TestFinalizeEvaluationRecord:
    """Test _finalize_evaluation_record helper function."""

    @pytest.fixture
    def sample_workflow_info(self) -> WorkflowInfo:
        """Sample workflow info."""
        return WorkflowInfo(
            id="validate-story",
            version="1.0.0",
            variant="default",
            patch=PatchInfo(applied=False),
        )

    @pytest.fixture
    def sample_story_info(self) -> StoryInfo:
        """Sample story info."""
        return StoryInfo(
            epic_num=13,
            story_num=4,
            title="Orchestrator Integration",
            complexity_flags={},
        )

    @pytest.fixture
    def sample_validation_output(self) -> ValidationOutput:
        """Sample validation output."""
        return ValidationOutput(
            provider="claude-sonnet",
            model="sonnet-4",
            content="# Validation Report\n\nTest.",
            timestamp=datetime.now(UTC),
            duration_ms=5000,
            token_count=500,
            provider_session_id="session-123",
        )

    @pytest.fixture
    def sample_deterministic(self) -> DeterministicMetrics:
        """Sample deterministic metrics."""
        return DeterministicMetrics(
            structure=StructureMetrics(
                char_count=100,
                heading_count=2,
                list_depth_max=1,
                code_block_count=0,
                sections_detected=("Report",),
            ),
            linguistic=LinguisticMetrics(
                avg_sentence_length=10.0,
                vocabulary_richness=0.5,
                flesch_reading_ease=50.0,
                vague_terms_count=1,
            ),
            reasoning=ReasoningSignals(
                cites_prd=True,
                cites_architecture=False,
                cites_story_sections=True,
                uses_conditionals=False,
                uncertainty_phrases_count=0,
                confidence_phrases_count=1,
            ),
            collected_at=datetime.now(UTC),
        )

    def test_merges_all_sources_into_record(
        self,
        sample_workflow_info: WorkflowInfo,
        sample_story_info: StoryInfo,
        sample_validation_output: ValidationOutput,
        sample_deterministic: DeterministicMetrics,
    ) -> None:
        """Merges deterministic + extracted metrics into LLMEvaluationRecord."""
        from bmad_assist.benchmarking.extraction import (
            ExtractedMetrics,
            FindingsData,
            LinguisticData,
            QualityData,
        )
        from bmad_assist.validation.benchmarking_integration import (
            _finalize_evaluation_record,
        )

        extracted = ExtractedMetrics(
            findings=FindingsData(
                total_count=5,
                by_severity={"major": 2, "minor": 3},
                by_category={"correctness": 3, "clarity": 2},
                has_fix_count=4,
                has_location_count=5,
                has_evidence_count=3,
            ),
            complexity_flags={"has_ui": True},
            linguistic=LinguisticData(formality_score=0.7, sentiment="neutral"),
            quality=QualityData(
                actionable_ratio=0.8,
                specificity_score=0.75,
                evidence_quality=0.6,
                internal_consistency=0.9,
            ),
            anomalies=(),
            extracted_at=datetime.now(UTC),
        )

        record = _finalize_evaluation_record(
            validation_output=sample_validation_output,
            deterministic=sample_deterministic,
            extracted=extracted,
            workflow_info=sample_workflow_info,
            story_info=sample_story_info,
            anonymized_id="Validator A",
            sequence_position=0,
        )

        # Check record type
        assert isinstance(record, LLMEvaluationRecord)

        # Check nested models populated
        assert record.workflow == sample_workflow_info
        assert record.story == sample_story_info
        assert record.evaluator.role == EvaluatorRole.VALIDATOR
        assert record.evaluator.role_id == "a"

        # Check output from deterministic
        assert record.output.char_count == 100
        assert record.output.heading_count == 2

        # Check findings from extracted
        assert record.findings is not None
        assert record.findings.total_count == 5

        # Check quality from extracted
        assert record.quality is not None
        assert record.quality.actionable_ratio == 0.8

        # Check consensus and ground_truth remain None
        assert record.consensus is None
        assert record.ground_truth is None

    def test_validates_record_against_pydantic_schema(
        self,
        sample_workflow_info: WorkflowInfo,
        sample_story_info: StoryInfo,
        sample_validation_output: ValidationOutput,
        sample_deterministic: DeterministicMetrics,
    ) -> None:
        """Validates merged record against Pydantic schema."""
        from bmad_assist.benchmarking.extraction import (
            ExtractedMetrics,
            FindingsData,
            LinguisticData,
            QualityData,
        )
        from bmad_assist.validation.benchmarking_integration import (
            _finalize_evaluation_record,
        )

        extracted = ExtractedMetrics(
            findings=FindingsData(
                total_count=0,
                by_severity={},
                by_category={},
                has_fix_count=0,
                has_location_count=0,
                has_evidence_count=0,
            ),
            complexity_flags={},
            linguistic=LinguisticData(formality_score=0.5, sentiment="neutral"),
            quality=QualityData(
                actionable_ratio=0.5,
                specificity_score=0.5,
                evidence_quality=0.5,
                internal_consistency=0.5,
            ),
            anomalies=(),
            extracted_at=datetime.now(UTC),
        )

        record = _finalize_evaluation_record(
            validation_output=sample_validation_output,
            deterministic=sample_deterministic,
            extracted=extracted,
            workflow_info=sample_workflow_info,
            story_info=sample_story_info,
            anonymized_id="Validator B",
            sequence_position=1,
        )

        # Should be valid Pydantic model (no exception)
        assert record.record_id is not None
        assert record.created_at is not None

        # Can serialize to dict
        data = record.model_dump()
        assert "record_id" in data
        assert "workflow" in data
        assert "story" in data


class TestValidationPhaseResultExtension:
    """Test ValidationPhaseResult extension with evaluation_records."""

    def test_has_evaluation_records_field(self) -> None:
        """ValidationPhaseResult has evaluation_records field."""
        from bmad_assist.validation.orchestrator import ValidationPhaseResult

        result = ValidationPhaseResult(
            anonymized_validations=[],
            session_id="test-session",
            validation_count=0,
        )

        assert hasattr(result, "evaluation_records")
        assert result.evaluation_records == []

    def test_evaluation_records_not_in_to_dict(self) -> None:
        """evaluation_records not serialized in to_dict (too large)."""
        from bmad_assist.validation.orchestrator import ValidationPhaseResult

        # Create minimal mock record
        mock_record = MagicMock(spec=LLMEvaluationRecord)

        result = ValidationPhaseResult(
            anonymized_validations=[],
            session_id="test-session",
            validation_count=2,
            validators=["a", "b"],
            evaluation_records=[mock_record],
        )

        data = result.to_dict()

        # Records should NOT be in to_dict output
        assert "evaluation_records" not in data
        assert data["validation_count"] == 2
        assert data["validators"] == ["a", "b"]


class TestSafeExtractMetrics:
    """Test _safe_extract_metrics error handling."""

    def test_returns_none_on_extraction_error(self) -> None:
        """Returns None when extraction fails."""
        from bmad_assist.validation.benchmarking_integration import (
            _safe_extract_metrics,
        )
        from bmad_assist.benchmarking.extraction import ExtractionContext

        context = ExtractionContext(
            story_epic=13,
            story_num=4,
            timestamp=datetime.now(UTC),
            project_root=Path("/tmp"),
        )

        # Mock extract_metrics_async to raise error
        with patch(
            "bmad_assist.validation.benchmarking_integration.extract_metrics_async"
        ) as mock_extract:
            mock_extract.side_effect = MetricsExtractionError("Test error")

            result = asyncio.run(_safe_extract_metrics("raw output", context))

            assert result is None

    def test_returns_metrics_on_success(self) -> None:
        """Returns ExtractedMetrics when extraction succeeds."""
        from bmad_assist.validation.benchmarking_integration import (
            _safe_extract_metrics,
        )
        from bmad_assist.benchmarking.extraction import (
            ExtractionContext,
            ExtractedMetrics,
            FindingsData,
            LinguisticData,
            QualityData,
        )

        context = ExtractionContext(
            story_epic=13,
            story_num=4,
            timestamp=datetime.now(UTC),
            project_root=Path("/tmp"),
        )

        mock_metrics = ExtractedMetrics(
            findings=FindingsData(
                total_count=0,
                by_severity={},
                by_category={},
                has_fix_count=0,
                has_location_count=0,
                has_evidence_count=0,
            ),
            complexity_flags={},
            linguistic=LinguisticData(formality_score=0.5, sentiment="neutral"),
            quality=QualityData(
                actionable_ratio=0.5,
                specificity_score=0.5,
                evidence_quality=0.5,
                internal_consistency=0.5,
            ),
            anomalies=(),
            extracted_at=datetime.now(UTC),
        )

        with patch(
            "bmad_assist.validation.benchmarking_integration.extract_metrics_async"
        ) as mock_extract:
            # Make it an async function
            async def async_return(*args: object, **kwargs: object) -> ExtractedMetrics:
                return mock_metrics

            mock_extract.side_effect = async_return

            result = asyncio.run(_safe_extract_metrics("raw output", context))

            assert result is not None
            assert result.findings.total_count == 0


class TestParallelExtraction:
    """Test _run_parallel_extraction function."""

    @pytest.fixture
    def sample_outputs(self) -> list[ValidationOutput]:
        """Create sample validation outputs."""
        return [
            ValidationOutput(
                provider="claude-sonnet",
                model="sonnet-4",
                content="# Report A\n\nContent A.",
                timestamp=datetime.now(UTC),
                duration_ms=1000,
                token_count=100,
                provider_session_id=None,
            ),
            ValidationOutput(
                provider="gemini-flash",
                model="gemini-2.0-flash",
                content="# Report B\n\nContent B.",
                timestamp=datetime.now(UTC),
                duration_ms=1500,
                token_count=150,
                provider_session_id=None,
            ),
        ]

    @pytest.fixture
    def sample_deterministics(self) -> list[DeterministicMetrics]:
        """Create sample deterministic metrics."""
        metrics = DeterministicMetrics(
            structure=StructureMetrics(
                char_count=100,
                heading_count=1,
                list_depth_max=0,
                code_block_count=0,
                sections_detected=("Report",),
            ),
            linguistic=LinguisticMetrics(
                avg_sentence_length=10.0,
                vocabulary_richness=0.5,
                flesch_reading_ease=50.0,
                vague_terms_count=0,
            ),
            reasoning=ReasoningSignals(
                cites_prd=False,
                cites_architecture=False,
                cites_story_sections=False,
                uses_conditionals=False,
                uncertainty_phrases_count=0,
                confidence_phrases_count=0,
            ),
            collected_at=datetime.now(UTC),
        )
        return [metrics, metrics]

    def test_returns_list_same_length_as_inputs(
        self,
        sample_outputs: list[ValidationOutput],
        sample_deterministics: list[DeterministicMetrics],
    ) -> None:
        """Returns list with same length as inputs."""
        from bmad_assist.validation.benchmarking_integration import (
            _run_parallel_extraction,
        )

        with patch(
            "bmad_assist.validation.benchmarking_integration._safe_extract_metrics"
        ) as mock_safe:
            # Return None for all
            async def async_return(*args: object, **kwargs: object) -> None:
                return None

            mock_safe.side_effect = async_return

            results = asyncio.run(
                _run_parallel_extraction(
                    successful_outputs=sample_outputs,
                    deterministic_results=sample_deterministics,
                    project_root=Path("/tmp"),
                    epic_num=13,
                    story_num=4,
                    run_timestamp=datetime.now(UTC),
                    timeout=300,
                )
            )

            assert len(results) == len(sample_outputs)


class TestBenchmarkingDisabled:
    """Test benchmarking disabled via config."""

    def test_skips_collection_when_disabled(self) -> None:
        """Skips all benchmarking when benchmarking.enabled=False."""
        from bmad_assist.validation.benchmarking_integration import (
            should_collect_benchmarking,
        )

        # Create config with benchmarking disabled
        mock_config = MagicMock()
        mock_config.benchmarking.enabled = False

        assert should_collect_benchmarking(mock_config) is False

    def test_collects_when_enabled(self) -> None:
        """Collects benchmarking when benchmarking.enabled=True."""
        from bmad_assist.validation.benchmarking_integration import (
            should_collect_benchmarking,
        )

        mock_config = MagicMock()
        mock_config.benchmarking.enabled = True

        assert should_collect_benchmarking(mock_config) is True
