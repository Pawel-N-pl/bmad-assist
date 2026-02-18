"""Core type definitions for Deep Verify.

This module provides the foundational data types for the Deep Verify system,
including artifact domains, evidence, findings, verdicts, and serialization utilities.

All dataclasses are frozen for immutability, following bmad-assist patterns.
Serialization functions are standalone (not methods) since frozen dataclasses
cannot have mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NewType

if TYPE_CHECKING:
    from bmad_assist.deep_verify.core.exceptions import CategorizedError
    from bmad_assist.deep_verify.infrastructure.types import CostSummary

# =============================================================================
# Type Aliases
# =============================================================================

# Method identifier format: "#NNN" (e.g., "#153", "#154")
MethodId = NewType("MethodId", str)

# Pattern identifier format: "XX-NNN" (e.g., "CC-001", "SEC-004")
PatternId = NewType("PatternId", str)

# Domain ambiguity levels
DomainAmbiguity = Literal["none", "low", "medium", "high"]

from typing import TypeVar

E = TypeVar("E", bound=Enum)


# =============================================================================
# Enums
# =============================================================================


class ArtifactDomain(str, Enum):
    """Artifact classification domains for Deep Verify.

    Domains are detected via LLM-based classification and determine which
    verification methods are executed.
    """

    SECURITY = "security"  # Authentication, authorization, cryptography, secrets
    STORAGE = "storage"  # Database operations, SQL, transactions, persistence
    TRANSFORM = "transform"  # Data transformation, parsing, serialization, pipelines
    CONCURRENCY = "concurrency"  # Parallel execution, async, workers, locks, mutexes
    API = "api"  # HTTP endpoints, REST, webhooks, external service integration
    MESSAGING = "messaging"  # Message queues, pub/sub, events, retries, DLQ
    PRD = "prd"  # Product requirements, user stories, scope management
    DOCUMENTATION = "documentation"  # Technical documentation, API docs, code-doc consistency


class Severity(str, Enum):
    """Finding severity levels for Deep Verify.

    Severity determines the weight in scoring and whether findings are blockers.
    """

    CRITICAL = "critical"  # Hard block - must fix
    ERROR = "error"  # Soft block - can override
    WARNING = "warning"  # Advisory - flag in report
    INFO = "info"  # Informational - minimal weight


class VerdictDecision(str, Enum):
    """Deterministic verdict decisions for Deep Verify.

    Based on aggregated evidence score against thresholds.
    """

    ACCEPT = "ACCEPT"  # Score < -3 - clean enough
    REJECT = "REJECT"  # Score > 6 - too many high-severity findings
    UNCERTAIN = "UNCERTAIN"  # -3 <= score <= 6 - needs human review


# =============================================================================
# Data Classes
# =============================================================================


@dataclass(frozen=True, slots=True)
class DomainConfidence:
    """Confidence for a detected domain.

    Attributes:
        domain: The detected domain.
        confidence: Confidence score 0.3-1.0 (below 0.3 excluded).
        signals: Specific terms/patterns indicating the domain.

    """

    domain: ArtifactDomain
    confidence: float
    signals: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        """Return a string representation of the domain confidence."""
        signals_str = f", signals={self.signals!r}" if self.signals else ""
        return f"DomainConfidence(domain={self.domain.value!r}, confidence={self.confidence:.2f}{signals_str})"


@dataclass(frozen=True, slots=True)
class DomainDetectionResult:
    """Result of artifact domain detection.

    Attributes:
        domains: List of detected domains with confidence.
        reasoning: Explanation of domain classification.
        ambiguity: Level of ambiguity in detection.
        duration_ms: Execution time in milliseconds.

    """

    domains: list[DomainConfidence]
    reasoning: str
    ambiguity: DomainAmbiguity = "none"
    duration_ms: int = 0

    def __repr__(self) -> str:
        """Return a string representation of the domain detection result."""
        domains_str = f"domains={self.domains!r}"
        reasoning_preview = (
            self.reasoning[:50] + "..." if len(self.reasoning) > 50 else self.reasoning
        )
        return f"DomainDetectionResult({domains_str}, reasoning={reasoning_preview!r}, ambiguity={self.ambiguity!r}, duration_ms={self.duration_ms})"


@dataclass(frozen=True, slots=True)
class Evidence:
    """Individual evidence item supporting a finding.

    Attributes:
        quote: Code or text snippet as evidence.
        line_number: Line number in source (if applicable).
        source: Source reference (file, URL, etc.).
        confidence: Evidence confidence 0.0-1.0.

    """

    quote: str
    line_number: int | None = None
    source: str = ""
    confidence: float = 1.0

    def __repr__(self) -> str:
        """Return a string representation of the evidence."""
        quote_preview = self.quote[:40] + "..." if len(self.quote) > 40 else self.quote
        line_str = f", line={self.line_number}" if self.line_number is not None else ""
        return f"Evidence(quote={quote_preview!r}{line_str}, confidence={self.confidence:.2f})"


@dataclass(frozen=True, slots=True)
class Signal:
    """Signal definition for pattern matching.

    Signals can be exact string matches or regex patterns with optional weights.

    Attributes:
        type: Signal type - "exact" for substring match, "regex" for regex match.
        pattern: The pattern string to match.
        weight: Weight of this signal in confidence calculation (default 1.0).

    """

    type: Literal["exact", "regex"]
    pattern: str
    weight: float = 1.0

    def __repr__(self) -> str:
        """Return a string representation of the signal."""
        weight_str = f", weight={self.weight:.1f}" if self.weight != 1.0 else ""
        return f"Signal(type={self.type!r}, pattern={self.pattern!r}{weight_str})"


@dataclass(frozen=True, slots=True)
class Pattern:
    """Verification pattern for signal matching.

    Used by Story 26.4 (Pattern Library) for type consistency.

    Attributes:
        id: Pattern identifier (e.g., "CC-001", "SEC-004", "CC-001-CODE-GO").
        domain: Domain this pattern applies to.
        signals: List of Signal objects to match.
        severity: Severity if pattern matches.
        description: Optional pattern description.
        remediation: Optional remediation guidance.
        language: Optional language code for code patterns (e.g., "go", "python").
                 None for spec patterns that apply to all languages.

    """

    id: PatternId
    domain: ArtifactDomain
    signals: list[Signal]
    severity: Severity
    description: str | None = None
    remediation: str | None = None
    language: str | None = None

    def __repr__(self) -> str:
        """Return a string representation of the pattern."""
        desc_str = f", description={self.description!r}" if self.description else ""
        lang_str = f", language={self.language!r}" if self.language else ""
        return f"Pattern(id={self.id!r}, domain={self.domain.value!r}, signals={len(self.signals)} signals{desc_str}{lang_str})"


@dataclass(frozen=True, slots=True)
class Finding:
    """Individual verification finding.

    Finding IDs (F1, F2, ...) are assigned during Verdict creation,
    not by the Finding dataclass itself.

    Attributes:
        id: Finding identifier (e.g., "F1", "F2").
        severity: Severity level of the finding.
        title: Brief finding title.
        description: Detailed finding description.
        method_id: Method that produced this finding (e.g., "#153").
        pattern_id: Pattern ID if matched (e.g., "CC-001"), None otherwise.
        domain: Domain this finding relates to (if any).
        evidence: List of evidence supporting this finding.

    """

    id: str
    severity: Severity
    title: str
    description: str
    method_id: MethodId
    pattern_id: PatternId | None = None
    domain: ArtifactDomain | None = None
    evidence: list[Evidence] = field(default_factory=list)

    def __repr__(self) -> str:
        """Return a string representation of the finding."""
        title_preview = self.title[:40] + "..." if len(self.title) > 40 else self.title
        pattern_str = f", pattern_id={self.pattern_id!r}" if self.pattern_id else ""
        domain_str = f", domain={self.domain.value!r}" if self.domain else ""
        return f"Finding(id={self.id!r}, severity={self.severity.value!r}, title={title_preview!r}, method_id={self.method_id!r}{pattern_str}{domain_str})"


@dataclass(frozen=True, slots=True)
class Verdict:
    """Verification verdict with findings and score.

    Attributes:
        decision: Final verdict decision (ACCEPT, REJECT, UNCERTAIN).
        score: Aggregated evidence score.
        findings: List of findings (with assigned IDs F1, F2, ...).
        domains_detected: Domains detected during analysis.
        methods_executed: Methods that were executed.
        summary: Human-readable summary of the verdict.
        cost_summary: Optional cost summary for the verification run.
        errors: List of errors that occurred during verification.
        input_metrics: Optional input validation metrics (size_bytes, line_count).

    """

    decision: VerdictDecision
    score: float
    findings: list[Finding]
    domains_detected: list[DomainConfidence]
    methods_executed: list[MethodId]
    summary: str
    cost_summary: CostSummary | None = None  # CostSummary from infrastructure
    errors: list[VerdictError] = field(default_factory=list)
    input_metrics: dict[str, int] | None = None

    def __repr__(self) -> str:
        """Return a string representation of the verdict."""
        summary_preview = self.summary[:50] + "..." if len(self.summary) > 50 else self.summary
        error_str = f", errors={len(self.errors)}" if self.errors else ""
        return (
            f"Verdict(decision={self.decision.value!r}, score={self.score:.2f}, "
            f"findings={len(self.findings)}, methods={len(self.methods_executed)}, "
            f"summary={summary_preview!r}{error_str})"
        )


@dataclass(frozen=True, slots=True)
class VerdictError:
    """Error information for the verdict.

    Attributes:
        method_id: Method ID where error occurred (None for general errors).
        error_type: Type of error (exception class name).
        error_message: Human-readable error message.
        category: Error category (retryable_transient, fatal_auth, etc.).

    """

    method_id: MethodId | None
    error_type: str
    error_message: str
    category: str

    def __repr__(self) -> str:
        """Return a string representation of the verdict error."""
        method_str = f"method={self.method_id!r}" if self.method_id else "general"
        return f"VerdictError({method_str}, type={self.error_type!r}, category={self.category!r})"


@dataclass(frozen=True, slots=True)
class MethodResult:
    """Result from a single method execution.

    Attributes:
        method_id: Method that was executed.
        findings: List of findings from the method.
        error: Error information if method failed, None otherwise.
        success: Whether the method executed successfully.

    """

    method_id: MethodId
    findings: list[Finding]
    error: CategorizedError | None
    success: bool

    def __repr__(self) -> str:
        """Return a string representation of the method result."""
        status = "success" if self.success else "failed"
        return f"MethodResult({self.method_id!r}, {status}, findings={len(self.findings)})"


@dataclass(frozen=True, slots=True)
class DeepVerifyValidationResult:
    """Result from Deep Verify validation for integration hooks.

    This is the output type used by integration hooks (Story 26.16, 26.20)
    to pass DV results to the validation/code_review synthesis phases.

    Attributes:
        findings: List of findings from verification.
        domains_detected: Domains detected during analysis.
        methods_executed: Methods that were executed.
        verdict: Final verdict decision.
        score: Aggregated evidence score.
        duration_ms: Execution time in milliseconds.
        error: Error message if verification failed, None otherwise.
        cost_summary: Optional cost summary for the verification run.

    """

    findings: list[Finding]
    domains_detected: list[DomainConfidence]
    methods_executed: list[MethodId]
    verdict: VerdictDecision
    score: float
    duration_ms: int
    error: str | None = None
    cost_summary: CostSummary | None = None  # CostSummary from infrastructure

    def __repr__(self) -> str:
        """Return a string representation of the validation result."""
        error_str = f", error={self.error!r}" if self.error else ""
        return (
            f"DeepVerifyValidationResult(verdict={self.verdict.value!r}, score={self.score:.2f}, "
            f"findings={len(self.findings)}, methods={len(self.methods_executed)}, "
            f"duration={self.duration_ms}ms{error_str})"
        )


# =============================================================================
# Serialization Utilities
# =============================================================================


def _serialize_enum(value: Enum) -> str:
    """Serialize an enum to its value."""
    return str(value.value)


def _deserialize_enum(value: str, enum_class: type[E]) -> E:
    """Deserialize a string to an enum member."""
    return enum_class(value)


def serialize_evidence(evidence: Evidence) -> dict[str, Any]:
    """Serialize Evidence to a dictionary."""
    return {
        "quote": evidence.quote,
        "line_number": evidence.line_number,
        "source": evidence.source,
        "confidence": evidence.confidence,
    }


def deserialize_evidence(data: dict[str, Any]) -> Evidence:
    """Deserialize a dictionary to Evidence."""
    return Evidence(
        quote=data["quote"],
        line_number=data.get("line_number"),
        source=data.get("source", ""),
        confidence=data.get("confidence", 1.0),
    )


def serialize_signal(signal: Signal) -> dict[str, Any]:
    """Serialize Signal to a dictionary."""
    return {
        "type": signal.type,
        "pattern": signal.pattern,
        "weight": signal.weight,
    }


def deserialize_signal(data: dict[str, Any]) -> Signal:
    """Deserialize a dictionary to Signal."""
    return Signal(
        type=data["type"],
        pattern=data["pattern"],
        weight=data.get("weight", 1.0),
    )


def serialize_pattern(pattern: Pattern) -> dict[str, Any]:
    """Serialize Pattern to a dictionary."""
    return {
        "id": pattern.id,
        "domain": _serialize_enum(pattern.domain),
        "signals": [serialize_signal(s) for s in pattern.signals],
        "severity": _serialize_enum(pattern.severity),
        "description": pattern.description,
        "remediation": pattern.remediation,
        "language": pattern.language,
    }


def deserialize_pattern(data: dict[str, Any]) -> Pattern:
    """Deserialize a dictionary to Pattern."""
    return Pattern(
        id=PatternId(data["id"]),
        domain=_deserialize_enum(data["domain"], ArtifactDomain),
        signals=[deserialize_signal(s) for s in data.get("signals", [])],
        severity=_deserialize_enum(data["severity"], Severity),
        description=data.get("description"),
        remediation=data.get("remediation"),
        language=data.get("language"),
    )


def serialize_domain_confidence(dc: DomainConfidence) -> dict[str, Any]:
    """Serialize DomainConfidence to a dictionary."""
    return {
        "domain": _serialize_enum(dc.domain),
        "confidence": dc.confidence,
        "signals": dc.signals,
    }


def deserialize_domain_confidence(data: dict[str, Any]) -> DomainConfidence:
    """Deserialize a dictionary to DomainConfidence."""
    return DomainConfidence(
        domain=_deserialize_enum(data["domain"], ArtifactDomain),
        confidence=data["confidence"],
        signals=data.get("signals", []),
    )


def serialize_finding(finding: Finding) -> dict[str, Any]:
    """Serialize Finding to a dictionary for JSON storage.

    Args:
        finding: Finding to serialize.

    Returns:
        Dictionary representation of the finding.

    """
    return {
        "id": finding.id,
        "severity": _serialize_enum(finding.severity),
        "title": finding.title,
        "description": finding.description,
        "method_id": finding.method_id,
        "pattern_id": finding.pattern_id,
        "domain": _serialize_enum(finding.domain) if finding.domain else None,
        "evidence": [serialize_evidence(e) for e in finding.evidence],
    }


def deserialize_finding(data: dict[str, Any]) -> Finding:
    """Deserialize a dictionary to Finding.

    Args:
        data: Dictionary from serialize_finding.

    Returns:
        Reconstructed Finding instance.

    """
    domain_data = data.get("domain")
    pattern_id_data = data.get("pattern_id")

    # Handle empty strings as None for optional fields
    pattern_id = PatternId(pattern_id_data) if pattern_id_data and pattern_id_data != "" else None
    domain = (
        _deserialize_enum(domain_data, ArtifactDomain)
        if domain_data and domain_data != ""
        else None
    )

    return Finding(
        id=data["id"],
        severity=_deserialize_enum(data["severity"], Severity),
        title=data["title"],
        description=data["description"],
        method_id=MethodId(data["method_id"]),
        pattern_id=pattern_id,
        domain=domain,
        evidence=[deserialize_evidence(e) for e in data.get("evidence", [])],
    )


def serialize_verdict_error(error: VerdictError) -> dict[str, Any]:
    """Serialize VerdictError to a dictionary.

    Args:
        error: VerdictError to serialize.

    Returns:
        Dictionary representation of the error.

    """
    return {
        "method_id": error.method_id,
        "error_type": error.error_type,
        "error_message": error.error_message,
        "category": error.category,
    }


def deserialize_verdict_error(data: dict[str, Any]) -> VerdictError:
    """Deserialize a dictionary to VerdictError.

    Args:
        data: Dictionary from serialize_verdict_error.

    Returns:
        Reconstructed VerdictError instance.

    """
    return VerdictError(
        method_id=MethodId(data["method_id"]) if data.get("method_id") else None,
        error_type=data["error_type"],
        error_message=data["error_message"],
        category=data["category"],
    )


def serialize_verdict(verdict: Verdict) -> dict[str, Any]:
    """Serialize Verdict to a dictionary for JSON storage.

    Args:
        verdict: Verdict to serialize.

    Returns:
        Dictionary representation of the verdict.

    """
    # Import here to avoid circular imports at module load time
    from bmad_assist.deep_verify.infrastructure.types import (
        serialize_cost_summary,
    )

    return {
        "decision": _serialize_enum(verdict.decision),
        "score": verdict.score,
        "findings": [serialize_finding(f) for f in verdict.findings],
        "domains_detected": [serialize_domain_confidence(dc) for dc in verdict.domains_detected],
        "methods_executed": verdict.methods_executed,
        "summary": verdict.summary,
        "cost_summary": serialize_cost_summary(verdict.cost_summary)
        if verdict.cost_summary
        else None,
        "errors": [serialize_verdict_error(e) for e in verdict.errors],
        "input_metrics": verdict.input_metrics,
    }


def deserialize_verdict(data: dict[str, Any]) -> Verdict:
    """Deserialize a dictionary to Verdict.

    Args:
        data: Dictionary from serialize_verdict.

    Returns:
        Reconstructed Verdict instance.

    """
    # Import here to avoid circular imports at module load time
    from bmad_assist.deep_verify.infrastructure.types import (
        deserialize_cost_summary,
    )

    cost_summary_data = data.get("cost_summary")
    cost_summary = deserialize_cost_summary(cost_summary_data) if cost_summary_data else None

    errors_data = data.get("errors", [])
    errors = [deserialize_verdict_error(e) for e in errors_data] if errors_data else []

    return Verdict(
        decision=_deserialize_enum(data["decision"], VerdictDecision),
        score=data["score"],
        findings=[deserialize_finding(f) for f in data.get("findings", [])],
        domains_detected=[
            deserialize_domain_confidence(dc) for dc in data.get("domains_detected", [])
        ],
        methods_executed=[MethodId(m) for m in data.get("methods_executed", [])],
        summary=data["summary"],
        cost_summary=cost_summary,
        errors=errors,
        input_metrics=data.get("input_metrics"),
    )


def serialize_validation_result(result: DeepVerifyValidationResult) -> dict[str, Any]:
    """Serialize DeepVerifyValidationResult to a dictionary.

    Args:
        result: Result to serialize.

    Returns:
        Dictionary representation for cache storage.

    """
    # Import here to avoid circular imports at module load time
    from bmad_assist.deep_verify.infrastructure.types import (
        serialize_cost_summary,
    )

    return {
        "findings": [serialize_finding(f) for f in result.findings],
        "domains_detected": [serialize_domain_confidence(dc) for dc in result.domains_detected],
        "methods_executed": result.methods_executed,
        "verdict": _serialize_enum(result.verdict),
        "score": result.score,
        "duration_ms": result.duration_ms,
        "error": result.error,
        "cost_summary": serialize_cost_summary(result.cost_summary)
        if result.cost_summary
        else None,
    }


@dataclass(frozen=True, slots=True)
class FileAnalysisResult:
    """Result of analyzing one file within a multi-turn batch session.

    Attributes:
        file_path: Path to the analyzed file.
        findings: List of findings from analysis.
        raw_response: Raw LLM response text.
        success: Whether analysis completed without error.
        error: Error message if analysis failed.
        duration_ms: Execution time in milliseconds.

    """

    file_path: Path
    findings: list[Finding]
    raw_response: str
    success: bool
    error: str | None = None
    duration_ms: int = 0


def deserialize_validation_result(data: dict[str, Any]) -> DeepVerifyValidationResult:
    """Deserialize a dictionary to DeepVerifyValidationResult.

    Args:
        data: Dictionary from serialize_validation_result.

    Returns:
        Reconstructed DeepVerifyValidationResult instance.

    """
    # Import here to avoid circular imports at module load time
    from bmad_assist.deep_verify.infrastructure.types import (
        deserialize_cost_summary,
    )

    cost_summary_data = data.get("cost_summary")
    cost_summary = deserialize_cost_summary(cost_summary_data) if cost_summary_data else None

    return DeepVerifyValidationResult(
        findings=[deserialize_finding(f) for f in data.get("findings", [])],
        domains_detected=[
            deserialize_domain_confidence(dc) for dc in data.get("domains_detected", [])
        ],
        methods_executed=[MethodId(m) for m in data.get("methods_executed", [])],
        verdict=_deserialize_enum(data["verdict"], VerdictDecision),
        score=data["score"],
        duration_ms=data["duration_ms"],
        error=data.get("error"),
        cost_summary=cost_summary,
    )
