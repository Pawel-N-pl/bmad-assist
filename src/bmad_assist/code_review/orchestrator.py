"""Code review orchestrator for Multi-LLM code review phase.

Story 13.10: Code Review Benchmarking Integration

This module coordinates the complete code review flow following the same
pattern as validation/orchestrator.py:
1. Compile code-review workflow once
2. Invoke ALL reviewers in parallel (multi + master)
3. Filter successful results
4. Check minimum threshold (≥2 distinct reviewers)
5. Anonymize reviews
6. Save mapping
7. Collect benchmarking metrics (if enabled)
8. Return CodeReviewPhaseResult

The key difference from validation is:
- workflow.id = "code-review" (not "validate-story")
- workflow.id = "code-review-synthesis" for synthesizer records

Public API:
    CodeReviewError: Base exception for code review errors
    InsufficientReviewsError: Raised when fewer than minimum reviews completed
    CodeReviewPhaseResult: Result dataclass for code review phase
    run_code_review_phase: Main orchestration function
    save_reviews_for_synthesis: Save reviews for inter-handler passing
    load_reviews_for_synthesis: Load reviews from cache
    CODE_REVIEW_WORKFLOW_ID: Constant for workflow identification
    CODE_REVIEW_SYNTHESIS_WORKFLOW_ID: Constant for synthesis workflow
"""

import asyncio
import json
import logging
import re
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
from bmad_assist.core.config import Config, get_phase_retries, get_phase_timeout
from bmad_assist.core.config.loaders import parse_parallel_delay
from bmad_assist.core.config.models.providers import (
    MultiProviderConfig,
    get_phase_provider_config,
)
from bmad_assist.core.exceptions import BmadAssistError, CompilerError
from bmad_assist.core.extraction import CODE_REVIEW_MARKERS, extract_report
from bmad_assist.core.io import get_original_cwd, save_prompt
from bmad_assist.core.loop.dashboard_events import (
    emit_security_review_completed,
    emit_security_review_failed,
    emit_security_review_started,
)
from bmad_assist.core.paths import get_paths
from bmad_assist.core.retry import invoke_with_timeout_retry
from bmad_assist.core.types import EpicId
from bmad_assist.deep_verify.core.types import DeepVerifyValidationResult
from bmad_assist.deep_verify.integration import (
    _resolve_code_files,
    run_deep_verify_code_review_batch,
    save_dv_findings_for_synthesis,
)
from bmad_assist.providers import get_provider
from bmad_assist.providers.base import BaseProvider
from bmad_assist.security.agent import run_security_review
from bmad_assist.security.integration import save_security_findings_for_synthesis
from bmad_assist.security.report import SecurityReport
from bmad_assist.validation.anonymizer import (
    AnonymizedValidation,
    ValidationOutput,
    anonymize_validations,
)
from bmad_assist.validation.benchmarking_integration import (
    _create_story_info,
    _create_workflow_info,
    _finalize_evaluation_record,
    _run_parallel_extraction,
    should_collect_benchmarking,
)

if TYPE_CHECKING:
    from bmad_assist.benchmarking import LLMEvaluationRecord
    from bmad_assist.validation.anonymizer import AnonymizationMapping
    from bmad_assist.validation.evidence_score import EvidenceScoreAggregate

logger = logging.getLogger(__name__)

# Workflow ID constants
CODE_REVIEW_WORKFLOW_ID = "code-review"
CODE_REVIEW_SYNTHESIS_WORKFLOW_ID = "code-review-synthesis"

# Type alias for reviewer invocation result (reviewer_id, output, deterministic, error)
_ReviewerResult = tuple[str, ValidationOutput | None, DeterministicMetrics | None, str | None]

__all__ = [
    "CodeReviewError",
    "InsufficientReviewsError",
    "CodeReviewPhaseResult",
    "run_code_review_phase",
    "save_reviews_for_synthesis",
    "load_reviews_for_synthesis",
    "CODE_REVIEW_WORKFLOW_ID",
    "CODE_REVIEW_SYNTHESIS_WORKFLOW_ID",
]

# Minimum reviewers required for synthesis
_MIN_REVIEWERS = 2


# F7 FIX: Use shared delayed_invoke instead of local duplicate
from bmad_assist.core.async_utils import delayed_invoke

# Tools allowed for reviewers (read-only access to codebase)
# Code reviewers need to read files to perform meaningful review, but must NOT modify anything
_REVIEWER_ALLOWED_TOOLS: list[str] = ["TodoWrite", "Read", "Glob", "Grep"]


class CodeReviewError(BmadAssistError):
    """Base exception for code review phase errors."""

    pass


class InsufficientReviewsError(CodeReviewError):
    """Raised when fewer than minimum reviews completed.

    Attributes:
        count: Number of successful reviews.
        minimum: Minimum required reviews.

    """

    def __init__(self, count: int, minimum: int = _MIN_REVIEWERS) -> None:
        """Initialize InsufficientReviewsError.

        Args:
            count: Number of successful reviews.
            minimum: Minimum required reviews.

        """
        self.count = count
        self.minimum = minimum
        super().__init__(
            f"Insufficient reviews: {count}/{minimum} minimum required from distinct reviewers"
        )


