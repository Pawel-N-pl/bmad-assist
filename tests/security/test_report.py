from __future__ import annotations

import pytest
from pydantic import ValidationError

from bmad_assist.security.report import SecurityFinding, SecurityReport

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _make_finding(**overrides) -> SecurityFinding:
    """Build a SecurityFinding with sensible defaults, overriding as needed."""
    defaults = {
        "id": "SEC-001",
        "file_path": "src/app.py",
        "line_number": 42,
        "cwe_id": "CWE-89",
        "severity": "HIGH",
        "title": "SQL Injection",
        "description": "User input in SQL query",
        "remediation": "Use parameterized queries",
        "confidence": 0.9,
    }
    defaults.update(overrides)
    return SecurityFinding(**defaults)


# ---------------------------------------------------------------------------
# SecurityFinding
# ---------------------------------------------------------------------------


class TestSecurityFinding:
    """Tests for the SecurityFinding model."""

    def test_basic_creation(self):
        f = _make_finding()
        assert f.id == "SEC-001"
        assert f.file_path == "src/app.py"
        assert f.line_number == 42
        assert f.cwe_id == "CWE-89"
        assert f.severity == "HIGH"
        assert f.title == "SQL Injection"
        assert f.description == "User input in SQL query"
        assert f.remediation == "Use parameterized queries"
        assert f.confidence == 0.9

    def test_default_line_number_is_zero(self):
        f = SecurityFinding(
            id="SEC-002",
            file_path="main.go",
            cwe_id="CWE-78",
            severity="HIGH",
            title="Command Injection",
            description="Shell command with user input",
            confidence=0.8,
        )
        assert f.line_number == 0

    def test_default_remediation_is_empty(self):
        f = SecurityFinding(
            id="SEC-003",
            file_path="main.go",
            cwe_id="CWE-78",
            severity="HIGH",
            title="Command Injection",
            description="Shell command with user input",
            confidence=0.8,
        )
        assert f.remediation == ""

    def test_confidence_min_zero(self):
        f = _make_finding(confidence=0.0)
        assert f.confidence == 0.0

    def test_confidence_max_one(self):
        f = _make_finding(confidence=1.0)
        assert f.confidence == 1.0

    def test_confidence_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            _make_finding(confidence=-0.1)

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValidationError):
            _make_finding(confidence=1.1)

    def test_frozen_model(self):
        f = _make_finding()
        with pytest.raises(ValidationError):
            f.severity = "LOW"

    def test_model_dump(self):
        f = _make_finding()
        d = f.model_dump()
        assert isinstance(d, dict)
        assert d["id"] == "SEC-001"
        assert d["confidence"] == 0.9

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            SecurityFinding(
                id="SEC-X",
                # file_path missing
                cwe_id="CWE-1",
                severity="LOW",
                title="Missing",
                description="desc",
                confidence=0.5,
            )


# ---------------------------------------------------------------------------
# SecurityReport - basics
# ---------------------------------------------------------------------------


class TestSecurityReport:
    """Tests for SecurityReport creation and basic behavior."""

    def test_empty_report(self):
        r = SecurityReport()
        assert r.findings == []
        assert r.languages_detected == []
        assert r.patterns_loaded == 0
        assert r.scan_duration_seconds == 0.0
        assert r.timed_out is False

    def test_report_with_findings(self):
        findings = [_make_finding(id="SEC-001"), _make_finding(id="SEC-002")]
        r = SecurityReport(
            findings=findings,
            languages_detected=["python"],
            patterns_loaded=20,
            scan_duration_seconds=12.5,
        )
        assert len(r.findings) == 2
        assert r.languages_detected == ["python"]
        assert r.patterns_loaded == 20
        assert r.scan_duration_seconds == 12.5
        assert r.timed_out is False

    def test_timed_out_report(self):
        r = SecurityReport(timed_out=True)
        assert r.timed_out is True

    def test_frozen_model(self):
        r = SecurityReport()
        with pytest.raises(ValidationError):
            r.timed_out = True


# ---------------------------------------------------------------------------
# SecurityReport.to_cache_dict / from_cache_dict
# ---------------------------------------------------------------------------


