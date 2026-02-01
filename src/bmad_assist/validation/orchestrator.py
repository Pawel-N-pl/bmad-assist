"""Validation orchestrator for Multi-LLM validation phase.

This module coordinates the complete validation flow:
1. Compile validate-story for each provider
2. Invoke validators in parallel
3. Extract validation reports from LLM output (using markers)
4. Collect ValidationOutput from each successful validator
5. Anonymize validations
6. Save individual validation reports
7. Save mapping
8. Check minimum threshold (AFTER saving to prevent data loss)
9. Run benchmarking extraction if enabled
10. Return results for synthesis phase

Story 22.8: Threshold check moved AFTER saving reports to prevent data loss.

Report Extraction:
    Validators output to stdout with markers:
    <!-- VALIDATION_REPORT_START --> ... <!-- VALIDATION_REPORT_END -->
    The orchestrator uses extract_validation_report() to extract clean content.

Story 11.7: Validation Phase Loop Integration

Public API:
    ValidationError: Base exception for validation errors
    InsufficientValidationsError: Raised when fewer than minimum validations completed
    ValidationPhaseResult: Result dataclass for validation phase
    run_validation_phase: Main orchestration function
    save_validations_for_synthesis: Save validations for inter-handler passing
    load_validations_for_synthesis: Load validations from cache
"""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.benchmarking import (
    CollectorContext,
    DeterministicMetrics,
    collect_deterministic_metrics,
)
from bmad_assist.compiler import compile_workflow
from bmad_assist.compiler.types import CompilerContext
from bmad_assist.core.config import Config, get_phase_timeout
from bmad_assist.core.config.loaders import parse_parallel_delay
from bmad_assist.core.config.models.providers import (
    MultiProviderConfig,
    get_phase_provider_config,
)
from bmad_assist.core.exceptions import BmadAssistError
from bmad_assist.core.io import get_original_cwd, save_prompt

# get_paths() NOT used - validations_dir derived from project_path directly
# to ensure reports are saved to the correct project (not CLI working directory)
from bmad_assist.core.types import EpicId
from bmad_assist.providers import get_provider
from bmad_assist.providers.base import BaseProvider
from bmad_assist.validation.anonymizer import (
    AnonymizedValidation,
    ValidationOutput,
    anonymize_validations,
    save_mapping,
)
from bmad_assist.validation.benchmarking_integration import (
    _create_story_info,
    _create_workflow_info,
    _finalize_evaluation_record,
    _run_parallel_extraction,
    should_collect_benchmarking,
)
from bmad_assist.validation.reports import extract_validation_report, save_validation_report

if TYPE_CHECKING:
    from bmad_assist.benchmarking import LLMEvaluationRecord
    from bmad_assist.validation.evidence_score import EvidenceScoreAggregate

logger = logging.getLogger(__name__)

# Type alias for validator invocation result (provider_id, output, deterministic, error)
_ValidatorResult = tuple[str, ValidationOutput | None, DeterministicMetrics | None, str | None]

__all__ = [
    "ValidationError",
    "InsufficientValidationsError",
    "ValidationPhaseResult",
    "run_validation_phase",
    "save_validations_for_synthesis",
    "load_validations_for_synthesis",
]

# Minimum validators required for synthesis
_MIN_VALIDATORS = 2


# F7 FIX: Use shared delayed_invoke instead of local duplicate
from bmad_assist.core.async_utils import delayed_invoke

# Tools allowed for validators (read-only + organization tools)
# Write/Edit/Bash restricted to prevent file modification
_VALIDATOR_ALLOWED_TOOLS: list[str] = [
    "TodoWrite",  # Task organization
    "Read",  # File reading
    "Grep",  # Content search
    "Glob",  # File pattern matching
    "WebFetch",  # Web content fetching
    "WebSearch",  # Web search
]


class ValidationError(BmadAssistError):
    """Base exception for validation phase errors."""

    pass


