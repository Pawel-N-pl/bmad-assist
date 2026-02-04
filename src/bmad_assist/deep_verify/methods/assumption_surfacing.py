"""Assumption Surfacing Method (#155) for Deep Verify.

This module implements the Assumption Surfacing verification method that detects
implicit assumptions in implementation artifacts. Method #155 runs conditionally
when CONCURRENCY or API domains are detected.

The method identifies unstated beliefs about system behavior, unwritten contracts
between components, or unvalidated assumptions about external dependencies that
could lead to bugs, race conditions, or integration failures if violated.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    Evidence,
    Finding,
    MethodId,
    PatternId,
    Severity,
)
from bmad_assist.deep_verify.methods.base import BaseVerificationMethod
from bmad_assist.providers import ClaudeSDKProvider

logger = logging.getLogger(__name__)

__all__ = [
    "AssumptionSurfacingMethod",
    "AssumptionCategory",
    "AssumptionDefinition",
    "RiskLevel",
    "AssumptionFindingData",
    "AssumptionAnalysisResponse",
    "ASSUMPTION_SURFACING_SYSTEM_PROMPT",
    "risk_to_severity",
    "risk_to_confidence",
    "get_category_definitions",
]

# =============================================================================
# Constants
# =============================================================================

DEFAULT_MODEL = "haiku"
DEFAULT_TIMEOUT = 30
DEFAULT_THRESHOLD = 0.6
MAX_ARTIFACT_LENGTH = 4000

# =============================================================================
# Enums
# =============================================================================


class AssumptionCategory(str, Enum):
    """Categories of implicit assumptions that can be surfaced.

    Each category represents a different type of implicit assumption
    that code might make about its environment, data, or dependencies.
    """

    ENVIRONMENTAL = "environmental"  # Runtime environment assumptions
    ORDERING = "ordering"  # Operation ordering assumptions
    DATA = "data"  # Data format/immutability assumptions
    TIMING = "timing"  # Execution timing assumptions
    CONTRACT = "contract"  # API contract assumptions


class RiskLevel(str, Enum):
    """Risk levels for assumption violation.

    Indicates how likely the assumption is to be violated
    and the severity of consequences if it is.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass(frozen=True)
class AssumptionDefinition:
    """Definition of an assumption category with metadata.

    Attributes:
        id: Category ID string (e.g., "ENV-001", "ORD-001").
        description: Description of assumption type.
        examples: Examples of common assumptions in this category.
        default_severity: Default severity if assumption is violated.

    """

    id: str
    description: str
    examples: list[str]
    default_severity: Severity

    def __repr__(self) -> str:
        """Return a string representation of the assumption definition."""
        return f"AssumptionDefinition(id={self.id!r}, description={self.description!r})"


# =============================================================================
# Category Definitions
# =============================================================================

ASSUMPTION_CATEGORIES: dict[AssumptionCategory, AssumptionDefinition] = {
    AssumptionCategory.ENVIRONMENTAL: AssumptionDefinition(
        id="ENV-001",
        description="Runtime environment assumptions (CPU, memory, network, permissions)",
        examples=[
            "Assumes specific number of CPU cores",
            "Assumes sufficient memory available",
            "Assumes network connectivity",
            "Assumes file system permissions",
        ],
        default_severity=Severity.WARNING,
    ),
    AssumptionCategory.ORDERING: AssumptionDefinition(
        id="ORD-001",
        description="Operation ordering and sequence guarantees",
        examples=[
            "Assumes init() called before process()",
            "Assumes channels closed in specific order",
            "Assumes map iteration order is deterministic",
            "Assumes stopCh is closed exactly once",
        ],
        default_severity=Severity.ERROR,
    ),
    AssumptionCategory.DATA: AssumptionDefinition(
        id="DAT-001",
        description="Data format, immutability, and constraint assumptions",
        examples=[
            "Assumes payload is immutable during processing",
            "Assumes input is already validated",
            "Assumes string is valid UTF-8",
            "Assumes slice not shared with caller",
        ],
        default_severity=Severity.ERROR,
    ),
    AssumptionCategory.TIMING: AssumptionDefinition(
        id="TIM-001",
        description="Execution timing, timeout, and deadline assumptions",
        examples=[
            "Assumes operation completes within timeout",
            "Assumes system clock is monotonic",
            "Assumes no significant clock skew",
        ],
        default_severity=Severity.WARNING,
    ),
    AssumptionCategory.CONTRACT: AssumptionDefinition(
        id="CON-001",
        description="API contract, caller behavior, external dependency assumptions",
        examples=[
            "Assumes caller provides valid authentication token",
            "Assumes external service respects context cancellation",
            "Assumes callback function is non-blocking",
        ],
        default_severity=Severity.ERROR,
    ),
}


