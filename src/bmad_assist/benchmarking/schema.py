"""Benchmarking schema module with Pydantic models for LLM evaluation metrics.

This module provides:
- MetricSource enum for field provenance annotation
- EvaluatorRole enum for evaluator classification
- Pydantic models for all metric categories
- source_field helper for annotated fields
- BenchmarkingError exception class

All models use source annotations via json_schema_extra to indicate
how each field value is obtained (deterministic vs LLM-assessed).
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator
from pydantic.fields import FieldInfo

from bmad_assist.core.exceptions import BmadAssistError
from bmad_assist.core.types import EpicId


class MetricSource(str, Enum):
    """Source of a metric field - indicates how value is obtained.

    Used in json_schema_extra annotations to document field provenance:
    - DETERMINISTIC: Python calculation, 100% reproducible
    - LLM_EXTRACTED: LLM parses from output, may vary between runs
    - LLM_ASSESSED: LLM makes qualitative judgment, inherently variable
    - SYNTHESIZER: Filled by synthesis phase after validation
    - POST_HOC: Filled after later phases (e.g., code review)
    """

    DETERMINISTIC = "deterministic"
    LLM_EXTRACTED = "llm_extracted"
    LLM_ASSESSED = "llm_assessed"
    SYNTHESIZER = "synthesizer"
    POST_HOC = "post_hoc"


class EvaluatorRole(str, Enum):
    """Role of the evaluator in the validation workflow.

    - VALIDATOR: Multi-LLM validator in parallel validation phase
    - SYNTHESIZER: Master LLM synthesizing validation results
    - MASTER: Master LLM in other contexts (dev, code review)
    """

    VALIDATOR = "validator"
    SYNTHESIZER = "synthesizer"
    MASTER = "master"


class BenchmarkingError(BmadAssistError):
    """Benchmarking metrics collection or storage error.

    Raised when:
    - Schema validation fails during record creation
    - Metrics extraction fails (Story 13.3)
    - Storage write fails (Story 13.5)
    """

    pass


def source_field(
    source: MetricSource,
    default: Any = ...,
    **kwargs: Any,
) -> FieldInfo:
    """Create a Field with source annotation.

    Args:
        source: MetricSource enum value indicating field provenance.
        default: Default value (... for required fields).
        **kwargs: Additional Field arguments (description, etc.).

    Returns:
        Pydantic FieldInfo with source annotation in json_schema_extra.

    Example:
        char_count: int = source_field(MetricSource.DETERMINISTIC, default=0)

    """
    extra = kwargs.pop("json_schema_extra", {})
    extra["source"] = source.value  # Store string value, not enum
    return Field(default=default, json_schema_extra=extra, **kwargs)  # type: ignore[no-any-return]


def _src(source: MetricSource) -> dict[str, Any]:
    """Create json_schema_extra dict with source annotation."""
    return {"source": source.value}


# =============================================================================
# Nested Models - Core
# =============================================================================


class PatchInfo(BaseModel):
    """Patch metadata for workflow compilation.

    Tracks whether a patch was applied and its identifying information.
    """

    applied: bool = Field(
        description="Whether patch was used",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    id: str | None = Field(
        default=None,
        description="Patch identifier",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    version: str | None = Field(
        default=None,
        description="Patch version",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    file_hash: str | None = Field(
        default=None,
        description="SHA256 hash of patch file",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )


class WorkflowInfo(BaseModel):
    """Workflow identification and compilation info.

    Tracks the workflow executed and any patches applied.
    """

    id: str = Field(
        description="Workflow identifier (e.g., 'create-story')",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    version: str = Field(
        description="Workflow version",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    variant: str = Field(
        description="Workflow variant (e.g., 'default', 'multi-llm')",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    patch: PatchInfo = Field(
        description="Patch information",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )


class StoryInfo(BaseModel):
    """Story metadata for evaluation context.

    Identifies the story being evaluated and its complexity characteristics.
    """

    epic_num: EpicId = Field(
        description="Epic identifier (int or string for modules)",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    story_num: int = Field(
        description="Story number within epic",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    title: str = Field(
        description="Story title",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    complexity_flags: dict[str, bool] = Field(
        description="Complexity indicators (has_ui_changes, has_api_changes, etc.)",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )


class EvaluatorInfo(BaseModel):
    """Evaluator identification and role assignment.

    Tracks which LLM provider/model performed the evaluation and in what role.
    """

    provider: str = Field(
        description="Provider name (e.g., 'claude', 'gemini')",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    model: str = Field(
        description="Model identifier (e.g., 'opus-4', 'gemini-2.0-flash')",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    role: EvaluatorRole = Field(
        description="Evaluator role in workflow",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    role_id: str | None = Field(
        default=None,
        description="Validator letter (a-z) or None for synthesizer",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    session_id: str = Field(
        description="Unique session identifier",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )

    @field_validator("role_id")
    @classmethod
    def validate_role_id(cls, v: str | None) -> str | None:
        """Validate role_id is single lowercase letter a-z or None.

        Note: Uses explicit ASCII range check ("a" <= v <= "z") instead of
        v.islower() because islower() accepts Unicode lowercase letters
        (ä, é, ñ, etc.) which violates the ASCII-only requirement.
        """
        if v is not None and (len(v) != 1 or not ("a" <= v <= "z")):
            raise ValueError("role_id must be single lowercase letter a-z")
        return v

    @model_validator(mode="after")
    def validate_role_id_for_role(self) -> "EvaluatorInfo":
        """Validate role_id is present for validators, None for synthesizer/master."""
        if self.role == EvaluatorRole.VALIDATOR and self.role_id is None:
            raise ValueError("role_id required for validators (must be a-z)")
        non_validator_roles = {EvaluatorRole.SYNTHESIZER, EvaluatorRole.MASTER}
        if self.role in non_validator_roles and self.role_id is not None:
            raise ValueError("role_id must be None for synthesizer/master roles")
        return self


# =============================================================================
# Nested Models - Telemetry and Output
# =============================================================================


class ExecutionTelemetry(BaseModel):
    """Execution timing and resource usage metrics.

    All timing fields are deterministic from system measurements.
    """

    start_time: datetime = Field(
        description="UTC start timestamp",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    end_time: datetime = Field(
        description="UTC end timestamp",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    duration_ms: int = Field(
        description="Duration in milliseconds",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    input_tokens: int = Field(
        description="Input token count",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    output_tokens: int = Field(
        description="Output token count",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    retries: int = Field(
        default=0,
        description="Number of retry attempts",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    sequence_position: int = Field(
        description="0-indexed workflow step order",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )


class OutputAnalysis(BaseModel):
    """Structural analysis of LLM output.

    Deterministic metrics from output parsing.
    """

    char_count: int = Field(
        description="Total character count",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    heading_count: int = Field(
        description="Number of markdown headings",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    list_depth_max: int = Field(
        description="Maximum nested list depth",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    code_block_count: int = Field(
        description="Number of code blocks",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    sections_detected: list[str] = Field(
        description="List of detected section names",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    anomalies: list[str] = Field(
        default_factory=list,
        description="List of structural anomalies detected",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )


class FindingsExtracted(BaseModel):
    """Extracted findings from validation output.

    Mix of deterministic counts and LLM-extracted categorizations.
    Updated for Evidence Score system (TIER 2).
    """

    total_count: int = Field(
        description="Total number of findings",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    by_severity: dict[str, int] = Field(
        description="Counts by severity (CRITICAL, IMPORTANT, MINOR for Evidence Score)",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    by_category: dict[str, int] = Field(
        description="Counts by category (security, performance, etc.)",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    has_fix_count: int = Field(
        description="Findings with suggested fixes",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    has_location_count: int = Field(
        description="Findings with specific locations",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    has_evidence_count: int = Field(
        description="Findings with supporting evidence (quotes)",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    # Evidence Score fields (TIER 2)
    evidence_score: float | None = Field(
        default=None,
        description="Calculated Evidence Score for this validator",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    evidence_verdict: str | None = Field(
        default=None,
        description="Evidence Score verdict (REJECT/MAJOR_REWORK/PASS/EXCELLENT)",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    clean_pass_count: int = Field(
        default=0,
        description="Number of CLEAN PASS categories (-0.5 each)",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )


# =============================================================================
# Nested Models - Quality and Patterns
# =============================================================================


class ReasoningPatterns(BaseModel):
    """Analysis of reasoning quality in LLM output.

    LLM-assessed metrics for argumentation quality.
    """

    cites_prd: bool = Field(
        description="References PRD document",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    cites_architecture: bool = Field(
        description="References architecture document",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    cites_story_sections: bool = Field(
        description="References story sections",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    uses_conditionals: bool = Field(
        description="Uses conditional reasoning (if/then)",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    uncertainty_phrases_count: int = Field(
        description="Count of uncertainty phrases",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    confidence_phrases_count: int = Field(
        description="Count of confidence phrases",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )


class LinguisticFingerprint(BaseModel):
    """Linguistic characteristics of LLM output.

    Mix of deterministic metrics and LLM-assessed characteristics.
    """

    avg_sentence_length: float = Field(
        description="Average words per sentence",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    vocabulary_richness: float = Field(
        description="Type-token ratio",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    flesch_reading_ease: float = Field(
        description="Flesch readability score",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    vague_terms_count: int = Field(
        description="Count of vague terms",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    formality_score: float = Field(
        description="Formality assessment (0-1)",
        json_schema_extra=_src(MetricSource.LLM_ASSESSED),
    )
    sentiment: str = Field(
        description="Sentiment classification",
        json_schema_extra=_src(MetricSource.LLM_ASSESSED),
    )


class QualitySignals(BaseModel):
    """Quality assessment signals for validation output.

    LLM-assessed quality metrics.
    """

    actionable_ratio: float = Field(
        description="Ratio of actionable findings (0-1)",
        json_schema_extra=_src(MetricSource.LLM_ASSESSED),
    )
    specificity_score: float = Field(
        description="Specificity assessment (0-1)",
        json_schema_extra=_src(MetricSource.LLM_ASSESSED),
    )
    evidence_quality: float = Field(
        description="Evidence quality score (0-1)",
        json_schema_extra=_src(MetricSource.LLM_ASSESSED),
    )
    follows_template: bool = Field(
        description="Output follows expected template",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    internal_consistency: float = Field(
        description="Internal consistency score (0-1)",
        json_schema_extra=_src(MetricSource.LLM_ASSESSED),
    )


# =============================================================================
# Nested Models - Consensus and Ground Truth
# =============================================================================


class ConsensusData(BaseModel):
    """Cross-evaluator agreement metrics.

    Populated by synthesizer during multi-LLM validation.
    Updated for Evidence Score system (TIER 2).
    """

    agreed_findings: int = Field(
        description="Findings agreed by 2+ validators (consensus)",
        json_schema_extra=_src(MetricSource.SYNTHESIZER),
    )
    unique_findings: int = Field(
        description="Findings from single validator only",
        json_schema_extra=_src(MetricSource.SYNTHESIZER),
    )
    disputed_findings: int = Field(
        description="Findings with conflicting assessments",
        json_schema_extra=_src(MetricSource.SYNTHESIZER),
    )
    missed_findings: int = Field(
        default=0,
        description="Findings missed by all (from ground truth)",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    agreement_score: float = Field(
        description="Overall agreement score (0-1)",
        json_schema_extra=_src(MetricSource.SYNTHESIZER),
    )
    false_positive_count: int = Field(
        default=0,
        description="False positives identified in review",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    # Evidence Score aggregate fields (TIER 2)
    aggregate_evidence_score: float | None = Field(
        default=None,
        description="Average Evidence Score across all validators",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    aggregate_evidence_verdict: str | None = Field(
        default=None,
        description="Aggregate Evidence Score verdict",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    consensus_ratio: float | None = Field(
        default=None,
        description="Ratio of consensus to total findings (0-1)",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )


class Amendment(BaseModel):
    """Post-hoc amendment to ground truth.

    Records changes to ground truth from code review findings.
    """

    timestamp: datetime = Field(
        description="UTC timestamp of amendment",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    phase: str = Field(
        description="Phase that triggered amendment (e.g., 'code_review')",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    note: str = Field(
        description="Description of amendment",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    delta_confirmed: int = Field(
        default=0,
        description="Change in confirmed findings count",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    delta_missed: int = Field(
        default=0,
        description="Change in missed findings count",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )


class GroundTruth(BaseModel):
    """Post-hoc feedback from code review and later phases.

    Tracks validation accuracy against actual implementation outcomes.
    """

    populated: bool = Field(
        description="Whether ground truth has been populated",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    populated_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when populated",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    findings_confirmed: int = Field(
        default=0,
        description="Validation findings confirmed by review",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    findings_false_alarm: int = Field(
        default=0,
        description="Validation findings that were false alarms",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    issues_missed: int = Field(
        default=0,
        description="Issues found in review but missed by validation",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    precision: float | None = Field(
        default=None,
        description="Precision score (confirmed / (confirmed + false_alarm))",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    recall: float | None = Field(
        default=None,
        description="Recall score (confirmed / (confirmed + missed))",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    amendments: list[Amendment] = Field(
        default_factory=list,
        description="List of post-hoc amendments",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )
    last_updated_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of last update",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )


# =============================================================================
# Nested Models - Environment
# =============================================================================


class EnvironmentInfo(BaseModel):
    """System environment and traceability information.

    All deterministic from system inspection.
    """

    bmad_assist_version: str = Field(
        description="bmad-assist package version",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    python_version: str = Field(
        description="Python interpreter version",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    platform: str = Field(
        description="Operating system platform",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    git_commit_hash: str | None = Field(
        default=None,
        description="Git commit hash of project",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )


# =============================================================================
# Root Model
# =============================================================================


class LLMEvaluationRecord(BaseModel):
    """Complete LLM evaluation metrics record.

    Root model composing all nested models for a single evaluation.
    Auto-generates record_id and created_at on instantiation.
    """

    # Identity fields - auto-generated
    record_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique record identifier (UUID4)",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of record creation",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )

    # Required nested models
    workflow: WorkflowInfo
    story: StoryInfo
    evaluator: EvaluatorInfo
    execution: ExecutionTelemetry
    output: OutputAnalysis
    environment: EnvironmentInfo

    # Optional nested models (populated by later phases)
    findings: FindingsExtracted | None = Field(
        default=None,
        description="Extracted findings (populated by 13.2/13.3)",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    reasoning: ReasoningPatterns | None = Field(
        default=None,
        description="Reasoning patterns (populated by 13.3)",
        json_schema_extra=_src(MetricSource.LLM_EXTRACTED),
    )
    linguistic: LinguisticFingerprint | None = Field(
        default=None,
        description="Linguistic fingerprint (populated by 13.2)",
        json_schema_extra=_src(MetricSource.DETERMINISTIC),
    )
    quality: QualitySignals | None = Field(
        default=None,
        description="Quality signals (populated by 13.6)",
        json_schema_extra=_src(MetricSource.SYNTHESIZER),
    )
    consensus: ConsensusData | None = Field(
        default=None,
        description="Consensus data (populated by 13.6)",
        json_schema_extra=_src(MetricSource.SYNTHESIZER),
    )
    ground_truth: GroundTruth | None = Field(
        default=None,
        description="Ground truth (populated by 13.7)",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )

    # Extensibility
    custom: dict[str, Any] | None = Field(
        default=None,
        description="Custom extension fields (NFR13)",
        json_schema_extra=_src(MetricSource.POST_HOC),
    )

    @field_serializer("created_at")
    def serialize_datetime(self, dt: datetime) -> str:
        """Serialize datetime to ISO 8601 with UTC timezone."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat()
