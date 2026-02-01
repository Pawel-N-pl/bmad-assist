"""Benchmarking integration helpers for validation orchestrator.

Story 13.4: Orchestrator Integration
Story 13.6: Synthesizer Schema Integration

This module provides helper functions for integrating benchmarking metrics
collection with the validation orchestrator. Functions create schema models
from validation outputs and deterministic/extracted metrics.

Public API:
    _parse_role_id: Parse role_id from anonymized ID with position-based fallback
    _create_collector_context: Create CollectorContext for deterministic metrics
    _create_evaluator_info: Create EvaluatorInfo from validation output
    _create_execution_telemetry: Create ExecutionTelemetry from validation output
    _create_environment_info: Create EnvironmentInfo with system state
    _create_workflow_info: Create WorkflowInfo with variant and patch info
    _create_story_info: Create StoryInfo with epic, num, title, complexity
    _finalize_evaluation_record: Merge all sources into LLMEvaluationRecord
    _safe_extract_metrics: Extract metrics with error handling
    _run_parallel_extraction: Run extraction in parallel for all validators
    should_collect_benchmarking: Check if benchmarking is enabled
    create_synthesizer_record: Create evaluation record for synthesizer (Story 13.6)
"""

from __future__ import annotations

import asyncio
import logging
import platform
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from bmad_assist import __version__
from bmad_assist.benchmarking import (
    CollectorContext,
    DeterministicMetrics,
    EnvironmentInfo,
    EvaluatorInfo,
    EvaluatorRole,
    ExecutionTelemetry,
    LLMEvaluationRecord,
    MetricsExtractionError,
    OutputAnalysis,
    PatchInfo,
    StoryInfo,
    WorkflowInfo,
    extract_metrics_async,
)
from bmad_assist.benchmarking.extraction import ExtractedMetrics, ExtractionContext
from bmad_assist.core.types import EpicId
from bmad_assist.validation.anonymizer import ValidationOutput
from bmad_assist.validation.synthesis_parser import extract_synthesis_metrics

if TYPE_CHECKING:
    from bmad_assist.core.config import Config

logger = logging.getLogger(__name__)


def _parse_role_id(
    anonymized_id: str | None,
    sequence_position: int,
    role: EvaluatorRole,
) -> str | None:
    """Parse role_id from anonymized ID with position-based fallback.

    For VALIDATOR role, extracts a single lowercase letter (a-z) from the
    anonymized ID format "Validator A" -> "a". If parsing fails, uses
    sequence_position to generate a deterministic fallback.

    For SYNTHESIZER/MASTER roles, always returns None (role_id is not
    applicable for these roles per EvaluatorInfo validation rules).

    Args:
        anonymized_id: Anonymized validator ID like "Validator A".
        sequence_position: Order in which validator completed (0-indexed).
        role: EvaluatorRole determining if role_id is applicable.

    Returns:
        Single lowercase letter (a-z) for VALIDATOR role, or None for
        SYNTHESIZER/MASTER roles.

    Examples:
        >>> _parse_role_id("Validator A", 0, EvaluatorRole.VALIDATOR)
        'a'
        >>> _parse_role_id("VALIDATOR B", 1, EvaluatorRole.VALIDATOR)
        'b'
        >>> _parse_role_id(None, 2, EvaluatorRole.VALIDATOR)
        'c'  # Fallback: chr(97 + (2 % 26))
        >>> _parse_role_id("   ", 0, EvaluatorRole.VALIDATOR)
        'a'  # Fallback from empty whitespace
        >>> _parse_role_id("gemini-gemini-3-pro-preview", 0, EvaluatorRole.VALIDATOR)
        'a'  # Fallback from malformed identifier
        >>> _parse_role_id("Validator A", 0, EvaluatorRole.SYNTHESIZER)
        None  # SYNTHESIZER/MASTER always get None

    """
    # CRITICAL: Only VALIDATOR role gets a role_id
    # SYNTHESIZER/MASTER must have role_id=None per EvaluatorInfo validation
    if role != EvaluatorRole.VALIDATOR:
        return None

    # Try to extract from anonymized_id
    if anonymized_id:
        # Strip whitespace first to handle "   " -> ""
        stripped = anonymized_id.strip()
        if stripped:
            parts = stripped.split()
            if parts:
                candidate = parts[-1].lower()
                # Validate: exactly 1 char, lowercase a-z
                if len(candidate) == 1 and "a" <= candidate <= "z":
                    return candidate

    # Fallback: use sequence position (0 -> 'a', 1 -> 'b', ..., wraps with modulo 26)
    fallback = chr(ord("a") + (sequence_position % 26))
    logger.warning(
        "Failed to parse role_id from %r, using fallback '%s' based on position %d",
        anonymized_id,
        fallback,
        sequence_position,
    )
    return fallback


