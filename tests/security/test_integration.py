"""Tests for security findings cache integration.

Covers:
- save_security_findings_for_synthesis creates correct cache file
- load_security_findings_from_cache loads and deserializes correctly
- Round-trip: save -> load -> compare
- Load with missing cache file returns None
- Load with corrupt JSON returns None
- Session ID used in filename pattern
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bmad_assist.security.integration import (
    load_security_findings_from_cache,
    save_security_findings_for_synthesis,
)
from bmad_assist.security.report import SecurityFinding, SecurityReport

# =============================================================================
# Fixtures
# =============================================================================


def _make_finding(
    id: str = "SEC-001",
    severity: str = "HIGH",
    confidence: float = 0.9,
) -> SecurityFinding:
    """Create a test SecurityFinding with sensible defaults."""
    return SecurityFinding(
        id=id,
        file_path="src/app.py",
        line_number=42,
        cwe_id="CWE-89",
        severity=severity,
        title=f"Test finding {id}",
        description=f"Description for {id}",
        remediation=f"Fix for {id}",
        confidence=confidence,
    )


def _make_report(
    findings: list[SecurityFinding] | None = None,
) -> SecurityReport:
    """Create a test SecurityReport."""
    if findings is None:
        findings = [
            _make_finding("SEC-001", "HIGH", 0.9),
            _make_finding("SEC-002", "MEDIUM", 0.7),
            _make_finding("SEC-003", "LOW", 0.5),
        ]
    return SecurityReport(
        findings=findings,
        languages_detected=["python", "javascript"],
        patterns_loaded=150,
        scan_duration_seconds=12.5,
        timed_out=False,
    )


# =============================================================================
# Save Tests
# =============================================================================


class TestSaveSecurityFindings:
    """Test save_security_findings_for_synthesis function."""

    def test_creates_cache_file(self, tmp_path: Path) -> None:
        """Test save creates the cache file at expected path."""
        report = _make_report()
        session_id = "abc-123"

        result_path = save_security_findings_for_synthesis(
            report, tmp_path, session_id
        )

        assert result_path.exists()
        assert result_path.is_file()

    def test_cache_file_path_pattern(self, tmp_path: Path) -> None:
        """Test cache file is at .bmad-assist/cache/security-{session_id}.json."""
        report = _make_report()
        session_id = "test-session-42"

        result_path = save_security_findings_for_synthesis(
            report, tmp_path, session_id
        )

        expected = tmp_path / ".bmad-assist" / "cache" / "security-test-session-42.json"
        assert result_path == expected

    def test_creates_cache_directory(self, tmp_path: Path) -> None:
        """Test save creates .bmad-assist/cache/ directory if missing."""
        report = _make_report()
        session_id = "dir-test"

        cache_dir = tmp_path / ".bmad-assist" / "cache"
        assert not cache_dir.exists()

        save_security_findings_for_synthesis(report, tmp_path, session_id)

        assert cache_dir.exists()
        assert cache_dir.is_dir()

    def test_saved_content_is_valid_json(self, tmp_path: Path) -> None:
        """Test saved file contains valid JSON."""
        report = _make_report()
        session_id = "json-check"

        result_path = save_security_findings_for_synthesis(
            report, tmp_path, session_id
        )

        content = result_path.read_text(encoding="utf-8")
        data = json.loads(content)
        assert isinstance(data, dict)

    def test_saved_content_includes_session_id(self, tmp_path: Path) -> None:
        """Test saved JSON includes the session_id field."""
        report = _make_report()
        session_id = "sess-789"

        result_path = save_security_findings_for_synthesis(
            report, tmp_path, session_id
        )

        data = json.loads(result_path.read_text(encoding="utf-8"))
        assert data["session_id"] == "sess-789"

    def test_saved_content_includes_findings(self, tmp_path: Path) -> None:
        """Test saved JSON includes findings data."""
        report = _make_report()
        session_id = "findings-check"

        result_path = save_security_findings_for_synthesis(
            report, tmp_path, session_id
        )

        data = json.loads(result_path.read_text(encoding="utf-8"))
        assert "findings" in data
        assert len(data["findings"]) == 3
        assert data["findings"][0]["id"] == "SEC-001"

    def test_saved_content_includes_metadata(self, tmp_path: Path) -> None:
        """Test saved JSON includes report metadata fields."""
        report = _make_report()
        session_id = "meta-check"

        result_path = save_security_findings_for_synthesis(
            report, tmp_path, session_id
        )

        data = json.loads(result_path.read_text(encoding="utf-8"))
        assert data["languages_detected"] == ["python", "javascript"]
        assert data["patterns_loaded"] == 150
        assert data["scan_duration_seconds"] == 12.5
        assert data["timed_out"] is False

    def test_empty_report(self, tmp_path: Path) -> None:
        """Test save works with empty report (no findings)."""
        report = SecurityReport()
        session_id = "empty-report"

        result_path = save_security_findings_for_synthesis(
            report, tmp_path, session_id
        )

        data = json.loads(result_path.read_text(encoding="utf-8"))
        assert data["findings"] == []
        assert data["languages_detected"] == []

    def test_session_id_with_special_characters(self, tmp_path: Path) -> None:
        """Test session_id with various characters works in filename."""
        report = _make_report()
        session_id = "run-2026-02-06T12-00-00Z"

        result_path = save_security_findings_for_synthesis(
            report, tmp_path, session_id
        )

        expected_name = "security-run-2026-02-06T12-00-00Z.json"
        assert result_path.name == expected_name
        assert result_path.exists()


# =============================================================================
# Load Tests
# =============================================================================


class TestLoadSecurityFindings:
    """Test load_security_findings_from_cache function."""

    def test_load_returns_security_report(self, tmp_path: Path) -> None:
        """Test load returns a SecurityReport instance."""
        report = _make_report()
        session_id = "load-test"
        save_security_findings_for_synthesis(report, tmp_path, session_id)

        result = load_security_findings_from_cache(session_id, tmp_path)

        assert isinstance(result, SecurityReport)

    def test_missing_cache_returns_none(self, tmp_path: Path) -> None:
        """Test load with non-existent cache file returns None."""
        result = load_security_findings_from_cache("nonexistent", tmp_path)
        assert result is None

    def test_missing_cache_dir_returns_none(self, tmp_path: Path) -> None:
        """Test load with non-existent cache directory returns None."""
        # Don't create .bmad-assist/cache/ at all
        result = load_security_findings_from_cache("no-dir", tmp_path)
        assert result is None

    def test_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        """Test load with corrupt JSON file returns None."""
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "security-corrupt.json"
        cache_file.write_text("{{not valid json", encoding="utf-8")

        result = load_security_findings_from_cache("corrupt", tmp_path)
        assert result is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        """Test load with empty file returns None."""
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "security-empty.json"
        cache_file.write_text("", encoding="utf-8")

        result = load_security_findings_from_cache("empty", tmp_path)
        assert result is None

    def test_invalid_structure_returns_none(self, tmp_path: Path) -> None:
        """Test load with valid JSON but invalid structure returns None."""
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "security-bad-struct.json"
        # Valid JSON but findings has invalid data (missing required fields)
        cache_file.write_text(
            json.dumps({"findings": [{"not_a_field": True}]}),
            encoding="utf-8",
        )

        result = load_security_findings_from_cache("bad-struct", tmp_path)
        assert result is None

    def test_session_id_stripped_from_loaded_data(self, tmp_path: Path) -> None:
        """Test session_id metadata is removed before deserialization."""
        report = _make_report()
        session_id = "strip-test"
        save_security_findings_for_synthesis(report, tmp_path, session_id)

        result = load_security_findings_from_cache(session_id, tmp_path)

        # SecurityReport should not have a session_id attribute
        assert result is not None
        assert not hasattr(result, "session_id") or "session_id" not in result.model_fields


# =============================================================================
# Round-Trip Tests
# =============================================================================


class TestRoundTrip:
    """Test save -> load round-trip preserves data."""

    def test_findings_preserved(self, tmp_path: Path) -> None:
        """Test findings are preserved through save/load cycle."""
        original = _make_report()
        session_id = "roundtrip-findings"

        save_security_findings_for_synthesis(original, tmp_path, session_id)
        loaded = load_security_findings_from_cache(session_id, tmp_path)

        assert loaded is not None
        assert len(loaded.findings) == len(original.findings)
        for orig_f, load_f in zip(original.findings, loaded.findings):
            assert orig_f.id == load_f.id
            assert orig_f.file_path == load_f.file_path
            assert orig_f.line_number == load_f.line_number
            assert orig_f.cwe_id == load_f.cwe_id
            assert orig_f.severity == load_f.severity
            assert orig_f.title == load_f.title
            assert orig_f.description == load_f.description
            assert orig_f.remediation == load_f.remediation
            assert orig_f.confidence == load_f.confidence

    def test_metadata_preserved(self, tmp_path: Path) -> None:
        """Test report metadata is preserved through save/load cycle."""
        original = _make_report()
        session_id = "roundtrip-meta"

        save_security_findings_for_synthesis(original, tmp_path, session_id)
        loaded = load_security_findings_from_cache(session_id, tmp_path)

        assert loaded is not None
        assert loaded.languages_detected == original.languages_detected
        assert loaded.patterns_loaded == original.patterns_loaded
        assert loaded.scan_duration_seconds == original.scan_duration_seconds
        assert loaded.timed_out == original.timed_out

    def test_empty_report_roundtrip(self, tmp_path: Path) -> None:
        """Test empty report survives round-trip."""
        original = SecurityReport()
        session_id = "roundtrip-empty"

        save_security_findings_for_synthesis(original, tmp_path, session_id)
        loaded = load_security_findings_from_cache(session_id, tmp_path)

        assert loaded is not None
        assert loaded.findings == []
        assert loaded.languages_detected == []
        assert loaded.patterns_loaded == 0
        assert loaded.scan_duration_seconds == 0.0
        assert loaded.timed_out is False

    def test_timed_out_report_roundtrip(self, tmp_path: Path) -> None:
        """Test timed_out=True is preserved."""
        original = SecurityReport(
            findings=[_make_finding()],
            languages_detected=["go"],
            patterns_loaded=50,
            scan_duration_seconds=300.0,
            timed_out=True,
        )
        session_id = "roundtrip-timeout"

        save_security_findings_for_synthesis(original, tmp_path, session_id)
        loaded = load_security_findings_from_cache(session_id, tmp_path)

        assert loaded is not None
        assert loaded.timed_out is True
        assert loaded.scan_duration_seconds == 300.0

    def test_multiple_sessions_independent(self, tmp_path: Path) -> None:
        """Test multiple sessions do not interfere with each other."""
        report_a = _make_report([_make_finding("SEC-A01", "HIGH", 0.95)])
        report_b = _make_report([_make_finding("SEC-B01", "LOW", 0.3)])

        save_security_findings_for_synthesis(report_a, tmp_path, "session-a")
        save_security_findings_for_synthesis(report_b, tmp_path, "session-b")

        loaded_a = load_security_findings_from_cache("session-a", tmp_path)
        loaded_b = load_security_findings_from_cache("session-b", tmp_path)

        assert loaded_a is not None
        assert loaded_b is not None
        assert len(loaded_a.findings) == 1
        assert loaded_a.findings[0].id == "SEC-A01"
        assert len(loaded_b.findings) == 1
        assert loaded_b.findings[0].id == "SEC-B01"


# =============================================================================
# Session ID Filename Tests
# =============================================================================


class TestSessionIdFilename:
    """Test session_id is correctly used in cache filename."""

    def test_simple_session_id(self, tmp_path: Path) -> None:
        """Test simple alphanumeric session ID in filename."""
        report = _make_report([])
        session_id = "abc123"

        result = save_security_findings_for_synthesis(report, tmp_path, session_id)
        assert result.name == "security-abc123.json"

    def test_uuid_session_id(self, tmp_path: Path) -> None:
        """Test UUID-style session ID in filename."""
        report = _make_report([])
        session_id = "550e8400-e29b-41d4-a716-446655440000"

        result = save_security_findings_for_synthesis(report, tmp_path, session_id)
        assert result.name == "security-550e8400-e29b-41d4-a716-446655440000.json"

    def test_load_uses_matching_session_id(self, tmp_path: Path) -> None:
        """Test load matches the exact session_id filename."""
        report = _make_report([])
        save_security_findings_for_synthesis(report, tmp_path, "target-id")
        save_security_findings_for_synthesis(report, tmp_path, "other-id")

        # Loading target-id should not get other-id
        loaded = load_security_findings_from_cache("target-id", tmp_path)
        assert loaded is not None

        # Non-existent session returns None
        missing = load_security_findings_from_cache("wrong-id", tmp_path)
        assert missing is None


# ---------------------------------------------------------------------------
# _normalize_confidence
# ---------------------------------------------------------------------------


class TestNormalizeConfidence:
    """Confidence normalization for LLM outputs (0-100 → 0.0-1.0)."""

    def test_fraction_passthrough(self):
        from bmad_assist.security.agent import _normalize_confidence

        assert _normalize_confidence(0.75) == 0.75

    def test_percentage_normalized(self):
        from bmad_assist.security.agent import _normalize_confidence

        assert _normalize_confidence(85) == pytest.approx(0.85)

    def test_zero(self):
        from bmad_assist.security.agent import _normalize_confidence

        assert _normalize_confidence(0) == 0.0

    def test_one(self):
        from bmad_assist.security.agent import _normalize_confidence

        assert _normalize_confidence(1.0) == 1.0

    def test_over_100_clamped(self):
        from bmad_assist.security.agent import _normalize_confidence

        assert _normalize_confidence(150) == 1.0

    def test_negative_clamped(self):
        from bmad_assist.security.agent import _normalize_confidence

        assert _normalize_confidence(-5) == 0.0

    def test_string_fallback(self):
        from bmad_assist.security.agent import _normalize_confidence

        assert _normalize_confidence("bad") == 0.5

    def test_none_fallback(self):
        from bmad_assist.security.agent import _normalize_confidence

        assert _normalize_confidence(None) == 0.5
