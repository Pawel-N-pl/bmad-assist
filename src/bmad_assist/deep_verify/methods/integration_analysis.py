"""Integration Analysis Method (#204) for Deep Verify.

This module implements the Integration Analysis verification method that analyzes
external system interactions and identifies integration vulnerabilities like missing
error handling, contract violations, and idempotency gaps. Method #204 runs
conditionally when API or MESSAGING domains are detected.

The method focuses on:
- API contract validation (request/response schemas, breaking changes)
- External service failure handling (down, slow, errors)
- API versioning compatibility
- Idempotency guarantees for external calls
- Retry and circuit breaker behavior
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
    "IntegrationAnalysisMethod",
    "IntegrationCategory",
    "IntegrationDefinition",
    "IntegrationRiskLevel",
    "IntegrationIssueData",
    "IntegrationAnalysisResponse",
    "INTEGRATION_ANALYSIS_SYSTEM_PROMPT",
    "get_integration_category_definitions",
    "risk_to_severity",
    "risk_to_confidence",
]

# =============================================================================
# Constants
# =============================================================================

MAX_ARTIFACT_LENGTH = 4000

# =============================================================================
# Enums
# =============================================================================


class IntegrationCategory(str, Enum):
    """Categories of integration analysis issues.

    Each category represents a different type of integration vulnerability
    that can occur when interacting with external systems.
    """

    CONTRACT = "contract"  # API contract validation issues
    FAILURE_MODES = "failure_modes"  # External service failure handling
    VERSIONING = "versioning"  # API versioning compatibility
    IDEMPOTENCY = "idempotency"  # Idempotency guarantees
    RETRY = "retry"  # Retry and circuit breaker behavior


class IntegrationRiskLevel(str, Enum):
    """Risk levels for integration issues.

    Indicates the severity of consequences if the integration issue manifests.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass(frozen=True)
class IntegrationDefinition:
    """Definition of an integration category with metadata.

    Attributes:
        id: Category ID string (e.g., "INT-CTR-001", "INT-FLM-001").
        description: Description of integration issue type.
        examples: Examples of common issues in this category.
        default_severity: Default severity if issue is found.

    """

    id: str
    description: str
    examples: list[str]
    default_severity: Severity

    def __repr__(self) -> str:
        """Return a string representation of the integration definition."""
        return f"IntegrationDefinition(id={self.id!r}, description={self.description!r})"


# =============================================================================
# Category Definitions
# =============================================================================

INTEGRATION_CATEGORIES: dict[IntegrationCategory, IntegrationDefinition] = {
    IntegrationCategory.CONTRACT: IntegrationDefinition(
        id="INT-CTR-001",
        description="API contract validation and compatibility issues",
        examples=[
            "Missing request/response schema validation",
            "Breaking changes in API contract",
            "Required fields not validated",
            "Type mismatches in API calls",
        ],
        default_severity=Severity.ERROR,
    ),
    IntegrationCategory.FAILURE_MODES: IntegrationDefinition(
        id="INT-FLM-001",
        description="External service failure handling",
        examples=[
            "No timeout configured for external calls",
            "Missing error handling for 5xx responses",
            "No fallback when service is unavailable",
            "Silent failures on connection errors",
        ],
        default_severity=Severity.ERROR,
    ),
    IntegrationCategory.VERSIONING: IntegrationDefinition(
        id="INT-VER-001",
        description="API versioning compatibility issues",
        examples=[
            "Hardcoded API version in URL",
            "No version negotiation",
            "Breaking changes not handled",
            "Deprecated API version used",
        ],
        default_severity=Severity.WARNING,
    ),
    IntegrationCategory.IDEMPOTENCY: IntegrationDefinition(
        id="INT-IDM-001",
        description="Idempotency guarantees for external calls",
        examples=[
            "Non-idempotent POST without key",
            "Duplicate requests processed multiple times",
            "No deduplication mechanism",
            "Retry without idempotency guarantee",
        ],
        default_severity=Severity.CRITICAL,
    ),
    IntegrationCategory.RETRY: IntegrationDefinition(
        id="INT-RTY-001",
        description="Retry and circuit breaker behavior",
        examples=[
            "No retry for transient failures",
            "Fixed interval retry without backoff",
            "Missing circuit breaker",
            "Infinite retry loops",
        ],
        default_severity=Severity.ERROR,
    ),
}