def get_category_definitions() -> list[AssumptionDefinition]:
    """Get all assumption category definitions.

    Returns a list of all category definitions including their IDs,
    descriptions, examples, and default severity levels. Useful for
    documentation and UI display of available assumption categories.

    Returns:
        List of AssumptionDefinition for all 5 categories:
        ENVIRONMENTAL, ORDERING, DATA, TIMING, CONTRACT.

    """
    return list(ASSUMPTION_CATEGORIES.values())


# =============================================================================
# Risk Mapping Functions
# =============================================================================


def risk_to_severity(risk: RiskLevel, is_dangerous: bool = False) -> Severity:
    """Map risk level to finding severity.

    Args:
        risk: The assessed violation risk level.
        is_dangerous: Whether this is a dangerous assumption (data races,
            auth bypass, resource exhaustion, deadlock potential).

    Returns:
        Corresponding severity for the finding.

    """
    if risk == RiskLevel.HIGH:
        return Severity.CRITICAL if is_dangerous else Severity.ERROR
    elif risk == RiskLevel.MEDIUM:
        return Severity.WARNING
    else:  # LOW
        return Severity.INFO


def risk_to_confidence(risk: RiskLevel) -> float:
    """Map risk level to evidence confidence score.

    Args:
        risk: The assessed violation risk level.

    Returns:
        Confidence score 0.0-1.0 based on risk:
        - HIGH risk -> 0.85 confidence
        - MEDIUM risk -> 0.65 confidence
        - LOW risk -> 0.45 confidence

    """
    mapping = {
        RiskLevel.HIGH: 0.85,
        RiskLevel.MEDIUM: 0.65,
        RiskLevel.LOW: 0.45,
    }
    return mapping.get(risk, 0.5)


# =============================================================================
# System Prompt
# =============================================================================

ASSUMPTION_SURFACING_SYSTEM_PROMPT = """You are an expert code reviewer specializing in identifying implicit assumptions.

Your task is to analyze the provided code/implementation artifact and identify implicit assumptions that are NOT explicitly documented or enforced.

Focus on UNSTATED beliefs about system behavior, UNWRITTEN contracts between components, or UNVALIDATED assumptions about external dependencies that are NOT EXPLICITLY documented in the code or comments.

Assumption categories:
1. ENVIRONMENTAL: Runtime environment assumptions (CPU count, memory, network, permissions)
2. ORDERING: Operation ordering and sequence guarantees
3. DATA: Data format, immutability, validation state
4. TIMING: Execution timing, timeouts, clock behavior
5. CONTRACT: API contracts, caller behavior, external dependencies

For each assumption you identify:
- Describe the implicit assumption being made
- Categorize it appropriately
- Assess violation risk (high/medium/low)
- Provide evidence from the code
- Explain consequences if violated
- Recommend how to handle it

IMPORTANT DISTINCTIONS:
- Only identify assumptions that are IMPLICIT (not explicitly documented in code or comments)
- Do NOT list common best practices as assumptions unless they are unstated in this specific context
- Focus on assumptions that could realistically be violated and cause actual problems
- Provide specific code quotes as evidence with line numbers when possible

Respond with valid JSON only. If analysis fails, return empty JSON object `{}`."""


# =============================================================================
# Pydantic Models for LLM Response
# =============================================================================