class InsufficientValidationsError(ValidationError):
    """Raised when fewer than minimum validations completed.

    Attributes:
        count: Number of successful validations.
        minimum: Minimum required validations.

    """

    def __init__(self, count: int, minimum: int = _MIN_VALIDATORS) -> None:
        """Initialize InsufficientValidationsError.

        Args:
            count: Number of successful validations.
            minimum: Minimum required validations.

        """
        self.count = count
        self.minimum = minimum
        super().__init__(
            f"Insufficient validations: {count}/{minimum} minimum required from distinct providers"
        )


@dataclass
class ValidationPhaseResult:
    """Result of the validation phase.

    Attributes:
        anonymized_validations: List of anonymized validation outputs.
        session_id: Anonymization session ID for traceability.
        validation_count: Number of successful validations.
        validators: List of validator IDs that completed successfully.
        failed_validators: List of validators that timed out/failed.
        evaluation_records: Benchmarking records (Story 13.4), one per successful validator.
        evidence_aggregate: Pre-calculated Evidence Score aggregate (TIER 2).

    """

    anonymized_validations: list[AnonymizedValidation]
    session_id: str
    validation_count: int
    validators: list[str] = field(default_factory=list)
    failed_validators: list[str] = field(default_factory=list)
    evaluation_records: list["LLMEvaluationRecord"] = field(default_factory=list)
    evidence_aggregate: "EvidenceScoreAggregate | None" = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for PhaseResult.outputs.

        Note: evaluation_records are NOT included in to_dict() as they are
        too large for PhaseResult.outputs. They are passed separately to
        the storage layer (Story 13.5).

        Returns:
            Dictionary with serializable values for PhaseResult.

        """
        return {
            "session_id": self.session_id,
            "validation_count": self.validation_count,
            "validators": self.validators,
            "failed_validators": self.failed_validators,
            # Records passed separately to storage layer
        }


def _calculate_evidence_aggregate(
    anonymized: list[AnonymizedValidation],
) -> "EvidenceScoreAggregate | None":
    """Calculate Evidence Score aggregate from anonymized validations.

    Parses evidence scores from each validation output and aggregates them.
    Failures are logged but don't break the validation phase.

    Args:
        anonymized: List of anonymized validation outputs.

    Returns:
        EvidenceScoreAggregate if at least one report could be parsed, None otherwise.

    """
    try:
        from bmad_assist.validation.evidence_score import (
            aggregate_evidence_scores,
            parse_evidence_findings,
        )

        evidence_reports = []
        for av in anonymized:
            report = parse_evidence_findings(av.content, av.validator_id)
            if report is not None:
                evidence_reports.append(report)
                logger.debug(
                    "Parsed evidence report for %s: score=%.1f",
                    av.validator_id,
                    report.total_score,
                )

        if evidence_reports:
            aggregate = aggregate_evidence_scores(evidence_reports)
            logger.info(
                "Evidence Score aggregate: total=%.1f, verdict=%s, validators=%d",
                aggregate.total_score,
                aggregate.verdict.value,
                len(evidence_reports),
            )
            return aggregate
        else:
            logger.warning("No valid Evidence Score reports found in validations")
            return None
    except Exception as e:
        # Don't fail validation phase if evidence scoring fails
        logger.warning("Evidence Score calculation failed: %s", e)
        return None


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text.

    Simple heuristic: ~4 characters per token on average.

    Args:
        text: Text to estimate tokens for.

    Returns:
        Estimated token count.

    """
    return len(text) // 4


