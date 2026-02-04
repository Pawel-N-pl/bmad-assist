"""Domain Expert Method (#203) for Deep Verify.

This module implements the Domain Expert verification method that applies
domain-specific constraints and best practices to identify violations of
industry standards, compliance requirements, and expert heuristics.

Method #203 runs for ALL domains (not conditionally restricted), applying
knowledge bases specific to the detected domains.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from bmad_assist.core.exceptions import ProviderError, ProviderTimeoutError
from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    Evidence,
    Finding,
    MethodId,
    PatternId,
    Severity,
)
from bmad_assist.deep_verify.knowledge import KnowledgeCategory, KnowledgeLoader, KnowledgeRule
from bmad_assist.deep_verify.methods.base import BaseVerificationMethod
from bmad_assist.deep_verify.methods.constants import (
    DEFAULT_MODEL,
    DEFAULT_THRESHOLD,
    DEFAULT_TIMEOUT,
)
from bmad_assist.providers import ClaudeSDKProvider

logger = logging.getLogger(__name__)

__all__ = [
    "DomainExpertMethod",
    "DomainExpertAnalysisResponse",
    "DomainExpertViolationData",
    "DOMAIN_EXPERT_SYSTEM_PROMPT",
    "resolve_finding_severity",
]

# =============================================================================
# Constants
# =============================================================================

MAX_ARTIFACT_LENGTH = 3500

DOMAIN_EXPERT_SYSTEM_PROMPT = """You are a domain expert code reviewer specializing in industry standards and best practices.

Your task is to analyze the provided code/implementation artifact against a set of domain-specific rules and identify any violations.

For each rule provided, determine if the artifact violates the rule. A violation occurs when the artifact contains code or patterns that contradict the rule's requirements or recommendations.

For each violation you identify:
- Reference the specific rule ID that was violated
- Quote the evidence from the code
- Explain how the artifact violates the rule
- Recommend how to fix the violation
- Provide a confidence score (0.0-1.0)

Focus on:
- Clear violations of stated rules (not general code quality issues)
- Specific evidence from the code
- Actionable remediation guidance

