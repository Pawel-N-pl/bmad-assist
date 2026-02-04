"""Temporal Consistency Method (#157) for Deep Verify.

This module implements the Temporal Consistency verification method that detects
time-related logic issues in implementation artifacts. Method #157 runs conditionally
when MESSAGING or STORAGE domains are detected.

The method identifies temporal bugs, race conditions, and timing inconsistencies
that could lead to data corruption, message loss, or system instability.
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
from bmad_assist.providers import ClaudeSDKProvider

logger = logging.getLogger(__name__)

__all__ = [
    "TemporalCategory",
    "TemporalConsistencyMethod",
    "TemporalDefinition",
    "ImpactLevel",
    "TemporalIssueData",
    "TemporalAnalysisResponse",
    "TEMPORAL_CONSISTENCY_SYSTEM_PROMPT",
    "impact_to_severity",
    "impact_to_confidence",
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


class TemporalCategory(str, Enum):
    """Categories of temporal consistency issues.

    Each category represents a different type of time-related bug
    that can occur in software systems.
    """

    TIMEOUT = "timeout"  # Timeout handling and cleanup issues
    ORDERING = "ordering"  # Event/message ordering
    CLOCK = "clock"  # Clock skew, monotonic time
    EXPIRATION = "expiration"  # TTL, lease management
    RACE_WINDOW = "race_window"  # TOCTOU race conditions


class ImpactLevel(str, Enum):
    """Impact levels for temporal issues.

    Indicates the severity of consequences if the temporal issue manifests.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass(frozen=True)
class TemporalDefinition:
    """Definition of a temporal category with metadata.

    Attributes:
        id: Category ID string (e.g., "TMP-001", "ORD-001").
        description: Description of temporal issue type.
        examples: Examples of common temporal bugs in this category.
        default_severity: Default severity if issue is found.

    """

    id: str
    description: str
    examples: list[str]
    default_severity: Severity

    def __repr__(self) -> str:
        """Return a string representation of the temporal definition."""
        return f"TemporalDefinition(id={self.id!r}, description={self.description!r})"


# =============================================================================
# Category Definitions
# =============================================================================

TEMPORAL_CATEGORIES: dict[TemporalCategory, TemporalDefinition] = {
    TemporalCategory.TIMEOUT: TemporalDefinition(
        id="TMP-001",
        description="Timeout handling and cleanup issues",
        examples=[
            "Timeout values colliding or overlapping",
            "Missing timeout cancellation",
            "Timeout not propagated to child operations",
            "Context deadline exceeded not handled",
        ],
        default_severity=Severity.ERROR,
    ),
    TemporalCategory.ORDERING: TemporalDefinition(
        id="ORD-TMP-001",
        description="Event and message ordering issues",
        examples=[
            "Assuming message delivery order",
            "Out-of-order event processing",
            "Missing sequence number validation",
            "Concurrent writes without ordering guarantee",
        ],
        default_severity=Severity.ERROR,
    ),
    TemporalCategory.CLOCK: TemporalDefinition(
        id="CLK-001",
        description="Clock and time-related assumptions",
        examples=[
            "Clock skew between systems",
            "Assuming monotonic system clock",
            "Using wall clock for timeouts",
            "Time zone handling issues",
        ],
        default_severity=Severity.WARNING,
    ),
    TemporalCategory.EXPIRATION: TemporalDefinition(
        id="EXP-001",
        description="TTL and expiration handling",
        examples=[
            "Stale data not detected",
            "TTL not respected",
            "Lease renewal race conditions",
            "Cache expiration inconsistencies",
        ],
        default_severity=Severity.ERROR,
    ),
    TemporalCategory.RACE_WINDOW: TemporalDefinition(
        id="RCW-001",
        description="Time-of-check to time-of-use race conditions",
        examples=[
            "Check-then-act patterns without locking",
            "Validation followed by use with gap",
            "State check before operation",
        ],
        default_severity=Severity.ERROR,
    ),
}


