"""Tests for pattern-specific types."""

import pytest

from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    Pattern,
    PatternId,
    Severity,
    Signal,
    deserialize_pattern,
    deserialize_signal,
    serialize_pattern,
    serialize_signal,
)
from bmad_assist.deep_verify.patterns.types import (
    MatchedSignal,
    PatternMatchResult,
    deserialize_match_result,
    deserialize_matched_signal,
    serialize_match_result,
    serialize_matched_signal,
)


class TestSignal:
    """Tests for Signal dataclass."""

    def test_signal_creation_exact(self) -> None:
        """Test creating an exact match signal."""
        signal = Signal(type="exact", pattern="race condition")
        assert signal.type == "exact"
        assert signal.pattern == "race condition"
        assert signal.weight == 1.0

    def test_signal_creation_regex(self) -> None:
        """Test creating a regex match signal."""
        signal = Signal(type="regex", pattern=r"\bgo\s+func\(", weight=2.0)
        assert signal.type == "regex"
        assert signal.pattern == r"\bgo\s+func\("
        assert signal.weight == 2.0

    def test_signal_repr(self) -> None:
        """Test Signal repr."""
        signal = Signal(type="exact", pattern="test")
        assert "Signal" in repr(signal)
        assert "exact" in repr(signal)
        assert "test" in repr(signal)

    def test_signal_repr_with_weight(self) -> None:
        """Test Signal repr with custom weight."""
        signal = Signal(type="exact", pattern="test", weight=2.5)
        assert "weight=2.5" in repr(signal)

    def test_signal_immutable(self) -> None:
        """Test that Signal is immutable (frozen dataclass)."""
        signal = Signal(type="exact", pattern="test")
        with pytest.raises(Exception):  # FrozenInstanceError
            signal.pattern = "modified"  # type: ignore[misc]


class TestMatchedSignal:
    """Tests for MatchedSignal dataclass."""

    def test_matched_signal_creation(self) -> None:
        """Test creating a MatchedSignal."""
        signal = Signal(type="exact", pattern="race condition")
        matched = MatchedSignal(
            signal=signal,
            line_number=42,
            matched_text="race condition detected",
        )
        assert matched.signal == signal
        assert matched.line_number == 42
        assert matched.matched_text == "race condition detected"

    def test_matched_signal_repr(self) -> None:
        """Test MatchedSignal repr."""
        signal = Signal(type="exact", pattern="test")
        matched = MatchedSignal(signal=signal, line_number=5, matched_text="test content")
        repr_str = repr(matched)
        assert "MatchedSignal" in repr_str
        assert "line=5" in repr_str

    def test_matched_signal_repr_long_text(self) -> None:
        """Test MatchedSignal repr truncates long text."""
        signal = Signal(type="exact", pattern="test")
        long_text = "x" * 100
        matched = MatchedSignal(signal=signal, line_number=1, matched_text=long_text)
        repr_str = repr(matched)
        assert "..." in repr_str
        assert len(repr_str) < len(long_text) + 50


