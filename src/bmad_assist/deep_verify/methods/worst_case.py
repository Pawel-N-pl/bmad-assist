"""Worst-Case Construction Method (#205) for Deep Verify.

This module implements the Worst-Case Construction verification method that builds
specific failure scenarios for implementation artifacts. Method #205 runs conditionally
when CONCURRENCY or MESSAGING domains are detected.

The method identifies cascade failures, resource exhaustion scenarios, thundering herds,
data corruption, and split-brain scenarios that could lead to system-wide outages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from bmad_assist.core.exceptions import ProviderError, ProviderTimeoutError
from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    Evidence,
    Finding,
    MethodId,
    PatternId,
    Severity,
)
from bmad_assist.deep_verify.methods.base import BaseVerificationMethod
from bmad_assist.deep_verify.methods.constants import (
    DEFAULT_MODEL,
    DEFAULT_THRESHOLD,
    DEFAULT_TIMEOUT,
)
from bmad_assist.providers import ClaudeSDKProvider

logger = logging.getLogger(__name__)

__all__ = [
    "WorstCaseCategory",
    "WorstCaseDefinition",
    "WorstCaseMethod",
    "WorstCaseScenarioData",
    "WorstCaseAnalysisResponse",
    "WORST_CASE_CONSTRUCTION_SYSTEM_PROMPT",
    "ScenarioSeverity",
    "get_category_definitions",
    "severity_to_confidence",
    "severity_to_finding_severity",
]

# =============================================================================
# Constants
# =============================================================================

MAX_ARTIFACT_LENGTH = 4000

# =============================================================================
# Enums
# =============================================================================


class WorstCaseCategory(str, Enum):
    """Categories of worst-case failure scenarios.

    Each category represents a different type of systemic failure
    that can occur in distributed and concurrent systems.
    """

    CASCADE = "cascade"  # Cascade failure scenarios
    EXHAUSTION = "exhaustion"  # Resource exhaustion scenarios
    THUNDERING_HERD = "thundering_herd"  # Thundering herd scenarios
    CORRUPTION = "corruption"  # Data corruption scenarios
    SPLIT_BRAIN = "split_brain"  # Split-brain scenarios


class ScenarioSeverity(str, Enum):
    """Scenario severity levels for worst-case analysis.

    Indicates the severity of consequences if the worst-case scenario manifests.
    """

    CATASTROPHIC = "catastrophic"
    SEVERE = "severe"
    MODERATE = "moderate"
    MINOR = "minor"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass(frozen=True)
class WorstCaseDefinition:
    """Definition of a worst-case category with metadata.

    Attributes:
        id: Category ID string (e.g., "WC-CAS-001", "WC-EXH-001").
        description: Description of worst-case scenario type.
        examples: Examples of common failure scenarios in this category.
        default_severity: Default severity if scenario is found.

    """

    id: str
    description: str
    examples: list[str]
    default_severity: Severity

    def __repr__(self) -> str:
        """Return a string representation of the worst case definition."""
        return f"WorstCaseDefinition(id={self.id!r}, description={self.description!r})"


# =============================================================================
# Category Definitions
# =============================================================================

WORST_CASE_CATEGORIES: dict[WorstCaseCategory, WorstCaseDefinition] = {
    WorstCaseCategory.CASCADE: WorstCaseDefinition(
        id="WC-CAS-001",
        description="Cascade failure scenarios where one failure triggers chain reaction",
        examples=[
            "Service A fails → Service B times out → Service C overloaded",
            "Database connection pool exhaustion → all requests blocked",
            "Single goroutine panic → entire process crash",
            "Lock ordering violation → distributed deadlock",
        ],
        default_severity=Severity.ERROR,
    ),
    WorstCaseCategory.EXHAUSTION: WorstCaseDefinition(
        id="WC-EXH-001",
        description="Resource exhaustion scenarios (memory, CPU, connections, file descriptors)",
        examples=[
            "Unbounded goroutine spawn → OOM kill",
            "Unlimited retry without backoff → connection pool exhaustion",
            "Unbounded cache growth → memory pressure",
            "File descriptor leak → 'too many open files' error",
        ],
        default_severity=Severity.ERROR,
    ),
    WorstCaseCategory.THUNDERING_HERD: WorstCaseDefinition(
        id="WC-THD-001",
        description="Thundering herd scenarios from synchronized retries or spawns",
        examples=[
            "All clients retry simultaneously after timeout",
            "Fixed-interval retries aligned across instances",
            "Health check failures trigger simultaneous reconnections",
            "Cache expiry causes stampede to backend",
        ],
        default_severity=Severity.ERROR,
    ),
    WorstCaseCategory.CORRUPTION: WorstCaseDefinition(
        id="WC-COR-001",
        description="Data corruption scenarios from race conditions or partial writes",
        examples=[
            "Concurrent map write → corrupted data structure",
            "Partial write to file → truncated/corrupted state",
            "Non-atomic state update → inconsistent read",
            "Message processed twice → duplicate side effects",
        ],
        default_severity=Severity.CRITICAL,
    ),
    WorstCaseCategory.SPLIT_BRAIN: WorstCaseDefinition(
        id="WC-SPB-001",
        description="Split-brain scenarios from distributed consensus failures",
        examples=[
            "Network partition → two leaders elected",
            "Clock skew → conflicting write timestamps",
            "Lease expiration race → simultaneous ownership",
            "Consensus timeout → divergent state across nodes",
        ],
        default_severity=Severity.CRITICAL,
    ),
}


def get_category_definitions() -> list[WorstCaseDefinition]:
    """Get all worst-case category definitions.

    Returns a list of all category definitions including their IDs,
    descriptions, examples, and default severity levels.

    Returns:
        List of WorstCaseDefinition for all 5 categories:
        CASCADE, EXHAUSTION, THUNDERING_HERD, CORRUPTION, SPLIT_BRAIN.

    """
    return list(WORST_CASE_CATEGORIES.values())


# =============================================================================
# Severity Mapping Functions
# =============================================================================


def severity_to_finding_severity(severity: ScenarioSeverity) -> Severity:
    """Map scenario severity to finding severity.

    Args:
        severity: The assessed scenario severity.

    Returns:
        Corresponding Severity for the finding.

    """
    mapping = {
        ScenarioSeverity.CATASTROPHIC: Severity.CRITICAL,
        ScenarioSeverity.SEVERE: Severity.ERROR,
        ScenarioSeverity.MODERATE: Severity.WARNING,
        ScenarioSeverity.MINOR: Severity.INFO,
    }
    return mapping.get(severity, Severity.WARNING)


def severity_to_confidence(severity: ScenarioSeverity) -> float:
    """Map scenario severity to evidence confidence score.

    Args:
        severity: The assessed scenario severity.

    Returns:
        Confidence score 0.0-1.0 based on severity:
        - CATASTROPHIC -> 0.95 confidence
        - SEVERE -> 0.85 confidence
        - MODERATE -> 0.65 confidence
        - MINOR -> 0.45 confidence

    """
    mapping = {
        ScenarioSeverity.CATASTROPHIC: 0.95,
        ScenarioSeverity.SEVERE: 0.85,
        ScenarioSeverity.MODERATE: 0.65,
        ScenarioSeverity.MINOR: 0.45,
    }
    return mapping.get(severity, 0.5)


def _is_catastrophic_scenario(category: str, scenario: str) -> bool:
    """Determine if scenario should be CATASTROPHIC severity.

    Catastrophic scenarios include total service crash, unrecoverable data loss,
    complete system outage.

    Args:
        category: The worst-case category.
        scenario: The scenario description.

    Returns:
        True if scenario should be CATASTROPHIC severity.

    """
    scenario_lower = scenario.lower()

    # General catastrophic keywords (apply to all categories)
    catastrophic_keywords = [
        "total crash",
        "complete outage",
        "unrecoverable",
        "data loss",
        "panic",
        "oom kill",
        "deadlock",
        "infinite loop",
        "corruption",
        "inconsistent state",
        "split brain",
    ]

    return any(keyword in scenario_lower for keyword in catastrophic_keywords)


# =============================================================================
# System Prompt
# =============================================================================

WORST_CASE_CONSTRUCTION_SYSTEM_PROMPT = """You are a reliability engineer specializing in failure mode analysis.

