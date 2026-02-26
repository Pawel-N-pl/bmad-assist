"""Tests for Deep Verify core types."""

from __future__ import annotations

import pytest

from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    DeepVerifyValidationResult,
    DomainConfidence,
    DomainDetectionResult,
    Evidence,
    Finding,
    MethodId,
    Pattern,
    PatternId,
    Severity,
    Verdict,
    VerdictDecision,
    deserialize_finding,
    deserialize_verdict,
    serialize_finding,
    serialize_verdict,
)

# =============================================================================
# Enum Tests
# =============================================================================


class TestArtifactDomain:
    """Tests for ArtifactDomain enum."""

    def test_all_domains_exist(self) -> None:
        """All 8 domains should be defined."""
        expected = {
            "security", "storage", "transform", "concurrency",
            "api", "messaging", "prd", "documentation",
        }
        actual = {d.value for d in ArtifactDomain}
        assert actual == expected

    def test_domain_values(self) -> None:
        """Domain values should match expected strings."""
        assert ArtifactDomain.SECURITY.value == "security"
        assert ArtifactDomain.STORAGE.value == "storage"
        assert ArtifactDomain.TRANSFORM.value == "transform"
        assert ArtifactDomain.CONCURRENCY.value == "concurrency"
        assert ArtifactDomain.API.value == "api"
        assert ArtifactDomain.MESSAGING.value == "messaging"


class TestSeverity:
    """Tests for Severity enum."""

    def test_all_severities_exist(self) -> None:
        """All 4 severity levels should be defined."""
        expected = {"critical", "error", "warning", "info"}
        actual = {s.value for s in Severity}
        assert actual == expected

    def test_severity_values(self) -> None:
        """Severity values should match expected strings."""
        assert Severity.CRITICAL.value == "critical"
        assert Severity.ERROR.value == "error"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"


class TestVerdictDecision:
    """Tests for VerdictDecision enum."""

    def test_all_verdicts_exist(self) -> None:
        """All 3 verdict decisions should be defined."""
        expected = {"ACCEPT", "REJECT", "UNCERTAIN"}
        actual = {v.value for v in VerdictDecision}
        assert actual == expected

    def test_verdict_values(self) -> None:
        """Verdict values should match expected strings."""
        assert VerdictDecision.ACCEPT.value == "ACCEPT"
        assert VerdictDecision.REJECT.value == "REJECT"
        assert VerdictDecision.UNCERTAIN.value == "UNCERTAIN"


# =============================================================================
# Dataclass Tests
# =============================================================================


class TestDomainConfidence:
    """Tests for DomainConfidence dataclass."""

    def test_basic_creation(self) -> None:
        """Should create DomainConfidence with required fields."""
        dc = DomainConfidence(domain=ArtifactDomain.SECURITY, confidence=0.85)
        assert dc.domain == ArtifactDomain.SECURITY
        assert dc.confidence == 0.85
        assert dc.signals == []

    def test_with_signals(self) -> None:
        """Should create DomainConfidence with signals."""
        dc = DomainConfidence(
            domain=ArtifactDomain.CONCURRENCY,
            confidence=0.9,
            signals=["goroutine", "mutex", "channel"],
        )
        assert dc.signals == ["goroutine", "mutex", "channel"]

    def test_immutability(self) -> None:
        """Frozen dataclass should be immutable."""
        dc = DomainConfidence(domain=ArtifactDomain.API, confidence=0.75)
        with pytest.raises(AttributeError):
            dc.confidence = 0.5  # type: ignore[misc]

    def test_repr(self) -> None:
        """Should have readable repr with truncated fields."""
        dc = DomainConfidence(domain=ArtifactDomain.SECURITY, confidence=0.85)
        repr_str = repr(dc)
        assert "DomainConfidence" in repr_str
        assert "security" in repr_str
        assert "0.85" in repr_str