def _calculate_evidence_aggregate(
    anonymized: list[AnonymizedValidation],
) -> "EvidenceScoreAggregate | None":
    """Calculate Evidence Score aggregate from anonymized reviews.

    Parses evidence scores from each review output and aggregates them.
    Failures are logged but don't break the code review phase.

    Args:
        anonymized: List of anonymized review outputs.

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
                "Evidence Score aggregate: total=%.1f, verdict=%s, reviewers=%d",
                aggregate.total_score,
                aggregate.verdict.value,
                len(evidence_reports),
            )
            return aggregate
        else:
            logger.warning("No valid Evidence Score reports found in reviews")
            return None
    except Exception as e:
        # Don't fail code review phase if evidence scoring fails
        logger.warning("Evidence Score calculation failed: %s", e)
        return None


@dataclass
class CodeReviewPhaseResult:
    """Result of the code review phase.

    Mirrors ValidationPhaseResult structure for consistency.

    Attributes:
        anonymized_reviews: List of anonymized review outputs.
        session_id: Anonymization session ID for traceability.
        review_count: Number of successful reviews.
        reviewers: List of reviewer IDs that completed successfully.
        failed_reviewers: List of reviewers that timed out/failed.
        evaluation_records: Benchmarking records, one per successful reviewer.
        evidence_aggregate: Aggregated Evidence Score from all reviewers (TIER 2).

    """

    anonymized_reviews: list[AnonymizedValidation]
    session_id: str
    review_count: int
    reviewers: list[str] = field(default_factory=list)
    failed_reviewers: list[str] = field(default_factory=list)
    evaluation_records: list["LLMEvaluationRecord"] = field(default_factory=list)
    evidence_aggregate: "EvidenceScoreAggregate | None" = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for PhaseResult.outputs.

        Note: evaluation_records are NOT included in to_dict() as they are
        too large for PhaseResult.outputs. They are passed separately to
        the storage layer.

        Returns:
            Dictionary with serializable values for PhaseResult.

        """
        return {
            "session_id": self.session_id,
            "review_count": self.review_count,
            "reviewers": self.reviewers,
            "failed_reviewers": self.failed_reviewers,
        }


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text.

    Simple heuristic: ~4 characters per token on average.

    Args:
        text: Text to estimate tokens for.

    Returns:
        Estimated token count.

    """
    return len(text) // 4


def _extract_code_review_report(raw_output: str) -> str:
    """Extract code review report from raw LLM output.

    Uses shared extraction logic from core/extraction.py:
    1. Primary: Extract between <!-- CODE_REVIEW_REPORT_START/END --> markers
    2. Fallback: Try ADVERSARIAL header, Review Summary, etc.
    3. Last resort: Return entire output stripped

    Args:
        raw_output: Raw output from code review LLM.

    Returns:
        Extracted report content. Never returns empty string.

    """
    return extract_report(raw_output, CODE_REVIEW_MARKERS)


async def _invoke_reviewer(
    provider: BaseProvider,
    prompt: str,
    timeout: int,
    reviewer_id: str,
    model: str,
    timeout_retries: int | None,
    allowed_tools: list[str] | None = None,
    run_timestamp: datetime | None = None,
    epic_num: EpicId = 0,
    story_num: int | str = 0,
    benchmarking_enabled: bool = False,
    settings_file: Path | None = None,
    color_index: int | None = None,
    cwd: Path | None = None,
    display_model: str | None = None,
    provider_name: str | None = None,
    thinking: bool | None = None,
    reasoning_effort: str | None = None,
) -> tuple[str, ValidationOutput | None, DeterministicMetrics | None, str | None]:
    """Invoke a single reviewer using asyncio.to_thread.

    Follows same pattern as validation _invoke_validator.

    Args:
        provider: Provider instance to invoke.
        prompt: Compiled prompt to send.
        timeout: Timeout in seconds.
        reviewer_id: Identifier for this reviewer (uses display_model for logging).
        model: Model to use for CLI invocation (e.g., "sonnet", "opus").
        allowed_tools: List of tool names to allow. If None, all tools allowed.
        run_timestamp: Unified timestamp for this review run. If None, uses now().
        epic_num: Epic number for benchmarking context.
        story_num: Story number for benchmarking context.
        benchmarking_enabled: Whether to collect deterministic metrics.
        settings_file: Optional path to provider settings file.
        color_index: Index for console output color (0-7). Each provider gets a
            different color for visual distinction in parallel execution.
        cwd: Working directory for the provider. Used to allow reviewers to
            access files in the target project directory.
        display_model: Human-readable model name for progress output.
        reasoning_effort: Reasoning effort level for supported providers (codex).

    Returns:
        Tuple of (reviewer_id, ValidationOutput or None, DeterministicMetrics or None,
        error_message or None).

    """
    try:
        start_time = datetime.now(UTC)
        review_timestamp = run_timestamp or start_time

        # Setup fallback for claude-sdk provider (SDK init timeout -> subprocess)
        fallback_invoke_fn = None
        if provider.provider_name == "claude":
            from bmad_assist.providers.claude import ClaudeSubprocessProvider

            fallback_invoke_fn = ClaudeSubprocessProvider().invoke
            logger.debug("Configured subprocess fallback for %s", reviewer_id)

        # Use asyncio.to_thread with timeout retry wrapper
        result = await asyncio.to_thread(
            invoke_with_timeout_retry,
            provider.invoke,
            timeout_retries=timeout_retries,
            phase_name="code_review",
            fallback_invoke_fn=fallback_invoke_fn,
            prompt=prompt,
            model=model,
            timeout=timeout,
            allowed_tools=allowed_tools,
            settings_file=settings_file,
            color_index=color_index,
            cwd=cwd,
            display_model=display_model,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        )

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

        if result.exit_code != 0:
            error_msg = result.stderr or f"Provider exited with code {result.exit_code}"
            logger.warning(
                "Reviewer %s returned non-zero exit code %d: %s",
                reviewer_id,
                result.exit_code,
                error_msg[:200],
            )
            return reviewer_id, None, None, error_msg

        # Extract review report from raw LLM output
        raw_content = result.stdout
        extracted_content = _extract_code_review_report(raw_content)

        # Use actual provider name for benchmarking (not composite reviewer_id)
        actual_provider = provider_name or provider.provider_name

        output = ValidationOutput(
            provider=actual_provider,
            model=result.model or "unknown",
            content=extracted_content,
            timestamp=review_timestamp,
            duration_ms=duration_ms,
            token_count=_estimate_tokens(extracted_content),
            provider_session_id=result.provider_session_id,
        )

        logger.info(
            "Reviewer %s completed in %dms (%d tokens, session=%s)",
            reviewer_id,
            duration_ms,
            output.token_count,
            (result.provider_session_id or "none")[:16],
        )

        # Collect deterministic metrics immediately after reviewer completes
        deterministic: DeterministicMetrics | None = None
        if benchmarking_enabled:
            try:
                context = CollectorContext(
                    story_epic=epic_num,
                    story_num=story_num,
                    timestamp=review_timestamp,
                )
                deterministic = collect_deterministic_metrics(extracted_content, context)
                logger.debug("Collected deterministic metrics for %s", reviewer_id)
            except Exception as e:
                logger.warning(
                    "Deterministic collection failed for %s: %s",
                    reviewer_id,
                    e,
                )
                # deterministic remains None - continue without metrics

        return reviewer_id, output, deterministic, None

    except TimeoutError:
        error_msg = f"Reviewer {reviewer_id} timed out after {timeout}s"
        logger.warning(error_msg)
        return reviewer_id, None, None, error_msg

    except Exception as e:
        error_msg = f"Reviewer {reviewer_id} failed: {e}"
        logger.warning(error_msg, exc_info=True)
        return reviewer_id, None, None, error_msg


def _compile_code_review_prompt(
    project_path: Path,
    epic_num: EpicId,
    story_num: int | str,
) -> str:
    """Compile code-review workflow.

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

    compiled = compile_workflow("code-review", context)
    return compiled.context