def get_integration_category_definitions() -> list[IntegrationDefinition]:
    """Get all integration category definitions.

    Returns a list of all category definitions including their IDs,
    descriptions, examples, and default severity levels.

    Returns:
        List of IntegrationDefinition for all 5 categories:
        CONTRACT, FAILURE_MODES, VERSIONING, IDEMPOTENCY, RETRY.

    """
    return list(INTEGRATION_CATEGORIES.values())


# =============================================================================
# Risk Mapping Functions
# =============================================================================


def risk_to_severity(risk: IntegrationRiskLevel) -> Severity:
    """Map risk level to finding severity.

    Args:
        risk: The assessed risk level.

    Returns:
        Corresponding severity for the finding.

    """
    mapping = {
        IntegrationRiskLevel.CRITICAL: Severity.CRITICAL,
        IntegrationRiskLevel.HIGH: Severity.ERROR,
        IntegrationRiskLevel.MEDIUM: Severity.WARNING,
        IntegrationRiskLevel.LOW: Severity.INFO,
    }
    return mapping.get(risk, Severity.WARNING)


def risk_to_confidence(risk: IntegrationRiskLevel) -> float:
    """Map risk level to evidence confidence score.

    Args:
        risk: The assessed risk level.

    Returns:
        Confidence score 0.0-1.0 based on risk:
        - CRITICAL risk -> 0.95 confidence
        - HIGH risk -> 0.85 confidence
        - MEDIUM risk -> 0.65 confidence
        - LOW risk -> 0.45 confidence

    """
    mapping = {
        IntegrationRiskLevel.CRITICAL: 0.95,
        IntegrationRiskLevel.HIGH: 0.85,
        IntegrationRiskLevel.MEDIUM: 0.65,
        IntegrationRiskLevel.LOW: 0.45,
    }
    return mapping.get(risk, 0.5)


def _is_critical_issue(category: str, issue: str) -> bool:
    """Determine if issue should be CRITICAL severity.

    Critical issues include data loss, duplicate processing, inconsistent state,
    unbounded growth, infinite loops, no fallback, cascade failures.

    Args:
        category: The integration category.
        issue: The issue description.

    Returns:
        True if issue should be CRITICAL severity.

    """
    issue_lower = issue.lower()

    # Critical keywords
    critical_keywords = [
        "data loss",
        "duplicate processing",
        "inconsistent state",
        "unbounded",
        "infinite loop",
        "no fallback",
        "cascade failure",
    ]

    for keyword in critical_keywords:
        if keyword in issue_lower:
            return True

    # IDEMPOTENCY category with specific patterns
    cat_lower = category.lower()
    if cat_lower == "idempotency":
        idempotency_critical = ["duplicate", "multiple times", "without key"]
        for kw in idempotency_critical:
            if kw in issue_lower:
                return True

    return False


# =============================================================================
# System Prompt
# =============================================================================

INTEGRATION_ANALYSIS_SYSTEM_PROMPT = """You are an integration expert specializing in external system interactions.

Your task is to analyze the provided code/implementation artifact and identify integration issues related to external system interactions.

Integration categories to analyze:
1. CONTRACT: API contract validation (request/response schemas, breaking changes, required fields)
   Example: Accessing response.json()["id"] without validating the field exists
   Example: Changing required field types without versioning

2. FAILURE_MODES: External service failure handling (timeouts, errors, unavailability, fallbacks)
   Example: requests.post(url, json=data) with no timeout parameter
   Example: No try/except around external API calls

3. VERSIONING: API versioning compatibility (version negotiation, breaking changes, deprecation)
   Example: Hardcoded API version in URL path instead of header negotiation
   Example: Using deprecated API v1 when v2 is available

4. IDEMPOTENCY: Idempotency guarantees (duplicate requests, keys, deduplication)
   Example: POST request for payment without Idempotency-Key header
   Example: Processing duplicate webhook events multiple times

5. RETRY: Retry and circuit breaker behavior (backoff, circuit breakers, retry limits)
   Example: Immediate retry on failure without exponential backoff
   Example: No circuit breaker for cascading failure scenarios

For each integration issue you identify:
- Describe the specific issue
- Categorize it appropriately
- Assess risk level (CRITICAL/HIGH/MEDIUM/LOW)
- Provide evidence from the code
- Explain consequences if issue manifests
- Recommend how to fix it

Focus on issues that:
- Could cause production incidents
- Affect system reliability or data consistency
- Are commonly missed in code reviews
- Have clear, actionable fixes

Respond with valid JSON only. If no issues found, return empty JSON object `{}`."""