class TestDomainDetectionResult:
    """Tests for DomainDetectionResult dataclass."""

    def test_basic_creation(self) -> None:
        """Should create DomainDetectionResult with required fields."""
        dc = DomainConfidence(domain=ArtifactDomain.API, confidence=0.9)
        result = DomainDetectionResult(
            domains=[dc],
            reasoning="Contains HTTP endpoints and webhook handlers",
        )
        assert len(result.domains) == 1
        assert result.ambiguity == "none"

    def test_with_ambiguity(self) -> None:
        """Should create with ambiguity level."""
        result = DomainDetectionResult(
            domains=[],
            reasoning="Unclear domain",
            ambiguity="high",
        )
        assert result.ambiguity == "high"

    def test_immutability(self) -> None:
        """Frozen dataclass should be immutable."""
        result = DomainDetectionResult(domains=[], reasoning="test")
        with pytest.raises(AttributeError):
            result.reasoning = "changed"  # type: ignore[misc]

    def test_repr_truncates_reasoning(self) -> None:
        """Repr should truncate long reasoning."""
        long_reasoning = "a" * 100
        result = DomainDetectionResult(domains=[], reasoning=long_reasoning)
        repr_str = repr(result)
        assert "..." in repr_str


class TestEvidence:
    """Tests for Evidence dataclass."""

    def test_basic_creation(self) -> None:
        """Should create Evidence with required fields."""
        ev = Evidence(quote="func foo() {}")
        assert ev.quote == "func foo() {}"
        assert ev.line_number is None
        assert ev.source == ""
        assert ev.confidence == 1.0

    def test_full_creation(self) -> None:
        """Should create Evidence with all fields."""
        ev = Evidence(
            quote="mutex.Lock()",
            line_number=42,
            source="src/main.go",
            confidence=0.95,
        )
        assert ev.line_number == 42
        assert ev.source == "src/main.go"
        assert ev.confidence == 0.95

    def test_immutability(self) -> None:
        """Frozen dataclass should be immutable."""
        ev = Evidence(quote="test")
        with pytest.raises(AttributeError):
            ev.quote = "changed"  # type: ignore[misc]

    def test_repr_truncates_quote(self) -> None:
        """Repr should truncate long quotes."""
        long_quote = "a" * 50
        ev = Evidence(quote=long_quote)
        repr_str = repr(ev)
        assert "..." in repr_str