def _extract_code_review_custom_metrics(
    story_file: Path,
) -> dict[str, Any]:
    """Extract code review specific metrics from story file.

    Parses File List section to count files and estimate LOC.

    Note: File List is populated AFTER dev-story phase completes.
    During code review, it should contain the implementation file list.

    Args:
        story_file: Path to story file.

    Returns:
        Dict with custom metrics for code review phase.

    """
    custom: dict[str, Any] = {
        "phase": "code-review",
        "file_count": None,
        "lines_of_code_reviewed": None,
        "test_coverage_delta": None,
    }

    if not story_file.exists():
        return custom

    try:
        content = story_file.read_text(encoding="utf-8")
    except OSError:
        return custom

    # Extract file count from File List section
    from bmad_assist.compiler.source_context import (
        _extract_file_list_section,
        extract_file_paths_from_section,
    )

    file_list_content = _extract_file_list_section(content)
    if file_list_content:
        file_paths = extract_file_paths_from_section(file_list_content)
        source_files = [f for f in file_paths if re.search(r"\.\w+$", f.strip())]
        custom["file_count"] = len(source_files) if source_files else None

    return custom


def _resolve_story_file(
    project_path: Path,
    epic_num: EpicId,
    story_num: int | str,
) -> Path | None:
    """Resolve story file path from epic/story numbers.

    Args:
        project_path: Project root path.
        epic_num: Epic number.
        story_num: Story number.

    Returns:
        Path to story file, or None if not found.

    """
    paths = get_paths()
    pattern = f"{epic_num}-{story_num}-*.md"
    matches = list(paths.stories_dir.glob(pattern))
    return matches[0] if matches else None


def _aggregate_dv_results(
    dv_batch_result: dict[Path, DeepVerifyValidationResult],
) -> DeepVerifyValidationResult | None:
    """Aggregate per-file DV results into a single combined result.

    Uses the same worst-verdict logic as load_dv_findings_from_cache()
    but operates on in-memory results without disk I/O.

    Args:
        dv_batch_result: Dict mapping file_path → DeepVerifyValidationResult.

    Returns:
        Aggregated DeepVerifyValidationResult if any valid results, None otherwise.

    """
    from bmad_assist.deep_verify.core.types import MethodId, VerdictDecision

    all_findings: list[Any] = []
    all_domains: list[Any] = []
    all_methods: set[str] = set()
    total_duration = 0
    worst_verdict: VerdictDecision | None = None
    min_score = 100.0

    for dv_result in dv_batch_result.values():
        all_findings.extend(dv_result.findings)
        all_domains.extend(dv_result.domains_detected)
        all_methods.update(str(m) for m in dv_result.methods_executed)
        total_duration += dv_result.duration_ms
        min_score = min(min_score, dv_result.score)

        # Track worst verdict (REJECT > UNCERTAIN > ACCEPT)
        if worst_verdict is None:
            worst_verdict = dv_result.verdict
        elif dv_result.verdict == VerdictDecision.REJECT:
            worst_verdict = VerdictDecision.REJECT
        elif (
            dv_result.verdict == VerdictDecision.UNCERTAIN
            and worst_verdict == VerdictDecision.ACCEPT
        ):
            worst_verdict = VerdictDecision.UNCERTAIN

    if worst_verdict is None:
        return None

    return DeepVerifyValidationResult(
        verdict=worst_verdict,
        score=min_score,
        findings=all_findings,
        domains_detected=all_domains,
        methods_executed=[MethodId(m) for m in all_methods],
        duration_ms=total_duration,
        error=None,
    )