Your task is to analyze the provided code/implementation artifact and construct specific, realistic WORST-CASE FAILURE SCENARIOS.

Focus on scenarios that could realistically occur in production and cause significant system impact.

Worst-case categories to analyze:
1. CASCADE: Cascade failures where one failure triggers chain reactions (service A fails → B fails → C fails)
2. EXHAUSTION: Resource exhaustion scenarios (OOM, connection pool depletion, file descriptor exhaustion)
3. THUNDERING_HERD: Synchronized behavior causing stampedes (all retries at once, simultaneous reconnections)
4. CORRUPTION: Data corruption from race conditions, partial writes, or inconsistent state
5. SPLIT_BRAIN: Distributed consensus failures (two leaders, divergent state across nodes)

For each worst-case scenario you construct:
- Describe the specific failure scenario
- Categorize it appropriately
- Assess severity (catastrophic/severe/moderate/minor)
- Identify the trigger conditions
- Explain the cascade effect (how failure propagates)
- Provide evidence from the code
- Recommend mitigation strategies

Scenario severity definitions:
- CATASTROPHIC: Total service crash, unrecoverable data loss, complete system outage
- SEVERE: Significant degradation, partial data loss, major functionality broken
- MODERATE: Performance impact, recoverable errors, reduced capacity
- MINOR: Minimal impact, self-healing, edge case only