async def _invoke_validator(
    provider: BaseProvider,
    prompt: str,
    timeout: int,
    provider_id: str,
    model: str,
    provider_name: str | None = None,
    allowed_tools: list[str] | None = None,
    run_timestamp: datetime | None = None,
    epic_num: EpicId = 0,
    story_num: int | str = 0,
    benchmarking_enabled: bool = False,
    settings_file: Path | None = None,
    color_index: int | None = None,
    cwd: Path | None = None,
    display_model: str | None = None,
    thinking: bool | None = None,
) -> tuple[str, ValidationOutput | None, DeterministicMetrics | None, str | None]:
    """Invoke a single validator using asyncio.to_thread.

    Args:
        provider: Provider instance to invoke.
        prompt: Compiled prompt to send.
        timeout: Timeout in seconds.
        provider_id: Identifier for this validator (used for logging/display).
        model: Model to use for CLI invocation (e.g., "sonnet", "opus").
        provider_name: Actual provider name for benchmarking (e.g., "claude-subprocess").
            If None, uses provider.provider_name.
        allowed_tools: List of tool names to allow. If None, all tools allowed.
            For validators, typically ["TodoWrite"] to prevent file modification.
        run_timestamp: Unified timestamp for this validation run. If None, uses now().
        epic_num: Epic number for benchmarking context (AC1).
        story_num: Story number for benchmarking context (AC1).
        benchmarking_enabled: Whether to collect deterministic metrics (AC1, AC7).
        settings_file: Optional path to provider settings file.
        color_index: Index for console output color (0-7). Each provider gets a
            different color for visual distinction in parallel execution.
        cwd: Working directory for the provider. Used to allow validators to
            access files in the target project directory.
        display_model: Human-readable model name for progress output (e.g., "glm-4.7"
            instead of "sonnet" when using GLM via settings file).
        thinking: Enable thinking mode for supported providers (e.g., kimi).
            If None, auto-detected from model name.

    Returns:
        Tuple of (provider_id, ValidationOutput or None, DeterministicMetrics or None,
        error_message or None).

    """
    try:
        start_time = datetime.now(UTC)
        # Use unified run timestamp for consistency across all validators
        validation_timestamp = run_timestamp or start_time

        # Use asyncio.wait_for with to_thread for ALL providers
        # This maintains BaseProvider contract boundary
        # Pass model and allowed_tools to control validator behavior
        result = await asyncio.wait_for(
            asyncio.to_thread(
                provider.invoke,
                prompt,
                model=model,
                timeout=timeout,
                allowed_tools=allowed_tools,
                settings_file=settings_file,
                color_index=color_index,
                cwd=cwd,
                display_model=display_model,
                thinking=thinking,
            ),  # type: ignore[call-arg]  # mypy doesn't handle to_thread kwargs well
            timeout=timeout,
        )

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

        if result.exit_code != 0:
            error_msg = result.stderr or f"Provider exited with code {result.exit_code}"
            logger.warning(
                "Validator %s returned non-zero exit code %d: %s",
                provider_id,
                result.exit_code,
                error_msg[:200],
            )
            return provider_id, None, None, error_msg

        # Extract validation report from raw LLM output
        # This handles markers, code blocks, and thinking/commentary
        raw_content = result.stdout
        extracted_content = extract_validation_report(raw_content)

        # Use actual provider name for benchmarking, not the display identifier
        actual_provider = provider_name or provider.provider_name

        output = ValidationOutput(
            provider=actual_provider,
            model=result.model or "unknown",
            content=extracted_content,
            timestamp=validation_timestamp,
            duration_ms=duration_ms,
            token_count=_estimate_tokens(extracted_content),
            provider_session_id=result.provider_session_id,
        )

        logger.info(
            "Validator %s completed in %dms (%d tokens, session=%s)",
            provider_id,
            duration_ms,
            output.token_count,
            (result.provider_session_id or "none")[:16],
        )

        # AC1: Collect deterministic metrics immediately after validator completes
        deterministic: DeterministicMetrics | None = None
        if benchmarking_enabled:
            try:
                context = CollectorContext(
                    story_epic=epic_num,
                    story_num=story_num,
                    timestamp=validation_timestamp,
                )
                deterministic = collect_deterministic_metrics(extracted_content, context)
                logger.debug("Collected deterministic metrics for %s", provider_id)
            except Exception as e:
                logger.warning(
                    "Deterministic collection failed for %s: %s",
                    provider_id,
                    e,
                )
                # deterministic remains None - AC6: continue without metrics

        return provider_id, output, deterministic, None

    except TimeoutError:
        error_msg = f"Validator {provider_id} timed out after {timeout}s"
        logger.warning(error_msg)
        return provider_id, None, None, error_msg

    except Exception as e:
        error_msg = f"Validator {provider_id} failed: {e}"
        logger.warning(error_msg, exc_info=True)
        return provider_id, None, None, error_msg