async def run_code_review_phase(
    config: Config,
    project_path: Path,
    epic_num: EpicId,
    story_num: int | str,
) -> CodeReviewPhaseResult:
    """Run complete code review phase with parallel Multi-LLM invocation.

    Follows same pattern as run_validation_phase():
    1. Compile code-review workflow once
    2. Invoke ALL reviewers in parallel (multi + master)
    3. Filter successful results
    4. Check minimum threshold (≥2 distinct reviewers)
    5. Anonymize reviews
    6. Save mapping
    7. Collect benchmarking metrics (if enabled)
    8. Return CodeReviewPhaseResult

    Args:
        config: Application configuration with provider settings.
        project_path: Path to project root.
        epic_num: Epic number being reviewed.
        story_num: Story number being reviewed.

    Returns:
        CodeReviewPhaseResult with anonymized reviews and metadata.

    Raises:
        InsufficientReviewsError: If fewer than 2 reviewers succeeded.

    """
    run_timestamp = datetime.now(UTC)

    logger.info(
        "Starting code review phase for story %s.%s (run=%s)",
        epic_num,
        story_num,
        run_timestamp.isoformat(),
    )

    # Step 1: Compile prompt once
    logger.debug("Compiling code-review workflow")
    prompt = _compile_code_review_prompt(project_path, epic_num, story_num)
    logger.debug("Compiled prompt: %d chars", len(prompt))

    # Save prompt to .bmad-assist/prompts/ (atomic write, always saved)
    save_prompt(project_path, epic_num, story_num, "code-review", prompt)

    # Step 2: Build list of reviewers (multi + master)
    timeout = get_phase_timeout(config, "code_review")
    timeout_retries = get_phase_retries(config, "code_review")
    benchmarking_enabled = should_collect_benchmarking(config)
    if benchmarking_enabled:
        logger.debug("Benchmarking enabled - will collect metrics")

    tasks: list[asyncio.Task[_ReviewerResult]] = []

    # [NEW] Add Deep Verify tasks for code files
    dv_enabled = (
        hasattr(config, "deep_verify") and config.deep_verify and config.deep_verify.enabled
    )
    dv_batch_task: asyncio.Task[dict[Path, DeepVerifyValidationResult]] | None = None
    dv_batch_files_info: list[tuple[Path, str]] = []  # (file_path, language) for result mapping
    if dv_enabled:
        logger.debug("Deep Verify enabled - discovering code files")
        code_files = _resolve_code_files(project_path, epic_num, story_num)
        if code_files:
            logger.info("Running batch Deep Verify on %d code files", len(code_files))
            # Build batch file list
            batch_files: list[tuple[Path, str]] = []
            for file_path, language in code_files:
                try:
                    code_content = file_path.read_text(encoding="utf-8")
                    batch_files.append((file_path, code_content))
                    dv_batch_files_info.append((file_path, language))
                except OSError as e:
                    logger.warning("Failed to read file for DV: %s - %s", file_path, e)

            # Get hunk ranges for each file (for intelligent context extraction)
            file_hunk_ranges: dict[Path, list[tuple[int, int]]] = {}
            try:
                from bmad_assist.compiler.source_context import get_hunk_ranges_for_file

                for fp, _content in batch_files:
                    try:
                        rel_path = str(fp.relative_to(project_path))
                        ranges = get_hunk_ranges_for_file(project_path, rel_path)
                        if ranges:
                            file_hunk_ranges[fp] = ranges
                    except (OSError, ValueError):
                        logger.debug("Could not get hunk ranges for %s", fp.name)
            except ImportError:
                logger.debug("source_context not available for hunk ranges")

            if batch_files:
                dv_batch_task = asyncio.create_task(
                    run_deep_verify_code_review_batch(
                        files=batch_files,
                        config=config,
                        project_path=project_path,
                        epic_num=epic_num,
                        story_num=story_num,
                        base_timeout=timeout,
                        file_hunk_ranges=file_hunk_ranges or None,
                    )
                )
        else:
            logger.debug("No code files found for Deep Verify")
    else:
        logger.debug("Deep Verify disabled or not configured")

    # Add multi providers (from phase_models if configured, else global providers.multi)
    # Color index based on provider order for visual distinction
    multi_configs_raw = get_phase_provider_config(config, "code_review")
    # Type narrowing: code_review is multi-LLM, so must be list
    multi_configs: list[MultiProviderConfig] = (
        multi_configs_raw if isinstance(multi_configs_raw, list) else []
    )
    for idx, multi_config in enumerate(multi_configs):
        provider = get_provider(multi_config.provider)
        # Use display_model (model_name if set) for logging, model for CLI invocation
        reviewer_id = f"{multi_config.provider}-{multi_config.display_model}"
        # Staggered start: each task waits idx * delay before starting
        # Parse delay at runtime for each task (randomization per-call if range configured)
        delay = parse_parallel_delay(config.parallel_delay) * idx
        coro = _invoke_reviewer(
            provider,
            prompt,
            timeout,
            reviewer_id,
            timeout_retries=timeout_retries,
            model=multi_config.model,
            allowed_tools=_REVIEWER_ALLOWED_TOOLS,
            run_timestamp=run_timestamp,
            epic_num=epic_num,
            story_num=story_num,
            benchmarking_enabled=benchmarking_enabled,
            settings_file=multi_config.settings_path,
            color_index=idx,
            cwd=project_path,
            display_model=multi_config.display_model,
            provider_name=multi_config.provider,
            thinking=multi_config.thinking,
            reasoning_effort=multi_config.reasoning_effort,
        )
        task = asyncio.create_task(delayed_invoke(delay, coro))
        tasks.append(task)

    # Add master as reviewer ONLY when using global providers.multi fallback
    # When phase_models.code_review is defined, user has full control - no auto-add
    phase_has_override = config.phase_models and "code_review" in config.phase_models
    if not phase_has_override:
        master_provider = get_provider(config.providers.master.provider)
        master_id = f"master-{config.providers.master.display_model}"
        master_color_index = len(multi_configs)
        # Staggered start for master: uses next index after all multi configs
        master_delay = parse_parallel_delay(config.parallel_delay) * master_color_index
        master_coro = _invoke_reviewer(
            master_provider,
            prompt,
            timeout,
            master_id,
            timeout_retries=timeout_retries,
            model=config.providers.master.model,
            allowed_tools=_REVIEWER_ALLOWED_TOOLS,
            run_timestamp=run_timestamp,
            epic_num=epic_num,
            story_num=story_num,
            benchmarking_enabled=benchmarking_enabled,
            settings_file=config.providers.master.settings_path,
            color_index=master_color_index,
            cwd=project_path,
            display_model=config.providers.master.display_model,
            provider_name=config.providers.master.provider,
        )
        master_task = asyncio.create_task(delayed_invoke(master_delay, master_coro))
        tasks.append(master_task)
    else:
        logger.debug("phase_models.code_review defined - master NOT auto-added")

    # [NEW] Add Security Agent task (parallel with reviewers and DV)
    security_task: asyncio.Task[SecurityReport] | None = None
    security_enabled = config.security_agent.enabled
    if security_enabled:
        try:
            logger.info("Security agent enabled - compiling security-review workflow")
            security_context = CompilerContext(
                project_root=project_path,
                output_folder=get_paths().output_folder,
                cwd=get_original_cwd(),
            )
            compiled_security = compile_workflow("security-review", security_context)
            security_prompt = compiled_security.context
            security_languages = compiled_security.variables.get(
                "detected_languages_list", []
            )
            security_patterns_count = compiled_security.variables.get(
                "patterns_loaded_count", 0
            )
            security_timeout = get_phase_timeout(config, "security_review")
            security_coro = run_security_review(
                config=config,
                project_path=project_path,
                compiled_prompt=security_prompt,
                timeout=security_timeout,
                languages=security_languages,
                patterns_loaded=security_patterns_count,
            )
            security_task = asyncio.create_task(security_coro)
            logger.debug("Security agent task created (timeout=%ds)", security_timeout)
            emit_security_review_started(run_id="", sequence_id=0)
        except (CompilerError, BmadAssistError) as e:
            logger.warning("Failed to compile security-review workflow: %s", e)
            security_task = None
    else:
        logger.debug("Security agent disabled")

    logger.info("Invoking %d reviewers in parallel", len(tasks))

    # Step 3: Run all reviewers (and DV batch + security tasks) in parallel
    all_tasks: list[asyncio.Task[Any]] = list(tasks)
    if dv_batch_task is not None:
        all_tasks.append(dv_batch_task)
    if security_task is not None:
        all_tasks.append(security_task)
    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    # Split results: regular reviewers vs DV batch vs security
    reviewer_results: list[_ReviewerResult | BaseException] = results[: len(tasks)]
    next_idx = len(tasks)
    dv_batch_result: dict[Path, DeepVerifyValidationResult] | BaseException | None = None
    if dv_batch_task is not None:
        dv_batch_result = results[next_idx]
        next_idx += 1
    security_result: SecurityReport | BaseException | None = (
        results[next_idx] if security_task is not None else None
    )

    # Step 4: Collect successful results (regular reviewers)
    successful_outputs: list[ValidationOutput] = []
    successful_deterministic: list[DeterministicMetrics] = []
    successful_reviewers: list[str] = []
    failed_reviewers: list[str] = []

    for result in reviewer_results:
        if isinstance(result, BaseException):
            logger.error("Unexpected exception in reviewer: %s", result)
            continue

        reviewer_id, output, deterministic, error = result

        if output is not None:
            successful_outputs.append(output)
            successful_reviewers.append(reviewer_id)
            if deterministic is not None:
                successful_deterministic.append(deterministic)
        else:
            failed_reviewers.append(reviewer_id)

    logger.info(
        "Review results: %d succeeded, %d failed",
        len(successful_outputs),
        len(failed_reviewers),
    )

    # Step 5: Anonymize reviews
    # Note: anonymize_validations() logs internally (Anonymizing N outputs, assignments, session ID)
    anonymized, mapping = anonymize_validations(successful_outputs, run_timestamp=run_timestamp)

    # Process DV batch results and save to cache (using session_id from mapping)
    dv_findings_saved = 0
    dv_result_dict: dict[Path, DeepVerifyValidationResult] = {}
    if dv_batch_result is not None:
        if isinstance(dv_batch_result, BaseException):
            logger.warning("DV batch task failed: %s", dv_batch_result)
        elif isinstance(dv_batch_result, dict):
            dv_result_dict = dv_batch_result
            # Build language lookup from dv_batch_files_info
            language_map: dict[Path, str] = dict(dv_batch_files_info)
            for file_path, dv_result in dv_result_dict.items():
                language = language_map.get(file_path, "unknown")
                try:
                    save_dv_findings_for_synthesis(
                        result=dv_result,
                        project_path=project_path,
                        session_id=mapping.session_id,
                        file_path=file_path,
                        language=language,
                    )
                    dv_findings_saved += 1
                    logger.debug("Saved DV findings for %s", file_path)
                except OSError as e:
                    logger.warning("Failed to save DV findings for %s: %s", file_path, e)

    # Save archival DV report to deep-verify/ (consolidated per-file breakdown)
    if dv_findings_saved > 0 and dv_result_dict:
        try:
            from bmad_assist.deep_verify.integration.reports import (
                save_deep_verify_batch_report,
            )

            dv_dir = get_paths().deep_verify_dir
            save_deep_verify_batch_report(
                batch_results=dv_result_dict,
                epic=epic_num,
                story=story_num,
                output_dir=dv_dir,
                phase_type="code-review",
            )
        except Exception as e:
            logger.warning("Failed to save archival DV report: %s", e)

    # Process security agent result and save to cache (using session_id from mapping)
    if security_result is not None:
        if isinstance(security_result, BaseException):
            logger.warning("Security agent task failed: %s", security_result)
            emit_security_review_failed(run_id="", sequence_id=0, error=str(security_result))
        elif isinstance(security_result, SecurityReport):
            # Save to cache for synthesis (required)
            try:
                save_security_findings_for_synthesis(
                    report=security_result,
                    project_path=project_path,
                    session_id=mapping.session_id,
                )
                logger.info(
                    "Saved security findings for synthesis: %d findings",
                    len(security_result.findings),
                )
            except OSError as e:
                logger.warning("Failed to save security findings to cache: %s", e)

            # Save archival MD to security-reports/ (always, even with zero findings)
            try:
                paths_obj = get_paths()
                sec_dir = paths_obj.security_reports_dir
                sec_dir.mkdir(parents=True, exist_ok=True)
                ts = run_timestamp.strftime("%Y%m%d-%H%M%S")
                report_path = sec_dir / f"security-{epic_num}-{story_num}-{ts}.md"
                report_path.write_text(security_result.to_markdown(), encoding="utf-8")
                logger.debug("Saved archival security report: %s", report_path.name)
            except OSError as e:
                logger.warning("Failed to save archival security report: %s", e)

            if security_result.timed_out:
                logger.warning("Security review timed out — synthesis will include timeout banner")

            # Emit SSE completion event with severity summary
            severity_summary: dict[str, int] = {}
            for f in security_result.findings:
                sev = f.severity.upper() if f.severity else "UNKNOWN"
                severity_summary[sev] = severity_summary.get(sev, 0) + 1
            emit_security_review_completed(
                run_id="",
                sequence_id=0,
                finding_count=len(security_result.findings),
                severity_summary=severity_summary,
                timed_out=security_result.timed_out,
            )

    # Step 7: Save individual review reports with index-based role_id
    # Role IDs: a, b, c... (matching benchmark records from Story 22.6)
    paths = get_paths()
    reviews_dir = paths.code_reviews_dir
    reviews_dir.mkdir(parents=True, exist_ok=True)

    # Save reports with role_id matching the anonymized validator letter
    # e.g., "Validator C" -> role_id='c', file: code-review-*-c-*.md
    reviewer_ids = list(mapping.mapping.keys())

    for idx, output in enumerate(successful_outputs):
        # Get anonymized_id from mapping (e.g., "Validator C")
        anonymized_id = reviewer_ids[idx] if idx < len(reviewer_ids) else output.provider

        # Extract role_id from anonymized_id: "Validator C" -> "c"
        if anonymized_id and anonymized_id.startswith("Validator "):
            role_id = anonymized_id[-1].lower()  # "Validator C" -> "c"
        else:
            role_id = chr(ord('a') + idx)  # fallback to index-based

        # Add role_id to mapping metadata for traceability
        if idx < len(reviewer_ids):
            mapping.mapping[reviewer_ids[idx]]["role_id"] = role_id

        # Save report with error handling (AC #5 - log warning, don't crash)
        try:
            _save_code_review_report(
                output=output,
                epic=epic_num,
                story=story_num,
                reviews_dir=reviews_dir,
                role_id=role_id,
                session_id=mapping.session_id,
                anonymized_id=anonymized_id,
            )
        except OSError:
            # Warning already logged by _save_code_review_report
            # Continue with other reports (AC #5)
            logger.warning(
                "Continuing code review phase after report save failure for %s",
                output.provider,
            )

    # Step 9: Check minimum threshold AFTER saving reports
    # If insufficient reviews, reports are still saved for debugging (fixes data loss bug)
    if len(successful_outputs) < _MIN_REVIEWERS:
        raise InsufficientReviewsError(
            count=len(successful_outputs),
            minimum=_MIN_REVIEWERS,
        )

    # Step 10: Save mapping with code-review prefix (with error handling)
    try:
        _save_code_review_mapping(mapping, project_path)
    except OSError as e:
        # Log warning but don't crash (AC #5)
        logger.warning(
            "Failed to save code review mapping: %s (continuing without mapping)",
            e,
        )

    # Step 11: Run parallel extraction and finalize evaluation records
    from bmad_assist.benchmarking import LLMEvaluationRecord

    evaluation_records: list[LLMEvaluationRecord] = []

    if benchmarking_enabled and len(successful_deterministic) == len(successful_outputs):
        logger.info(
            "Running parallel metrics extraction for %d reviewers",
            len(successful_outputs),
        )

        try:
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

            # Create workflow info with code-review workflow ID
            workflow_info = _create_workflow_info(
                workflow_id=CODE_REVIEW_WORKFLOW_ID,
                variant=config.workflow_variant,
                patch_applied=False,
            )

            # Resolve story file for custom metrics
            story_file = _resolve_story_file(project_path, epic_num, story_num)
            custom_metrics = (
                _extract_code_review_custom_metrics(story_file)
                if story_file
                else {"phase": "code-review"}
            )

            for idx, (output, deterministic, extracted) in enumerate(
                zip(successful_outputs, successful_deterministic, extracted_list, strict=True)
            ):
                if extracted is None:
                    logger.warning(
                        "Skipping record for %s due to extraction failure",
                        output.provider,
                    )
                    continue

                # Get anonymized_id from mapping by index (same pattern as report saving)
                anonymized_id = reviewer_ids[idx] if idx < len(reviewer_ids) else ""

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

                # Add custom metrics to record
                if record.custom is None:
                    record = record.model_copy(update={"custom": custom_metrics})
                else:
                    merged_custom = {**record.custom, **custom_metrics}
                    record = record.model_copy(update={"custom": merged_custom})

                evaluation_records.append(record)

            logger.info(
                "Benchmarking complete: %d evaluation records created",
                len(evaluation_records),
            )

        except Exception as e:
            # Extraction failures don't block code review phase
            logger.error("Parallel extraction failed: %s", e, exc_info=True)

    elif benchmarking_enabled:
        logger.warning(
            "Skipping extraction: deterministic metrics count (%d) != outputs count (%d)",
            len(successful_deterministic),
            len(successful_outputs),
        )

    logger.info(
        "Code review phase complete. Session ID: %s",
        mapping.session_id,
    )

    # TIER 2: Calculate Evidence Score aggregate from reviewer outputs
    evidence_aggregate = _calculate_evidence_aggregate(anonymized)

    return CodeReviewPhaseResult(
        anonymized_reviews=anonymized,
        session_id=mapping.session_id,
        review_count=len(successful_outputs),
        reviewers=successful_reviewers,
        failed_reviewers=failed_reviewers,
        evaluation_records=evaluation_records,
        evidence_aggregate=evidence_aggregate,
    )