class TestSecurityReportCaching:
    """Tests for cache serialization round-trips."""

    def test_round_trip_empty_report(self):
        original = SecurityReport()
        data = original.to_cache_dict()
        restored = SecurityReport.from_cache_dict(data)
        assert restored.findings == []
        assert restored.languages_detected == []
        assert restored.patterns_loaded == 0
        assert restored.scan_duration_seconds == 0.0
        assert restored.timed_out is False

    def test_round_trip_with_findings(self):
        findings = [
            _make_finding(id="SEC-001", confidence=0.9, severity="HIGH"),
            _make_finding(id="SEC-002", confidence=0.5, severity="LOW"),
        ]
        original = SecurityReport(
            findings=findings,
            languages_detected=["python", "go"],
            patterns_loaded=35,
            scan_duration_seconds=45.7,
            timed_out=False,
        )
        data = original.to_cache_dict()
        restored = SecurityReport.from_cache_dict(data)

        assert len(restored.findings) == 2
        assert restored.findings[0].id == "SEC-001"
        assert restored.findings[1].id == "SEC-002"
        assert restored.languages_detected == ["python", "go"]
        assert restored.patterns_loaded == 35
        assert restored.scan_duration_seconds == 45.7
        assert restored.timed_out is False

    def test_round_trip_timed_out(self):
        original = SecurityReport(timed_out=True)
        data = original.to_cache_dict()
        restored = SecurityReport.from_cache_dict(data)
        assert restored.timed_out is True

    def test_to_cache_dict_structure(self):
        r = SecurityReport(
            findings=[_make_finding()],
            languages_detected=["go"],
            patterns_loaded=10,
            scan_duration_seconds=3.0,
        )
        data = r.to_cache_dict()
        assert "findings" in data
        assert "languages_detected" in data
        assert "patterns_loaded" in data
        assert "scan_duration_seconds" in data
        assert "timed_out" in data
        assert isinstance(data["findings"], list)
        assert isinstance(data["findings"][0], dict)

    def test_from_cache_dict_missing_keys_uses_defaults(self):
        # Minimal dict with only findings
        data: dict = {"findings": []}
        r = SecurityReport.from_cache_dict(data)
        assert r.findings == []
        assert r.languages_detected == []
        assert r.patterns_loaded == 0
        assert r.scan_duration_seconds == 0.0
        assert r.timed_out is False

    def test_from_cache_dict_empty_dict(self):
        r = SecurityReport.from_cache_dict({})
        assert r.findings == []

    def test_finding_fields_preserved_in_round_trip(self):
        f = _make_finding(
            id="SEC-X",
            file_path="pkg/handler.go",
            line_number=100,
            cwe_id="CWE-22",
            severity="MEDIUM",
            title="Path Traversal",
            description="Unsanitised path",
            remediation="Use filepath.Clean",
            confidence=0.75,
        )
        original = SecurityReport(findings=[f])
        data = original.to_cache_dict()
        restored = SecurityReport.from_cache_dict(data)
        rf = restored.findings[0]
        assert rf.id == "SEC-X"
        assert rf.file_path == "pkg/handler.go"
        assert rf.line_number == 100
        assert rf.cwe_id == "CWE-22"
        assert rf.severity == "MEDIUM"
        assert rf.title == "Path Traversal"
        assert rf.description == "Unsanitised path"
        assert rf.remediation == "Use filepath.Clean"
        assert rf.confidence == 0.75


# ---------------------------------------------------------------------------
# SecurityReport.filter_for_synthesis
# ---------------------------------------------------------------------------