class AssumptionFindingData(BaseModel):
    """Single assumption finding from LLM response."""

    assumption: str = Field(..., min_length=5)
    category: str = Field(...)
    violation_risk: str = Field(...)
    evidence_quote: str = Field(..., min_length=1)
    line_number: int | None = Field(default=None)
    consequences: str = Field(default="")
    recommendation: str = Field(default="")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Validate category is one of allowed values."""
        allowed = {"environmental", "ordering", "data", "timing", "contract"}
        v_lower = v.lower()
        if v_lower not in allowed:
            raise ValueError(f"Invalid category: {v}. Must be one of: {allowed}")
        return v_lower

    @field_validator("violation_risk")
    @classmethod
    def validate_risk(cls, v: str) -> str:
        """Validate risk is one of allowed values."""
        allowed = {"high", "medium", "low"}
        v_lower = v.lower()
        if v_lower not in allowed:
            raise ValueError(f"Invalid risk: {v}. Must be one of: {allowed}")
        return v_lower


class AssumptionAnalysisResponse(BaseModel):
    """Expected LLM response structure for assumption analysis."""

    assumptions: list[AssumptionFindingData] = Field(default_factory=list)


# =============================================================================
# Assumption Surfacing Method
# =============================================================================


class AssumptionSurfacingMethod(BaseVerificationMethod):
    """Assumption Surfacing Method (#155) - Implicit assumption detection.

    This method analyzes artifact text to identify implicit assumptions that
    could be violated, leading to bugs, race conditions, or integration failures.

    Method #155 runs conditionally when CONCURRENCY or API domains are detected,
    unlike the always-run methods (#153 Pattern Match and #154 Boundary Analysis).

    Attributes:
        method_id: Unique method identifier "#155".
        _provider: ClaudeSDKProvider for LLM calls.
        _model: Model identifier for LLM calls.
        _threshold: Minimum confidence threshold for findings (0.0-1.0).
        _timeout: Timeout in seconds for LLM calls.
        _categories: Optional list of categories to limit analysis.

    Example:
        >>> method = AssumptionSurfacingMethod()
        >>> findings = await method.analyze(
        ...     "code with implicit assumptions",
        ...     domains=[ArtifactDomain.CONCURRENCY]
        ... )
        >>> for f in findings:
        ...     print(f"{f.id}: {f.title}")

    """

    method_id: MethodId

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        timeout: int = DEFAULT_TIMEOUT,
        categories: list[AssumptionCategory] | None = None,
        llm_client: Any | None = None,
    ) -> None:
        """Initialize the Assumption Surfacing Method.

        Args:
            model: Model identifier for LLM calls (default: "haiku").
            threshold: Minimum confidence threshold for findings (default: 0.6).
            timeout: Timeout in seconds for LLM calls (default: 30).
            categories: Optional list of categories to limit analysis.
                       If None, analyzes all categories.
            llm_client: Optional LLMClient for managed LLM calls. If provided,
                       uses LLMClient (with retry, rate limiting, cost tracking).
                       If None, creates direct ClaudeSDKProvider.

        Raises:
            ValueError: If threshold is not between 0.0 and 1.0.

        """
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be between 0.0 and 1.0, got {threshold}")

        self.method_id = MethodId("#155")
        self._llm_client = llm_client
        # Only create provider if LLMClient NOT provided
        self._provider: ClaudeSDKProvider | None
        if llm_client is None:
            self._provider = ClaudeSDKProvider()
        else:
            self._provider = None
        self._model = model
        self._threshold = threshold
        self._timeout = timeout
        self._categories = categories or list(AssumptionCategory)

    def __repr__(self) -> str:
        """Return a string representation of the method."""
        return (
            f"AssumptionSurfacingMethod("
            f"method_id={self.method_id!r}, model='{self._model}', threshold={self._threshold}"
            f")"
        )

    async def analyze(
        self,
        artifact_text: str,
        **kwargs: Any,
    ) -> list[Finding]:
        """Analyze artifact for implicit assumptions.

        Args:
            artifact_text: The text content to analyze for implicit assumptions.
            **kwargs: Additional context including:
                - domains: Optional list[ArtifactDomain] to determine if method should run
                - config: Optional DeepVerifyConfig (not used currently)

        Returns:
            List of Finding objects for identified assumptions with
            confidence >= threshold. Findings have temporary IDs "#155-F1",
            "#155-F2", etc. which will be reassigned by DeepVerifyEngine.
            Returns empty list if CONCURRENCY or API domain is not detected.

        """
        if not artifact_text or not artifact_text.strip():
            logger.debug("Empty artifact text, returning no findings")
            return []

        # Extract domains from kwargs
        domains = kwargs.get("domains")

        # Check if method should run for detected domains
        if not self._should_run_for_domains(domains):
            logger.debug(
                "Assumption surfacing skipped: no CONCURRENCY or API domain detected (domains=%s)",
                domains,
            )
            return []

        try:
            logger.debug(
                "Running assumption surfacing analysis (domains=%s, categories=%s)",
                domains,
                [c.value for c in self._categories],
            )

            # Run sync LLM call in thread pool to avoid blocking
            result = await asyncio.to_thread(self._analyze_assumptions_sync, artifact_text)

            # Convert results to findings with filtering by threshold
            findings: list[Finding] = []
            finding_idx = 0

            for assumption_data in result.assumptions:
                confidence = risk_to_confidence(RiskLevel(assumption_data.violation_risk))
                if confidence >= self._threshold:
                    finding_idx += 1
                    findings.append(
                        self._create_finding_from_assumption(
                            assumption_data, finding_idx, domains or []
                        )
                    )

            logger.debug(
                "Assumption surfacing found %d assumptions (threshold=%.2f)",
                len(findings),
                self._threshold,
            )

            return findings

        except Exception as e:
            logger.warning("Assumption surfacing failed: %s", e, exc_info=True)
            return []

    def _should_run_for_domains(self, domains: list[ArtifactDomain] | None) -> bool:
        """Check if method should run for detected domains.

        Method #155 runs only when CONCURRENCY or API domain is detected.

        Args:
            domains: List of detected domains (may be None).

        Returns:
            True if CONCURRENCY or API is in the domains list, False otherwise.

        """
        if not domains:
            return False

        return ArtifactDomain.CONCURRENCY in domains or ArtifactDomain.API in domains

    def _analyze_assumptions_sync(self, artifact_text: str) -> AssumptionAnalysisResponse:
        """Analyze artifact for implicit assumptions using LLM (synchronous).

        Uses LLMClient if available, otherwise falls back to direct provider.

        Args:
            artifact_text: The text to analyze.

        Returns:
            AssumptionAnalysisResponse with identified assumptions.

        """
        prompt = self._build_prompt(artifact_text)

        if self._llm_client:
            # Use LLMClient for managed calls (async bridge)
            # CRITICAL: Use run_async_in_thread() instead of asyncio.run() to avoid
            # shutting down the default executor (which the outer event loop uses)
            from bmad_assist.core.async_utils import run_async_in_thread

            result = run_async_in_thread(
                self._llm_client.invoke(
                    prompt=prompt,
                    model=self._model,
                    timeout=self._timeout,
                    method_id=str(self.method_id),
                )
            )
            raw_response = result.stdout
        else:
            # Direct provider call (legacy fallback)
            assert self._provider is not None
            result = self._provider.invoke(
                prompt=prompt,
                model=self._model,
                timeout=self._timeout,
            )
            raw_response = self._provider.parse_output(result)

        return self._parse_response(raw_response)

    def _build_prompt(self, artifact_text: str) -> str:
        """Build the prompt for LLM assumption analysis.

        Args:
            artifact_text: The text to analyze.

        Returns:
            Formatted prompt string.

        """
        truncated = artifact_text[:MAX_ARTIFACT_LENGTH]
        was_truncated = len(artifact_text) > MAX_ARTIFACT_LENGTH

        # Build category descriptions
        category_descriptions = []
        for cat in self._categories:
            definition = ASSUMPTION_CATEGORIES[cat]
            category_descriptions.append(f"- {cat.value.upper()}: {definition.description}")

        categories_str = "\n".join(category_descriptions)

        # Add truncation warning if content was truncated
        truncation_notice = ""
        if was_truncated:
            truncation_notice = (
                f"\n⚠️ IMPORTANT: Artifact was truncated from {len(artifact_text)} "
                f"to {MAX_ARTIFACT_LENGTH} characters. Assumptions beyond this point "
                f"will NOT be detected.\n\n"
            )

        return (
            f"{ASSUMPTION_SURFACING_SYSTEM_PROMPT}\n\n"
            f"Artifact to analyze (truncated to {MAX_ARTIFACT_LENGTH} chars):{truncation_notice}\n"
            f"```\n{truncated}\n```\n\n"
            f"Categories to analyze:\n"
            f"{categories_str}\n\n"
            f"Identify all implicit assumptions in the artifact. "
            f"For each assumption, provide:\n"
            f"- assumption: Description of the implicit assumption\n"
            f"- category: One of [environmental, ordering, data, timing, contract]\n"
            f"- violation_risk: One of [high, medium, low]\n"
            f"- evidence_quote: Code snippet showing where assumption is made\n"
            f"- line_number: Line number (if identifiable)\n"
            f"- consequences: What happens if assumption is violated\n"
            f"- recommendation: How to handle or document the assumption\n\n"
            f"Respond with JSON in this format:\n"
            f"{{\n"
            f'    "assumptions": [\n'
            f"        {{\n"
            f'            "assumption": "Assumes X...",\n'
            f'            "category": "data",\n'
            f'            "violation_risk": "high",\n'
            f'            "evidence_quote": "code snippet",\n'
            f'            "line_number": 42,\n'
            f'            "consequences": "If violated, Y will happen...",\n'
            f'            "recommendation": "Add explicit check for..."\n'
            f"        }}\n"
            f"    ]\n"
            f"}}"
        )

    def _parse_response(self, raw_response: str) -> AssumptionAnalysisResponse:
        """Parse LLM response with robust JSON extraction.

        Handles:
        - JSON inside markdown code blocks (```json...```)
        - Raw JSON objects
        - Nested braces by tracking depth

        Args:
            raw_response: Raw text response from LLM.

        Returns:
            Parsed AssumptionAnalysisResponse.

        Raises:
            ValueError: If response cannot be parsed.

        """
        # Try to extract from markdown code block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_response, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # Find JSON by matching braces - handle nested objects
            brace_depth = 0
            start_idx = -1
            json_str = ""
            for i, char in enumerate(raw_response):
                if char == "{":
                    if brace_depth == 0:
                        start_idx = i
                    brace_depth += 1
                elif char == "}":
                    brace_depth -= 1
                    if brace_depth == 0 and start_idx >= 0:
                        json_str = raw_response[start_idx : i + 1]
                        break

            if not json_str:
                # Try to find the "assumptions" array directly
                match = re.search(r'"assumptions"\s*:\s*(\[.*?\])', raw_response, re.DOTALL)
                if match:
                    json_str = '{"assumptions": ' + match.group(1) + "}"
                else:
                    raise ValueError("No JSON found in response")

        # Parse with Pydantic validation
        data = json.loads(json_str)
        return AssumptionAnalysisResponse(**data)

    def _create_finding_from_assumption(
        self,
        assumption_data: AssumptionFindingData,
        index: int,
        detected_domains: list[ArtifactDomain],
    ) -> Finding:
        """Convert assumption analysis data to Finding.

        Args:
            assumption_data: The assumption data from LLM response.
            index: The index for generating finding ID.
            detected_domains: List of domains detected in the artifact.

        Returns:
            Finding object with all relevant details.

        """
        finding_id = f"#155-F{index}"

        # Map risk to severity and confidence
        risk = RiskLevel(assumption_data.violation_risk)

        # Determine if this is a "dangerous" assumption for CRITICAL severity
        is_dangerous = self._is_dangerous_assumption(
            assumption_data.category, assumption_data.assumption
        )
        severity = risk_to_severity(risk, is_dangerous)
        confidence = risk_to_confidence(risk)

        # Build title from assumption description
        title = f"Assumes {assumption_data.assumption}"
        if len(title) > 80:
            title = title[:77] + "..."

        # Build comprehensive description
        description_parts = [
            f"Implicit assumption: {assumption_data.assumption}",
            "",
            f"Category: {assumption_data.category}",
            f"Violation risk: {assumption_data.violation_risk}",
        ]

        if assumption_data.consequences:
            description_parts.extend(
                [
                    "",
                    f"Consequences if violated: {assumption_data.consequences}",
                ]
            )

        if assumption_data.recommendation:
            description_parts.extend(
                [
                    "",
                    f"Recommendation: {assumption_data.recommendation}",
                ]
            )

        description = "\n".join(description_parts)

        # Create evidence
        evidence = []
        if assumption_data.evidence_quote:
            evidence.append(
                Evidence(
                    quote=assumption_data.evidence_quote,
                    line_number=assumption_data.line_number,
                    source="#155",
                    confidence=confidence,
                )
            )

        # Determine pattern_id from category
        category_enum = AssumptionCategory(assumption_data.category.lower())
        pattern_id = PatternId(ASSUMPTION_CATEGORIES[category_enum].id)

        # Determine domain based on category and detected domains
        domain = self._assign_domain_for_assumption(assumption_data.category, detected_domains)

        return Finding(
            id=finding_id,
            severity=severity,
            title=title,
            description=description,
            method_id=MethodId("#155"),
            pattern_id=pattern_id,
            domain=domain,
            evidence=evidence,
        )

    def _is_dangerous_assumption(self, category: str, assumption: str) -> bool:
        """Check if an assumption is considered dangerous (qualifies for CRITICAL).

        Dangerous assumptions include those related to:
        - Data races
        - Authentication/authorization bypass
        - Resource exhaustion
        - Deadlock potential

        Args:
            category: The assumption category.
            assumption: The assumption description.

        Returns:
            True if the assumption is dangerous, False otherwise.

        """
        assumption_lower = assumption.lower()
        category_lower = category.lower()

        # Category-specific dangerous patterns - only check for the specific category
        if category_lower == "ordering":
            # Focus on ordering guarantees that, if violated, cause panics or deadlocks
            ordering_dangerous = [
                "close exactly once",
                "single execution",
                "deadlock",
                "lock order",
                "acquisition order",
            ]
            for keyword in ordering_dangerous:
                if keyword in assumption_lower:
                    return True

        if category_lower == "data":
            # Focus on data race and shared state issues
            data_dangerous = [
                "data race",
                "race condition",
                "concurrent modification",
                "shared mutable state",
                "immutable during concurrent",
            ]
            for keyword in data_dangerous:
                if keyword in assumption_lower:
                    return True

        if category_lower == "contract":
            # Focus on security-critical contract violations
            contract_dangerous = [
                "authentication bypass",
                "authorization bypass",
                "auth bypass",
                "privilege escalation",
                "injection",
            ]
            for keyword in contract_dangerous:
                if keyword in assumption_lower:
                    return True

        # General dangerous keywords (apply to all categories)
        general_dangerous = [
            "resource exhaustion",
            "oom",
            "memory leak",
            "crash",
            "corruption",
            "deadlock",
            "panic",
        ]
        return any(keyword in assumption_lower for keyword in general_dangerous)

    def _assign_domain_for_assumption(
        self,
        category: str,
        detected_domains: list[ArtifactDomain],
    ) -> ArtifactDomain | None:
        """Assign domain to a finding based on its category and detected domains.

        Args:
            category: The assumption category.
            detected_domains: List of domains detected in the artifact.

        Returns:
            ArtifactDomain for the finding, or None if cannot be determined.

        """
        category_lower = category.lower()

        # CONTRACT category → API (if available)
        if category_lower == "contract":
            if ArtifactDomain.API in detected_domains:
                return ArtifactDomain.API
            # Fallback to CONCURRENCY if API not detected
            if ArtifactDomain.CONCURRENCY in detected_domains:
                return ArtifactDomain.CONCURRENCY

        # Other categories → CONCURRENCY (if available)
        if ArtifactDomain.CONCURRENCY in detected_domains:
            return ArtifactDomain.CONCURRENCY

        # Fallback to API if CONCURRENCY not detected
        if ArtifactDomain.API in detected_domains:
            return ArtifactDomain.API

        return None