Focus on scenarios that are:
- Realistic in production systems (not theoretical edge cases)
- Have clear trigger conditions
- Would cause measurable business impact
- Could be prevented with code changes

Respond with valid JSON only. If no worst-case scenarios found, return empty JSON object `{}`."""


# =============================================================================
# Pydantic Models for LLM Response
# =============================================================================


class WorstCaseScenarioData(BaseModel):
    """Pydantic model for individual worst-case scenario in LLM response."""

    scenario: str = Field(..., min_length=5, description="Description of the worst-case scenario")
    category: str = Field(..., min_length=1, description="Worst-case category")
    severity: str = Field(..., min_length=1, description="Scenario severity assessment")
    trigger: str = Field(..., min_length=1, description="What conditions trigger this scenario")
    cascade_effect: str = Field(..., min_length=1, description="How failure propagates")
    evidence_quote: str = Field(..., min_length=1, description="Code snippet showing vulnerability")
    line_number: int | None = Field(None, description="Line number if identifiable")
    mitigation: str = Field(..., min_length=1, description="How to prevent or mitigate")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Validate category is one of allowed values."""
        allowed = {"cascade", "exhaustion", "thundering_herd", "corruption", "split_brain"}
        v_lower = v.lower()
        if v_lower not in allowed:
            raise ValueError(f"category must be one of {allowed}, got {v}")
        return v_lower

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        """Validate severity is one of allowed values."""
        allowed = {"catastrophic", "severe", "moderate", "minor"}
        v_lower = v.lower()
        if v_lower not in allowed:
            raise ValueError(f"severity must be one of {allowed}, got {v}")
        return v_lower


class WorstCaseAnalysisResponse(BaseModel):
    """Pydantic model for full worst-case analysis response."""

    scenarios: list[WorstCaseScenarioData] = Field(
        default_factory=list, description="List of constructed worst-case scenarios"
    )


# =============================================================================
# Worst-Case Construction Method
# =============================================================================