def _create_collector_context(
    story_epic: EpicId,
    story_num: int,
    timestamp: datetime,
) -> CollectorContext:
    """Create CollectorContext for deterministic metrics.

    Args:
        story_epic: Epic number.
        story_num: Story number within epic.
        timestamp: UTC-aware timestamp for collection.

    Returns:
        CollectorContext with story info and timestamp.

    """
    return CollectorContext(
        story_epic=story_epic,
        story_num=story_num,
        timestamp=timestamp,
    )


def _create_evaluator_info(
    validation_output: ValidationOutput,
    role: EvaluatorRole,
    anonymized_id: str | None,
    sequence_position: int,
) -> EvaluatorInfo:
    """Create EvaluatorInfo from validation output.

    Args:
        validation_output: Contains provider and model info.
        role: EvaluatorRole.VALIDATOR for validators.
        anonymized_id: Anonymized validator ID like "Validator A".
        sequence_position: Order in which validator completed.

    Returns:
        EvaluatorInfo with provider/model and derived role_id.

    """
    # Use provider and model directly from ValidationOutput
    # provider is now the actual provider name (e.g., "claude-subprocess", "gemini", "kimi")
    # model is the actual model from ProviderResult (e.g., "opus", "gemini-2.5-flash")
    provider = validation_output.provider
    model = validation_output.model

    # Derive role_id from anonymized ID with fallback: "Validator A" -> "a"
    role_id = _parse_role_id(anonymized_id, sequence_position, role)

    return EvaluatorInfo(
        provider=provider,
        model=model,
        role=role,
        role_id=role_id,
        session_id=validation_output.provider_session_id or "",
    )


def _create_execution_telemetry(
    validation_output: ValidationOutput,
    sequence_position: int,
) -> ExecutionTelemetry:
    """Create ExecutionTelemetry from validation output.

    Args:
        validation_output: Contains timing and token info.
        sequence_position: Order in which validator completed.

    Returns:
        ExecutionTelemetry with calculated end_time.

    """
    # Calculate end_time from timestamp + duration
    start_time = validation_output.timestamp
    duration_ms = validation_output.duration_ms
    end_time = start_time + timedelta(milliseconds=duration_ms)

    return ExecutionTelemetry(
        start_time=start_time,
        end_time=end_time,
        duration_ms=duration_ms,
        input_tokens=0,  # Not available from current ValidationOutput
        output_tokens=validation_output.token_count,
        retries=0,  # Not tracked currently
        sequence_position=sequence_position,
    )


def _create_environment_info() -> EnvironmentInfo:
    """Create EnvironmentInfo with current system state.

    Returns:
        EnvironmentInfo with bmad-assist version, Python version,
        platform, and git commit hash if available.

    """
    # Get git commit hash if in repo
    git_hash: str | None = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            git_hash = result.stdout.strip()[:12]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return EnvironmentInfo(
        bmad_assist_version=__version__,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        platform=platform.system(),
        git_commit_hash=git_hash,
    )


def _create_workflow_info(
    workflow_id: str,
    variant: str,
    patch_applied: bool,
    patch_path: Path | None = None,
) -> WorkflowInfo:
    """Create WorkflowInfo with variant and patch info.

    Args:
        workflow_id: Workflow identifier (e.g., 'validate-story').
        variant: Workflow variant for A/B testing.
        patch_applied: Whether a patch was used.
        patch_path: Optional path to patch file.

    Returns:
        WorkflowInfo with variant and patch metadata.

    """
    patch_info = PatchInfo(
        applied=patch_applied,
        id=patch_path.stem if patch_path else None,
        version=None,  # Could be extracted from patch metadata
        file_hash=None,  # Could be calculated if needed
    )

    return WorkflowInfo(
        id=workflow_id,
        version="1.0.0",  # Could be extracted from workflow.yaml
        variant=variant,
        patch=patch_info,
    )