def _filter_outlier_reviews(
    reviews: list[AnonymizedValidation],
    sigma_threshold: float = 2.0,
) -> list[AnonymizedValidation]:
    """Drop statistical outlier reviews by size (sigma test only).

    Uses standard deviation to detect reviews that are significantly
    larger than their peers — these are likely malformed or runaway outputs.
    Normal-size variation is expected and preserved.

    Args:
        reviews: List of anonymized reviews.
        sigma_threshold: Number of standard deviations above mean to drop.
            Default 2.0 means drop if > mean + 2*std_dev.

    Returns:
        List with extreme outliers removed.

    """
    if len(reviews) <= 2:
        # Need at least 3 for meaningful statistics
        return reviews

    lengths = [len(r.content) for r in reviews]
    mean_len = sum(lengths) / len(lengths)
    variance = sum((ln - mean_len) ** 2 for ln in lengths) / len(lengths)
    std_dev = variance ** 0.5

    if std_dev == 0:
        return reviews

    result: list[AnonymizedValidation] = []
    rejected: list[tuple[str, int, float]] = []

    for review in reviews:
        length = len(review.content)
        sigma = (length - mean_len) / std_dev

        if sigma > sigma_threshold:
            rejected.append((review.validator_id, length, sigma))
        else:
            result.append(review)

    if rejected:
        logger.warning(
            "Dropped %d outlier review(s): %s",
            len(rejected),
            ", ".join(
                f"{vid} ({length:,} chars, {sigma:.1f}σ)" for vid, length, sigma in rejected
            ),
        )
        logger.info(
            "Review size stats: mean=%.0f chars, std=%.0f chars, kept=%d, dropped=%d",
            mean_len, std_dev, len(result), len(rejected),
        )

    return result