def _compile_validation_prompt(
    project_path: Path,
    epic_num: EpicId,
    story_num: int | str,
) -> str:
    """Compile validate-story workflow.

    Args:
        project_path: Path to project root.
        epic_num: Epic number.
        story_num: Story number.

    Returns:
        Compiled prompt XML.

    """
    # Use get_original_cwd() to preserve original CWD when running as subprocess
    from bmad_assist.core.paths import get_paths

    paths = get_paths()
    context = CompilerContext(
        project_root=project_path,
        output_folder=paths.implementation_artifacts,
        project_knowledge=paths.project_knowledge,
        cwd=get_original_cwd(),
        resolved_variables={
            "epic_num": epic_num,
            "story_num": story_num,
        },
    )

    compiled = compile_workflow("validate-story", context)
    return compiled.context


async def run_validation_phase(
    config: Config,
    project_path: Path,
    epic_num: EpicId,
    story_num: int | str,
) -> ValidationPhaseResult:
    """Run complete validation phase with parallel Multi-LLM invocation.

    Orchestrates the complete validation flow:
    1. Compile validate-story once
    2. Invoke ALL validators in parallel (multi + master)
    3. Filter successful results
    4. Anonymize validations
    5. Save individual validation reports
    6. Save mapping
    7. Check minimum threshold (AFTER saving to prevent data loss)
    8. Run benchmarking extraction if enabled
    9. Return ValidationPhaseResult

    Story 22.8: Threshold check moved AFTER saving reports to prevent data loss.

    Args:
        config: Application configuration with provider settings.
        project_path: Path to project root.
        epic_num: Epic number being validated.
        story_num: Story number being validated.

    Returns:
        ValidationPhaseResult with anonymized validations and metadata.

    Raises:
        InsufficientValidationsError: If fewer than 2 validators succeeded.

    """
    # Generate unified timestamp for this validation run
    # All validation outputs, reports, and cache files will use this timestamp
    run_timestamp = datetime.now(UTC)

    logger.info(
        "Starting validation phase for story %s.%s (run=%s)",
        epic_num,
        story_num,
        run_timestamp.isoformat(),
    )

    # Step 1: Compile prompt once
    logger.debug("Compiling validate-story workflow")
    prompt = _compile_validation_prompt(project_path, epic_num, story_num)
    logger.debug("Compiled prompt: %d chars", len(prompt))

    # Save prompt to .bmad-assist/prompts/ (atomic write, always saved)
    save_prompt(project_path, epic_num, story_num, "validate-story", prompt)

    # Step 2: Build list of validators (multi + master)
    timeout = get_phase_timeout(config, "validate_story")
    # AC7: Check if benchmarking is enabled
    benchmarking_enabled = should_collect_benchmarking(config)
    if benchmarking_enabled:
        logger.debug("Benchmarking enabled - will collect metrics")

    # Type now includes DeterministicMetrics as 3rd element (AC1)
    tasks: list[asyncio.Task[_ValidatorResult]] = []

    # Add multi providers (from phase_models if configured, else global providers.multi)
    # Restrict tools to prevent file modification (only TodoWrite allowed)
    # Color index based on provider order for visual distinction
    multi_configs_raw = get_phase_provider_config(config, "validate_story")
    # Type narrowing: validate_story is multi-LLM, so must be list
    multi_configs: list[MultiProviderConfig] = (
        multi_configs_raw if isinstance(multi_configs_raw, list) else []
    )
    for idx, multi_config in enumerate(multi_configs):
        provider = get_provider(multi_config.provider)
        # Use display_model (model_name if set) for logging, model for CLI invocation
        provider_id = f"{multi_config.provider}-{multi_config.display_model}"
        # Staggered start: each task waits idx * delay before starting
        # Parse delay at runtime for each task (randomization per-call if range configured)
        delay = parse_parallel_delay(config.parallel_delay) * idx
        coro = _invoke_validator(
            provider,
            prompt,
            timeout,
            provider_id,
            model=multi_config.model,
            provider_name=multi_config.provider,  # Actual provider for benchmarking
            allowed_tools=_VALIDATOR_ALLOWED_TOOLS,
            run_timestamp=run_timestamp,
            epic_num=epic_num,
            story_num=story_num,
            benchmarking_enabled=benchmarking_enabled,
            settings_file=multi_config.settings_path,
            color_index=idx,
            cwd=project_path,
            display_model=multi_config.display_model,
            thinking=multi_config.thinking,
        )
        task = asyncio.create_task(delayed_invoke(delay, coro))
        tasks.append(task)

    # Add master as validator ONLY when using global providers.multi fallback
    # When phase_models.validate_story is defined, user has full control - no auto-add
    phase_has_override = config.phase_models and "validate_story" in config.phase_models
    if not phase_has_override:
        master_provider = get_provider(config.providers.master.provider)
        master_id = f"master-{config.providers.master.display_model}"
        master_color_index = len(multi_configs)
        # Staggered start for master: uses next index after all multi configs
        master_delay = parse_parallel_delay(config.parallel_delay) * master_color_index
        master_coro = _invoke_validator(
            master_provider,
            prompt,
            timeout,
            master_id,
            model=config.providers.master.model,
            provider_name=config.providers.master.provider,  # Actual provider for benchmarking
            allowed_tools=_VALIDATOR_ALLOWED_TOOLS,
            run_timestamp=run_timestamp,
            epic_num=epic_num,
            story_num=story_num,
            benchmarking_enabled=benchmarking_enabled,
            settings_file=config.providers.master.settings_path,
            color_index=master_color_index,
            cwd=project_path,
            display_model=config.providers.master.display_model,
        )
        master_task = asyncio.create_task(delayed_invoke(master_delay, master_coro))
        tasks.append(master_task)
    else:
        logger.debug(
            "phase_models.validate_story defined - master NOT auto-added"
        )

    logger.info("Invoking %d validators in parallel", len(tasks))

    # Step 3: Run all validators in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Step 4: Collect successful results (now includes deterministic metrics)
    successful_outputs: list[ValidationOutput] = []
    successful_deterministic: list[DeterministicMetrics] = []  # AC1: paired with outputs
    successful_validators: list[str] = []
    failed_validators: list[str] = []

    for result in results:
        if isinstance(result, BaseException):
            # Unexpected exception (shouldn't happen with return_exceptions=True)
            logger.error("Unexpected exception in validator: %s", result)
            continue

        # result is tuple[str, ValidationOutput | None, DeterministicMetrics | None, str | None]
        provider_id, output, deterministic, error = result

        if output is not None:
            successful_outputs.append(output)
            successful_validators.append(provider_id)
            # AC1: Store deterministic metrics alongside output (may be None if collection failed)
            if deterministic is not None:
                successful_deterministic.append(deterministic)
        else:
            failed_validators.append(provider_id)

    # Story 22.11 Task 6.5: Log complete validation results summary
    total_validators = len(successful_validators) + len(failed_validators)
    logger.info(
        "All %d validators completed (%d succeeded, %d failed/timeout)",
        total_validators,
        len(successful_validators),
        len(failed_validators),
    )

    # Story 22.11 Task 6.2: Log individual validator completion details
    for provider_id in successful_validators:
        logger.info("Validator %s completed successfully", provider_id)
    for provider_id in failed_validators:
        logger.warning("Validator %s failed", provider_id)

    # Step 5: Anonymize validations FIRST (before saving reports)
    # This ensures report filenames use anonymized IDs, not provider names
    # Pass run_timestamp for consistent timestamps across all artifacts
    anonymized, mapping = anonymize_validations(successful_outputs, run_timestamp=run_timestamp)
    logger.debug("Anonymizing %d validation outputs", len(successful_outputs))
    for validator_id, meta in mapping.mapping.items():
        logger.debug("Assigned %s to %s/%s", validator_id, meta["provider"], meta["model"])
    logger.debug("Anonymization complete. Session ID: %s", mapping.session_id)

    # Step 6: Save individual validation reports with anonymized IDs
    # PATH RESOLUTION NOTE:
    # Using get_paths() singleton is correct for normal bmad-assist run.
    # The singleton IS initialized for the current project in cli.py.
    #
    # Historical note: This code previously avoided get_paths() due to
    # experiment scenarios where CLI runs on PROJECT_A but validates
    # files in PROJECT_B. That case is now handled by experiments/runner.py
    # which calls _reset_paths() + init_paths(target_project) before each run.
    #
    # For external paths support, we MUST use get_paths() to respect
    # user's configured output_folder location.
    # Story 22.8: Save reports BEFORE threshold check to prevent data loss on partial failure
    from bmad_assist.core.paths import get_paths

    validations_dir = get_paths().validations_dir
    validations_dir.mkdir(parents=True, exist_ok=True)

    # Save reports with role_id (a, b, c...) for filename and anonymized_id for display
    # Use output index for deterministic role_id assignment
    # AC #5: Log warnings on save failure but don't crash validation phase
    role_ids = "abcdefghijklmnopqrstuvwxyz"
    validator_ids = list(mapping.mapping.keys())

    for idx, output in enumerate(successful_outputs):
        # Generate role_id from index (a, b, c...)
        role_id = role_ids[idx] if idx < len(role_ids) else f"role_{idx}"

        # Get anonymized_id from mapping for display (Validator A, etc.)
        anonymized_id = validator_ids[idx] if idx < len(validator_ids) else None

        try:
            save_validation_report(
                output=output,
                epic=epic_num,
                story=story_num,
                phase="VALIDATE_STORY",
                validations_dir=validations_dir,
                anonymized_id=anonymized_id,
                role_id=role_id,
                session_id=mapping.session_id,  # Story 22.8 AC#3: Link to mapping
            )
        except OSError as e:
            # AC #5: Log warning but continue with other reports
            logger.warning(
                "Failed to save validation report for validator %s: %s",
                role_id,
                e,
            )
            # Continue with next report rather than crashing

    # Step 7: Save mapping (with error handling per AC #5)
    try:
        save_mapping(mapping, project_path)
    except OSError as e:
        logger.warning(
            "Failed to save validation mapping: %s",
            e,
        )

    # Step 8: Check minimum threshold AFTER saving reports
    # Story 22.8: Moved threshold check to AFTER saving to prevent data loss
    # If only 1 validator succeeds, we still want to save that single report
    # before raising InsufficientValidationsError
    if len(successful_outputs) < _MIN_VALIDATORS:
        raise InsufficientValidationsError(
            count=len(successful_outputs),
            minimum=_MIN_VALIDATORS,
        )

    # Step 9: AC2/AC3 - Run parallel extraction and finalize evaluation records
    from bmad_assist.benchmarking import LLMEvaluationRecord  # Local import to avoid circular

    evaluation_records: list[LLMEvaluationRecord] = []

    # Allow partial benchmarking: extract for validators with successful metrics collection
    # Don't skip ALL benchmarking just because ONE validator's metrics failed to parse
    if benchmarking_enabled and len(successful_deterministic) > 0:
        logger.info(
            "Running parallel metrics extraction for %d validators",
            len(successful_outputs),
        )

        try:
            # AC2: Run extraction in parallel for validators with successful metrics
            # Note: extracted_list length may differ from successful_outputs if some metrics failed
            extracted_list = await _run_parallel_extraction(
                successful_outputs=successful_outputs,
                deterministic_results=successful_deterministic,
                project_root=project_path,
                epic_num=epic_num,
                story_num=story_num,
                run_timestamp=run_timestamp,
                timeout=timeout,
                config=config,
            )

            # AC3/AC4: Finalize evaluation records with workflow variant
            workflow_info = _create_workflow_info(
                workflow_id="validate-story",
                variant=config.workflow_variant,  # AC4: propagate variant
                patch_applied=False,  # TODO: detect from compiler context in future
            )

            # Map deterministic metrics by provider index to handle partial extraction
            # Zip without strict to allow different list lengths when some metrics failed
            for idx, (output, deterministic, extracted) in enumerate(
                zip(successful_outputs, successful_deterministic, extracted_list, strict=False)
            ):
                # AC6: Skip if extraction failed (partial results discarded)
                if extracted is None:
                    logger.warning(
                        "Skipping record for %s due to extraction failure",
                        output.provider,
                    )
                    continue

                # Look up anonymized_id by index (consistent with Step 7)
                validator_ids = list(mapping.mapping.keys())
                anonymized_id = validator_ids[idx] if idx < len(validator_ids) else ""

                story_info = _create_story_info(
                    epic_num=epic_num,
                    story_num=story_num,
                    title=f"Story {epic_num}.{story_num}",
                    complexity_flags=extracted.to_complexity_flags(),
                )

                record = _finalize_evaluation_record(
                    validation_output=output,
                    deterministic=deterministic,
                    extracted=extracted,
                    workflow_info=workflow_info,
                    story_info=story_info,
                    anonymized_id=anonymized_id,
                    sequence_position=idx,
                )
                evaluation_records.append(record)

            logger.info(
                "Benchmarking complete: %d evaluation records created",
                len(evaluation_records),
            )

        except Exception as e:
            # AC6: Extraction failures don't block validation phase
            logger.error("Parallel extraction failed: %s", e, exc_info=True)
            # Continue with empty evaluation_records

    elif benchmarking_enabled:
        logger.warning(
            "Skipping extraction: deterministic metrics count (%d) != outputs count (%d)",
            len(successful_deterministic),
            len(successful_outputs),
        )

    logger.info(
        "Validation phase complete. Session ID: %s",
        mapping.session_id,
    )

    # TIER 2: Calculate Evidence Score aggregate from anonymized validations
    evidence_aggregate = _calculate_evidence_aggregate(anonymized)

    # AC5: Return evaluation_records in ValidationPhaseResult
    return ValidationPhaseResult(
        anonymized_validations=anonymized,
        session_id=mapping.session_id,
        validation_count=len(successful_outputs),
        validators=successful_validators,
        failed_validators=failed_validators,
        evaluation_records=evaluation_records,
        evidence_aggregate=evidence_aggregate,
    )