def _create_story_info(
    epic_num: EpicId,
    story_num: int | str,
    title: str,
    complexity_flags: dict[str, bool],
) -> StoryInfo:
    """Create StoryInfo with epic, num, title, and complexity flags.

    Args:
        epic_num: Epic number.
        story_num: Story number within epic.
        title: Story title.
        complexity_flags: Complexity indicators from extraction.

    Returns:
        StoryInfo with all story metadata.

    """
    return StoryInfo(
        epic_num=epic_num,
        story_num=story_num,
        title=title,
        complexity_flags=complexity_flags,
    )


def _finalize_evaluation_record(
    validation_output: ValidationOutput,
    deterministic: DeterministicMetrics,
    extracted: ExtractedMetrics,
    workflow_info: WorkflowInfo,
    story_info: StoryInfo,
    anonymized_id: str,
    sequence_position: int,
) -> LLMEvaluationRecord:
    """Create complete LLMEvaluationRecord from all sources.

    Merges deterministic metrics, extracted metrics, and context info
    into a single LLMEvaluationRecord that passes Pydantic validation.

    Args:
        validation_output: Original validation output.
        deterministic: Deterministic metrics from collector.
        extracted: LLM-extracted metrics.
        workflow_info: Workflow identification and variant.
        story_info: Story metadata.
        anonymized_id: Anonymized validator ID.
        sequence_position: Order in which validator completed.

    Returns:
        Complete LLMEvaluationRecord ready for storage.

    """
    evaluator = _create_evaluator_info(
        validation_output,
        role=EvaluatorRole.VALIDATOR,
        anonymized_id=anonymized_id,
        sequence_position=sequence_position,
    )

    execution = _create_execution_telemetry(
        validation_output,
        sequence_position=sequence_position,
    )

    environment = _create_environment_info()

    # Merge linguistic: deterministic base + LLM-assessed additions
    linguistic = extracted.to_linguistic_fingerprint(deterministic.linguistic)

    return LLMEvaluationRecord(
        # record_id and created_at auto-generated
        workflow=workflow_info,
        story=story_info,
        evaluator=evaluator,
        execution=execution,
        output=deterministic.to_output_analysis(),
        findings=extracted.to_findings_extracted(),
        reasoning=deterministic.to_reasoning_patterns(),
        linguistic=linguistic,
        quality=extracted.to_quality_signals(),
        consensus=None,  # Populated by Story 13.6
        ground_truth=None,  # Populated by Story 13.7
        environment=environment,
        custom={"complexity_flags": extracted.to_complexity_flags()},
    )


def should_collect_benchmarking(config: Config) -> bool:
    """Check if benchmarking collection is enabled.

    Args:
        config: Application configuration.

    Returns:
        True if benchmarking.enabled is True, False otherwise.

    """
    return config.benchmarking.enabled


async def _safe_extract_metrics(
    raw_output: str,
    context: ExtractionContext,
) -> ExtractedMetrics | None:
    """Extract metrics with error handling.

    Args:
        raw_output: Raw validator output to analyze.
        context: ExtractionContext with story info and config.

    Returns:
        ExtractedMetrics if successful, None if extraction failed.

    """
    try:
        return await extract_metrics_async(raw_output, context)
    except MetricsExtractionError as e:
        logger.warning(
            "Extraction failed for story %s.%s: %s",
            context.story_epic,
            context.story_num,
            e,
        )
        return None