class TestPatternMatchResult:
    """Tests for PatternMatchResult dataclass."""

    def test_result_creation(self) -> None:
        """Test creating a PatternMatchResult."""
        pattern = Pattern(
            id=PatternId("CC-001"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[],
            severity=Severity.CRITICAL,
        )
        result = PatternMatchResult(
            pattern=pattern,
            confidence=0.75,
            matched_signals=[],
            unmatched_signals=[],
        )
        assert result.pattern == pattern
        assert result.confidence == 0.75
        assert result.matched_signals == []
        assert result.unmatched_signals == []

    def test_result_repr(self) -> None:
        """Test PatternMatchResult repr."""
        pattern = Pattern(
            id=PatternId("CC-001"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[],
            severity=Severity.CRITICAL,
        )
        result = PatternMatchResult(
            pattern=pattern,
            confidence=0.75,
            matched_signals=[],
            unmatched_signals=[],
        )
        repr_str = repr(result)
        assert "PatternMatchResult" in repr_str
        assert "CC-001" in repr_str
        assert "0.75" in repr_str


class TestSignalSerialization:
    """Tests for Signal serialization."""

    def test_serialize_exact_signal(self) -> None:
        """Test serializing an exact signal."""
        signal = Signal(type="exact", pattern="race condition")
        data = serialize_signal(signal)
        assert data == {
            "type": "exact",
            "pattern": "race condition",
            "weight": 1.0,
        }

    def test_serialize_regex_signal(self) -> None:
        """Test serializing a regex signal."""
        signal = Signal(type="regex", pattern=r"\bgo\s+func\(", weight=2.0)
        data = serialize_signal(signal)
        assert data == {
            "type": "regex",
            "pattern": r"\bgo\s+func\(",
            "weight": 2.0,
        }

    def test_deserialize_exact_signal(self) -> None:
        """Test deserializing an exact signal."""
        data = {"type": "exact", "pattern": "race condition", "weight": 1.0}
        signal = deserialize_signal(data)
        assert signal.type == "exact"
        assert signal.pattern == "race condition"
        assert signal.weight == 1.0

    def test_deserialize_missing_weight(self) -> None:
        """Test deserializing signal without weight defaults to 1.0."""
        data = {"type": "exact", "pattern": "test"}
        signal = deserialize_signal(data)
        assert signal.weight == 1.0

    def test_round_trip_signal(self) -> None:
        """Test round-trip serialization of Signal."""
        original = Signal(type="regex", pattern=r"\btest\b", weight=1.5)
        data = serialize_signal(original)
        restored = deserialize_signal(data)
        assert original == restored


class TestPatternSerialization:
    """Tests for Pattern serialization."""

    def test_serialize_pattern(self) -> None:
        """Test serializing a pattern."""
        pattern = Pattern(
            id=PatternId("CC-001"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[
                Signal(type="exact", pattern="race condition"),
                Signal(type="regex", pattern=r"\bgo\s+func\("),
            ],
            severity=Severity.CRITICAL,
            description="Race condition pattern",
            remediation="Use mutex",
        )
        data = serialize_pattern(pattern)
        assert data["id"] == "CC-001"
        assert data["domain"] == "concurrency"
        assert data["severity"] == "critical"
        assert data["description"] == "Race condition pattern"
        assert data["remediation"] == "Use mutex"
        assert len(data["signals"]) == 2

    def test_deserialize_pattern(self) -> None:
        """Test deserializing a pattern."""
        data = {
            "id": "CC-001",
            "domain": "concurrency",
            "severity": "critical",
            "signals": [
                {"type": "exact", "pattern": "race condition", "weight": 1.0},
            ],
            "description": "Race condition pattern",
            "remediation": "Use mutex",
        }
        pattern = deserialize_pattern(data)
        assert pattern.id == PatternId("CC-001")
        assert pattern.domain == ArtifactDomain.CONCURRENCY
        assert pattern.severity == Severity.CRITICAL
        assert len(pattern.signals) == 1
        assert pattern.signals[0].pattern == "race condition"

    def test_round_trip_pattern(self) -> None:
        """Test round-trip serialization of Pattern."""
        original = Pattern(
            id=PatternId("SEC-001"),
            domain=ArtifactDomain.SECURITY,
            signals=[Signal(type="exact", pattern="timing attack")],
            severity=Severity.ERROR,
            description="Timing attack vulnerability",
        )
        data = serialize_pattern(original)
        restored = deserialize_pattern(data)
        assert original.id == restored.id
        assert original.domain == restored.domain
        assert original.severity == restored.severity
        assert original.description == restored.description


class TestMatchedSignalSerialization:
    """Tests for MatchedSignal serialization."""

    def test_serialize_matched_signal(self) -> None:
        """Test serializing a MatchedSignal."""
        signal = Signal(type="exact", pattern="race condition")
        matched = MatchedSignal(
            signal=signal,
            line_number=42,
            matched_text="race condition detected",
        )
        data = serialize_matched_signal(matched)
        assert data["line_number"] == 42
        assert data["matched_text"] == "race condition detected"
        assert data["signal"]["type"] == "exact"

    def test_deserialize_matched_signal(self) -> None:
        """Test deserializing a MatchedSignal."""
        data = {
            "signal": {"type": "exact", "pattern": "test", "weight": 1.0},
            "line_number": 10,
            "matched_text": "test found",
        }
        matched = deserialize_matched_signal(data)
        assert matched.line_number == 10
        assert matched.matched_text == "test found"
        assert matched.signal.pattern == "test"


class TestPatternMatchResultSerialization:
    """Tests for PatternMatchResult serialization."""

    def test_serialize_match_result(self) -> None:
        """Test serializing a PatternMatchResult."""
        pattern = Pattern(
            id=PatternId("CC-001"),
            domain=ArtifactDomain.CONCURRENCY,
            signals=[Signal(type="exact", pattern="race")],
            severity=Severity.CRITICAL,
        )
        signal = Signal(type="exact", pattern="race")
        matched = MatchedSignal(signal=signal, line_number=5, matched_text="race found")
        result = PatternMatchResult(
            pattern=pattern,
            confidence=1.0,
            matched_signals=[matched],
            unmatched_signals=[],
        )
        data = serialize_match_result(result)
        assert data["confidence"] == 1.0
        assert data["pattern"]["id"] == "CC-001"
        assert len(data["matched_signals"]) == 1
        assert data["matched_signals"][0]["line_number"] == 5

    def test_deserialize_match_result(self) -> None:
        """Test deserializing a PatternMatchResult."""
        data = {
            "pattern": {
                "id": "CC-001",
                "domain": "concurrency",
                "severity": "critical",
                "signals": [{"type": "exact", "pattern": "race", "weight": 1.0}],
                "description": None,
                "remediation": None,
            },
            "confidence": 0.75,
            "matched_signals": [
                {
                    "signal": {"type": "exact", "pattern": "race", "weight": 1.0},
                    "line_number": 5,
                    "matched_text": "race condition",
                }
            ],
            "unmatched_signals": [],
        }
        result = deserialize_match_result(data)
        assert result.confidence == 0.75
        assert result.pattern.id == PatternId("CC-001")
        assert len(result.matched_signals) == 1
        assert result.matched_signals[0].line_number == 5