# =============================================================================
# Inter-handler data passing (Option C: File-based with session_id)
# =============================================================================


def save_validations_for_synthesis(
    anonymized: list[AnonymizedValidation],
    project_root: Path,
    session_id: str | None = None,
    run_timestamp: datetime | None = None,
    failed_validators: list[str] | None = None,
    evidence_aggregate: "EvidenceScoreAggregate | None" = None,
) -> str:
    """Save anonymized validations for synthesis phase retrieval.

    Uses file-based storage at .bmad-assist/cache/validations-{session_id}.json
    Cache version 2 includes Evidence Score aggregate data.

    Args:
        anonymized: List of anonymized validations.
        project_root: Project root directory.
        session_id: Optional session ID to use. If None, generates new UUID.
            Pass mapping.session_id to maintain traceability with anonymizer.
        run_timestamp: Unified timestamp for this validation run. If None, uses now().
        failed_validators: List of validators that failed/timed out (Story 22.8 AC#4).
        evidence_aggregate: Pre-calculated Evidence Score aggregate (TIER 2).

    Returns:
        Session ID for later retrieval.

    """
    # Import here to avoid circular dependency
    from bmad_assist.validation.evidence_score import Severity

    if session_id is None:
        session_id = str(uuid.uuid4())
    cache_dir = project_root / ".bmad-assist" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    file_path = cache_dir / f"validations-{session_id}.json"
    temp_path = file_path.with_suffix(".json.tmp")

    # Use unified run timestamp for consistency
    timestamp = run_timestamp or datetime.now(UTC)

    data: dict[str, Any] = {
        "cache_version": 2,  # ADR-4: Cache versioning for Evidence Score
        "session_id": session_id,
        "timestamp": timestamp.isoformat(),
        "validations": [
            {
                "validator_id": v.validator_id,
                "content": v.content,
                "original_ref": v.original_ref,
            }
            for v in anonymized
        ],
    }

    # Story 22.8 AC#4: Store failed_validators for synthesis context
    if failed_validators:
        data["failed_validators"] = failed_validators

    # TIER 2: Store Evidence Score aggregate
    if evidence_aggregate is not None:
        data["evidence_score"] = {
            "total_score": evidence_aggregate.total_score,
            "verdict": evidence_aggregate.verdict.value,
            "per_validator": {
                vid: {
                    "score": evidence_aggregate.per_validator_scores[vid],
                    "verdict": evidence_aggregate.per_validator_verdicts[vid].value,
                }
                for vid in evidence_aggregate.per_validator_scores
            },
            "findings_summary": {
                "CRITICAL": evidence_aggregate.findings_by_severity.get(Severity.CRITICAL, 0),
                "IMPORTANT": evidence_aggregate.findings_by_severity.get(Severity.IMPORTANT, 0),
                "MINOR": evidence_aggregate.findings_by_severity.get(Severity.MINOR, 0),
                "CLEAN_PASS": evidence_aggregate.total_clean_passes,
            },
            "consensus_ratio": evidence_aggregate.consensus_ratio,
            "total_findings": evidence_aggregate.total_findings,
            "consensus_count": len(evidence_aggregate.consensus_findings),
            "unique_count": len(evidence_aggregate.unique_findings),
        }

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, file_path)
        logger.info("Saved validations for synthesis (v2): %s", file_path)
    except OSError:
        if temp_path.exists():
            temp_path.unlink()
        raise

    return session_id