async def _run_parallel_extraction(
    successful_outputs: list[ValidationOutput],
    deterministic_results: list[DeterministicMetrics],
    project_root: Path,
    epic_num: EpicId,
    story_num: int | str,
    run_timestamp: datetime,
    timeout: int,
    config: Config | None = None,
) -> list[ExtractedMetrics | None]:
    """Run metrics extraction in parallel for all validators.

    Args:
        successful_outputs: List of successful validation outputs.
        deterministic_results: List of deterministic metrics (same order).
        project_root: Project root path.
        epic_num: Epic number.
        story_num: Story number.
        run_timestamp: Unified timestamp for this validation run.
        timeout: Timeout in seconds.
        config: Optional config for extraction provider/model.

    Returns:
        List with same order as inputs. Failed extractions are None.

    """
    extraction_tasks = []

    # Get extraction provider/model from helper config or use defaults
    extraction_provider = "claude-subprocess"
    extraction_model = "haiku"
    extraction_settings_file = None
    if config is not None and config.providers.helper:
        extraction_provider = config.providers.helper.provider
        # Prefer model_name (e.g., "glm-4.5-air") over model (e.g., "haiku")
        extraction_model = config.providers.helper.model_name or config.providers.helper.model
        settings_path = config.providers.helper.settings_path
        extraction_settings_file = str(settings_path) if settings_path else None

    for output in successful_outputs:
        context = ExtractionContext(
            story_epic=epic_num,
            story_num=story_num,
            timestamp=run_timestamp,
            project_root=project_root,
            timeout_seconds=timeout,
            provider=extraction_provider,
            model=extraction_model,
            settings_file=extraction_settings_file,
        )
        task = asyncio.create_task(_safe_extract_metrics(output.content, context))
        extraction_tasks.append(task)

    # Run all extractions in parallel
    results = await asyncio.gather(*extraction_tasks, return_exceptions=False)
    return list(results)


def create_synthesizer_record(
    synthesis_output: str,
    workflow_info: WorkflowInfo,
    story_info: StoryInfo,
    provider: str,
    model: str,
    start_time: datetime,
    end_time: datetime,
    input_tokens: int,
    output_tokens: int,
    validator_count: int,
) -> LLMEvaluationRecord:
    """Create evaluation record for synthesizer.

    Story 13.6: Synthesizer Schema Integration

    The synthesizer record captures metrics from the synthesis phase,
    including quality and consensus data extracted from structured JSON output.

    Args:
        synthesis_output: Raw synthesis LLM output containing metrics JSON.
        workflow_info: Workflow identification (validate-story-synthesis).
        story_info: Story being validated.
        provider: Synthesizer provider name.
        model: Synthesizer model name.
        start_time: Synthesis start time (UTC).
        end_time: Synthesis end time (UTC).
        input_tokens: Input token count.
        output_tokens: Output token count.
        validator_count: Number of validators (for sequence_position).

    Returns:
        LLMEvaluationRecord for synthesizer with extracted metrics.

    """
    # Extract metrics from synthesis output
    metrics = extract_synthesis_metrics(synthesis_output)

    # Create evaluator info for synthesizer
    # CRITICAL: synthesizer has role_id=None per EvaluatorInfo validation
    evaluator = EvaluatorInfo(
        provider=provider,
        model=model,
        role=EvaluatorRole.SYNTHESIZER,
        role_id=None,  # CRITICAL: synthesizer has no role_id
        session_id=str(uuid4()),
    )

    # Calculate duration
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    execution = ExecutionTelemetry(
        start_time=start_time,
        end_time=end_time,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        retries=0,
        sequence_position=validator_count,  # Synthesizer runs after all validators
    )

    # Analyze output structure
    output = OutputAnalysis(
        char_count=len(synthesis_output),
        heading_count=synthesis_output.count("\n#"),
        list_depth_max=0,  # Not calculated for synthesis
        code_block_count=synthesis_output.count("```"),
        sections_detected=[],  # Not extracted for synthesis
        anomalies=[],
    )

    environment = _create_environment_info()

    return LLMEvaluationRecord(
        # record_id and created_at auto-generated
        workflow=workflow_info,
        story=story_info,
        evaluator=evaluator,
        execution=execution,
        output=output,
        environment=environment,
        quality=metrics.quality if metrics else None,
        consensus=metrics.consensus if metrics else None,
        ground_truth=None,  # Populated by Story 13.7
    )