class TestPattern:
    """Tests for Pattern dataclass."""

    def test_basic_creation(self) -> None:
        """Should create Pattern with required fields."""
        pattern = Pattern(
            id=PatternId("CC-001"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=["go func(", "sync.Mutex"],
            severity=Severity.ERROR,
        )
        assert pattern.id == "CC-001"
        assert pattern.description is None

    def test_with_description(self) -> None:
        """Should create Pattern with optional description."""
        pattern = Pattern(
            id=PatternId("SEC-001"),
            domain=ArtifactDomain.SECURITY,
            signals=["md5", "sha1"],
            severity=Severity.CRITICAL,
            description="Weak cryptographic algorithm detected",
        )
        assert pattern.description == "Weak cryptographic algorithm detected"

    def test_immutability(self) -> None:
        """Frozen dataclass should be immutable."""
        pattern = Pattern(
            id=PatternId("CC-001"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=["test"],
            severity=Severity.WARNING,
        )
        with pytest.raises(AttributeError):
            pattern.signals = []  # type: ignore[misc]


class TestFinding:
    """Tests for Finding dataclass."""

    def test_basic_creation(self) -> None:
        """Should create Finding with required fields."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Race condition detected",
            description="Concurrent access to shared variable without lock",
            method_id=MethodId("#153"),
        )
        assert finding.id == "F1"
        assert finding.pattern_id is None
        assert finding.domain is None
        assert finding.evidence == []

    def test_full_creation(self) -> None:
        """Should create Finding with all fields."""
        ev = Evidence(quote="x += 1", line_number=42)
        finding = Finding(
            id="F2",
            severity=Severity.CRITICAL,
            title="SQL injection vulnerability",
            description="User input directly concatenated into SQL query",
            method_id=MethodId("#201"),
            pattern_id=PatternId("SEC-004"),
            domain=ArtifactDomain.SECURITY,
            evidence=[ev],
        )
        assert finding.pattern_id == "SEC-004"
        assert finding.domain == ArtifactDomain.SECURITY
        assert len(finding.evidence) == 1

    def test_immutability(self) -> None:
        """Frozen dataclass should be immutable."""
        finding = Finding(
            id="F1",
            severity=Severity.WARNING,
            title="test",
            description="test",
            method_id=MethodId("#153"),
        )
        with pytest.raises(AttributeError):
            finding.title = "changed"  # type: ignore[misc]

    def test_repr_truncates_title(self) -> None:
        """Repr should truncate long titles."""
        long_title = "a" * 50
        finding = Finding(
            id="F1",
            severity=Severity.INFO,
            title=long_title,
            description="test",
            method_id=MethodId("#153"),
        )
        repr_str = repr(finding)
        assert "..." in repr_str


class TestVerdict:
    """Tests for Verdict dataclass."""

    def test_basic_creation(self) -> None:
        """Should create Verdict with required fields."""
        verdict = Verdict(
            decision=VerdictDecision.ACCEPT,
            score=-4.0,
            findings=[],
            domains_detected=[],
            methods_executed=[],
            summary="All checks passed",
        )
        assert verdict.decision == VerdictDecision.ACCEPT
        assert verdict.score == -4.0

    def test_with_findings(self) -> None:
        """Should create Verdict with findings."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Test finding",
            description="Test description",
            method_id=MethodId("#153"),
        )
        verdict = Verdict(
            decision=VerdictDecision.REJECT,
            score=8.0,
            findings=[finding],
            domains_detected=[DomainConfidence(ArtifactDomain.SECURITY, 0.9)],
            methods_executed=[MethodId("#153"), MethodId("#201")],
            summary="Critical issues found",
        )
        assert len(verdict.findings) == 1
        assert len(verdict.methods_executed) == 2

    def test_immutability(self) -> None:
        """Frozen dataclass should be immutable."""
        verdict = Verdict(
            decision=VerdictDecision.UNCERTAIN,
            score=0.0,
            findings=[],
            domains_detected=[],
            methods_executed=[],
            summary="test",
        )
        with pytest.raises(AttributeError):
            verdict.score = 1.0  # type: ignore[misc]

    def test_repr_truncates_summary(self) -> None:
        """Repr should truncate long summary."""
        long_summary = "a" * 60
        verdict = Verdict(
            decision=VerdictDecision.ACCEPT,
            score=-4.0,
            findings=[],
            domains_detected=[],
            methods_executed=[],
            summary=long_summary,
        )
        repr_str = repr(verdict)
        assert "..." in repr_str


class TestDeepVerifyValidationResult:
    """Tests for DeepVerifyValidationResult dataclass."""

    def test_basic_creation(self) -> None:
        """Should create DeepVerifyValidationResult with required fields."""
        result = DeepVerifyValidationResult(
            findings=[],
            domains_detected=[],
            methods_executed=[],
            verdict=VerdictDecision.ACCEPT,
            score=-4.0,
            duration_ms=1500,
        )
        assert result.verdict == VerdictDecision.ACCEPT
        assert result.score == -4.0
        assert result.duration_ms == 1500
        assert result.error is None

    def test_with_error(self) -> None:
        """Should create with error message."""
        result = DeepVerifyValidationResult(
            findings=[],
            domains_detected=[],
            methods_executed=[],
            verdict=VerdictDecision.UNCERTAIN,
            score=0.0,
            duration_ms=0,
            error="LLM API timeout",
        )
        assert result.error == "LLM API timeout"

    def test_immutability(self) -> None:
        """Frozen dataclass should be immutable."""
        result = DeepVerifyValidationResult(
            findings=[],
            domains_detected=[],
            methods_executed=[],
            verdict=VerdictDecision.ACCEPT,
            score=-4.0,
            duration_ms=1000,
        )
        with pytest.raises(AttributeError):
            result.duration_ms = 2000  # type: ignore[misc]

    def test_repr_with_error(self) -> None:
        """Repr should include error if present."""
        result = DeepVerifyValidationResult(
            findings=[],
            domains_detected=[],
            methods_executed=[],
            verdict=VerdictDecision.ACCEPT,
            score=-4.0,
            duration_ms=1000,
            error="test error",
        )
        repr_str = repr(result)
        assert "error=" in repr_str


# =============================================================================
# Serialization Tests
# =============================================================================


class TestEvidenceSerialization:
    """Tests for Evidence serialization."""

    def test_round_trip(self) -> None:
        """Serialize then deserialize should preserve equality."""
        from bmad_assist.deep_verify.core.types import (
            deserialize_evidence,
            serialize_evidence,
        )

        original = Evidence(
            quote="mutex.Lock()",
            line_number=42,
            source="src/main.go",
            confidence=0.95,
        )
        serialized = serialize_evidence(original)
        deserialized = deserialize_evidence(serialized)

        assert deserialized.quote == original.quote
        assert deserialized.line_number == original.line_number
        assert deserialized.source == original.source
        assert deserialized.confidence == original.confidence

    def test_defaults(self) -> None:
        """Deserialize should apply defaults for missing fields."""
        from bmad_assist.deep_verify.core.types import deserialize_evidence

        data = {"quote": "test"}
        ev = deserialize_evidence(data)
        assert ev.line_number is None
        assert ev.source == ""
        assert ev.confidence == 1.0


class TestDomainConfidenceSerialization:
    """Tests for DomainConfidence serialization."""

    def test_round_trip(self) -> None:
        """Serialize then deserialize should preserve equality."""
        from bmad_assist.deep_verify.core.types import (
            deserialize_domain_confidence,
            serialize_domain_confidence,
        )

        original = DomainConfidence(
            domain=ArtifactDomain.CONCURRENCY,
            confidence=0.9,
            signals=["goroutine", "mutex"],
        )
        serialized = serialize_domain_confidence(original)
        deserialized = deserialize_domain_confidence(serialized)

        assert deserialized.domain == original.domain
        assert deserialized.confidence == original.confidence
        assert deserialized.signals == original.signals


class TestFindingSerialization:
    """Tests for Finding serialization."""

    def test_round_trip_basic(self) -> None:
        """Serialize then deserialize should preserve equality."""
        original = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Test finding",
            description="Test description",
            method_id=MethodId("#153"),
        )
        serialized = serialize_finding(original)
        deserialized = deserialize_finding(serialized)

        assert deserialized.id == original.id
        assert deserialized.severity == original.severity
        assert deserialized.title == original.title
        assert deserialized.description == original.description
        assert deserialized.method_id == original.method_id
        assert deserialized.pattern_id is None
        assert deserialized.domain is None

    def test_round_trip_full(self) -> None:
        """Serialize then deserialize with all fields."""
        ev = Evidence(quote="test", line_number=10, confidence=0.9)
        original = Finding(
            id="F2",
            severity=Severity.CRITICAL,
            title="Critical issue",
            description="Detailed description",
            method_id=MethodId("#201"),
            pattern_id=PatternId("SEC-001"),
            domain=ArtifactDomain.SECURITY,
            evidence=[ev],
        )
        serialized = serialize_finding(original)
        deserialized = deserialize_finding(serialized)

        assert deserialized.pattern_id == original.pattern_id
        assert deserialized.domain == original.domain
        assert len(deserialized.evidence) == 1
        assert deserialized.evidence[0].quote == ev.quote


