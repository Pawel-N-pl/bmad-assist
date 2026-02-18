"""Core orchestration engine for Deep Verify.

This module provides the DeepVerifyEngine class that coordinates domain detection,
method selection, parallel execution, finding aggregation, and verdict scoring.
It ties together all verification methods (Stories 26.2-26.14) into a unified
verification workflow.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import random
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.core.exceptions import ProviderError, ProviderTimeoutError
from bmad_assist.deep_verify.core.domain_detector import DomainDetector
from bmad_assist.deep_verify.core.exceptions import (
    ErrorCategorizer,
    ErrorCategory,
)
from bmad_assist.deep_verify.core.input_validator import InputValidator
from bmad_assist.deep_verify.core.language_detector import LanguageDetector
from bmad_assist.deep_verify.core.method_selector import MethodSelector
from bmad_assist.deep_verify.core.scoring import EvidenceScorer
from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    DomainConfidence,
    DomainDetectionResult,
    Finding,
    MethodId,
    MethodResult,
    Severity,
    Verdict,
    VerdictDecision,
    VerdictError,
)
from bmad_assist.deep_verify.infrastructure.llm_client import LLMClient
from bmad_assist.providers.base import BaseProvider

if TYPE_CHECKING:
    from bmad_assist.core.config.models.providers import HelperProviderConfig
    from bmad_assist.deep_verify.config import (
        DeepVerifyConfig,
        DeepVerifyProviderConfig,
        MethodConfig,
    )
    from bmad_assist.deep_verify.methods.base import BaseVerificationMethod

logger = logging.getLogger(__name__)

# =============================================================================
# Verification Context
# =============================================================================


@dataclass(frozen=True, slots=True)
class VerificationContext:
    """Context for artifact verification.

    Attributes:
        file_path: Path to source file (if applicable).
        language: Programming language identifier (if known).
        project_stacks: Project-level tech stacks (e.g. ["javascript", "python"]).
            Used as fallback when per-file language detection fails.
        story_ref: Story reference string (if applicable).
        epic_num: Epic number (int or str) for context.
        story_num: Story number (int or str) for context.

    """

    file_path: Path | None = None
    language: str | None = None
    project_stacks: tuple[str, ...] = ()
    story_ref: str | None = None
    epic_num: int | str | None = None
    story_num: int | str | None = None


# =============================================================================
# Deep Verify Engine
# =============================================================================


class DeepVerifyEngine:
    """Core orchestration engine for Deep Verify verification.

    The engine coordinates the complete verification workflow:
    1. Domain detection (with keyword fallback)
    2. Method selection based on domains and config
    3. Parallel method execution with timeout handling
    4. Finding deduplication and limit enforcement
    5. Scoring and verdict determination

    Attributes:
        _config: DeepVerifyConfig with all settings.
        _project_root: Project root path.
        _domain_detector: DomainDetector instance.
        _language_detector: LanguageDetector instance.
        _scorer: EvidenceScorer with configured thresholds.
        _method_selector: MethodSelector for method selection.

    Example:
        >>> from pathlib import Path
        >>> engine = DeepVerifyEngine(project_root=Path("."))
        >>> verdict = await engine.verify("def authenticate_user(token): ...")
        >>> print(verdict.decision)
        VerdictDecision.ACCEPT

    """

    def __init__(
        self,
        project_root: Path,
        config: DeepVerifyConfig | None = None,
        domain_detector: DomainDetector | None = None,
        language_detector: LanguageDetector | None = None,
        helper_provider_config: HelperProviderConfig | None = None,
    ) -> None:
        """Initialize the Deep Verify Engine.

        Args:
            project_root: Path to project root (required).
            config: DeepVerifyConfig instance. If None, uses default config.
            domain_detector: DomainDetector instance. If None, creates one
                with project_root.
            language_detector: LanguageDetector instance. If None, creates one.
            helper_provider_config: Global helper provider config. Used as fallback
                when deep_verify.provider is not specified.

        """
        from bmad_assist.deep_verify.config import DeepVerifyConfig

        self._config = config or DeepVerifyConfig()
        self._project_root = project_root
        self._helper_provider_config = helper_provider_config

        # Create LLM client with resolved provider (MOVED UP)
        self._llm_client, self._model = self._create_llm_client()

        # Domain detector with fallback creation
        if domain_detector:
            self._domain_detector = domain_detector
        else:
            # Respect configured default timeout for domain detection
            timeout = self._config.llm_config.default_timeout_seconds
            self._domain_detector = DomainDetector(
                project_root=project_root,
                timeout=timeout,
                model=self._model,
                llm_client=self._llm_client,
            )

        # Language detector with fallback creation
        if language_detector:
            self._language_detector = language_detector
        else:
            self._language_detector = LanguageDetector()

        # Evidence scorer with full config
        self._scorer = EvidenceScorer(
            severity_weights=self._config.get_severity_weights(),
            clean_pass_bonus=self._config.clean_pass_bonus,
            reject_threshold=self._config.reject_threshold,
            accept_threshold=self._config.accept_threshold,
        )



        # Method selector with LLM client
        self._method_selector = MethodSelector(
            self._config,
            llm_client=self._llm_client,
            model=self._model,
        )

        # Input validator for resource limits
        self._input_validator = InputValidator(self._config.resource_limits)

        # Error categorizer for error handling
        self._error_categorizer = ErrorCategorizer()

        logger.debug(
            "DeepVerifyEngine initialized with project_root=%s, provider=%s, model=%s",
            project_root,
            self._resolved_provider_name,
            self._model,
        )

    def _create_llm_client(self) -> tuple[LLMClient, str]:
        """Create LLM client with resolved provider configuration.

        Resolution order:
        1. deep_verify.provider (explicit override)
        2. global helper provider config
        3. fallback to claude-sdk with haiku

        Returns:
            Tuple of (LLMClient, model_name).

        """
        provider: BaseProvider
        model: str

        # Check for DV-specific provider override
        dv_provider_config = self._config.provider
        settings_file: Path | None = None
        thinking: bool | None = None

        if dv_provider_config is not None:
            provider = self._create_provider_from_dv_config(dv_provider_config)
            model = dv_provider_config.model
            settings_file = dv_provider_config.settings_path
            thinking = dv_provider_config.thinking or None  # False → None (omit)
            self._resolved_provider_name = f"deep_verify.provider ({dv_provider_config.provider})"
            logger.debug(
                "Using deep_verify.provider override: %s/%s",
                dv_provider_config.provider,
                model,
            )
        elif self._helper_provider_config is not None:
            provider = self._create_provider_from_helper_config(self._helper_provider_config)
            model = self._helper_provider_config.model
            settings_file = self._helper_provider_config.settings_path
            self._resolved_provider_name = f"helper ({self._helper_provider_config.provider})"
            logger.debug(
                "Using global helper provider: %s/%s",
                self._helper_provider_config.provider,
                model,
            )
        else:
            # Fallback to claude-sdk with haiku
            from bmad_assist.providers import ClaudeSDKProvider

            provider = ClaudeSDKProvider()
            model = "haiku"
            self._resolved_provider_name = "fallback (claude-sdk)"
            logger.debug("Using fallback provider: claude-sdk/haiku")

        client = LLMClient(
            self._config,
            provider,
            settings_file=settings_file,
            thinking=thinking,
        )
        return client, model

    def _create_provider_from_dv_config(
        self,
        config: DeepVerifyProviderConfig,
    ) -> BaseProvider:
        """Create provider instance from DeepVerifyProviderConfig.

        Args:
            config: DeepVerifyProviderConfig with provider settings.

        Returns:
            Configured BaseProvider instance.

        Note:
            Settings and thinking mode are stored in config and will be
            passed to invoke() calls via LLMClient if needed in future.

        """
        from bmad_assist.providers import get_provider

        # get_provider returns an instance, not a class
        return get_provider(config.provider)

    def _create_provider_from_helper_config(
        self,
        config: HelperProviderConfig,
    ) -> BaseProvider:
        """Create provider instance from HelperProviderConfig.

        Args:
            config: HelperProviderConfig with provider settings.

        Returns:
            Configured BaseProvider instance.

        """
        from bmad_assist.providers import get_provider

        # get_provider returns an instance, not a class
        return get_provider(config.provider)

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"DeepVerifyEngine(project_root={self._project_root!r}, "
            f"config_enabled={self._config.enabled})"
        )

    # ========================================================================
    # Main Verification Method
    # ========================================================================

    async def verify(
        self,
        artifact_text: str,
        context: VerificationContext | None = None,
        timeout: int | None = None,
    ) -> Verdict:
        """Verify artifact using selected methods.

        This is the main entry point for artifact verification. It:
        1. Validates input (handles None/empty cases, size/line limits)
        2. Detects domains (with keyword fallback on failure)
        3. Selects and runs verification methods in parallel
        4. Deduplicates findings and enforces limits
        5. Calculates score and determines verdict
        6. Generates human-readable summary

        Args:
            artifact_text: The artifact text to verify.
            context: Optional VerificationContext with additional metadata.
            timeout: Optional timeout override (seconds). If None, uses
                sum of method timeouts from config.

        Returns:
            Verdict with decision, score, findings, and summary.

        Raises:
            ValueError: If artifact_text is None.

        """
        if artifact_text is None:
            raise ValueError("artifact_text cannot be None")

        if not artifact_text.strip():
            # Empty artifact - return ACCEPT with zero score
            return self._empty_verdict(
                DomainDetectionResult(domains=[], reasoning="Empty artifact", ambiguity="none")
            )

        # 1. Input validation (size and line count limits)
        validation_result = self._input_validator.validate(artifact_text)
        if not validation_result.is_valid:
            logger.warning("Input validation failed: %s", validation_result.error_message)
            return self._rejection_verdict(
                validation_result.error_message or "Input validation failed",
                size_bytes=validation_result.size_bytes,
                line_count=validation_result.line_count,
            )

        # 0. Initialize context if None
        if context is None:
            context = VerificationContext()

        # 1. Auto-detect language if not provided in context
        if context.language is None and context.file_path is not None:
            lang_info = self._language_detector.detect(context.file_path, artifact_text)
            if not lang_info.is_unknown:
                context = replace(context, language=lang_info.language)
                logger.debug(
                    "Detected language: %s (confidence: %.2f)",
                    lang_info.language,
                    lang_info.confidence,
                )
            elif context.project_stacks:
                # Fallback: use first project stack as language hint
                fallback_lang = context.project_stacks[0]
                context = replace(context, language=fallback_lang)
                logger.debug(
                    "Using project stack as language fallback: %s (for %s)",
                    fallback_lang,
                    context.file_path.name if context.file_path else "unknown",
                )

        # 2. Domain detection (with keyword fallback)
        logger.info("Deep Verify: detecting domains...")
        domain_result = await self._detect_domains(artifact_text, context)
        domains = [d.domain for d in domain_result.domains]
        if domains:
            logger.info("Deep Verify: detected domains: %s", ", ".join(domains))
        else:
            logger.info("Deep Verify: no specific domains detected")

        # 2. Method selection
        methods = self._method_selector.select(domains)
        if not methods:
            logger.info("Deep Verify: no methods selected, returning ACCEPT")
            return self._empty_verdict(domain_result)

        method_names = [m.method_id for m in methods]
        logger.info("Deep Verify: selected %d methods: %s", len(methods), ", ".join(method_names))

        # 3. Parallel method execution with partial results
        method_results = await self._run_methods_with_errors(
            methods, artifact_text, context, timeout, domains
        )

        # Extract findings and errors from results
        findings: list[Finding] = []
        errors: list[VerdictError] = []
        for mr in method_results:
            if mr.success:
                findings.extend(mr.findings)
            elif mr.error:
                errors.append(
                    VerdictError(
                        method_id=mr.method_id,
                        error_type=type(mr.error.error).__name__,
                        error_message=mr.error.message,
                        category=mr.error.category.value,
                    )
                )

        # 4. Deduplication and limits
        findings = self._deduplicate_findings(findings)
        findings = self._apply_finding_limits(findings)
        findings = self._assign_finding_ids(findings)

        # 5. Scoring (EvidenceScorer.determine_verdict handles CRITICAL findings)
        clean_passes = self._calculate_clean_passes(findings, domain_result.domains)
        score = self._scorer.calculate_score(findings, clean_passes)
        decision = self._scorer.determine_verdict(score, findings)

        # 6. Generate verdict
        input_metrics = {
            "size_bytes": validation_result.size_bytes,
            "line_count": validation_result.line_count,
        }

        verdict = Verdict(
            decision=decision,
            score=score,
            findings=findings,
            domains_detected=domain_result.domains,
            methods_executed=[m.method_id for m in methods],
            summary=self._generate_summary(decision, score, findings, domains, methods),
            errors=errors,
            input_metrics=input_metrics,
        )

        logger.info(
            "Deep Verify: complete - verdict=%s, score=%.1f, findings=%d",
            decision.value,
            score,
            len(findings),
        )

        return verdict

    # ========================================================================
    # Batch Verification
    # ========================================================================

    async def verify_batch(
        self,
        files: list[tuple[Path, str]],
        context: VerificationContext | None = None,
        base_timeout: int | None = None,
        file_hunk_ranges: dict[Path, list[tuple[int, int]]] | None = None,
    ) -> dict[Path, Verdict]:
        """Batch verify multiple files via multi-turn sessions.

        Delegates to BatchVerifyOrchestrator which runs one session per method
        across all files, reducing N×M LLM calls to M sessions.

        Args:
            files: List of (file_path, content) tuples.
            context: Optional verification context.
            base_timeout: Base timeout per file in seconds.
            file_hunk_ranges: Optional per-file hunk ranges from git diff.

        Returns:
            Dict mapping file_path → Verdict.

        """
        from bmad_assist.deep_verify.core.batch import BatchVerifyOrchestrator

        orchestrator = BatchVerifyOrchestrator(
            self._config,
            self._project_root,
            helper_provider_config=self._helper_provider_config,
        )
        return await orchestrator.verify_batch(
            files, context, base_timeout, file_hunk_ranges=file_hunk_ranges
        )

    # ========================================================================
    # Domain Detection with Fallback
    # ========================================================================

    async def _detect_domains(
        self,
        artifact_text: str,
        context: VerificationContext | None = None,
    ) -> DomainDetectionResult:
        """Detect domains with LLM + keyword fallback.

        First tries LLM-based detection via DomainDetector. If that fails,
        falls back to keyword-based detection.

        Args:
            artifact_text: Text to analyze for domain detection.
            context: Optional verification context with language hint.

        Returns:
            DomainDetectionResult with detected domains.

        """
        # Extract language hint from context if available
        language_hint = context.language if context else None

        try:
            # Try LLM detection first (run sync method in thread pool to avoid blocking)
            return await asyncio.to_thread(
                self._domain_detector.detect,
                artifact_text,
                language_hint=language_hint,
            )
        except (ProviderError, ProviderTimeoutError, ValueError, json.JSONDecodeError) as e:
            # Handles known exceptions from domain detection including JSON parse errors
            logger.debug("Domain detection LLM unusable, using keyword fallback: %s", e)
            return self._keyword_domain_detection(artifact_text)

    def _keyword_domain_detection(self, artifact_text: str) -> DomainDetectionResult:
        """Fallback keyword-based domain detection.

        Args:
            artifact_text: Text to analyze.

        Returns:
            DomainDetectionResult from keyword analysis.

        """
        text_lower = artifact_text.lower()
        detected: list[DomainConfidence] = []

        keywords: dict[ArtifactDomain, list[str]] = {
            ArtifactDomain.SECURITY: [
                "auth",
                "token",
                "encrypt",
                "password",
                "permission",
                "credential",
                "secret",
                "jwt",
                "oauth",
                "hash",
            ],
            ArtifactDomain.API: [
                "endpoint",
                "request",
                "response",
                "http",
                "api",
                "rest",
                "json",
                "graphql",
                "grpc",
                "webhook",
            ],
            ArtifactDomain.CONCURRENCY: [
                "async",
                "thread",
                "lock",
                "race",
                "concurrent",
                "parallel",
                "mutex",
                "semaphore",
                "goroutine",
                "worker",
            ],
            ArtifactDomain.STORAGE: [
                "database",
                "db",
                "cache",
                "persist",
                "storage",
                "sql",
                "query",
                "transaction",
                "repository",
                "orm",
            ],
            ArtifactDomain.MESSAGING: [
                "queue",
                "message",
                "event",
                "stream",
                "kafka",
                "rabbitmq",
                "pubsub",
                "consumer",
                "producer",
                "topic",
            ],
            ArtifactDomain.TRANSFORM: [
                "convert",
                "transform",
                "parse",
                "serialize",
                "format",
                "marshal",
                "unmarshal",
                "encode",
                "decode",
                "csv",
                "xml",
            ],
            ArtifactDomain.PRD: [
                "story",
                "epic",
                "user story",
                "acceptance criteria",
                "stakeholder",
                "feature",
                "requirement",
                "product",
            ],
            ArtifactDomain.DOCUMENTATION: [
                "documentation",
                "api doc",
                "readme",
                "guide",
                "tutorial",
                "reference",
                "specification",
            ],
        }

        for domain, words in keywords.items():
            matches = sum(1 for word in words if word in text_lower)
            if matches > 0:
                confidence = min(matches / 3, 1.0)  # Cap at 1.0
                detected.append(
                    DomainConfidence(
                        domain=domain,
                        confidence=confidence,
                        signals=[w for w in words if w in text_lower][:5],
                    )
                )

        return DomainDetectionResult(
            domains=detected,
            reasoning="Domain detection via keyword fallback (LLM unavailable)",
            ambiguity="high" if detected else "none",
        )

    # ========================================================================
    # Method Execution
    # ========================================================================

    async def _run_methods_with_errors(
        self,
        methods: list[BaseVerificationMethod],
        artifact_text: str,
        context: VerificationContext | None,
        timeout: int | None,
        domains: list[ArtifactDomain] | None = None,
    ) -> list[MethodResult]:
        """Run methods with staggered spawning, timeout, and error handling.

        Spawns each method as an async task with a configurable stagger delay
        (default 1s ± 20% jitter) between launches to avoid rate limiting.
        All tasks then run concurrently and are awaited together.

        Args:
            methods: List of methods to execute.
            artifact_text: Text to analyze.
            context: Optional verification context.
            timeout: Optional timeout override.
            domains: Detected artifact domains for method filtering.

        Returns:
            List of MethodResult with findings and error information.

        """
        # Stagger delay from config (default 1.0s, ±20% jitter)
        stagger = self._config.llm_config.method_stagger_seconds if self._config else 0.5
        jitter_factor = 0.2

        # Spawn tasks with stagger delay between each
        tasks: list[asyncio.Task[MethodResult]] = []
        for idx, method in enumerate(methods):
            if idx > 0 and stagger > 0:
                jitter = random.uniform(1 - jitter_factor, 1 + jitter_factor)
                delay = stagger * jitter
                logger.debug(
                    "Stagger delay %.2fs before spawning method %s",
                    delay,
                    method.method_id,
                )
                await asyncio.sleep(delay)
            task = asyncio.create_task(
                self._run_single_method_with_result(
                    method, artifact_text, context, timeout, domains,
                ),
                name=f"dv-{method.method_id}",
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        method_results: list[MethodResult] = []
        for method, result in zip(methods, results, strict=True):
            if isinstance(result, Exception):
                # Method raised an exception - categorize it
                categorized = self._error_categorizer.classify(result, method.method_id)
                method_results.append(
                    MethodResult(
                        method_id=method.method_id,
                        findings=[],
                        error=categorized,
                        success=False,
                    )
                )
                logger.warning(
                    "Method %s failed: %s (category=%s)",
                    method.method_id,
                    result,
                    categorized.category.value,
                )
            elif isinstance(result, MethodResult):
                method_results.append(result)
            else:
                logger.warning(
                    "Method %s returned unexpected type: %s",
                    method.method_id,
                    type(result),
                )
                method_results.append(
                    MethodResult(
                        method_id=method.method_id,
                        findings=[],
                        error=None,
                        success=True,
                    )
                )

        return method_results

    async def _run_single_method_with_result(
        self,
        method: BaseVerificationMethod,
        artifact_text: str,
        context: VerificationContext | None,
        timeout: int | None,
        domains: list[ArtifactDomain] | None = None,
    ) -> MethodResult:
        """Run a single method and return a MethodResult.

        Args:
            method: Method to execute.
            artifact_text: Text to analyze.
            context: Optional verification context.
            timeout: Optional timeout override.
            domains: Detected artifact domains for method filtering.

        Returns:
            MethodResult with findings or error information.

        """
        try:
            findings = await self._run_single_method(method, artifact_text, context, timeout, domains)
            return MethodResult(
                method_id=method.method_id,
                findings=findings,
                error=None,
                success=True,
            )
        except (TimeoutError, ProviderError, ProviderTimeoutError, ValueError, TypeError) as e:
            # Categorize specific exceptions and return failed result
            categorized = self._error_categorizer.classify(e, method.method_id)
            return MethodResult(
                method_id=method.method_id,
                findings=[],
                error=categorized,
                success=False,
            )

    async def _run_single_method(
        self,
        method: BaseVerificationMethod,
        artifact_text: str,
        context: VerificationContext | None,
        timeout: int | None,
        domains: list[ArtifactDomain] | None = None,
    ) -> list[Finding]:
        """Run a single method with timeout and error handling.

        Args:
            method: Method to execute.
            artifact_text: Text to analyze.
            context: Optional verification context.
            timeout: Optional timeout override.
            domains: Detected artifact domains for method filtering.

        Returns:
            List of findings from the method, or empty list on timeout/failure.

        Raises:
            Exception: Re-raises non-timeout exceptions for logging.

        """
        try:
            kwargs: dict[str, Any] = {}
            if domains is not None:
                kwargs["domains"] = domains
            if context is not None:
                kwargs["context"] = context

            # Get method-specific timeout from config
            method_timeout = self._get_method_timeout(method.method_id)
            effective_timeout = timeout or method_timeout

            logger.info("Deep Verify: running method %s...", method.method_id)
            coro = method.analyze(artifact_text, **kwargs)

            if effective_timeout:
                # Python 3.11+ asyncio.timeout context manager
                async with asyncio.timeout(effective_timeout):
                    findings = await coro
            else:
                findings = await coro

            logger.info(
                "Deep Verify: method %s completed (%d findings)",
                method.method_id,
                len(findings),
            )
            return findings

        except TimeoutError:
            logger.warning("Deep Verify: method %s timed out", method.method_id)
            return []
        except (ProviderError, ProviderTimeoutError, ValueError) as e:
            logger.warning("Method %s raised exception: %s", method.method_id, e)
            raise

    def _get_method_timeout(self, method_id: MethodId) -> int | None:
        """Get timeout for specific method from config.

        Args:
            method_id: Method identifier.

        Returns:
            Timeout in seconds, or None if not configured.

        """
        method_configs: dict[MethodId, MethodConfig] = {
            MethodId("#153"): self._config.method_153_pattern_match,
            MethodId("#154"): self._config.method_154_boundary_analysis,
            MethodId("#155"): self._config.method_155_assumption_surfacing,
            MethodId("#157"): self._config.method_157_temporal_consistency,
            MethodId("#201"): self._config.method_201_adversarial_review,
            MethodId("#203"): self._config.method_203_domain_expert,
            MethodId("#204"): self._config.method_204_integration_analysis,
            MethodId("#205"): self._config.method_205_worst_case,
        }
        config = method_configs.get(method_id)
        return config.timeout_seconds if config else None

    # ========================================================================
    # Finding Processing
    # ========================================================================

    def _deduplicate_findings(self, findings: list[Finding]) -> list[Finding]:
        """Remove duplicate findings based on evidence quote similarity.

        Compares findings by:
        1. Pattern ID match (if both have pattern_id)
        2. Evidence quote similarity (>80% match via difflib.SequenceMatcher)

        Keeps the highest severity duplicate when matches are found.

        Args:
            findings: List of findings to deduplicate.

        Returns:
            List of deduplicated findings.

        """
        if not findings:
            return []

        # Severity priority for comparison (higher = more severe)
        severity_priority = {
            Severity.CRITICAL: 4,
            Severity.ERROR: 3,
            Severity.WARNING: 2,
            Severity.INFO: 1,
        }

        unique: list[Finding] = []

        for finding in findings:
            is_duplicate = False
            for existing in unique:
                # Check pattern_id match
                if finding.pattern_id and finding.pattern_id == existing.pattern_id:
                    is_duplicate = True
                    # Keep higher severity
                    if severity_priority.get(finding.severity, 0) > severity_priority.get(
                        existing.severity, 0
                    ):
                        idx = unique.index(existing)
                        unique[idx] = finding
                    break

                # Check evidence quote similarity (>80%)
                if finding.evidence and existing.evidence:
                    # Compare first evidence quote
                    f_quote = finding.evidence[0].quote if finding.evidence else ""
                    e_quote = existing.evidence[0].quote if existing.evidence else ""
                    if f_quote and e_quote:
                        similarity = difflib.SequenceMatcher(None, f_quote, e_quote).ratio()
                        if similarity > 0.8:
                            is_duplicate = True
                            # Keep higher severity
                            if severity_priority.get(finding.severity, 0) > severity_priority.get(
                                existing.severity, 0
                            ):
                                idx = unique.index(existing)
                                unique[idx] = finding
                            break

            if not is_duplicate:
                unique.append(finding)

        if len(unique) < len(findings):
            logger.debug(
                "Deduplicated %d findings to %d",
                len(findings),
                len(unique),
            )

        return unique

    def _apply_finding_limits(self, findings: list[Finding]) -> list[Finding]:
        """Enforce max findings per method and max total findings.

        Sorts by severity (CRITICAL first) before truncating to ensure
        high-severity findings are preserved.

        Uses limits from config.resource_limits.

        Args:
            findings: List of findings to limit.

        Returns:
            Limited list of findings.

        """
        if not findings:
            return []

        limits = self._config.resource_limits

        # Sort by severity (CRITICAL first)
        sorted_findings = self._sort_by_severity(findings)

        # Count per method
        method_counts: dict[MethodId, int] = {}
        limited: list[Finding] = []

        for finding in sorted_findings:
            count = method_counts.get(finding.method_id, 0)
            if count >= limits.max_findings_per_method:
                logger.warning(
                    "Method %s findings truncated at %d",
                    finding.method_id,
                    limits.max_findings_per_method,
                )
                continue
            if len(limited) >= limits.max_total_findings:
                logger.warning(
                    "Total findings truncated at %d",
                    limits.max_total_findings,
                )
                break

            method_counts[finding.method_id] = count + 1
            limited.append(finding)

        return limited

    def _sort_by_severity(self, findings: list[Finding]) -> list[Finding]:
        """Sort findings by severity (CRITICAL first).

        Args:
            findings: List of findings to sort.

        Returns:
            Sorted list of findings.

        """
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.ERROR: 1,
            Severity.WARNING: 2,
            Severity.INFO: 3,
        }
        return sorted(findings, key=lambda f: severity_order.get(f.severity, 99))

    def _assign_finding_ids(self, findings: list[Finding]) -> list[Finding]:
        """Reassign sequential finding IDs (F1, F2, F3...).

        Sorts findings by severity (CRITICAL first) before ID assignment
        to ensure consistent, meaningful ordering.

        Args:
            findings: List of findings to reassign IDs.

        Returns:
            List of findings with reassigned IDs.

        """
        if not findings:
            return []

        # Sort by severity (CRITICAL first)
        sorted_findings = self._sort_by_severity(findings)

        reassigned: list[Finding] = []
        for i, finding in enumerate(sorted_findings, 1):
            new_id = f"F{i}"
            reassigned.append(replace(finding, id=new_id))

        return reassigned

    def _calculate_clean_passes(
        self,
        findings: list[Finding],
        detected_domains: list[DomainConfidence],
    ) -> int:
        """Calculate number of domains with zero findings.

        Args:
            findings: All findings from verification.
            detected_domains: Domains that were detected.

        Returns:
            Number of domains with zero findings (clean passes).

        """
        if not detected_domains:
            return 0

        # Count findings per domain
        findings_per_domain: dict[ArtifactDomain, int] = {d.domain: 0 for d in detected_domains}

        for finding in findings:
            if finding.domain and finding.domain in findings_per_domain:
                findings_per_domain[finding.domain] += 1

        # Count domains with zero findings
        clean_count = sum(1 for count in findings_per_domain.values() if count == 0)
        return clean_count

    # ========================================================================
    # Verdict Generation
    # ========================================================================

    def _generate_summary(
        self,
        decision: VerdictDecision,
        score: float,
        findings: list[Finding],
        domains: list[ArtifactDomain],
        methods: list[BaseVerificationMethod],
    ) -> str:
        """Generate human-readable summary.

        Format: "{decision} verdict (score: {score}). {n} findings: {findings_list}.
                Domains: {domain_names}. Methods: {method_ids}."

        Args:
            decision: Verdict decision.
            score: Evidence score.
            findings: List of findings.
            domains: List of detected domains.
            methods: List of executed methods.

        Returns:
            Formatted summary string.

        """
        # Finding IDs list
        if findings:
            finding_ids = ", ".join(f.id for f in findings)
        else:
            finding_ids = "none"

        # Domain names
        domain_names = ", ".join(d.value for d in domains) if domains else "none"

        # Method IDs
        method_ids = ", ".join(str(m.method_id) for m in methods) if methods else "none"

        return (
            f"{decision.value} verdict (score: {score:.1f}). "
            f"{len(findings)} findings: {finding_ids}. "
            f"Domains: {domain_names}. Methods: {method_ids}."
        )

    def _empty_verdict(self, domain_result: DomainDetectionResult) -> Verdict:
        """Return verdict when no methods are selected.

        Returns ACCEPT verdict with score 0.0 and empty findings.

        Args:
            domain_result: Domain detection result (for domain info).

        Returns:
            Verdict for empty/edge case.

        """
        domains = [d.domain for d in domain_result.domains]
        domain_names = ", ".join(d.value for d in domains) if domains else "none"

        summary = (
            f"ACCEPT verdict (score: 0.0). 0 findings: none. "
            f"Domains: {domain_names}. Methods: none."
        )

        return Verdict(
            decision=VerdictDecision.ACCEPT,
            score=0.0,
            findings=[],
            domains_detected=domain_result.domains,
            methods_executed=[],
            summary=summary,
        )

    def _rejection_verdict(
        self,
        error_message: str,
        size_bytes: int = 0,
        line_count: int = 0,
    ) -> Verdict:
        """Return REJECT verdict when input validation fails.

        Args:
            error_message: Error message describing why input was rejected.
            size_bytes: Size of the input in bytes.
            line_count: Number of lines in the input.

        Returns:
            REJECT verdict with error information.

        """
        input_metrics = {
            "size_bytes": size_bytes,
            "line_count": line_count,
        }

        # Create a finding for the validation error
        validation_finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Input Validation Failed",
            description=error_message,
            method_id=MethodId("validation"),
            evidence=[],
        )

        summary = (
            f"REJECT verdict (score: 0.0). 1 finding: F1. "
            f"Input validation failed: {error_message}. "
            f"size={size_bytes}B, lines={line_count}."
        )

        return Verdict(
            decision=VerdictDecision.REJECT,
            score=0.0,
            findings=[validation_finding],
            domains_detected=[],
            methods_executed=[],
            summary=summary,
            errors=[
                VerdictError(
                    method_id=None,
                    error_type="InputValidationError",
                    error_message=error_message,
                    category=ErrorCategory.FATAL_INVALID.value,
                )
            ],
            input_metrics=input_metrics,
        )