def get_category_definitions() -> list[TemporalDefinition]:
    """Get all temporal category definitions.

    Returns a list of all category definitions including their IDs,
    descriptions, examples, and default severity levels. Useful for
    documentation and UI display of available temporal categories.

    Returns:
        List of TemporalDefinition for all 5 categories:
        TIMEOUT, ORDERING, CLOCK, EXPIRATION, RACE_WINDOW.

    """
    return list(TEMPORAL_CATEGORIES.values())


# =============================================================================
# Impact Mapping Functions
# =============================================================================


def impact_to_severity(impact: ImpactLevel) -> Severity:
    """Map impact level to finding severity.

    Args:
        impact: The assessed impact level.

    Returns:
        Corresponding severity for the finding.

    """
    mapping = {
        ImpactLevel.HIGH: Severity.ERROR,
        ImpactLevel.MEDIUM: Severity.WARNING,
        ImpactLevel.LOW: Severity.INFO,
    }
    return mapping.get(impact, Severity.WARNING)


def impact_to_confidence(impact: ImpactLevel) -> float:
    """Map impact level to evidence confidence score.

    Args:
        impact: The assessed impact level.

    Returns:
        Confidence score 0.0-1.0 based on impact:
        - HIGH impact -> 0.85 confidence
        - MEDIUM impact -> 0.65 confidence
        - LOW impact -> 0.45 confidence

    """
    mapping = {
        ImpactLevel.HIGH: 0.85,
        ImpactLevel.MEDIUM: 0.65,
        ImpactLevel.LOW: 0.45,
    }
    return mapping.get(impact, 0.5)


def _is_critical_issue(issue_data: TemporalIssueData) -> bool:
    """Determine if temporal issue should be CRITICAL severity.

    Critical issues include data loss, message loss, corruption potential.

    Args:
        issue_data: The temporal issue data from LLM.

    Returns:
        True if issue should be CRITICAL severity.

    """
    try:
        # ImpactLevel values are lowercase: "high", "medium", "low"
        impact = ImpactLevel(issue_data.impact.lower())
    except ValueError:
        return False

    if impact != ImpactLevel.HIGH:
        return False

    # High-impact issues in these categories are critical
    critical_categories = {
        TemporalCategory.RACE_WINDOW,
        TemporalCategory.EXPIRATION,
    }

    try:
        category = TemporalCategory(issue_data.category.lower())
        if category in critical_categories:
            return True
    except ValueError:
        pass

    # Check for critical keywords in issue description
    critical_keywords = [
        "data loss",
        "message loss",
        "corruption",
        "inconsistent state",
        "duplicate processing",
        "lost message",
        "stale data used",
    ]
    issue_lower = issue_data.issue.lower()
    return any(keyword in issue_lower for keyword in critical_keywords)


# =============================================================================
# System Prompt
# =============================================================================

TEMPORAL_CONSISTENCY_SYSTEM_PROMPT = """You are an expert in temporal consistency and time-related bugs in software systems.

Your task is to analyze the provided code/implementation artifact and identify temporal consistency issues that could lead to:
- Data corruption or inconsistency
- Message loss or duplication
- Race conditions due to timing
- Clock-related bugs

Temporal categories to analyze:
1. TIMEOUT: Timeout handling, cancellation, cleanup issues, timeout collisions
2. ORDERING: Event/message ordering assumptions, out-of-order processing
3. CLOCK: Clock skew, monotonic time assumptions, wall clock vs monotonic clock
4. EXPIRATION: TTL handling, lease management, stale data detection
5. RACE_WINDOW: TOCTOU (time-of-check to time-of-use) race conditions

For each temporal issue you identify:
- Describe the specific temporal issue
- Categorize it appropriately
- Assess impact (high/medium/low)
- Provide evidence from the code
- Explain consequences if issue manifests
- Recommend how to fix it

Focus on issues that are:
- Realistic in production systems
- Could cause actual data/message loss or corruption
- Related to time, ordering, or synchronization

Respond with valid JSON only. If analysis fails, return empty JSON object `{}`."""