Respond with valid JSON only. If no rules are violated, return empty JSON object `{}`."""


# =============================================================================
# Severity Resolution Function
# =============================================================================


def resolve_finding_severity(rule: KnowledgeRule) -> Severity:
    """Resolve finding severity from rule category and severity field.

    Resolution order:
    1. For STANDARDS/COMPLIANCE: use rule's severity if CRITICAL or ERROR
    2. For BEST_PRACTICES: always WARNING (ignore rule severity)
    3. For HEURISTICS: always INFO (ignore rule severity)
    4. Default: use category-based mapping

    Args:
        rule: The knowledge rule being evaluated.

    Returns:
        Corresponding Severity for the finding.

    """
    # Rule severity overrides for high-impact categories
    if rule.category in (KnowledgeCategory.STANDARDS, KnowledgeCategory.COMPLIANCE):
        if rule.severity in (Severity.CRITICAL, Severity.ERROR):
            return rule.severity
        # For standards/compliance without explicit critical/error, default to ERROR
        return Severity.ERROR

    # Category defaults (rule severity ignored for these)
    if rule.category == KnowledgeCategory.BEST_PRACTICES:
        return Severity.WARNING
    if rule.category == KnowledgeCategory.HEURISTICS:
        return Severity.INFO

    # Default fallback
    return Severity.WARNING


# =============================================================================
# Pydantic Models for LLM Response
# =============================================================================


class DomainExpertViolationData(BaseModel):
    """Pydantic model for individual violation in LLM response."""

    rule_id: str = Field(..., min_length=1, description="ID of violated rule")
    rule_title: str = Field(..., min_length=1, description="Title of violated rule")
    evidence_quote: str = Field(..., min_length=1, description="Code snippet")
    line_number: int | None = Field(None, description="Line number if identifiable")
    violation_explanation: str = Field(..., min_length=1, description="How rule is violated")
    remediation: str = Field(..., min_length=1, description="How to fix")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence 0.0-1.0")


class DomainExpertAnalysisResponse(BaseModel):
    """Pydantic model for full domain expert analysis response."""

    violations: list[DomainExpertViolationData] = Field(
        default_factory=list, description="List of rule violations"
    )


# =============================================================================
# Domain Expert Method
# =============================================================================


class DomainExpertMethod(BaseVerificationMethod):
    """Domain Expert Method (#203) - Domain standards compliance review.

    This method analyzes artifact text against domain-specific knowledge bases
    using LLM-based expert review. It identifies violations of industry standards,
    compliance requirements, and domain best practices.

    Unlike other conditional methods, Domain Expert runs for ALL domains,
    loading appropriate knowledge bases based on detected domains.

    Method #203 applies knowledge bases in these categories:
    - STANDARDS: Industry standards (OWASP Top 10, PCI-DSS, HIPAA, etc.)
    - COMPLIANCE: Regulatory requirements
    - BEST_PRACTICES: Domain conventions and best practices
    - HEURISTICS: Expert rules of thumb

    Attributes:
        method_id: Unique method identifier "#203".
        _provider: ClaudeSDKProvider for LLM calls.
        _model: Model identifier for LLM calls.
        _threshold: Minimum confidence threshold for findings (0.0-1.0).
        _timeout: Timeout in seconds for LLM calls.
        _loader: KnowledgeLoader for loading domain-specific rules.

    Example:
        >>> method = DomainExpertMethod()
        >>> findings = await method.analyze(
        ...     "code with SQL injection vulnerability",
        ...     domains=[ArtifactDomain.SECURITY]
        ... )
        >>> for f in findings:
        ...     print(f"{f.id}: {f.title}")

    """

    method_id: MethodId = MethodId("#203")

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        timeout: int = DEFAULT_TIMEOUT,
        knowledge_dir: Path | None = None,
        llm_client: Any | None = None,
    ) -> None:
        """Initialize the Domain Expert Method.

        Args:
            model: Model identifier for LLM calls (default: "haiku").
            threshold: Minimum confidence threshold for findings (default: 0.6).
            timeout: Timeout in seconds for LLM calls (default: 30).
            knowledge_dir: Optional directory containing knowledge base YAML files.
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

        # Initialize knowledge loader
        self._loader = KnowledgeLoader(knowledge_dir)

    def __repr__(self) -> str:
        """Return a string representation of the method."""
        return (
            f"DomainExpertMethod("
            f"method_id={self.method_id!r}, "
            f"model='{self._model}', "
            f"threshold={self._threshold}"
            f")"
        )

    async def analyze(
        self,
        artifact_text: str,
        **kwargs: Any,
    ) -> list[Finding]:
        """Analyze artifact against domain knowledge bases.

        This method runs for ALL artifacts regardless of domain. It loads
        appropriate knowledge bases based on detected domains and uses LLM
        to identify rule violations.

        Args:
            artifact_text: The text content to analyze for rule violations.
            **kwargs: Additional context including:
                - domains: Optional list[ArtifactDomain] to select knowledge bases
                - config: Optional DeepVerifyConfig (not used currently)

        Returns:
            List of Finding objects for violated rules with confidence >= threshold.
            Findings have temporary IDs "#203-F1", "#203-F2", etc. which will be
            reassigned by DeepVerifyEngine.

        """
        if not artifact_text or not artifact_text.strip():
            logger.debug("Empty artifact text, returning no findings")
            return []

        # Extract domains from kwargs
        domains = kwargs.get("domains")

        # Load knowledge base rules
        rules = self._loader.load(domains)

        if not rules:
            logger.warning("No knowledge base rules available for analysis")
            return []

        logger.debug(
            "Running domain expert analysis (domains=%s, rules=%d)",
            domains,
            len(rules),
        )

        try:
            # Run sync LLM call in thread pool to avoid blocking
            result = await asyncio.to_thread(self._analyze_rules_sync, artifact_text, rules)

            # Convert results to findings with filtering by threshold
            findings: list[Finding] = []
            finding_idx = 0

            for violation_data in result.violations:
                if violation_data.confidence >= self._threshold:
                    finding_idx += 1
                    findings.append(
                        self._create_finding_from_violation(violation_data, finding_idx, rules)
                    )

            logger.debug(
                "Domain expert found %d violations (threshold=%.2f)",
                len(findings),
                self._threshold,
            )

            return findings

        except (ProviderError, ProviderTimeoutError) as e:
            logger.warning("Domain expert failed: %s", e)
            return []
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            logger.warning("Domain expert failed - parse error: %s", e)
            return []

    def _analyze_rules_sync(
        self,
        artifact_text: str,
        rules: list[KnowledgeRule],
    ) -> DomainExpertAnalysisResponse:
        """Analyze artifact against rules using LLM (synchronous).

        Uses LLMClient if available, otherwise falls back to direct provider.

        Args:
            artifact_text: The text to analyze.
            rules: List of knowledge rules to evaluate against.

        Returns:
            DomainExpertAnalysisResponse with identified violations.

        """
        prompt = self._build_prompt(artifact_text, rules)

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

    def _build_prompt(self, artifact_text: str, rules: list[KnowledgeRule]) -> str:
        """Build the prompt for LLM domain expert analysis.

        Args:
            artifact_text: The text to analyze.
            rules: List of knowledge rules to evaluate.

        Returns:
            Formatted prompt string.

        """
        was_truncated = len(artifact_text) > MAX_ARTIFACT_LENGTH
        truncated = artifact_text[:MAX_ARTIFACT_LENGTH]

        # Build rules section
        rules_str = "\n\n".join(
            f"Rule ID: {rule.id}\n"
            f"Domain: {rule.domain}\n"
            f"Category: {rule.category.value}\n"
            f"Title: {rule.title}\n"
            f"Description: {rule.description}\n"
            f"Severity if violated: {rule.severity.value}"
            for rule in rules
        )

        # Add truncation warning if content was truncated
        truncation_notice = ""
        if was_truncated:
            truncation_notice = (
                f"\n⚠️ IMPORTANT: Artifact was truncated from {len(artifact_text)} "
                f"to {MAX_ARTIFACT_LENGTH} characters. Violations beyond this point "
                f"will NOT be detected.\n\n"
            )

        return (
            f"{DOMAIN_EXPERT_SYSTEM_PROMPT}\n\n"
            f"Artifact to analyze (truncated to {MAX_ARTIFACT_LENGTH} chars):{truncation_notice}\n"
            f"```\n{truncated}\n```\n\n"
            f"Rules to evaluate against:\n\n"
            f"{rules_str}\n\n"
            f"Identify all rule violations in the artifact. For each violation, provide:\n"
            f"- rule_id: ID of the violated rule\n"
            f"- rule_title: Title of the violated rule\n"
            f"- evidence_quote: Code snippet showing the violation\n"
            f"- line_number: Line number (if identifiable)\n"
            f"- violation_explanation: How the artifact violates the rule\n"
            f"- remediation: How to fix the violation\n"
            f"- confidence: 0.0-1.0 confidence score\n\n"
            f"Respond with JSON in this format:\n"
            f"{{\n"
            f'    "violations": [\n'
            f"        {{\n"
            f'            "rule_id": "SEC-001",\n'
            f'            "rule_title": "Rule Title",\n'
            f'            "evidence_quote": "code snippet",\n'
            f'            "line_number": 42,\n'
            f'            "violation_explanation": "This violates the rule because...",\n'
            f'            "remediation": "Fix by...",\n'
            f'            "confidence": 0.85\n'
            f"        }}\n"
            f"    ]\n"
            f"}}"
        )

    def _parse_response(self, raw_response: str) -> DomainExpertAnalysisResponse:
        """Parse LLM response with robust JSON extraction.

        Handles:
        - JSON inside markdown code blocks (```json...```)
        - Raw JSON objects
        - Nested braces by tracking depth

        Args:
            raw_response: Raw text response from LLM.

        Returns:
            Parsed DomainExpertAnalysisResponse.

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
                # Try to find the "violations" array directly
                match = re.search(r'"violations"\s*:\s*(\[.*?\])', raw_response, re.DOTALL)
                if match:
                    json_str = '{"violations": ' + match.group(1) + "}"
                else:
                    raise ValueError("No JSON found in response")

        # Parse with Pydantic validation
        data = json.loads(json_str)
        return DomainExpertAnalysisResponse(**data)

    def _create_finding_from_violation(
        self,
        violation_data: DomainExpertViolationData,
        index: int,
        rules: list[KnowledgeRule],
    ) -> Finding:
        """Convert domain expert analysis data to Finding.

        Args:
            violation_data: The violation data from LLM response.
            index: The index for generating finding ID (1-based).
            rules: List of loaded rules to find the matched rule.

        Returns:
            Finding object with all relevant details.

        """
        finding_id = f"#203-F{index}"

        # Find the matching rule
        matched_rule: KnowledgeRule | None = None
        for rule in rules:
            if rule.id == violation_data.rule_id:
                matched_rule = rule
                break

        # Determine severity
        if matched_rule:
            severity = resolve_finding_severity(matched_rule)
        else:
            # Fallback severity if rule not found
            severity = Severity.WARNING

        # Build title (truncate to 80 chars)
        title = violation_data.rule_title
        if len(title) > 80:
            title = title[:77] + "..."

        # Build comprehensive description
        description_parts = [
            f"Rule: {violation_data.rule_title}",
            "",
            f"Violation: {violation_data.violation_explanation}",
        ]

        if matched_rule:
            description_parts.extend(
                [
                    "",
                    f"Rule Description: {matched_rule.description}",
                ]
            )
            if matched_rule.references:
                description_parts.extend(
                    [
                        "",
                        "References:",
                    ]
                )
                for ref in matched_rule.references:
                    description_parts.append(f"  - {ref}")

        if violation_data.remediation:
            description_parts.extend(
                [
                    "",
                    f"Remediation: {violation_data.remediation}",
                ]
            )

        description = "\n".join(description_parts)

        # Create evidence
        evidence = []
        if violation_data.evidence_quote and violation_data.evidence_quote.strip():
            evidence.append(
                Evidence(
                    quote=violation_data.evidence_quote,
                    line_number=violation_data.line_number,
                    source="#203",
                    confidence=violation_data.confidence,
                )
            )

        # Determine domain
        domain: ArtifactDomain | None = None
        if matched_rule and matched_rule.domain != "general":
            with contextlib.suppress(ValueError):
                domain = ArtifactDomain(matched_rule.domain)

        # Pattern ID from rule
        pattern_id = PatternId(violation_data.rule_id) if violation_data.rule_id else None

        return Finding(
            id=finding_id,
            severity=severity,
            title=title,
            description=description,
            method_id=MethodId("#203"),
            pattern_id=pattern_id,
            domain=domain,
            evidence=evidence,
        )
