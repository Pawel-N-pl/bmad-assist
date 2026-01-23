"""Validation module for Multi-LLM validation synthesis.

This module provides functionality to:
- Anonymize validation outputs before Master LLM synthesis
- Orchestrate parallel Multi-LLM validation
- Manage inter-handler data passing for synthesis phase
- Persist validation and synthesis reports with YAML frontmatter
- Integrate benchmarking metrics collection (Story 13.4)
- Extract structured metrics from synthesis output (Story 13.6)
- Calculate deterministic Evidence Score (TIER 2)

Public API:
    Anonymizer:
    - ValidationOutput: Input data model for validation results
    - AnonymizedValidation: Output data model for anonymized validations
    - AnonymizationMapping: Mapping from anonymous IDs to original providers
    - anonymize_validations(): Main anonymization function
    - save_mapping(): Persist mapping for post-synthesis reference
    - get_mapping(): Retrieve mapping by session ID

    Orchestrator:
    - ValidationError: Base exception for validation errors
    - InsufficientValidationsError: Raised when fewer than minimum validations
    - ValidationPhaseResult: Result dataclass for validation phase
    - run_validation_phase(): Main orchestration function
    - save_validations_for_synthesis(): Save validations for inter-handler passing
    - load_validations_for_synthesis(): Load validations from cache

    Reports:
    - ValidationReportMetadata: Parsed report metadata dataclass
    - list_validations(): Query validation reports with filtering
    - save_validation_report(): Save validation reports with YAML frontmatter
    - save_synthesis_report(): Save synthesis reports with YAML frontmatter

    Benchmarking Integration (Story 13.4):
    - should_collect_benchmarking(): Check if benchmarking is enabled

    Synthesis Parser (Story 13.6):
    - SynthesisMetrics: Dataclass for extracted quality and consensus metrics
    - extract_synthesis_metrics(): Extract structured metrics from synthesis output
    - create_synthesizer_record(): Create evaluation record for synthesizer

    Evidence Score (TIER 2):
    - Severity: Enum for CRITICAL/IMPORTANT/MINOR severity levels
    - Verdict: Enum for REJECT/MAJOR_REWORK/PASS/EXCELLENT verdicts
    - EvidenceFinding: Dataclass for individual findings
    - EvidenceScoreReport: Per-validator Evidence Score report
    - EvidenceScoreAggregate: Aggregate across multiple validators
    - calculate_evidence_score(): Calculate score from findings
    - determine_verdict(): Map score to verdict
    - parse_evidence_findings(): Parse Evidence Score from report content
    - aggregate_evidence_scores(): Aggregate multiple validator reports
    - format_evidence_score_context(): Format for synthesis prompt injection
    - EvidenceScoreError: Base exception for Evidence Score module
    - AllValidatorsFailedError: All validators failed to produce reports
    - CacheVersionError: Cache version incompatible
    - CacheFormatError: Cache structure invalid
"""

from bmad_assist.validation.anonymizer import (
    AnonymizationMapping,
    AnonymizedValidation,
    ValidationOutput,
    anonymize_validations,
    get_mapping,
    save_mapping,
)
from bmad_assist.validation.benchmarking_integration import (
    create_synthesizer_record,
    should_collect_benchmarking,
)
from bmad_assist.validation.orchestrator import (
    InsufficientValidationsError,
    ValidationError,
    ValidationPhaseResult,
    load_validations_for_synthesis,
    run_validation_phase,
    save_validations_for_synthesis,
)
from bmad_assist.validation.reports import (
    ValidationReportMetadata,
    list_validations,
    save_synthesis_report,
    save_validation_report,
)
from bmad_assist.validation.synthesis_parser import (
    SynthesisMetrics,
    extract_synthesis_metrics,
)
from bmad_assist.validation.evidence_score import (
    AllValidatorsFailedError,
    CacheFormatError,
    CacheVersionError,
    EvidenceFinding,
    EvidenceScoreAggregate,
    EvidenceScoreError,
    EvidenceScoreReport,
    Severity,
    Verdict,
    aggregate_evidence_scores,
    calculate_evidence_score,
    determine_verdict,
    format_evidence_score_context,
    parse_evidence_findings,
)

__all__ = [
    # Anonymizer
    "ValidationOutput",
    "AnonymizedValidation",
    "AnonymizationMapping",
    "anonymize_validations",
    "save_mapping",
    "get_mapping",
    # Orchestrator
    "ValidationError",
    "InsufficientValidationsError",
    "ValidationPhaseResult",
    "run_validation_phase",
    "save_validations_for_synthesis",
    "load_validations_for_synthesis",
    # Reports
    "ValidationReportMetadata",
    "list_validations",
    "save_validation_report",
    "save_synthesis_report",
    # Benchmarking Integration (Story 13.4)
    "should_collect_benchmarking",
    # Synthesis Parser (Story 13.6)
    "SynthesisMetrics",
    "extract_synthesis_metrics",
    "create_synthesizer_record",
    # Evidence Score (TIER 2)
    "Severity",
    "Verdict",
    "EvidenceFinding",
    "EvidenceScoreReport",
    "EvidenceScoreAggregate",
    "calculate_evidence_score",
    "determine_verdict",
    "parse_evidence_findings",
    "aggregate_evidence_scores",
    "format_evidence_score_context",
    "EvidenceScoreError",
    "AllValidatorsFailedError",
    "CacheVersionError",
    "CacheFormatError",
]