# =============================================================================
# Pydantic Models for LLM Response
# =============================================================================


class IntegrationIssueData(BaseModel):
    """Pydantic model for individual integration issue in LLM response."""

    issue: str = Field(..., min_length=1, description="Description of the issue")
    category: str = Field(..., min_length=1, description="Integration category")
    risk: str = Field(..., min_length=1, description="Risk level assessment")
    evidence_quote: str = Field(..., min_length=1, description="Code snippet showing issue")
    line_number: int | None = Field(None, description="Line number if identifiable")
    consequences: str = Field(..., min_length=1, description="Consequences if issue manifests")
    recommendation: str = Field(..., min_length=1, description="How to fix the issue")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Validate category is one of allowed values."""
        try:
            # Use enum for strict validation (case-sensitive)
            return IntegrationCategory(v).value
        except ValueError as e:
            allowed_values = [cat.value for cat in IntegrationCategory]
            raise ValueError(f"category must be one of {allowed_values}, got {v}") from e

    @field_validator("risk")
    @classmethod
    def validate_risk(cls, v: str) -> str:
        """Validate risk is one of allowed values."""
        try:
            # Use enum for strict validation (case-sensitive)
            return IntegrationRiskLevel(v).value
        except ValueError as e:
            allowed_values = [risk.value for risk in IntegrationRiskLevel]
            raise ValueError(f"risk must be one of {allowed_values}, got {v}") from e

    @field_validator("line_number")
    @classmethod
    def validate_line_number(cls, v: int | None) -> int | None:
        """Validate line number is positive if provided."""
        if v is not None and v < 1:
            raise ValueError(f"line_number must be >= 1, got {v}")
        return v


class IntegrationAnalysisResponse(BaseModel):
    """Pydantic model for full integration analysis response."""

    integration_issues: list[IntegrationIssueData] = Field(
        default_factory=list, description="List of identified integration issues"
    )


# =============================================================================
# Integration Analysis Method
# =============================================================================


class IntegrationAnalysisMethod(BaseVerificationMethod):
    """Integration Analysis Method (#204) - External system interaction verification.

    This method analyzes artifact text to identify integration vulnerabilities
    like missing error handling, contract violations, and idempotency gaps.

    Method #204 runs conditionally when API or MESSAGING domains are detected,
    unlike the always-run methods (#153 Pattern Match and #154 Boundary Analysis).

    Attributes:
        method_id: Unique method identifier "#204".
        _provider: ClaudeSDKProvider for LLM calls.
        _model: Model identifier for LLM calls.
        _threshold: Minimum confidence threshold for findings (0.0-1.0).
        _timeout: Timeout in seconds for LLM calls.
        _categories: Optional list of categories to limit analysis.

    Example:
        >>> method = IntegrationAnalysisMethod()
        >>> findings = await method.analyze(
        ...     "code with API integration",
        ...     domains=[ArtifactDomain.API]
        ... )
        >>> for f in findings:
        ...     print(f"{f.id}: {f.title}")

    """

    method_id: MethodId = MethodId("#204")

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        timeout: int = DEFAULT_TIMEOUT,
        categories: list[IntegrationCategory] | None = None,
        llm_client: Any | None = None,
    ) -> None:
        """Initialize the Integration Analysis Method.

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
        self._categories = categories or list(IntegrationCategory)

    def __repr__(self) -> str:
        """Return a string representation of the method."""
        return (
            f"IntegrationAnalysisMethod("
            f"method_id={self.method_id!r}, model='{self._model}', threshold={self._threshold}"
            f")"
        )

    async def analyze(
        self,
        artifact_text: str,
        **kwargs: Any,
    ) -> list[Finding]:
        """Analyze artifact for integration issues.

        Args:
            artifact_text: The text content to analyze for integration issues.
            **kwargs: Additional context including:
                - domains: Optional list[ArtifactDomain] to determine if method should run
                - config: Optional DeepVerifyConfig (not used currently)

        Returns:
            List of Finding objects for identified issues with
            confidence >= threshold. Findings have temporary IDs "#204-F1",
            "#204-F2", etc. which will be reassigned by DeepVerifyEngine.
            Returns empty list if API or MESSAGING domain is not detected.

        """
        if not artifact_text or not artifact_text.strip():
            logger.debug("Empty artifact text, returning no findings")
            return []

        # Extract domains from kwargs
        domains = kwargs.get("domains")

        # Check if method should run for detected domains
        if not self._should_run_for_domains(domains):
            logger.debug(
                "Integration analysis skipped: no API or MESSAGING domain detected (domains=%s)",
                domains,
            )
            return []

        try:
            logger.debug(
                "Running integration analysis (domains=%s, categories=%s)",
                domains,
                [c.value for c in self._categories],
            )

            # Run sync LLM call in thread pool to avoid blocking
            result = await asyncio.to_thread(self._analyze_integration_issues_sync, artifact_text)

            # Convert results to findings with filtering by threshold
            findings: list[Finding] = []
            finding_idx = 0

            for issue_data in result.integration_issues:
                # Check for critical override BEFORE filtering to ensure
                # critical issues are not dropped due to low initial confidence
                is_critical = _is_critical_issue(issue_data.category, issue_data.issue)
                if is_critical:
                    confidence = 0.95  # Critical issues get max confidence
                else:
                    confidence = risk_to_confidence(IntegrationRiskLevel(issue_data.risk))

                if confidence >= self._threshold:
                    findings.append(
                        self._create_finding_from_issue(
                            issue_data, finding_idx, domains or [], is_critical=is_critical
                        )
                    )
                    finding_idx += 1

            logger.debug(
                "Integration analysis found %d issues (threshold=%.2f)",
                len(findings),
                self._threshold,
            )

            return findings

        except (ProviderError, ProviderTimeoutError) as e:
            logger.warning("Integration analysis failed: %s", e)
            return []
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            logger.warning("Integration analysis failed - parse error: %s", e)
            return []

    def _should_run_for_domains(self, domains: list[ArtifactDomain] | None) -> bool:
        """Check if method should run for detected domains.

        Method #204 runs only when API or MESSAGING domain is detected.

        Args:
            domains: List of detected domains (may be None).

        Returns:
            True if API or MESSAGING is in the domains list, False otherwise.

        """
        if not domains:
            return False

        return ArtifactDomain.API in domains or ArtifactDomain.MESSAGING in domains

    def _analyze_integration_issues_sync(self, artifact_text: str) -> IntegrationAnalysisResponse:
        """Analyze artifact for integration issues using LLM (synchronous).

        Uses LLMClient if available, otherwise falls back to direct provider.

        Args:
            artifact_text: The text to analyze.

        Returns:
            IntegrationAnalysisResponse with identified issues.

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
        """Build the prompt for LLM integration analysis.

        Args:
            artifact_text: The text to analyze.

        Returns:
            Formatted prompt string.

        """
        was_truncated = len(artifact_text) > MAX_ARTIFACT_LENGTH
        truncated = artifact_text[:MAX_ARTIFACT_LENGTH]

        # Build category descriptions
        category_descriptions = []
        for cat in self._categories:
            definition = INTEGRATION_CATEGORIES[cat]
            category_descriptions.append(f"- {cat.value.upper()}: {definition.description}")
            # Add examples for clarity (limit to 2 per category)
            for example in definition.examples[:2]:
                category_descriptions.append(f"    Example: {example}")

        categories_str = "\n".join(category_descriptions)

        # Add truncation warning if content was truncated
        truncation_notice = ""
        if was_truncated:
            truncation_notice = (
                f"\n⚠️ IMPORTANT: Artifact was truncated from {len(artifact_text)} "
                f"to {MAX_ARTIFACT_LENGTH} characters. Issues beyond this point "
                f"will NOT be detected.\n\n"
            )

        return (
            f"{INTEGRATION_ANALYSIS_SYSTEM_PROMPT}\n\n"
            f"Artifact to analyze (truncated to {MAX_ARTIFACT_LENGTH} chars):{truncation_notice}\n"
            f"```\n{truncated}\n```\n\n"
            f"Categories to analyze:\n"
            f"{categories_str}\n\n"
            f"Identify all integration issues in the artifact. "
            f"For each issue, provide:\n"
            f"- issue: Description of the integration issue\n"
            f"- category: One of [contract, failure_modes, versioning, idempotency, retry]\n"
            f"- risk: One of [critical, high, medium, low]\n"
            f"- evidence_quote: Code snippet showing where issue exists\n"
            f"- line_number: Line number (if identifiable)\n"
            f"- consequences: What happens if issue manifests\n"
            f"- recommendation: How to fix the issue\n\n"
            f"Respond with JSON in this format:\n"
            f"{{\n"
            f'    "integration_issues": [\n'
            f"        {{\n"
            f'            "issue": "Description...",\n'
            f'            "category": "contract",\n'
            f'            "risk": "high",\n'
            f'            "evidence_quote": "code snippet",\n'
            f'            "line_number": 42,\n'
            f'            "consequences": "If this happens...",\n'
            f'            "recommendation": "Add validation for..."\n'
            f"        }}\n"
            f"    ]\n"
            f"}}"
        )

    def _parse_response(self, raw_response: str) -> IntegrationAnalysisResponse:
        """Parse LLM response with robust JSON extraction.

        Handles:
        - JSON inside markdown code blocks (```json...```)
        - Raw JSON objects
        - Nested braces by tracking depth

        Args:
            raw_response: Raw text response from LLM.

        Returns:
            Parsed IntegrationAnalysisResponse.

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
                # Try to find the "integration_issues" array directly
                # Use greedy matching to handle nested arrays properly
                match = re.search(r'"integration_issues"\s*:\s*(\[.*\])', raw_response, re.DOTALL)
                if match:
                    json_str = '{"integration_issues": ' + match.group(1) + "}"
                else:
                    raise ValueError("No JSON found in response")

        # Parse with Pydantic validation
        data = json.loads(json_str)
        return IntegrationAnalysisResponse(**data)

    def _create_finding_from_issue(
        self,
        issue_data: IntegrationIssueData,
        index: int,
        detected_domains: list[ArtifactDomain],
        is_critical: bool = False,
    ) -> Finding:
        """Convert integration analysis data to Finding.

        Args:
            issue_data: The issue data from LLM response.
            index: The index for generating finding ID.
            detected_domains: List of domains detected in the artifact.

        Returns:
            Finding object with all relevant details.

        """
        finding_id = f"#204-F{index + 1}"

        # Map risk to severity and confidence
        risk = IntegrationRiskLevel(issue_data.risk)

        # Apply CRITICAL severity override (is_critical already computed in analyze())
        if is_critical:
            severity = Severity.CRITICAL
            confidence = 0.95
        else:
            severity = risk_to_severity(risk)
            confidence = risk_to_confidence(risk)

        # Build title from issue description
        title = issue_data.issue
        if len(title) > 80:
            title = title[:77] + "..."

        # Build comprehensive description
        description_parts = [
            f"Integration issue: {issue_data.issue}",
            "",
            f"Category: {issue_data.category}",
            f"Risk level: {issue_data.risk}",
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
                    source="#204",
                    confidence=confidence,
                )
            )

        # Determine pattern_id from category
        try:
            category_enum = IntegrationCategory(issue_data.category.lower())
            pattern_id = PatternId(INTEGRATION_CATEGORIES[category_enum].id)
        except (ValueError, KeyError):
            pattern_id = None

        # Determine domain based on category and detected domains
        domain = self._assign_domain_for_category(issue_data.category, detected_domains)

        return Finding(
            id=finding_id,
            severity=severity,
            title=title,
            description=description,
            method_id=MethodId("#204"),
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
            category: The integration category.
            detected_domains: List of domains detected in the artifact.

        Returns:
            ArtifactDomain for the finding, or None if cannot be determined.

        """
        cat_lower = category.lower()

        # CONTRACT, VERSIONING, IDEMPOTENCY → API (with MESSAGING fallback)
        if cat_lower in ("contract", "versioning", "idempotency"):
            if ArtifactDomain.API in detected_domains:
                return ArtifactDomain.API
            if ArtifactDomain.MESSAGING in detected_domains:
                return ArtifactDomain.MESSAGING

        # FAILURE_MODES, RETRY → MESSAGING (with API fallback)
        if cat_lower in ("failure_modes", "retry"):
            if ArtifactDomain.MESSAGING in detected_domains:
                return ArtifactDomain.MESSAGING
            if ArtifactDomain.API in detected_domains:
                return ArtifactDomain.API

        # Return None if no appropriate domain mapping found
        # Don't fallback to arbitrary domains like STORAGE
        return None