# =============================================================================
# Report persistence (matches validation/reports.py pattern)
# =============================================================================


def _save_code_review_report(
    output: ValidationOutput,
    epic: EpicId,
    story: int | str,  # Support EpicId = int | str (TD-001)
    reviews_dir: Path,
    role_id: str,
    session_id: str,
    anonymized_id: str | None = None,
) -> Path:
    """Save a code review report with YAML frontmatter.

    File path pattern (Story 22.7):
    {reviews_dir}/code-review-{epic}-{story}-{role_id}-{timestamp}.md

    where role_id is index-based (a, b, c...) to prevent report overwriting
    when multiple reviewers use the same provider/model.

    Args:
        output: ValidationOutput from reviewer.
        epic: Epic number.
        story: Story number.
        reviews_dir: Path to code-reviews directory.
        role_id: Index-based role ID (a, b, c...) for filename.
        session_id: Anonymization session ID for correlation.
        anonymized_id: Anonymous reviewer ID (e.g., "Validator A") for
            frontmatter display.

    Returns:
        Path to saved report file.

    Raises:
        OSError: If write fails (logged by caller).

    """
    import frontmatter

    timestamp = output.timestamp
    from bmad_assist.core.io import get_timestamp

    timestamp_str = get_timestamp(timestamp)

    # Create directory if it doesn't exist (AC #5)
    reviews_dir.mkdir(parents=True, exist_ok=True)

    # Use index-based role_id for filename (a, b, c...) to prevent overwriting
    filename = f"code-review-{epic}-{story}-{role_id}-{timestamp_str}.md"
    file_path = reviews_dir / filename

    # Build YAML frontmatter with anonymized ID for display
    # NOTE: Do NOT include provider/model - reports must be anonymized!
    # Story 22.7 AC #3: session_id required for traceability
    frontmatter_data = {
        "type": "code-review",
        "session_id": session_id,
        "role_id": role_id,
        "reviewer_id": anonymized_id or f"Reviewer {role_id.upper()}",
        "timestamp": timestamp.isoformat(),
        "epic": epic,
        "story": story,
        "phase": "CODE_REVIEW",
        "duration_ms": output.duration_ms,
        "token_count": output.token_count,
    }

    post = frontmatter.Post(output.content, **frontmatter_data)
    content = frontmatter.dumps(post)

    # Use centralized atomic_write with PID collision protection (AC #5, Story 22.7)
    from bmad_assist.core.io import atomic_write

    try:
        atomic_write(file_path, content)
        logger.info("Saved code review report: %s", file_path)
        return file_path
    except OSError as e:
        # Log warning but don't crash (AC #5)
        logger.warning(
            "Failed to save code review report: %s (error: %s)",
            file_path,
            e,
        )
        # Re-raise for caller to handle
        raise