class TestFilterForSynthesis:
    """Tests for confidence filtering and prioritization."""

    def _build_findings(self) -> list[SecurityFinding]:
        return [
            _make_finding(id="H1", severity="HIGH", confidence=0.95),
            _make_finding(id="H2", severity="HIGH", confidence=0.6),
            _make_finding(id="M1", severity="MEDIUM", confidence=0.8),
            _make_finding(id="M2", severity="MEDIUM", confidence=0.4),
            _make_finding(id="L1", severity="LOW", confidence=0.9),
            _make_finding(id="L2", severity="LOW", confidence=0.3),
        ]

    def test_default_min_confidence_filters_low(self):
        r = SecurityReport(findings=self._build_findings())
        result = r.filter_for_synthesis()
        ids = [f.id for f in result]
        # M2 (0.4) and L2 (0.3) should be excluded (below default 0.5)
        assert "M2" not in ids
        assert "L2" not in ids

    def test_default_includes_high_confidence(self):
        r = SecurityReport(findings=self._build_findings())
        result = r.filter_for_synthesis()
        ids = [f.id for f in result]
        assert "H1" in ids
        assert "H2" in ids
        assert "M1" in ids
        assert "L1" in ids

    def test_custom_min_confidence(self):
        r = SecurityReport(findings=self._build_findings())
        result = r.filter_for_synthesis(min_confidence=0.8)
        ids = [f.id for f in result]
        assert ids == ["H1", "M1", "L1"]

    def test_max_findings_cap(self):
        r = SecurityReport(findings=self._build_findings())
        result = r.filter_for_synthesis(min_confidence=0.0, max_findings=3)
        assert len(result) == 3

    def test_severity_ordering(self):
        r = SecurityReport(findings=self._build_findings())
        result = r.filter_for_synthesis(min_confidence=0.0)
        severities = [f.severity for f in result]
        # HIGH should come before MEDIUM, MEDIUM before LOW
        high_idxs = [i for i, s in enumerate(severities) if s == "HIGH"]
        med_idxs = [i for i, s in enumerate(severities) if s == "MEDIUM"]
        low_idxs = [i for i, s in enumerate(severities) if s == "LOW"]
        if high_idxs and med_idxs:
            assert max(high_idxs) < min(med_idxs)
        if med_idxs and low_idxs:
            assert max(med_idxs) < min(low_idxs)

    def test_confidence_descending_within_severity(self):
        r = SecurityReport(findings=self._build_findings())
        result = r.filter_for_synthesis(min_confidence=0.0)
        # Within HIGH severity, higher confidence should come first
        high_findings = [f for f in result if f.severity == "HIGH"]
        confidences = [f.confidence for f in high_findings]
        assert confidences == sorted(confidences, reverse=True)

    def test_empty_findings(self):
        r = SecurityReport(findings=[])
        result = r.filter_for_synthesis()
        assert result == []

    def test_all_below_threshold(self):
        findings = [_make_finding(confidence=0.1), _make_finding(id="SEC-002", confidence=0.2)]
        r = SecurityReport(findings=findings)
        result = r.filter_for_synthesis(min_confidence=0.5)
        assert result == []

    def test_max_findings_default_is_25(self):
        findings = [_make_finding(id=f"SEC-{i:03d}", confidence=0.9) for i in range(30)]
        r = SecurityReport(findings=findings)
        result = r.filter_for_synthesis()
        assert len(result) == 25

    def test_max_findings_one(self):
        findings = [
            _make_finding(id="SEC-001", severity="HIGH", confidence=0.9),
            _make_finding(id="SEC-002", severity="LOW", confidence=0.8),
        ]
        r = SecurityReport(findings=findings)
        result = r.filter_for_synthesis(max_findings=1)
        assert len(result) == 1
        assert result[0].id == "SEC-001"


# ---------------------------------------------------------------------------
# SecurityReport.to_markdown
# ---------------------------------------------------------------------------


