"""Adversarial Review Method (#201) for Deep Verify.

This module implements the Adversarial Review verification method that systematically
challenges all claims and decisions in implementation artifacts. Method #201 runs
conditionally when SECURITY or API domains are detected.

The method identifies security vulnerabilities, bypass opportunities, and edge cases
through adversarial thinking from an attacker's perspective.
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
    "AdversarialCategory",
    "AdversarialDefinition",
    "AdversarialReviewMethod",
    "AdversarialReviewResponse",
    "AdversarialVulnerabilityData",
    "ADVERSARIAL_REVIEW_SYSTEM_PROMPT",
    "ThreatLevel",
    "get_category_definitions",
    "threat_to_confidence",
    "threat_to_severity",
]

# =============================================================================
# Constants
# =============================================================================

MAX_ARTIFACT_LENGTH = 4000

# =============================================================================
# Enums
# =============================================================================


class AdversarialCategory(str, Enum):
    """Categories of adversarial review issues.

    Each category represents a different type of vulnerability
    that can be found through adversarial thinking.
    """

    BYPASS = "bypass"  # Authentication/authorization bypass
    LOAD = "load"  # Behavior under extreme load
    ERROR_PATHS = "error_paths"  # Vulnerabilities in error handling
    EDGE_INPUTS = "edge_inputs"  # Malicious input handling


class ThreatLevel(str, Enum):
    """Threat levels for adversarial vulnerabilities.

    Indicates the severity of the security threat if exploited.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass(frozen=True)
class AdversarialDefinition:
    """Definition of an adversarial category with metadata.

    Attributes:
        id: Category ID string (e.g., "ADV-BYP-001", "ADV-LOD-001").
        description: Description of adversarial issue type.
        examples: Examples of common vulnerabilities in this category.
        default_severity: Default severity if vulnerability is found.

    """

    id: str
    description: str
    examples: list[str]
    default_severity: Severity

    def __repr__(self) -> str:
        """Return a string representation of the adversarial definition."""
        return f"AdversarialDefinition(id={self.id!r}, description={self.description!r})"


# =============================================================================
# Category Definitions
# =============================================================================

ADVERSARIAL_CATEGORIES: dict[AdversarialCategory, AdversarialDefinition] = {
    AdversarialCategory.BYPASS: AdversarialDefinition(
        id="ADV-BYP-001",
        description="Authentication and authorization bypass opportunities",
        examples=[
            "Route enumeration via status code differences",
            "IDOR (Insecure Direct Object Reference) vulnerabilities",
            "JWT validation bypass",
            "Privilege escalation paths",
        ],
        default_severity=Severity.CRITICAL,
    ),
    AdversarialCategory.LOAD: AdversarialDefinition(
        id="ADV-LOD-001",
        description="Behavior under extreme load or resource exhaustion",
        examples=[
            "DoS via unbounded resource consumption",
            "Race conditions under high concurrency",
            "Circuit breaker bypass opportunities",
            "Rate limiting circumvention",
        ],
        default_severity=Severity.ERROR,
    ),
    AdversarialCategory.ERROR_PATHS: AdversarialDefinition(
        id="ADV-ERR-001",
        description="Vulnerabilities in error handling paths",
        examples=[
            "Information leakage in error messages",
            "Exception handler bypass",
            "Error-based oracle attacks",
            "Stack trace exposure",
        ],
        default_severity=Severity.ERROR,
    ),
    AdversarialCategory.EDGE_INPUTS: AdversarialDefinition(
        id="ADV-EDG-001",
        description="Malicious input handling and injection vectors",
        examples=[
            "SQL injection through edge case inputs",
            "Command injection via shell metacharacters",
            "Path traversal with encoded sequences",
            "NoSQL injection in query parameters",
        ],
        default_severity=Severity.CRITICAL,
    ),
}


def get_category_definitions() -> list[AdversarialDefinition]:
    """Get all adversarial category definitions.

    Returns a list of all category definitions including their IDs,
    descriptions, examples, and default severity levels.

    Returns:
        List of AdversarialDefinition for all 4 categories:
        BYPASS, LOAD, ERROR_PATHS, EDGE_INPUTS.

    """
    return list(ADVERSARIAL_CATEGORIES.values())


# =============================================================================
# Threat Mapping Functions
# =============================================================================