def _save_code_review_mapping(
    mapping: "AnonymizationMapping",
    project_root: Path,
) -> Path:
    """Save code review anonymization mapping to cache directory.

    Story 22.7: Uses code-review-mapping prefix to distinguish from validation.

    File path pattern:
    {project_root}/.bmad-assist/cache/code-review-mapping-{session_id}.json

    Args:
        mapping: AnonymizationMapping to persist.
        project_root: Project root directory.

    Returns:
        Path to saved mapping file.

    Raises:
        OSError: If write fails.

    """
    from bmad_assist.core.io import atomic_write

    cache_dir = project_root / ".bmad-assist" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    filename = f"code-review-mapping-{mapping.session_id}.json"
    target_path = cache_dir / filename

    data = {
        "session_id": mapping.session_id,
        "timestamp": mapping.timestamp.isoformat(),
        "mapping": mapping.mapping,
    }

    # Use centralized atomic_write with PID collision protection (Story 22.7)
    content = json.dumps(data, indent=2)
    atomic_write(target_path, content)
    logger.info("Saved code review mapping: %s", target_path)
    return target_path


# =============================================================================
# Inter-handler data passing (matches validation pattern)
# =============================================================================


def save_reviews_for_synthesis(
    anonymized: list[AnonymizedValidation],
    project_root: Path,
    session_id: str | None = None,
    run_timestamp: datetime | None = None,
    failed_reviewers: list[str] | None = None,
    evidence_aggregate: "EvidenceScoreAggregate | None" = None,
) -> str:
    """Save anonymized reviews for synthesis phase retrieval.

    Uses file-based storage at .bmad-assist/cache/code-reviews-{session_id}.json
    Cache version 2 includes Evidence Score aggregate data.

    Story 22.7: Include failed_reviewers metadata for synthesis context.

    Args:
        anonymized: List of anonymized reviews.
        project_root: Project root directory.
        session_id: Optional session ID to use. If None, generates new UUID.
        run_timestamp: Unified timestamp for this review run. If None, uses now().
        failed_reviewers: Optional list of failed reviewer IDs for synthesis context.
        evidence_aggregate: Pre-calculated Evidence Score aggregate (TIER 2).

    Returns:
        Session ID for later retrieval.

    """
    from bmad_assist.core.io import atomic_write
    from bmad_assist.validation.evidence_score import Severity

    if session_id is None:
        session_id = str(uuid.uuid4())
    cache_dir = project_root / ".bmad-assist" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    file_path = cache_dir / f"code-reviews-{session_id}.json"

    timestamp = run_timestamp or datetime.now(UTC)

    data: dict[str, Any] = {
        "cache_version": 2,  # ADR-4: Cache versioning for Evidence Score
        "session_id": session_id,
        "timestamp": timestamp.isoformat(),
        "reviews": [
            {
                "reviewer_id": v.validator_id,
                "content": v.content,
                "original_ref": v.original_ref,
            }
            for v in anonymized
        ],
        # Story 22.7: Include failed reviewer metadata for synthesis
        "failed_reviewers": failed_reviewers or [],
    }

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

    # Use centralized atomic_write with PID collision protection (Story 22.7)
    content = json.dumps(data, indent=2)
    atomic_write(file_path, content)
    logger.info("Saved reviews for synthesis (v2): %s", file_path)

    return session_id