def load_validations_for_synthesis(
    session_id: str,
    project_root: Path,
) -> tuple[list[AnonymizedValidation], list[str], dict[str, Any] | None]:
    """Load anonymized validations by session ID.

    Args:
        session_id: Session ID from save_validations_for_synthesis.
        project_root: Project root directory.

    Returns:
        Tuple of (validations, failed_validators, evidence_score):
        - validations: List of AnonymizedValidation objects.
        - failed_validators: List of validators that failed/timed out (Story 22.8 AC#4).
            Empty list for backward compatibility with old cache files.
        - evidence_score: Pre-calculated Evidence Score dict (TIER 2) or None.

    Raises:
        ValidationError: If file not found or invalid.
        CacheVersionError: If cache version is v1 (requires re-run).
        CacheFormatError: If v2 cache is missing required keys.

    """
    # Import here to avoid circular dependency
    from bmad_assist.validation.evidence_score import CacheVersionError

    cache_dir = project_root / ".bmad-assist" / "cache"
    file_path = cache_dir / f"validations-{session_id}.json"

    if not file_path.exists():
        raise ValidationError(f"Validations not found for session: {session_id}")

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValidationError(f"Invalid validation cache file: {e}") from e
    except OSError as e:
        raise ValidationError(f"Cannot read validation cache: {e}") from e

    # ADR-4: Check cache version
    cache_version = data.get("cache_version")
    if cache_version is None or cache_version < 2:
        raise CacheVersionError(
            found_version=cache_version,
            required_version=2,
            message=(
                f"Validation cache version {cache_version or 'missing'} is incompatible. "
                "Evidence Score TIER 2 requires cache version 2. "
                "Re-run validation phase to generate new cache."
            ),
        )

    # Load evidence_score (optional - may be None if validators use old report format)
    evidence_score = data.get("evidence_score")
    if evidence_score is None:
        # TIER 2 evidence_score is optional - validators may use Story Quality Verdict
        # format instead of Evidence Score format. Log warning but continue.
        logger.warning(
            "Cache file %s has no evidence_score - validators may use incompatible report format. "
            "Synthesis will proceed without Evidence Score context.",
            file_path.name,
        )

    validations = []
    for v in data.get("validations", []):
        validations.append(
            AnonymizedValidation(
                validator_id=v["validator_id"],
                content=v["content"],
                original_ref=v["original_ref"],
            )
        )

    # Story 22.8 AC#4: Load failed_validators with backward compatibility
    # Use 'or' to handle both missing key AND explicit None value in old cache files
    failed_validators = data.get("failed_validators") or []

    logger.debug(
        "Loaded %d validations, %d failed validators, evidence_score=%s for session %s",
        len(validations),
        len(failed_validators),
        evidence_score.get("total_score") if evidence_score else None,
        session_id,
    )
    return validations, failed_validators, evidence_score