def threat_to_severity(threat: ThreatLevel) -> Severity:
    """Map threat level to finding severity.

    Args:
        threat: The assessed threat level.

    Returns:
        Corresponding severity for the finding.

    """
    mapping = {
        ThreatLevel.CRITICAL: Severity.CRITICAL,
        ThreatLevel.HIGH: Severity.ERROR,
        ThreatLevel.MEDIUM: Severity.WARNING,
        ThreatLevel.LOW: Severity.INFO,
    }
    return mapping.get(threat, Severity.WARNING)


def threat_to_confidence(threat: ThreatLevel) -> float:
    """Map threat level to evidence confidence score.

    Args:
        threat: The assessed threat level.

    Returns:
        Confidence score 0.0-1.0 based on threat:
        - CRITICAL threat -> 0.95 confidence
        - HIGH threat -> 0.85 confidence
        - MEDIUM threat -> 0.65 confidence
        - LOW threat -> 0.45 confidence

    """
    mapping = {
        ThreatLevel.CRITICAL: 0.95,
        ThreatLevel.HIGH: 0.85,
        ThreatLevel.MEDIUM: 0.65,
        ThreatLevel.LOW: 0.45,
    }
    return mapping.get(threat, 0.5)


def _is_critical_threat(category: str, vulnerability: str) -> bool:
    """Determine if threat should be CRITICAL severity.

    Critical threats include authentication bypass, injection, privilege escalation.

    Args:
        category: The adversarial category.
        vulnerability: The vulnerability description.

    Returns:
        True if threat should be CRITICAL severity.

    """
    vuln_lower = vulnerability.lower()
    cat_lower = category.lower()

    # Critical keywords in vulnerability description
    # These are security-critical issues that warrant CRITICAL severity
    critical_keywords = [
        "authentication bypass",
        "authorization bypass",
        "auth bypass",
        "privilege escalation",
        "sql injection",
        "command injection",
        "remote code execution",
        "rce",
        "ssrf",
        "path traversal",
        "insecure direct object",
        "idor",
        "jwt bypass",
        "jwt validation bypass",
    ]

    for keyword in critical_keywords:
        # Use word boundary checking for short keywords to prevent substring matches
        # e.g., "rce" should not match inside "resour**rce** exhaustion"
        if len(keyword) <= 4:
            # For short keywords, ensure they appear as whole words
            pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, vuln_lower):
                return True
        else:
            if keyword in vuln_lower:
                return True

    # Also check for standalone dangerous keywords (with word boundaries)
    # These indicate serious issues when they appear standalone
    standalone_critical = ["data race", "deadlock", "corruption"]
    for term in standalone_critical:
        if term in vuln_lower:
            return True

    # Check category-specific critical patterns
    if cat_lower == "bypass":
        bypass_critical = ["bypass", "circumvent", "evade"]
        for kw in bypass_critical:
            if kw in vuln_lower and ("auth" in vuln_lower or "access" in vuln_lower):
                return True
        # Also check for jwt/validation bypass specifically
        if "jwt" in vuln_lower and "bypass" in vuln_lower:
            return True

    if cat_lower == "edge_inputs":
        injection_patterns = ["injection", "arbitrary", "execute"]
        for kw in injection_patterns:
            if kw in vuln_lower:
                return True

    # LOAD and ERROR_PATHS categories don't have critical patterns
    # (resource exhaustion without other dangerous keywords is not critical)

    return False


# =============================================================================
# System Prompt
# =============================================================================

ADVERSARIAL_REVIEW_SYSTEM_PROMPT = """You are an expert security researcher and red team operator.

Your task is to analyze the provided code/implementation artifact from an ATTACKER'S perspective. Think adversarially - how would you break this?

Adversarial categories to analyze:
1. BYPASS: Authentication/authorization bypass opportunities (JWT bypass, IDOR, privilege escalation, route enumeration)
2. LOAD: Behavior under extreme load or resource exhaustion (DoS vectors, race conditions, resource exhaustion)
3. ERROR_PATHS: Vulnerabilities in error handling paths (info leakage, exception bypass, error oracles)
4. EDGE_INPUTS: Malicious input handling (injection vectors, path traversal, encoding tricks)

For each vulnerability you identify:
- Describe the specific vulnerability
- Categorize it appropriately
- Assess threat level (critical/high/medium/low)
- Provide evidence from the code
- Explain the attack vector (how would you exploit this?)
- Recommend how to fix it

Think like an attacker:
- How can I bypass the security controls?
- What happens if I send unexpected input?
- Can I trigger errors that reveal sensitive information?
- What happens under extreme load or concurrent access?

Respond with valid JSON only. If no vulnerabilities found, return empty JSON object `{}`."""