class TestToMarkdown:
    """Tests for markdown report generation."""

    def test_empty_report_markdown(self):
        r = SecurityReport()
        md = r.to_markdown()
        assert "# Security Review Report" in md
        assert "No security findings detected." in md

    def test_frontmatter_present(self):
        r = SecurityReport(
            languages_detected=["python"],
            patterns_loaded=20,
            scan_duration_seconds=5.3,
        )
        md = r.to_markdown()
        assert md.startswith("---\n")
        assert "languages: ['python']" in md
        assert "patterns_loaded: 20" in md
        assert "scan_duration_seconds: 5.3" in md
        assert "timed_out: False" in md
        assert "total_findings: 0" in md

    def test_timed_out_in_frontmatter(self):
        r = SecurityReport(timed_out=True)
        md = r.to_markdown()
        assert "timed_out: True" in md

    def test_findings_in_markdown(self):
        f = _make_finding(
            id="SEC-001",
            file_path="src/db.py",
            line_number=55,
            cwe_id="CWE-89",
            severity="HIGH",
            title="SQL Injection",
            description="Bad query",
            remediation="Use params",
            confidence=0.9,
        )
        r = SecurityReport(findings=[f])
        md = r.to_markdown()
        assert "## SEC-001: SQL Injection" in md
        assert "**File:** `src/db.py`:55" in md
        assert "**CWE:** CWE-89" in md
        assert "**Severity:** HIGH" in md
        assert "**Confidence:** 0.9" in md
        assert "**Description:** Bad query" in md
        assert "**Remediation:** Use params" in md

    def test_no_remediation_omits_line(self):
        f = _make_finding(remediation="")
        r = SecurityReport(findings=[f])
        md = r.to_markdown()
        assert "**Remediation:**" not in md

    def test_summary_counts(self):
        findings = [
            _make_finding(id="H1", severity="HIGH", confidence=0.9),
            _make_finding(id="H2", severity="HIGH", confidence=0.8),
            _make_finding(id="M1", severity="MEDIUM", confidence=0.7),
            _make_finding(id="L1", severity="LOW", confidence=0.6),
        ]
        r = SecurityReport(findings=findings)
        md = r.to_markdown()
        assert "**Summary:** 2 HIGH, 1 MEDIUM, 1 LOW" in md

    def test_findings_sorted_by_severity_in_markdown(self):
        findings = [
            _make_finding(id="L1", severity="LOW", confidence=0.9),
            _make_finding(id="H1", severity="HIGH", confidence=0.9),
            _make_finding(id="M1", severity="MEDIUM", confidence=0.9),
        ]
        r = SecurityReport(findings=findings)
        md = r.to_markdown()
        h_pos = md.index("## H1:")
        m_pos = md.index("## M1:")
        l_pos = md.index("## L1:")
        assert h_pos < m_pos < l_pos

    def test_multiple_findings_all_rendered(self):
        findings = [_make_finding(id=f"SEC-{i:03d}") for i in range(5)]
        r = SecurityReport(findings=findings)
        md = r.to_markdown()
        for i in range(5):
            assert f"SEC-{i:03d}" in md

    def test_total_findings_in_frontmatter(self):
        findings = [_make_finding(id=f"SEC-{i}") for i in range(3)]
        r = SecurityReport(findings=findings)
        md = r.to_markdown()
        assert "total_findings: 3" in md

    def test_markdown_is_string(self):
        r = SecurityReport(findings=[_make_finding()])
        md = r.to_markdown()
        assert isinstance(md, str)

    def test_analysis_quality_in_frontmatter(self):
        r = SecurityReport(findings=[_make_finding()], analysis_quality="degraded")
        md = r.to_markdown()
        assert "analysis_quality: degraded" in md


class TestAnalysisQuality:
    """Tests for analysis_quality field."""

    def test_default_is_full(self):
        r = SecurityReport()
        assert r.analysis_quality == "full"

    def test_set_to_degraded(self):
        r = SecurityReport(analysis_quality="degraded")
        assert r.analysis_quality == "degraded"

    def test_set_to_failed(self):
        r = SecurityReport(analysis_quality="failed")
        assert r.analysis_quality == "failed"

    def test_set_to_partial(self):
        r = SecurityReport(analysis_quality="partial")
        assert r.analysis_quality == "partial"

    def test_invalid_value_rejected(self):
        with pytest.raises(Exception):
            SecurityReport(analysis_quality="invalid")  # type: ignore[arg-type]

    def test_cache_round_trip(self):
        r = SecurityReport(
            findings=[_make_finding()],
            analysis_quality="degraded",
        )
        cache = r.to_cache_dict()
        assert cache["analysis_quality"] == "degraded"
        restored = SecurityReport.from_cache_dict(cache)
        assert restored.analysis_quality == "degraded"

    def test_cache_backward_compat_defaults_to_full(self):
        """Old cache entries without analysis_quality should default to 'full'."""
        cache = {
            "findings": [],
            "languages_detected": ["python"],
            "patterns_loaded": 10,
            "scan_duration_seconds": 1.5,
            "timed_out": False,
            # No analysis_quality key
        }
        restored = SecurityReport.from_cache_dict(cache)
        assert restored.analysis_quality == "full"