def load_reviews_for_synthesis(
    session_id: str,
    project_root: Path,
) -> tuple[list[AnonymizedValidation], list[str], dict[str, Any] | None]:
    """Load anonymized reviews by session ID.

    Story 22.7: Also returns failed reviewer metadata for synthesis context.

    Args:
        session_id: Session ID from save_reviews_for_synthesis.
        project_root: Project root directory.

    Returns:
        Tuple of (reviews, failed_reviewers, evidence_score):
        - reviews: List of AnonymizedValidation objects.
        - failed_reviewers: List of reviewers that failed/timed out.
        - evidence_score: Pre-calculated Evidence Score dict (TIER 2) or None.

    Raises:
        CodeReviewError: If file not found or invalid.
        CacheVersionError: If cache version is v1 (requires re-run).
        CacheFormatError: If v2 cache is missing required keys.

    """
    from bmad_assist.validation.evidence_score import CacheFormatError, CacheVersionError

    cache_dir = project_root / ".bmad-assist" / "cache"
    file_path = cache_dir / f"code-reviews-{session_id}.json"

    if not file_path.exists():
        raise CodeReviewError(f"Reviews not found for session: {session_id}")

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise CodeReviewError(f"Invalid review cache file: {e}") from e
    except OSError as e:
        raise CodeReviewError(f"Cannot read review cache: {e}") from e

    # ADR-4: Check cache version
    cache_version = data.get("cache_version")
    if cache_version is None or cache_version < 2:
        raise CacheVersionError(
            found_version=cache_version,
            required_version=2,
            message=(
                f"Code review cache version {cache_version or 'missing'} is incompatible. "
                "Evidence Score TIER 2 requires cache version 2. "
                "Re-run code review phase to generate new cache."
            ),
        )

    # Validate v2 cache has evidence_score key
    evidence_score = data.get("evidence_score")
    if evidence_score is None:
        raise CacheFormatError(
            "Cache version 2 is missing required 'evidence_score' key. "
            "Re-run code review phase to generate valid cache."
        )

    reviews = []
    for v in data.get("reviews", []):
        reviews.append(
            AnonymizedValidation(
                validator_id=v["reviewer_id"],
                content=v["content"],
                original_ref=v["original_ref"],
            )
        )

    # Story 22.7: Load failed reviewer metadata
    failed_reviewers = data.get("failed_reviewers", [])

    logger.debug(
        "Loaded %d reviews, %d failed reviewers, evidence_score=%s for session %s",
        len(reviews),
        len(failed_reviewers),
        evidence_score.get("total_score") if evidence_score else None,
        session_id,
    )
    return reviews, failed_reviewers, evidence_score