class WorstCaseMethod(BaseVerificationMethod):
    """Worst-Case Construction Method (#205) - Failure scenario construction.

    This method analyzes artifact text to construct specific worst-case failure
    scenarios that could lead to system-wide outages or data corruption.

    Method #205 runs conditionally when CONCURRENCY or MESSAGING domains are detected,
    unlike the always-run methods (#153 Pattern Match and #154 Boundary Analysis).

    Attributes:
        method_id: Unique method identifier "#205".
        _provider: ClaudeSDKProvider for LLM calls.
        _model: Model identifier for LLM calls.
        _threshold: Minimum confidence threshold for findings (0.0-1.0).
        _timeout: Timeout in seconds for LLM calls.
        _categories: Optional list of categories to limit analysis.

    Example:
        >>> method = WorstCaseMethod()
        >>> findings = await method.analyze(
        ...     "code with unbounded map",
        ...     domains=[ArtifactDomain.CONCURRENCY]
        ... )
        >>> for f in findings:
        ...     print(f"{f.id}: {f.title}")

    """

    method_id: MethodId = MethodId("#205")

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        timeout: int = DEFAULT_TIMEOUT,
        categories: list[WorstCaseCategory] | None = None,
        llm_client: Any | None = None,
    ) -> None:
        """Initialize the Worst-Case Construction Method.

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
        self._categories = categories or list(WorstCaseCategory)

    def __repr__(self) -> str:
        """Return a string representation of the method."""
        return (
            f"WorstCaseMethod("
            f"method_id={self.method_id!r}, model='{self._model}', threshold={self._threshold}"
            f")"
        )

    async def analyze(
        self,
        artifact_text: str,
        **kwargs: Any,
    ) -> list[Finding]:
        """Analyze artifact for worst-case failure scenarios.

        Args:
            artifact_text: The text content to analyze for worst-case scenarios.
            **kwargs: Additional context including:
                - domains: Optional list[ArtifactDomain] to determine if method should run
                - config: Optional DeepVerifyConfig (not used currently)

        Returns:
            List of Finding objects for identified worst-case scenarios with
            confidence >= threshold. Findings have temporary IDs "#205-F1",
            "#205-F2", etc. which will be reassigned by DeepVerifyEngine.
            Returns empty list if CONCURRENCY or MESSAGING domain is not detected.

        """
        if not artifact_text or not artifact_text.strip():
            logger.debug("Empty artifact text, returning no findings")
            return []

        # Extract domains from kwargs
        domains = kwargs.get("domains")

        # Check if method should run for detected domains
        if not self._should_run_for_domains(domains):
            logger.debug(
                "Worst-case construction skipped: no CONCURRENCY or MESSAGING domain detected (domains=%s)",
                domains,
            )
            return []

        try:
            logger.debug(
                "Running worst-case construction analysis (domains=%s, categories=%s)",
                domains,
                [c.value for c in self._categories],
            )

            # Run sync LLM call in thread pool to avoid blocking
            result = await asyncio.to_thread(self._analyze_worst_cases_sync, artifact_text)

            # Convert results to findings with filtering by threshold
            findings: list[Finding] = []
            finding_idx = 0

            for scenario_data in result.scenarios:
                confidence = severity_to_confidence(ScenarioSeverity(scenario_data.severity))
                if confidence >= self._threshold:
                    finding_idx += 1
                    findings.append(
                        self._create_finding_from_scenario(
                            scenario_data, finding_idx, domains or []
                        )
                    )

            logger.debug(
                "Worst-case construction found %d scenarios (threshold=%.2f)",
                len(findings),
                self._threshold,
            )

            return findings

        except (ProviderError, ProviderTimeoutError) as e:
            logger.warning("Worst-case construction analysis failed: %s", e)
            return []
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            logger.warning("Worst-case construction analysis failed - parse error: %s", e)
            return []

    def _should_run_for_domains(self, domains: list[ArtifactDomain] | None) -> bool:
        """Check if method should run for detected domains.

        Method #205 runs only when CONCURRENCY or MESSAGING domain is detected.

        Args:
            domains: List of detected domains (may be None).

        Returns:
            True if CONCURRENCY or MESSAGING is in the domains list, False otherwise.

        """
        if not domains:
            return False

        return ArtifactDomain.CONCURRENCY in domains or ArtifactDomain.MESSAGING in domains

    def _analyze_worst_cases_sync(self, artifact_text: str) -> WorstCaseAnalysisResponse:
        """Analyze artifact for worst-case scenarios using LLM (synchronous).

        Uses LLMClient if available, otherwise falls back to direct provider.

        Args:
            artifact_text: The text to analyze.

        Returns:
            WorstCaseAnalysisResponse with identified worst-case scenarios.

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
        """Build the prompt for LLM worst-case analysis.

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
            definition = WORST_CASE_CATEGORIES[cat]
            category_descriptions.append(f"- {cat.value.upper()}: {definition.description}")
            # Add examples for clarity
            for example in definition.examples[:2]:  # Limit to 2 examples per category
                category_descriptions.append(f"    Example: {example}")

        categories_str = "\n".join(category_descriptions)

        # Add truncation warning if content was truncated
        truncation_notice = ""
        if was_truncated:
            truncation_notice = (
                f"\n⚠️ IMPORTANT: Artifact was truncated from {len(artifact_text)} "
                f"to {MAX_ARTIFACT_LENGTH} characters. Worst-case scenarios beyond this point "
                f"will NOT be detected.\n\n"
            )

        return (
            f"{WORST_CASE_CONSTRUCTION_SYSTEM_PROMPT}\n\n"
            f"Artifact to analyze (truncated to {MAX_ARTIFACT_LENGTH} chars):{truncation_notice}\n"
            f"```\n{truncated}\n```\n\n"
            f"Categories to analyze:\n"
            f"{categories_str}\n\n"
            f"Construct worst-case failure scenarios for this artifact. "
            f"For each scenario, provide:\n"
            f"- scenario: Description of the worst-case failure scenario\n"
            f"- category: One of [cascade, exhaustion, thundering_herd, corruption, split_brain]\n"
            f"- severity: One of [catastrophic, severe, moderate, minor]\n"
            f"- trigger: What conditions trigger this scenario\n"
            f"- cascade_effect: How the failure propagates and impacts the system\n"
            f"- evidence_quote: Code snippet showing where vulnerability exists\n"
            f"- line_number: Line number (if identifiable)\n"
            f"- mitigation: How to prevent or mitigate the scenario\n\n"
            f"Respond with JSON in this format:\n"
            f"{{\n"
            f'    "scenarios": [\n'
            f"        {{\n"
            f'            "scenario": "Description...",\n'
            f'            "category": "exhaustion",\n'
            f'            "severity": "catastrophic",\n'
            f'            "trigger": "When unbounded input is received...",\n'
            f'            "cascade_effect": "Service crashes, causing cascading failures...",\n'
            f'            "evidence_quote": "code snippet",\n'
            f'            "line_number": 42,\n'
            f'            "mitigation": "Add bounds checking and backpressure..."\n'
            f"        }}\n"
            f"    ]\n"
            f"}}"
        )

    def _parse_response(self, raw_response: str) -> WorstCaseAnalysisResponse:
        """Parse LLM response with robust JSON extraction.

        Handles:
        - JSON inside markdown code blocks (```json...```)
        - Raw JSON objects
        - Nested braces by tracking depth

        Args:
            raw_response: Raw text response from LLM.

        Returns:
            Parsed WorstCaseAnalysisResponse.

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
                # Try to find the "scenarios" array directly
                match = re.search(r'"scenarios"\s*:\s*(\[.*?\])', raw_response, re.DOTALL)
                if match:
                    json_str = '{"scenarios": ' + match.group(1) + "}"
                else:
                    raise ValueError("No JSON found in response")

        # Parse with Pydantic validation
        data = json.loads(json_str)
        return WorstCaseAnalysisResponse(**data)

    def _create_finding_from_scenario(
        self,
        scenario_data: WorstCaseScenarioData,
        index: int,
        detected_domains: list[ArtifactDomain],
    ) -> Finding:
        """Convert worst-case scenario data to Finding.

        Args:
            scenario_data: The scenario data from LLM response.
            index: The index for generating finding ID.
            detected_domains: List of domains detected in the artifact.

        Returns:
            Finding object with all relevant details.

        """
        finding_id = f"#205-F{index + 1}"

        # Map severity to finding severity and confidence
        severity = ScenarioSeverity(scenario_data.severity)

        # Check for CRITICAL severity override for catastrophic scenarios
        is_catastrophic = _is_catastrophic_scenario(scenario_data.category, scenario_data.scenario)
        if is_catastrophic:
            finding_severity = Severity.CRITICAL
            confidence = 0.95  # Match catastrophic confidence
        else:
            finding_severity = severity_to_finding_severity(severity)
            confidence = severity_to_confidence(severity)

        # Build title from scenario description
        title = scenario_data.scenario
        if len(title) > 80:
            title = title[:77] + "..."

        # Build comprehensive description
        description_parts = [
            f"Worst-case scenario: {scenario_data.scenario}",
            "",
            f"Category: {scenario_data.category}",
            f"Severity: {scenario_data.severity}",
        ]

        if scenario_data.trigger:
            description_parts.extend(
                [
                    "",
                    f"Trigger: {scenario_data.trigger}",
                ]
            )

        if scenario_data.cascade_effect:
            description_parts.extend(
                [
                    "",
                    f"Cascade effect: {scenario_data.cascade_effect}",
                ]
            )

        if scenario_data.mitigation:
            description_parts.extend(
                [
                    "",
                    f"Mitigation: {scenario_data.mitigation}",
                ]
            )

        description = "\n".join(description_parts)

        # Create evidence
        evidence = []
        if scenario_data.evidence_quote and scenario_data.evidence_quote.strip():
            evidence.append(
                Evidence(
                    quote=scenario_data.evidence_quote,
                    line_number=scenario_data.line_number,
                    source="#205",
                    confidence=confidence,
                )
            )

        # Determine pattern_id from category
        try:
            category_enum = WorstCaseCategory(scenario_data.category.lower())
            pattern_id = PatternId(WORST_CASE_CATEGORIES[category_enum].id)
        except (ValueError, KeyError):
            pattern_id = None

        # Determine domain based on category and detected domains
        domain = self._assign_domain_for_category(scenario_data.category, detected_domains)

        return Finding(
            id=finding_id,
            severity=finding_severity,
            title=title,
            description=description,
            method_id=MethodId("#205"),
            pattern_id=pattern_id,
            domain=domain,
            evidence=evidence,
        )

    def _assign_domain_for_category(
        self,
        category: str,
        detected_domains: list[ArtifactDomain],
    ) -> ArtifactDomain | None:
        """Assign domain to a finding based on its category and detected domains.

        Args:
            category: The worst-case category.
            detected_domains: List of domains detected in the artifact.

        Returns:
            ArtifactDomain for the finding, or None if cannot be determined.

        """
        cat_lower = category.lower()

        # CASCADE, EXHAUSTION, CORRUPTION → CONCURRENCY (with MESSAGING fallback)
        if cat_lower in ("cascade", "exhaustion", "corruption"):
            if ArtifactDomain.CONCURRENCY in detected_domains:
                return ArtifactDomain.CONCURRENCY
            if ArtifactDomain.MESSAGING in detected_domains:
                return ArtifactDomain.MESSAGING

        # THUNDERING_HERD, SPLIT_BRAIN → MESSAGING (with CONCURRENCY fallback)
        if cat_lower in ("thundering_herd", "split_brain"):
            if ArtifactDomain.MESSAGING in detected_domains:
                return ArtifactDomain.MESSAGING
            if ArtifactDomain.CONCURRENCY in detected_domains:
                return ArtifactDomain.CONCURRENCY

        # Default: first detected domain
        if detected_domains:
            return detected_domains[0]

        return None