class TestVerdictSerialization:
    """Tests for Verdict serialization."""

    def test_round_trip(self) -> None:
        """Serialize then deserialize should preserve equality."""
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Test",
            description="Test",
            method_id=MethodId("#153"),
        )
        dc = DomainConfidence(domain=ArtifactDomain.API, confidence=0.8)
        original = Verdict(
            decision=VerdictDecision.REJECT,
            score=8.5,
            findings=[finding],
            domains_detected=[dc],
            methods_executed=[MethodId("#153")],
            summary="Issues found",
        )
        serialized = serialize_verdict(original)
        deserialized = deserialize_verdict(serialized)

        assert deserialized.decision == original.decision
        assert deserialized.score == original.score
        assert len(deserialized.findings) == 1
        assert len(deserialized.domains_detected) == 1
        assert deserialized.methods_executed == original.methods_executed
        assert deserialized.summary == original.summary


class TestValidationResultSerialization:
    """Tests for DeepVerifyValidationResult serialization."""

    def test_round_trip(self) -> None:
        """Serialize then deserialize should preserve equality."""
        from bmad_assist.deep_verify.core.types import (
            deserialize_validation_result,
            serialize_validation_result,
        )

        original = DeepVerifyValidationResult(
            findings=[],
            domains_detected=[DomainConfidence(ArtifactDomain.SECURITY, 0.9)],
            methods_executed=[MethodId("#153")],
            verdict=VerdictDecision.ACCEPT,
            score=-4.0,
            duration_ms=1500,
            error=None,
        )
        serialized = serialize_validation_result(original)
        deserialized = deserialize_validation_result(serialized)

        assert deserialized.verdict == original.verdict
        assert deserialized.score == original.score
        assert deserialized.duration_ms == original.duration_ms
        assert deserialized.error == original.error

    def test_with_error(self) -> None:
        """Round trip with error message."""
        from bmad_assist.deep_verify.core.types import (
            deserialize_validation_result,
            serialize_validation_result,
        )

        original = DeepVerifyValidationResult(
            findings=[],
            domains_detected=[],
            methods_executed=[],
            verdict=VerdictDecision.UNCERTAIN,
            score=0.0,
            duration_ms=0,
            error="API timeout",
        )
        serialized = serialize_validation_result(original)
        deserialized = deserialize_validation_result(serialized)

        assert deserialized.error == "API timeout"


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge case tests for types."""

    def test_empty_evidence_list(self) -> None:
        """Finding can have empty evidence list."""
        finding = Finding(
            id="F1",
            severity=Severity.WARNING,
            title="Warning",
            description="No evidence provided",
            method_id=MethodId("#154"),
            evidence=[],
        )
        assert finding.evidence == []

    def test_multiple_evidence(self) -> None:
        """Finding can have multiple evidence items."""
        ev1 = Evidence(quote="line 1", line_number=10)
        ev2 = Evidence(quote="line 2", line_number=20)
        finding = Finding(
            id="F1",
            severity=Severity.ERROR,
            title="Error",
            description="Multiple evidence",
            method_id=MethodId("#153"),
            evidence=[ev1, ev2],
        )
        assert len(finding.evidence) == 2

    def test_unicode_in_strings(self) -> None:
        """Should handle unicode in text fields."""
        finding = Finding(
            id="F1",
            severity=Severity.INFO,
            title="Unicode test: ñoño 🚀",
            description="Description with unicode: 日本語",
            method_id=MethodId("#153"),
        )
        assert "ñoño" in finding.title
        assert "日本語" in finding.description

    def test_multiline_description(self) -> None:
        """Should handle multiline descriptions."""
        desc = """Line 1
        Line 2
        Line 3"""
        finding = Finding(
            id="F1",
            severity=Severity.WARNING,
            title="Multiline",
            description=desc,
            method_id=MethodId("#153"),
        )
        assert finding.description == desc

    def test_special_chars_in_quotes(self) -> None:
        """Evidence quote can contain special characters."""
        quote = 'if x < 0 && y > 10 { return "error" }'
        ev = Evidence(quote=quote)
        assert ev.quote == quote