# =============================================================================
# Pydantic Models for LLM Response
# =============================================================================


class TemporalIssueData(BaseModel):
    """Single temporal issue from LLM response."""

    issue: str = Field(..., min_length=5)
    category: str = Field(...)
    impact: str = Field(...)
    evidence_quote: str = Field(..., min_length=1)
    line_number: int | None = Field(default=None)
    consequences: str = Field(default="")
    recommendation: str = Field(default="")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Validate category is one of allowed values."""
        allowed = {"timeout", "ordering", "clock", "expiration", "race_window"}
        v_lower = v.lower()
        if v_lower not in allowed:
            raise ValueError(f"Invalid category: {v}. Must be one of: {allowed}")
        return v_lower

    @field_validator("impact")
    @classmethod
    def validate_impact(cls, v: str) -> str:
        """Validate impact is one of allowed values."""
        allowed = {"high", "medium", "low"}
        v_lower = v.lower()
        if v_lower not in allowed:
            raise ValueError(f"Invalid impact: {v}. Must be one of: {allowed}")
        return v_lower


class TemporalAnalysisResponse(BaseModel):
    """Expected LLM response structure for temporal analysis."""

    temporal_issues: list[TemporalIssueData] = Field(default_factory=list)


# =============================================================================
# Temporal Consistency Method
# =============================================================================


class TemporalConsistencyMethod(BaseVerificationMethod):
    """Temporal Consistency Method (#157) - Time-related bug detection.

    This method analyzes artifact text to identify temporal logic issues that
    could lead to data corruption, message loss, or system instability.

    Method #157 runs conditionally when MESSAGING or STORAGE domains are detected,
    unlike the always-run methods (#153 Pattern Match and #154 Boundary Analysis).

    Attributes:
        method_id: Unique method identifier "#157".
        _provider: ClaudeSDKProvider for LLM calls.
        _model: Model identifier for LLM calls.
        _threshold: Minimum confidence threshold for findings (0.0-1.0).
        _timeout: Timeout in seconds for LLM calls.
        _categories: Optional list of categories to limit analysis.

    Example:
        >>> method = TemporalConsistencyMethod()
        >>> findings = await method.analyze(
        ...     "code with timeout collision",
        ...     domains=[ArtifactDomain.MESSAGING]
        ... )
        >>> for f in findings:
        ...     print(f"{f.id}: {f.title}")

    """

    method_id: MethodId = MethodId("#157")

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        timeout: int = DEFAULT_TIMEOUT,
        categories: list[TemporalCategory] | None = None,
        llm_client: Any | None = None,
    ) -> None:
        """Initialize the Temporal Consistency Method.

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
        self._categories = categories or list(TemporalCategory)

    def __repr__(self) -> str:
        """Return a string representation of the method."""
        return (
            f"TemporalConsistencyMethod("
            f"method_id={self.method_id!r}, model='{self._model}', threshold={self._threshold}"
            f")"
        )

    async def analyze(
        self,
        artifact_text: str,
        **kwargs: Any,
    ) -> list[Finding]:
        """Analyze artifact for temporal consistency issues.

        Args:
            artifact_text: The text content to analyze for temporal issues.
            **kwargs: Additional context including:
                - domains: Optional list[ArtifactDomain] to determine if method should run
                - config: Optional DeepVerifyConfig (not used currently)

        Returns:
            List of Finding objects for identified temporal issues with
            confidence >= threshold. Findings have temporary IDs "#157-F1",
            "#157-F2", etc. which will be reassigned by DeepVerifyEngine.
            Returns empty list if MESSAGING or STORAGE domain is not detected.

        """
        if not artifact_text or not artifact_text.strip():
            logger.debug("Empty artifact text, returning no findings")
            return []

        # Extract domains from kwargs
        domains = kwargs.get("domains")

        # Check if method should run for detected domains
        if not self._should_run_for_domains(domains):
            logger.debug(
                "Temporal consistency skipped: no MESSAGING or STORAGE domain detected (domains=%s)",
                domains,
            )
            return []

        try:
            logger.debug(
                "Running temporal consistency analysis (domains=%s, categories=%s)",
                domains,
                [c.value for c in self._categories],
            )

            # Run sync LLM call in thread pool to avoid blocking
            result = await asyncio.to_thread(self._analyze_temporal_issues_sync, artifact_text)

            # Convert results to findings with filtering by threshold
            findings: list[Finding] = []
            finding_idx = 0

            for issue_data in result.temporal_issues:
                confidence = impact_to_confidence(ImpactLevel(issue_data.impact))
                if confidence >= self._threshold:
                    finding_idx += 1
                    findings.append(
                        self._create_finding_from_issue(issue_data, finding_idx, domains or [])
                    )

            logger.debug(
                "Temporal consistency found %d issues (threshold=%.2f)",
                len(findings),
                self._threshold,
            )

            return findings

        except (ProviderError, ProviderTimeoutError) as e:
            logger.warning("Temporal consistency analysis failed: %s", e)
            return []
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Temporal consistency analysis failed - parse error: %s", e)
            return []

    def _should_run_for_domains(self, domains: list[ArtifactDomain] | None) -> bool:
        """Check if method should run for detected domains.

        Method #157 runs only when MESSAGING or STORAGE domain is detected.

        Args:
            domains: List of detected domains (may be None).

        Returns:
            True if MESSAGING or STORAGE is in the domains list, False otherwise.

        """
        if not domains:
            return False

        return ArtifactDomain.MESSAGING in domains or ArtifactDomain.STORAGE in domains

    def _analyze_temporal_issues_sync(self, artifact_text: str) -> TemporalAnalysisResponse:
        """Analyze artifact for temporal issues using LLM (synchronous).

        Uses LLMClient if available, otherwise falls back to direct provider.

        Args:
            artifact_text: The text to analyze.

        Returns:
            TemporalAnalysisResponse with identified temporal issues.

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
        """Build the prompt for LLM temporal analysis.

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
            definition = TEMPORAL_CATEGORIES[cat]
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
                f"to {MAX_ARTIFACT_LENGTH} characters. Temporal issues beyond this point "
                f"will NOT be detected.\n\n"
            )

        return (
            f"{TEMPORAL_CONSISTENCY_SYSTEM_PROMPT}\n\n"
            f"Artifact to analyze (truncated to {MAX_ARTIFACT_LENGTH} chars):{truncation_notice}\n"
            f"```\n{truncated}\n```\n\n"
            f"Categories to analyze:\n"
            f"{categories_str}\n\n"
            f"Identify all temporal consistency issues in the artifact. "
            f"For each issue, provide:\n"
            f"- issue: Description of the temporal issue\n"
            f"- category: One of [timeout, ordering, clock, expiration, race_window]\n"
            f"- impact: One of [high, medium, low]\n"
            f"- evidence_quote: Code snippet showing where issue exists\n"
            f"- line_number: Line number (if identifiable)\n"
            f"- consequences: What happens if issue manifests\n"
            f"- recommendation: How to fix or mitigate the issue\n\n"
            f"Respond with JSON in this format:\n"
            f"{{\n"
            f'    "temporal_issues": [\n'
            f"        {{\n"
            f'            "issue": "Description...",\n'
            f'            "category": "timeout",\n'
            f'            "impact": "high",\n'
            f'            "evidence_quote": "code snippet",\n'
            f'            "line_number": 42,\n'
            f'            "consequences": "If this happens...",\n'
            f'            "recommendation": "Use monotonic clock instead..."\n'
            f"        }}\n"
            f"    ]\n"
            f"}}"
        )

    def _parse_response(self, raw_response: str) -> TemporalAnalysisResponse:
        """Parse LLM response with robust JSON extraction.

        Handles:
        - JSON inside markdown code blocks (```json...```)
        - Raw JSON objects
        - Nested braces by tracking depth

        Args:
            raw_response: Raw text response from LLM.

        Returns:
            Parsed TemporalAnalysisResponse.

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
                # Try to find the "temporal_issues" array directly
                match = re.search(r'"temporal_issues"\s*:\s*(\[.*?\])', raw_response, re.DOTALL)
                if match:
                    json_str = '{"temporal_issues": ' + match.group(1) + "}"
                else:
                    raise ValueError("No JSON found in response")

        # Parse with Pydantic validation
        data = json.loads(json_str)
        return TemporalAnalysisResponse(**data)

    def _create_finding_from_issue(
        self,
        issue_data: TemporalIssueData,
        index: int,
        detected_domains: list[ArtifactDomain],
    ) -> Finding:
        """Convert temporal analysis data to Finding.

        Args:
            issue_data: The temporal issue data from LLM response.
            index: The index for generating finding ID.
            detected_domains: List of domains detected in the artifact.

        Returns:
            Finding object with all relevant details.

        """
        finding_id = f"#157-F{index + 1}"

        # Map impact to severity and confidence
        impact = ImpactLevel(issue_data.impact)

        # Check for CRITICAL severity
        is_critical = _is_critical_issue(issue_data)
        if is_critical:
            severity = Severity.CRITICAL
        else:
            severity = impact_to_severity(impact)
        confidence = impact_to_confidence(impact)

        # Build title from issue description
        title = issue_data.issue
        if len(title) > 80:
            title = title[:77] + "..."

        # Build comprehensive description
        description_parts = [
            f"Temporal issue: {issue_data.issue}",
            "",
            f"Category: {issue_data.category}",
            f"Impact: {issue_data.impact}",
        ]

        if issue_data.consequences:
            description_parts.extend(
                [
                    "",
                    f"Consequences: {issue_data.consequences}",
                ]
            )

        if issue_data.recommendation:
            description_parts.extend(
                [
                    "",
                    f"Recommendation: {issue_data.recommendation}",
                ]
            )

        description = "\n".join(description_parts)

        # Create evidence
        evidence = []
        if issue_data.evidence_quote and issue_data.evidence_quote.strip():
            evidence.append(
                Evidence(
                    quote=issue_data.evidence_quote,
                    line_number=issue_data.line_number,
                    source="#157",
                    confidence=confidence,
                )
            )

        # Determine pattern_id from category
        try:
            category_enum = TemporalCategory(issue_data.category.lower())
            pattern_id = PatternId(TEMPORAL_CATEGORIES[category_enum].id)
        except (ValueError, KeyError):
            pattern_id = None

        # Determine domain based on category and detected domains
        domain = self._assign_domain_for_category(issue_data.category, detected_domains)

        return Finding(
            id=finding_id,
            severity=severity,
            title=title,
            description=description,
            method_id=MethodId("#157"),
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
            category: The temporal category.
            detected_domains: List of domains detected in the artifact.

        Returns:
            ArtifactDomain for the finding, or None if cannot be determined.

        """
        category_lower = category.lower()

        # TIMEOUT, ORDERING → MESSAGING (with STORAGE fallback)
        if category_lower in ("timeout", "ordering"):
            if ArtifactDomain.MESSAGING in detected_domains:
                return ArtifactDomain.MESSAGING
            if ArtifactDomain.STORAGE in detected_domains:
                return ArtifactDomain.STORAGE

        # CLOCK, EXPIRATION, RACE_WINDOW → STORAGE (with MESSAGING fallback)
        if category_lower in ("clock", "expiration", "race_window"):
            if ArtifactDomain.STORAGE in detected_domains:
                return ArtifactDomain.STORAGE
            if ArtifactDomain.MESSAGING in detected_domains:
                return ArtifactDomain.MESSAGING

        # Default: first detected domain
        if detected_domains:
            return detected_domains[0]

        return None
