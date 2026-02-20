"""Tests for benchmarking schema module.

Tests cover:
- MetricSource enum values (AC2)
- EvaluatorRole enum values (AC1)
- source_field helper function (AC2)
- All Pydantic models (AC1, AC3, AC4)
- Module exports (AC5)
- Identity field auto-generation (AC6)
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from pydantic.fields import FieldInfo


class TestMetricSourceEnum:
    """Test AC2: MetricSource enum with 5 source types."""

    def test_metric_source_enum_has_five_values(self) -> None:
        """Verify all 5 source types exist."""
        from bmad_assist.benchmarking import MetricSource

        assert len(MetricSource) == 5
        assert MetricSource.DETERMINISTIC.value == "deterministic"
        assert MetricSource.LLM_EXTRACTED.value == "llm_extracted"
        assert MetricSource.LLM_ASSESSED.value == "llm_assessed"
        assert MetricSource.SYNTHESIZER.value == "synthesizer"
        assert MetricSource.POST_HOC.value == "post_hoc"

    def test_metric_source_is_string_enum(self) -> None:
        """Verify MetricSource is a string enum."""
        from bmad_assist.benchmarking import MetricSource

        # String enum allows direct string comparison
        assert MetricSource.DETERMINISTIC == "deterministic"


class TestEvaluatorRoleEnum:
    """Test AC1: EvaluatorRole enum with 3 role types."""

    def test_evaluator_role_enum_has_three_values(self) -> None:
        """Verify all 3 role types exist."""
        from bmad_assist.benchmarking import EvaluatorRole

        assert len(EvaluatorRole) == 3
        assert EvaluatorRole.VALIDATOR.value == "validator"
        assert EvaluatorRole.SYNTHESIZER.value == "synthesizer"
        assert EvaluatorRole.MASTER.value == "master"

    def test_evaluator_role_is_string_enum(self) -> None:
        """Verify EvaluatorRole is a string enum."""
        from bmad_assist.benchmarking import EvaluatorRole

        assert EvaluatorRole.VALIDATOR == "validator"


class TestSourceFieldHelper:
    """Test AC2: source_field helper function."""

    def test_source_field_returns_field_info(self) -> None:
        """Verify source_field returns FieldInfo type."""
        from bmad_assist.benchmarking import MetricSource, source_field

        result = source_field(MetricSource.DETERMINISTIC, default=0)
        assert isinstance(result, FieldInfo)

    def test_source_field_creates_proper_annotations(self) -> None:
        """Verify source_field adds source annotation to json_schema_extra."""
        from bmad_assist.benchmarking import MetricSource, source_field

        result = source_field(MetricSource.LLM_EXTRACTED, default="test")

        # Source should be stored as string value, not enum
        assert result.json_schema_extra is not None
        assert result.json_schema_extra["source"] == "llm_extracted"

    def test_source_field_preserves_default(self) -> None:
        """Verify source_field preserves the default value."""
        from bmad_assist.benchmarking import MetricSource, source_field

        result = source_field(MetricSource.DETERMINISTIC, default=42)
        assert result.default == 42

    def test_source_field_preserves_extra_kwargs(self) -> None:
        """Verify source_field passes through additional Field kwargs."""
        from bmad_assist.benchmarking import MetricSource, source_field

        result = source_field(
            MetricSource.DETERMINISTIC,
            default=0,
            description="Test description",
        )
        assert result.description == "Test description"

    def test_source_field_merges_json_schema_extra(self) -> None:
        """Verify source_field merges existing json_schema_extra with source."""
        from bmad_assist.benchmarking import MetricSource, source_field

        result = source_field(
            MetricSource.DETERMINISTIC,
            default=0,
            json_schema_extra={"example": 100},
        )
        assert result.json_schema_extra is not None
        assert result.json_schema_extra["source"] == "deterministic"
        assert result.json_schema_extra["example"] == 100


class TestBenchmarkingError:
    """Test AC5: BenchmarkingError exception class."""

    def test_benchmarking_error_inherits_bmad_assist_error(self) -> None:
        """Verify BenchmarkingError inherits from BmadAssistError."""
        from bmad_assist.benchmarking import BenchmarkingError
        from bmad_assist.core.exceptions import BmadAssistError

        assert issubclass(BenchmarkingError, BmadAssistError)

    def test_benchmarking_error_can_be_raised(self) -> None:
        """Verify BenchmarkingError can be raised with message."""
        from bmad_assist.benchmarking import BenchmarkingError

        with pytest.raises(BenchmarkingError, match="Test error message"):
            raise BenchmarkingError("Test error message")


class TestPatchInfo:
    """Test AC3: PatchInfo model."""

    def test_patch_info_all_fields(self) -> None:
        """Verify PatchInfo contains all required fields."""
        from bmad_assist.benchmarking import PatchInfo

        patch = PatchInfo(
            applied=True,
            id="test-patch-v1",
            version="1.0.0",
            file_hash="abc123def456",
        )
        assert patch.applied is True
        assert patch.id == "test-patch-v1"
        assert patch.version == "1.0.0"
        assert patch.file_hash == "abc123def456"

    def test_patch_info_optional_fields_default_none(self) -> None:
        """Verify PatchInfo optional fields default to None."""
        from bmad_assist.benchmarking import PatchInfo

        patch = PatchInfo(applied=False)
        assert patch.applied is False
        assert patch.id is None
        assert patch.version is None
        assert patch.file_hash is None


class TestWorkflowInfo:
    """Test AC1, AC3: WorkflowInfo model with nested PatchInfo."""

    def test_workflow_info_with_patch(self) -> None:
        """Verify WorkflowInfo contains nested PatchInfo."""
        from bmad_assist.benchmarking import PatchInfo, WorkflowInfo

        workflow = WorkflowInfo(
            id="create-story",
            version="1.0.0",
            variant="default",
            patch=PatchInfo(applied=True, id="patch-1"),
        )
        assert workflow.id == "create-story"
        assert workflow.version == "1.0.0"
        assert workflow.variant == "default"
        assert workflow.patch.applied is True
        assert workflow.patch.id == "patch-1"


class TestStoryInfo:
    """Test AC1: StoryInfo model with complexity_flags."""

    def test_story_info_all_fields(self) -> None:
        """Verify StoryInfo contains all required fields."""
        from bmad_assist.benchmarking import StoryInfo

        story = StoryInfo(
            epic_num=13,
            story_num=1,
            title="Benchmarking Schema",
            complexity_flags={
                "has_ui_changes": False,
                "has_api_changes": True,
                "has_db_changes": False,
                "has_security_impact": False,
                "requires_migration": False,
            },
        )
        assert story.epic_num == 13
        assert story.story_num == 1
        assert story.title == "Benchmarking Schema"
        assert story.complexity_flags["has_api_changes"] is True

    def test_complexity_flags_dict_type(self) -> None:
        """Verify complexity_flags is dict[str, bool]."""
        from bmad_assist.benchmarking import StoryInfo

        story = StoryInfo(
            epic_num=1,
            story_num=1,
            title="Test",
            complexity_flags={"custom_flag": True},
        )
        assert isinstance(story.complexity_flags, dict)
        assert story.complexity_flags["custom_flag"] is True


class TestEvaluatorInfo:
    """Test AC1, AC4: EvaluatorInfo model with role_id validation."""

    def test_evaluator_info_valid_role_id(self) -> None:
        """Verify EvaluatorInfo accepts valid role_id (a-z)."""
        from bmad_assist.benchmarking import EvaluatorInfo, EvaluatorRole

        for letter in "abcdefghijklmnopqrstuvwxyz":
            evaluator = EvaluatorInfo(
                provider="claude",
                model="opus-4",
                role=EvaluatorRole.VALIDATOR,
                role_id=letter,
                session_id="session-123",
            )
            assert evaluator.role_id == letter

    def test_evaluator_info_role_id_none_for_synthesizer(self) -> None:
        """Verify EvaluatorInfo accepts None role_id for synthesizer."""
        from bmad_assist.benchmarking import EvaluatorInfo, EvaluatorRole

        evaluator = EvaluatorInfo(
            provider="claude",
            model="opus-4",
            role=EvaluatorRole.SYNTHESIZER,
            role_id=None,
            session_id="session-123",
        )
        assert evaluator.role_id is None

    def test_evaluator_info_role_id_invalid_uppercase(self) -> None:
        """Verify EvaluatorInfo rejects uppercase role_id."""
        from bmad_assist.benchmarking import EvaluatorInfo, EvaluatorRole

        with pytest.raises(ValidationError, match="role_id"):
            EvaluatorInfo(
                provider="claude",
                model="opus-4",
                role=EvaluatorRole.VALIDATOR,
                role_id="A",  # Uppercase - invalid
                session_id="session-123",
            )

    def test_evaluator_info_role_id_invalid_number(self) -> None:
        """Verify EvaluatorInfo rejects numeric role_id."""
        from bmad_assist.benchmarking import EvaluatorInfo, EvaluatorRole

        with pytest.raises(ValidationError, match="role_id"):
            EvaluatorInfo(
                provider="claude",
                model="opus-4",
                role=EvaluatorRole.VALIDATOR,
                role_id="1",  # Number - invalid
                session_id="session-123",
            )

    def test_evaluator_info_role_id_invalid_multi_char(self) -> None:
        """Verify EvaluatorInfo rejects multi-character role_id."""
        from bmad_assist.benchmarking import EvaluatorInfo, EvaluatorRole

        with pytest.raises(ValidationError, match="role_id"):
            EvaluatorInfo(
                provider="claude",
                model="opus-4",
                role=EvaluatorRole.VALIDATOR,
                role_id="ab",  # Multiple chars - invalid
                session_id="session-123",
            )

    def test_evaluator_info_validator_requires_role_id(self) -> None:
        """Verify VALIDATOR role requires role_id."""
        from bmad_assist.benchmarking import EvaluatorInfo, EvaluatorRole

        with pytest.raises(ValidationError, match="role_id required for validators"):
            EvaluatorInfo(
                provider="claude",
                model="opus-4",
                role=EvaluatorRole.VALIDATOR,
                role_id=None,  # Missing for validator - invalid
                session_id="session-123",
            )

    def test_evaluator_info_synthesizer_rejects_role_id(self) -> None:
        """Verify SYNTHESIZER role rejects non-None role_id."""
        from bmad_assist.benchmarking import EvaluatorInfo, EvaluatorRole

        with pytest.raises(ValidationError, match="role_id must be None"):
            EvaluatorInfo(
                provider="claude",
                model="opus-4",
                role=EvaluatorRole.SYNTHESIZER,
                role_id="a",  # Should be None for synthesizer
                session_id="session-123",
            )

    def test_evaluator_info_master_rejects_role_id(self) -> None:
        """Verify MASTER role rejects non-None role_id."""
        from bmad_assist.benchmarking import EvaluatorInfo, EvaluatorRole

        with pytest.raises(ValidationError, match="role_id must be None"):
            EvaluatorInfo(
                provider="claude",
                model="opus-4",
                role=EvaluatorRole.MASTER,
                role_id="a",  # Should be None for master
                session_id="session-123",
            )

    def test_evaluator_info_master_accepts_none_role_id(self) -> None:
        """Verify MASTER role accepts None role_id."""
        from bmad_assist.benchmarking import EvaluatorInfo, EvaluatorRole

        evaluator = EvaluatorInfo(
            provider="claude",
            model="opus-4",
            role=EvaluatorRole.MASTER,
            role_id=None,
            session_id="session-123",
        )
        assert evaluator.role_id is None


class TestModuleExports:
    """Test AC5: Module exports all public classes."""

    def test_all_exports_available(self) -> None:
        """Verify all public classes are exported from __init__.py."""
        from bmad_assist import benchmarking

        # Enums
        assert hasattr(benchmarking, "MetricSource")
        assert hasattr(benchmarking, "EvaluatorRole")

        # Exception
        assert hasattr(benchmarking, "BenchmarkingError")

        # Helper function
        assert hasattr(benchmarking, "source_field")

        # All models from AC1
        assert hasattr(benchmarking, "LLMEvaluationRecord")
        assert hasattr(benchmarking, "WorkflowInfo")
        assert hasattr(benchmarking, "StoryInfo")
        assert hasattr(benchmarking, "EvaluatorInfo")
        assert hasattr(benchmarking, "ExecutionTelemetry")
        assert hasattr(benchmarking, "OutputAnalysis")
        assert hasattr(benchmarking, "FindingsExtracted")
        assert hasattr(benchmarking, "ReasoningPatterns")
        assert hasattr(benchmarking, "LinguisticFingerprint")
        assert hasattr(benchmarking, "QualitySignals")
        assert hasattr(benchmarking, "ConsensusData")
        assert hasattr(benchmarking, "GroundTruth")
        assert hasattr(benchmarking, "EnvironmentInfo")
        assert hasattr(benchmarking, "PatchInfo")
        assert hasattr(benchmarking, "Amendment")


class TestLLMEvaluationRecord:
    """Test AC1, AC6: LLMEvaluationRecord root model."""

    def _create_minimal_record(self) -> "LLMEvaluationRecord":
        """Create a minimal valid LLMEvaluationRecord for testing."""
        from bmad_assist.benchmarking import (
            EnvironmentInfo,
            EvaluatorInfo,
            EvaluatorRole,
            ExecutionTelemetry,
            LLMEvaluationRecord,
            OutputAnalysis,
            PatchInfo,
            StoryInfo,
            WorkflowInfo,
        )

        return LLMEvaluationRecord(
            workflow=WorkflowInfo(
                id="create-story",
                version="1.0.0",
                variant="default",
                patch=PatchInfo(applied=False),
            ),
            story=StoryInfo(
                epic_num=13,
                story_num=1,
                title="Test Story",
                complexity_flags={"has_ui_changes": False},
            ),
            evaluator=EvaluatorInfo(
                provider="claude",
                model="opus-4",
                role=EvaluatorRole.VALIDATOR,
                role_id="a",
                session_id="test-session",
            ),
            execution=ExecutionTelemetry(
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC),
                duration_ms=1000,
                input_tokens=500,
                output_tokens=1500,
                retries=0,
                sequence_position=0,
            ),
            output=OutputAnalysis(
                char_count=5000,
                heading_count=5,
                list_depth_max=2,
                code_block_count=3,
                sections_detected=["Overview", "Findings"],
            ),
            environment=EnvironmentInfo(
                bmad_assist_version="1.0.0",
                python_version="3.11.0",
                platform="linux",
            ),
        )

    def test_llm_evaluation_record_complete(self) -> None:
        """Test full model instantiation with all required fields."""
        record = self._create_minimal_record()

        assert record.workflow.id == "create-story"
        assert record.story.epic_num == 13
        assert record.evaluator.provider == "claude"
        assert record.execution.duration_ms == 1000
        assert record.output.char_count == 5000
        assert record.environment.bmad_assist_version == "1.0.0"

    def test_record_id_auto_generation(self) -> None:
        """Verify record_id is auto-generated as UUID4 format."""
        record = self._create_minimal_record()

        # Should be a valid UUID4 string
        assert record.record_id is not None
        assert len(record.record_id) == 36  # UUID format: 8-4-4-4-12

        # Parse as UUID to verify format
        parsed = UUID(record.record_id, version=4)
        assert str(parsed) == record.record_id

    def test_record_id_unique_per_instance(self) -> None:
        """Verify each instance gets a unique record_id."""
        record1 = self._create_minimal_record()
        record2 = self._create_minimal_record()

        assert record1.record_id != record2.record_id

    def test_created_at_auto_generation(self) -> None:
        """Verify created_at is auto-generated as UTC datetime."""
        before = datetime.now(UTC)
        record = self._create_minimal_record()
        after = datetime.now(UTC)

        assert record.created_at is not None
        assert record.created_at.tzinfo is not None  # Has timezone
        assert before <= record.created_at <= after

    def test_datetime_serialization(self) -> None:
        """Verify datetime serializes to ISO 8601 with timezone."""
        record = self._create_minimal_record()

        # Serialize to dict/JSON
        data = record.model_dump(mode="json")

        # Should be ISO 8601 format with timezone
        created_at_str = data["created_at"]
        assert "+" in created_at_str or "Z" in created_at_str  # Has timezone indicator
        assert "T" in created_at_str  # ISO 8601 separator

        # Should be parseable back
        parsed = datetime.fromisoformat(created_at_str)
        assert parsed.tzinfo is not None

    def test_optional_fields_default_none(self) -> None:
        """Verify optional nested models default to None."""
        record = self._create_minimal_record()

        assert record.findings is None
        assert record.reasoning is None
        assert record.linguistic is None
        assert record.quality is None
        assert record.consensus is None
        assert record.ground_truth is None
        assert record.custom is None

    def test_model_json_serialization_round_trip(self) -> None:
        """Test full JSON serialization/deserialization round-trip."""
        from bmad_assist.benchmarking import LLMEvaluationRecord

        record = self._create_minimal_record()

        # Serialize to JSON string
        json_str = record.model_dump_json()

        # Deserialize back
        restored = LLMEvaluationRecord.model_validate_json(json_str)

        # Should match original
        assert restored.record_id == record.record_id
        assert restored.workflow.id == record.workflow.id
        assert restored.story.epic_num == record.story.epic_num
        assert restored.evaluator.role_id == record.evaluator.role_id

    def test_source_annotation_accessibility(self) -> None:
        """Verify source annotations are accessible via model_fields."""
        from bmad_assist.benchmarking import OutputAnalysis

        # Get field info for char_count
        field_info = OutputAnalysis.model_fields["char_count"]

        # Source should be in json_schema_extra
        assert field_info.json_schema_extra is not None
        assert field_info.json_schema_extra["source"] == "deterministic"


class TestExecutionTelemetry:
    """Test AC1: ExecutionTelemetry model."""

    def test_execution_telemetry_all_fields(self) -> None:
        """Verify ExecutionTelemetry contains all fields."""
        from bmad_assist.benchmarking import ExecutionTelemetry

        telemetry = ExecutionTelemetry(
            start_time=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            end_time=datetime(2025, 1, 1, 12, 1, 0, tzinfo=UTC),
            duration_ms=60000,
            input_tokens=1000,
            output_tokens=2000,
            retries=1,
            sequence_position=2,
        )

        assert telemetry.duration_ms == 60000
        assert telemetry.input_tokens == 1000
        assert telemetry.output_tokens == 2000
        assert telemetry.retries == 1
        assert telemetry.sequence_position == 2


class TestOutputAnalysis:
    """Test AC1: OutputAnalysis model."""

    def test_output_analysis_all_fields(self) -> None:
        """Verify OutputAnalysis contains all fields."""
        from bmad_assist.benchmarking import OutputAnalysis

        output = OutputAnalysis(
            char_count=10000,
            heading_count=8,
            list_depth_max=3,
            code_block_count=5,
            sections_detected=["Summary", "Findings", "Recommendations"],
            anomalies=["Missing required section"],
        )

        assert output.char_count == 10000
        assert output.heading_count == 8
        assert output.list_depth_max == 3
        assert output.code_block_count == 5
        assert len(output.sections_detected) == 3
        assert len(output.anomalies) == 1

    def test_output_analysis_anomalies_default(self) -> None:
        """Verify anomalies defaults to empty list."""
        from bmad_assist.benchmarking import OutputAnalysis

        output = OutputAnalysis(
            char_count=100,
            heading_count=1,
            list_depth_max=0,
            code_block_count=0,
            sections_detected=[],
        )

        assert output.anomalies == []


class TestFindingsExtracted:
    """Test AC1: FindingsExtracted model."""

    def test_findings_extracted_all_fields(self) -> None:
        """Verify FindingsExtracted contains all fields."""
        from bmad_assist.benchmarking import FindingsExtracted

        findings = FindingsExtracted(
            total_count=15,
            by_severity={"critical": 2, "major": 5, "minor": 6, "nit": 2},
            by_category={"security": 3, "performance": 4, "correctness": 8},
            has_fix_count=10,
            has_location_count=12,
            has_evidence_count=8,
        )

        assert findings.total_count == 15
        assert findings.by_severity["critical"] == 2
        assert findings.by_category["security"] == 3
        assert findings.has_fix_count == 10


class TestReasoningPatterns:
    """Test AC1: ReasoningPatterns model."""

    def test_reasoning_patterns_all_fields(self) -> None:
        """Verify ReasoningPatterns contains all fields."""
        from bmad_assist.benchmarking import ReasoningPatterns

        reasoning = ReasoningPatterns(
            cites_prd=True,
            cites_architecture=True,
            cites_story_sections=False,
            uses_conditionals=True,
            uncertainty_phrases_count=3,
            confidence_phrases_count=7,
        )

        assert reasoning.cites_prd is True
        assert reasoning.confidence_phrases_count == 7


class TestLinguisticFingerprint:
    """Test AC1: LinguisticFingerprint model."""

    def test_linguistic_fingerprint_all_fields(self) -> None:
        """Verify LinguisticFingerprint contains all fields."""
        from bmad_assist.benchmarking import LinguisticFingerprint

        linguistic = LinguisticFingerprint(
            avg_sentence_length=15.5,
            vocabulary_richness=0.75,
            flesch_reading_ease=45.0,
            vague_terms_count=3,
            formality_score=0.8,
            sentiment="neutral",
        )

        assert linguistic.avg_sentence_length == 15.5
        assert linguistic.vocabulary_richness == 0.75
        assert linguistic.formality_score == 0.8
        assert linguistic.sentiment == "neutral"


class TestQualitySignals:
    """Test AC1: QualitySignals model."""

    def test_quality_signals_all_fields(self) -> None:
        """Verify QualitySignals contains all fields."""
        from bmad_assist.benchmarking import QualitySignals

        quality = QualitySignals(
            actionable_ratio=0.9,
            specificity_score=0.85,
            evidence_quality=0.7,
            follows_template=True,
            internal_consistency=0.95,
        )

        assert quality.actionable_ratio == 0.9
        assert quality.follows_template is True
        assert quality.internal_consistency == 0.95


class TestConsensusData:
    """Test AC1: ConsensusData model."""

    def test_consensus_data_all_fields(self) -> None:
        """Verify ConsensusData contains all fields."""
        from bmad_assist.benchmarking import ConsensusData

        consensus = ConsensusData(
            agreed_findings=10,
            unique_findings=3,
            disputed_findings=2,
            missed_findings=1,
            agreement_score=0.85,
            false_positive_count=2,
        )

        assert consensus.agreed_findings == 10
        assert consensus.unique_findings == 3
        assert consensus.agreement_score == 0.85


class TestGroundTruth:
    """Test AC1: GroundTruth model."""

    def test_ground_truth_all_fields(self) -> None:
        """Verify GroundTruth contains all fields."""
        from bmad_assist.benchmarking import Amendment, GroundTruth

        ground_truth = GroundTruth(
            populated=True,
            populated_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            findings_confirmed=8,
            findings_false_alarm=2,
            issues_missed=3,
            precision=0.8,
            recall=0.727,
            amendments=[
                Amendment(
                    timestamp=datetime(2025, 1, 2, 12, 0, 0, tzinfo=UTC),
                    phase="code_review",
                    note="Found additional issue",
                    delta_confirmed=0,
                    delta_missed=1,
                )
            ],
            last_updated_at=datetime(2025, 1, 2, 12, 0, 0, tzinfo=UTC),
        )

        assert ground_truth.populated is True
        assert ground_truth.findings_confirmed == 8
        assert ground_truth.precision == 0.8
        assert len(ground_truth.amendments) == 1
        assert ground_truth.amendments[0].phase == "code_review"

    def test_ground_truth_defaults(self) -> None:
        """Verify GroundTruth optional fields have correct defaults."""
        from bmad_assist.benchmarking import GroundTruth

        ground_truth = GroundTruth(populated=False)

        assert ground_truth.populated_at is None
        assert ground_truth.findings_confirmed == 0
        assert ground_truth.findings_false_alarm == 0
        assert ground_truth.issues_missed == 0
        assert ground_truth.precision is None
        assert ground_truth.recall is None
        assert ground_truth.amendments == []
        assert ground_truth.last_updated_at is None


class TestAmendment:
    """Test AC1: Amendment model."""

    def test_amendment_all_fields(self) -> None:
        """Verify Amendment contains all fields."""
        from bmad_assist.benchmarking import Amendment

        amendment = Amendment(
            timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            phase="code_review",
            note="Discovered missed security issue",
            delta_confirmed=1,
            delta_missed=2,
        )

        assert amendment.phase == "code_review"
        assert amendment.note == "Discovered missed security issue"
        assert amendment.delta_confirmed == 1
        assert amendment.delta_missed == 2


class TestEnvironmentInfo:
    """Test AC1: EnvironmentInfo model."""

    def test_environment_info_all_fields(self) -> None:
        """Verify EnvironmentInfo contains all fields."""
        from bmad_assist.benchmarking import EnvironmentInfo

        env = EnvironmentInfo(
            bmad_assist_version="1.0.0",
            python_version="3.11.5",
            platform="linux",
            git_commit_hash="abc123def456",
        )

        assert env.bmad_assist_version == "1.0.0"
        assert env.python_version == "3.11.5"
        assert env.platform == "linux"
        assert env.git_commit_hash == "abc123def456"

    def test_environment_info_git_hash_optional(self) -> None:
        """Verify git_commit_hash is optional and defaults to None."""
        from bmad_assist.benchmarking import EnvironmentInfo

        env = EnvironmentInfo(
            bmad_assist_version="1.0.0",
            python_version="3.11.5",
            platform="linux",
        )

        assert env.git_commit_hash is None