# =============================================================================
# Pydantic Models for LLM Response
# =============================================================================


class AdversarialVulnerabilityData(BaseModel):
    """Pydantic model for individual vulnerability in LLM response."""

    vulnerability: str = Field(..., min_length=1, description="Description of the vulnerability")
    category: str = Field(..., min_length=1, description="Adversarial category")
    threat_level: str = Field(..., min_length=1, description="Threat level assessment")
    evidence_quote: str = Field(..., min_length=1, description="Code snippet showing vulnerability")
    line_number: int | None = Field(None, description="Line number if identifiable")
    attack_vector: str = Field(..., min_length=1, description="How attacker could exploit this")
    remediation: str = Field(..., min_length=1, description="How to fix or mitigate")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Validate category is one of allowed values."""
        allowed = {"bypass", "load", "error_paths", "edge_inputs"}
        v_lower = v.lower()
        if v_lower not in allowed:
            raise ValueError(f"category must be one of {allowed}, got {v}")
        return v_lower

    @field_validator("threat_level")
    @classmethod
    def validate_threat_level(cls, v: str) -> str:
        """Validate threat_level is one of allowed values."""
        allowed = {"critical", "high", "medium", "low"}
        v_lower = v.lower()
        if v_lower not in allowed:
            raise ValueError(f"threat_level must be one of {allowed}, got {v}")
        return v_lower


class AdversarialReviewResponse(BaseModel):
    """Pydantic model for full adversarial review response."""

    vulnerabilities: list[AdversarialVulnerabilityData] = Field(
        default_factory=list, description="List of identified vulnerabilities"
    )


# =============================================================================
# Adversarial Review Method
# =============================================================================


class AdversarialReviewMethod(BaseVerificationMethod):
    """Adversarial Review Method (#201) - Security vulnerability detection.

    This method analyzes artifact text to identify security vulnerabilities,
    bypass opportunities, and edge cases through adversarial thinking.

    Method #201 runs conditionally when SECURITY or API domains are detected,
    unlike the always-run methods (#153 Pattern Match and #154 Boundary Analysis).

    Attributes:
        method_id: Unique method identifier "#201".
        _provider: ClaudeSDKProvider for LLM calls.
        _model: Model identifier for LLM calls.
        _threshold: Minimum confidence threshold for findings (0.0-1.0).
        _timeout: Timeout in seconds for LLM calls.
        _categories: Optional list of categories to limit analysis.

    Example:
        >>> method = AdversarialReviewMethod()
        >>> findings = await method.analyze(
        ...     "code with auth bypass vulnerability",
        ...     domains=[ArtifactDomain.SECURITY]
        ... )
        >>> for f in findings:
        ...     print(f"{f.id}: {f.title}")

    """

    method_id: MethodId = MethodId("#201")

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        timeout: int = DEFAULT_TIMEOUT,
        categories: list[AdversarialCategory] | None = None,
        llm_client: Any | None = None,
    ) -> None:
        """Initialize the Adversarial Review Method.

        Args:
            model: Model identifier for LLM calls (default: "haiku").
            threshold: Minimum confidence threshold for findings (default: 0.6).
            timeout: Timeout in seconds for LLM calls (default: 30).
            categories: Optional list of categories to limit analysis.
                       If None, analyzes all categories.
            llm_client: Optional LLMClient for managed LLM calls. If provided,
                       uses LLMClient for all LLM calls (with retry, rate limiting,
                       cost tracking). If not provided, uses direct provider.

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
        self._categories = categories or list(AdversarialCategory)

    def __repr__(self) -> str:
        """Return a string representation of the method."""
        return (
            f"AdversarialReviewMethod("
            f"method_id={self.method_id!r}, model='{self._model}', threshold={self._threshold}"
            f")"
        )

    async def analyze(
        self,
        artifact_text: str,
        **kwargs: Any,
    ) -> list[Finding]:
        """Analyze artifact for security vulnerabilities.

        Args:
            artifact_text: The text content to analyze for vulnerabilities.
            **kwargs: Additional context including:
                - domains: Optional list[ArtifactDomain] to determine if method should run
                - config: Optional DeepVerifyConfig (not used currently)

        Returns:
            List of Finding objects for identified vulnerabilities with
            confidence >= threshold. Findings have temporary IDs "#201-F1",
            "#201-F2", etc. which will be reassigned by DeepVerifyEngine.
            Returns empty list if SECURITY or API domain is not detected.

        """
        if not artifact_text or not artifact_text.strip():
            logger.debug("Empty artifact text, returning no findings")
            return []

        # Extract domains from kwargs
        domains = kwargs.get("domains")

        # Check if method should run for detected domains
        if not self._should_run_for_domains(domains):
            logger.debug(
                "Adversarial review skipped: no SECURITY or API domain detected (domains=%s)",
                domains,
            )
            return []

        try:
            logger.debug(
                "Running adversarial review analysis (domains=%s, categories=%s)",
                domains,
                [c.value for c in self._categories],
            )

            # Run sync LLM call in thread pool to avoid blocking
            result = await asyncio.to_thread(self._analyze_vulnerabilities_sync, artifact_text)

            # Convert results to findings with filtering by threshold
            findings: list[Finding] = []
            finding_idx = 0

            for vuln_data in result.vulnerabilities:
                confidence = threat_to_confidence(ThreatLevel(vuln_data.threat_level))
                if confidence >= self._threshold:
                    findings.append(
                        self._create_finding_from_vulnerability(
                            vuln_data, finding_idx, domains or []
                        )
                    )
                    finding_idx += 1

            logger.debug(
                "Adversarial review found %d vulnerabilities (threshold=%.2f)",
                len(findings),
                self._threshold,
            )

            return findings

        except (ProviderError, ProviderTimeoutError) as e:
            logger.warning("Adversarial review failed: %s", e)
            return []
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            logger.warning("Adversarial review failed - parse error: %s", e)
            return []

    def _should_run_for_domains(self, domains: list[ArtifactDomain] | None) -> bool:
        """Check if method should run for detected domains.

        Method #201 runs only when SECURITY or API domain is detected.

        Args:
            domains: List of detected domains (may be None).

        Returns:
            True if SECURITY or API is in the domains list, False otherwise.

        """
        if not domains:
            return False

        return ArtifactDomain.SECURITY in domains or ArtifactDomain.API in domains

    def _analyze_vulnerabilities_sync(self, artifact_text: str) -> AdversarialReviewResponse:
        """Analyze artifact for vulnerabilities using LLM (synchronous).

        This method is synchronous because ClaudeSDKProvider.invoke() is sync.
        Run it via asyncio.to_thread() from async analyze() method.

        Args:
            artifact_text: The text to analyze.

        Returns:
            AdversarialReviewResponse with identified vulnerabilities.

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
                    method_id=self.method_id,
                )
            )
            raw_response = result.stdout
        else:
            # Call LLM synchronously (this blocks, so run in thread pool)
            # _provider is always set when _llm_client is None (see __init__)
            assert self._provider is not None
            result = self._provider.invoke(
                prompt=prompt,
                model=self._model,
                timeout=self._timeout,
            )
            raw_response = self._provider.parse_output(result)

        return self._parse_response(raw_response)

    def _build_prompt(self, artifact_text: str) -> str:
        """Build the prompt for LLM adversarial analysis.

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
            definition = ADVERSARIAL_CATEGORIES[cat]
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
                f"to {MAX_ARTIFACT_LENGTH} characters. Vulnerabilities beyond this point "
                f"will NOT be detected.\n\n"
            )

        return (
            f"{ADVERSARIAL_REVIEW_SYSTEM_PROMPT}\n\n"
            f"Artifact to analyze (truncated to {MAX_ARTIFACT_LENGTH} chars):{truncation_notice}\n"
            f"```\n{truncated}\n```\n\n"
            f"Categories to analyze:\n"
            f"{categories_str}\n\n"
            f"Identify all vulnerabilities from an attacker's perspective. "
            f"For each vulnerability, provide:\n"
            f"- vulnerability: Description of the vulnerability\n"
            f"- category: One of [bypass, load, error_paths, edge_inputs]\n"
            f"- threat_level: One of [critical, high, medium, low]\n"
            f"- evidence_quote: Code snippet showing where vulnerability exists\n"
            f"- line_number: Line number (if identifiable)\n"
            f"- attack_vector: How an attacker could exploit this\n"
            f"- remediation: How to fix or mitigate the vulnerability\n\n"
            f"Respond with JSON in this format:\n"
            f"{{\n"
            f'    "vulnerabilities": [\n'
            f"        {{\n"
            f'            "vulnerability": "Description...",\n'
            f'            "category": "bypass",\n'
            f'            "threat_level": "critical",\n'
            f'            "evidence_quote": "code snippet",\n'
            f'            "line_number": 42,\n'
            f'            "attack_vector": "An attacker could...",\n'
            f'            "remediation": "Add validation for..."\n'
            f"        }}\n"
            f"    ]\n"
            f"}}"
        )

    def _parse_response(self, raw_response: str) -> AdversarialReviewResponse:
        """Parse LLM response with robust JSON extraction.

        Handles:
        - JSON inside markdown code blocks (```json...```)
        - Raw JSON objects
        - Nested braces by tracking depth

        Args:
            raw_response: Raw text response from LLM.

        Returns:
            Parsed AdversarialReviewResponse.

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
                # Try to find the "vulnerabilities" array directly
                match = re.search(r'"vulnerabilities"\s*:\s*(\[.*?\])', raw_response, re.DOTALL)
                if match:
                    json_str = '{"vulnerabilities": ' + match.group(1) + "}"
                else:
                    raise ValueError("No JSON found in response")

        # Parse with Pydantic validation
        data = json.loads(json_str)
        return AdversarialReviewResponse(**data)

    def _create_finding_from_vulnerability(
        self,
        vuln_data: AdversarialVulnerabilityData,
        index: int,
        detected_domains: list[ArtifactDomain],
    ) -> Finding:
        """Convert adversarial analysis data to Finding.

        Args:
            vuln_data: The vulnerability data from LLM response.
            index: The index for generating finding ID.
            detected_domains: List of domains detected in the artifact.

        Returns:
            Finding object with all relevant details.

        """
        finding_id = f"#201-F{index + 1}"

        # Map threat to severity and confidence
        threat = ThreatLevel(vuln_data.threat_level)

        # Check for CRITICAL severity
        is_critical = _is_critical_threat(vuln_data.category, vuln_data.vulnerability)
        if is_critical:
            severity = Severity.CRITICAL
        else:
            severity = threat_to_severity(threat)
        confidence = threat_to_confidence(threat)

        # Build title from vulnerability description
        title = vuln_data.vulnerability
        if len(title) > 80:
            title = title[:77] + "..."

        # Build comprehensive description
        description_parts = [
            f"Vulnerability: {vuln_data.vulnerability}",
            "",
            f"Category: {vuln_data.category}",
            f"Threat level: {vuln_data.threat_level}",
        ]

        if vuln_data.attack_vector:
            description_parts.extend(
                [
                    "",
                    f"Attack vector: {vuln_data.attack_vector}",
                ]
            )

        if vuln_data.remediation:
            description_parts.extend(
                [
                    "",
                    f"Remediation: {vuln_data.remediation}",
                ]
            )

        description = "\n".join(description_parts)

        # Create evidence
        evidence = []
        if vuln_data.evidence_quote and vuln_data.evidence_quote.strip():
            evidence.append(
                Evidence(
                    quote=vuln_data.evidence_quote,
                    line_number=vuln_data.line_number,
                    source="#201",
                    confidence=confidence,
                )
            )

        # Determine pattern_id from category
        try:
            category_enum = AdversarialCategory(vuln_data.category.lower())
            pattern_id = PatternId(ADVERSARIAL_CATEGORIES[category_enum].id)
        except (ValueError, KeyError):
            pattern_id = None

        # Determine domain based on category and detected domains
        domain = self._assign_domain_for_category(vuln_data.category, detected_domains)

        return Finding(
            id=finding_id,
            severity=severity,
            title=title,
            description=description,
            method_id=MethodId("#201"),
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
            category: The adversarial category.
            detected_domains: List of domains detected in the artifact.

        Returns:
            ArtifactDomain for the finding, or None if cannot be determined.

        """
        cat_lower = category.lower()

        # BYPASS, EDGE_INPUTS → SECURITY (with API fallback)
        if cat_lower in ("bypass", "edge_inputs"):
            if ArtifactDomain.SECURITY in detected_domains:
                return ArtifactDomain.SECURITY
            if ArtifactDomain.API in detected_domains:
                return ArtifactDomain.API

        # LOAD, ERROR_PATHS → API (with SECURITY fallback)
        if cat_lower in ("load", "error_paths"):
            if ArtifactDomain.API in detected_domains:
                return ArtifactDomain.API
            if ArtifactDomain.SECURITY in detected_domains:
                return ArtifactDomain.SECURITY

        # Default: first detected domain
        if detected_domains:
            return detected_domains[0]

        return None
