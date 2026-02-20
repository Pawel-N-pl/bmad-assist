"""Tests for security findings in synthesis handler.

Tests cover:
- _get_security_findings_from_cache() returns formatted dict when findings exist
- Returns None when no cache file
- Confidence filtering (min_confidence=0.5)
- max_findings limit from config
- render_prompt() includes security_findings in resolved_variables
- Timed-out report handling

Uses mocking for load_security_findings_from_cache and compiler.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from bmad_assist.core.config import (
    BenchmarkingConfig,
    Config,
    MasterProviderConfig,
    MultiProviderConfig,
    ProviderConfig,
)
from bmad_assist.core.loop.handlers.code_review_synthesis import (
    CodeReviewSynthesisHandler,
)
from bmad_assist.security.config import SecurityAgentConfig
from bmad_assist.security.report import SecurityFinding, SecurityReport

# ============================================================================
# Helpers
# ============================================================================


def _make_config(
    security_enabled: bool = True,
    max_findings: int = 25,
) -> Config:
    """Create a Config with security agent settings."""
    return Config(
        providers=ProviderConfig(
            master=MasterProviderConfig(provider="claude", model="opus"),
            multi=[
                MultiProviderConfig(provider="gemini", model="gemini-2.5-flash"),
            ],
        ),
        timeout=300,
        benchmarking=BenchmarkingConfig(enabled=False),
        workflow_variant="default",
        security_agent=SecurityAgentConfig(
            enabled=security_enabled,
            max_findings=max_findings,
        ),
    )


def _make_finding(
    id: str = "SEC-001",
    severity: str = "HIGH",
    confidence: float = 0.9,
    file_path: str = "src/app.py",
    line_number: int = 42,
    cwe_id: str = "CWE-89",
    title: str = "SQL Injection",
    description: str = "Unsanitized input in query",
    remediation: str = "Use parameterized queries",
) -> SecurityFinding:
    """Create a SecurityFinding with defaults."""
    return SecurityFinding(
        id=id,
        file_path=file_path,
        line_number=line_number,
        cwe_id=cwe_id,
        severity=severity,
        title=title,
        description=description,
        remediation=remediation,
        confidence=confidence,
    )


def _make_report(
    findings: list[SecurityFinding] | None = None,
    timed_out: bool = False,
    languages: list[str] | None = None,
    analysis_quality: str = "full",
) -> SecurityReport:
    """Create a SecurityReport with given findings."""
    return SecurityReport(
        findings=findings or [],
        languages_detected=languages or ["python"],
        patterns_loaded=42,
        scan_duration_seconds=5.0,
        timed_out=timed_out,
        analysis_quality=analysis_quality,  # type: ignore[arg-type]
    )


def _make_handler(
    tmp_path: Path,
    config: Config | None = None,
) -> CodeReviewSynthesisHandler:
    """Create a CodeReviewSynthesisHandler with given config."""
    if config is None:
        config = _make_config()
    return CodeReviewSynthesisHandler(config=config, project_path=tmp_path)


# ============================================================================
# Tests: _get_security_findings_from_cache - returns formatted dict
# ============================================================================


class TestGetSecurityFindingsFromCache:
    """Test _get_security_findings_from_cache() method."""

    def test_returns_formatted_dict_when_findings_exist(self, tmp_path: Path) -> None:
        """Returns dict with findings data when cache has findings."""
        findings = [
            _make_finding(id="SEC-001", severity="HIGH", confidence=0.9),
            _make_finding(id="SEC-002", severity="MEDIUM", confidence=0.7),
        ]
        report = _make_report(findings=findings, languages=["python", "go"])
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-abc")

        assert result is not None
        assert len(result["findings"]) == 2
        assert result["findings"][0]["id"] == "SEC-001"
        assert result["findings"][0]["severity"] == "HIGH"
        assert result["findings"][0]["confidence"] == 0.9
        assert result["findings"][0]["file_path"] == "src/app.py"
        assert result["findings"][0]["line_number"] == 42
        assert result["findings"][0]["cwe_id"] == "CWE-89"
        assert result["findings"][0]["title"] == "SQL Injection"
        assert result["findings"][0]["description"] == "Unsanitized input in query"
        assert result["findings"][0]["remediation"] == "Use parameterized queries"
        assert result["languages_detected"] == ["python", "go"]
        assert result["timed_out"] is False
        assert result["total_findings"] == 2
        assert result["filtered_count"] == 2

    def test_returns_none_when_no_cache_file(self, tmp_path: Path) -> None:
        """Returns None when load_security_findings_from_cache returns None."""
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=None,
        ):
            result = handler._get_security_findings_from_cache("nonexistent-session")

        assert result is None

    def test_returns_none_on_oserror(self, tmp_path: Path) -> None:
        """Returns None when load raises OSError."""
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            side_effect=OSError("disk error"),
        ):
            result = handler._get_security_findings_from_cache("session-err")

        assert result is None

    def test_returns_none_on_json_decode_error(self, tmp_path: Path) -> None:
        """Returns None when load raises JSONDecodeError."""
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            side_effect=json.JSONDecodeError("bad json", "", 0),
        ):
            result = handler._get_security_findings_from_cache("session-bad")

        assert result is None

    def test_returns_none_on_value_error(self, tmp_path: Path) -> None:
        """Returns None when load raises ValueError (e.g., bad confidence)."""
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            side_effect=ValueError("invalid data"),
        ):
            result = handler._get_security_findings_from_cache("session-val")

        assert result is None


# ============================================================================
# Tests: Confidence filtering
# ============================================================================


class TestConfidenceFiltering:
    """Test that min_confidence=0.5 filter is applied."""

    def test_findings_below_threshold_are_excluded(self, tmp_path: Path) -> None:
        """Findings with confidence < 0.5 are filtered out."""
        findings = [
            _make_finding(id="SEC-001", severity="HIGH", confidence=0.9),
            _make_finding(id="SEC-002", severity="MEDIUM", confidence=0.6),
            _make_finding(id="SEC-003", severity="LOW", confidence=0.4),  # Below threshold
            _make_finding(id="SEC-004", severity="LOW", confidence=0.3),  # Below threshold
        ]
        report = _make_report(findings=findings)
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-filter")

        assert result is not None
        assert result["filtered_count"] == 2
        assert result["total_findings"] == 4
        # Only findings with confidence >= 0.5 should be included
        ids = [f["id"] for f in result["findings"]]
        assert "SEC-001" in ids
        assert "SEC-002" in ids
        assert "SEC-003" not in ids
        assert "SEC-004" not in ids

    def test_all_below_threshold_returns_none(self, tmp_path: Path) -> None:
        """When all findings are below threshold and not timed out, returns None."""
        findings = [
            _make_finding(id="SEC-001", severity="HIGH", confidence=0.3),
            _make_finding(id="SEC-002", severity="MEDIUM", confidence=0.2),
        ]
        report = _make_report(findings=findings, timed_out=False)
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-all-low")

        assert result is None

    def test_all_below_threshold_but_timed_out_returns_data(self, tmp_path: Path) -> None:
        """When all findings are below threshold but timed_out=True, still returns data."""
        findings = [
            _make_finding(id="SEC-001", severity="HIGH", confidence=0.3),
        ]
        report = _make_report(findings=findings, timed_out=True)
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-timed-out")

        assert result is not None
        assert result["timed_out"] is True
        assert result["filtered_count"] == 0
        assert result["total_findings"] == 1

    def test_findings_at_exact_threshold_are_included(self, tmp_path: Path) -> None:
        """Findings with confidence == 0.5 are included (>= check)."""
        findings = [
            _make_finding(id="SEC-001", severity="HIGH", confidence=0.5),
        ]
        report = _make_report(findings=findings)
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-exact")

        assert result is not None
        assert result["filtered_count"] == 1
        assert result["findings"][0]["id"] == "SEC-001"


# ============================================================================
# Tests: max_findings limit
# ============================================================================


class TestMaxFindingsLimit:
    """Test that max_findings from config caps the number of findings."""

    def test_max_findings_caps_output(self, tmp_path: Path) -> None:
        """Only max_findings findings are included in the result."""
        findings = [
            _make_finding(id=f"SEC-{i:03d}", severity="HIGH", confidence=0.9)
            for i in range(10)
        ]
        report = _make_report(findings=findings)
        config = _make_config(max_findings=3)
        handler = _make_handler(tmp_path, config=config)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-cap")

        assert result is not None
        assert result["filtered_count"] == 3
        assert result["total_findings"] == 10
        assert len(result["findings"]) == 3

    def test_max_findings_default_25(self, tmp_path: Path) -> None:
        """Default max_findings=25 caps at 25 findings."""
        findings = [
            _make_finding(id=f"SEC-{i:03d}", severity="MEDIUM", confidence=0.8)
            for i in range(30)
        ]
        report = _make_report(findings=findings)
        config = _make_config(max_findings=25)
        handler = _make_handler(tmp_path, config=config)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-default-cap")

        assert result is not None
        assert result["filtered_count"] == 25
        assert result["total_findings"] == 30

    def test_fewer_findings_than_max_returns_all(self, tmp_path: Path) -> None:
        """When findings < max_findings, all are returned."""
        findings = [
            _make_finding(id="SEC-001", severity="HIGH", confidence=0.9),
            _make_finding(id="SEC-002", severity="MEDIUM", confidence=0.7),
        ]
        report = _make_report(findings=findings)
        config = _make_config(max_findings=25)
        handler = _make_handler(tmp_path, config=config)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-few")

        assert result is not None
        assert result["filtered_count"] == 2
        assert result["total_findings"] == 2

    def test_severity_priority_in_capped_results(self, tmp_path: Path) -> None:
        """When capped, HIGH findings are prioritized over MEDIUM and LOW."""
        findings = [
            _make_finding(id="SEC-LOW", severity="LOW", confidence=0.9),
            _make_finding(id="SEC-MED", severity="MEDIUM", confidence=0.9),
            _make_finding(id="SEC-HIGH", severity="HIGH", confidence=0.9),
        ]
        report = _make_report(findings=findings)
        config = _make_config(max_findings=2)
        handler = _make_handler(tmp_path, config=config)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-priority")

        assert result is not None
        assert result["filtered_count"] == 2
        ids = [f["id"] for f in result["findings"]]
        # HIGH should be first, then MEDIUM (LOW is dropped by cap)
        assert ids[0] == "SEC-HIGH"
        assert ids[1] == "SEC-MED"


# ============================================================================
# Tests: render_prompt includes security_findings
# ============================================================================


class TestRenderPromptSecurityFindings:
    """Test that render_prompt() includes security_findings in resolved_variables."""

    def _setup_handler_for_render(
        self,
        tmp_path: Path,
        security_findings: dict[str, Any] | None,
    ) -> tuple[CodeReviewSynthesisHandler, MagicMock]:
        """Set up handler with mocks for render_prompt testing.

        Returns (handler, mock_compile_workflow).
        """
        config = _make_config(security_enabled=True)
        handler = _make_handler(tmp_path, config=config)

        # Create cache dir with session file
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)
        session_file = cache_dir / "code-reviews-session-abc.json"
        session_file.write_text(json.dumps({
            "session_id": "session-abc",
            "reviews": [],
        }))

        return handler, security_findings

    def test_security_findings_included_in_resolved_variables(self, tmp_path: Path) -> None:
        """render_prompt passes security_findings dict to CompilerContext.resolved_variables."""
        config = _make_config(security_enabled=True)
        handler = _make_handler(tmp_path, config=config)

        # Set up session cache
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)
        session_file = cache_dir / "code-reviews-session-abc.json"
        session_file.write_text(json.dumps({
            "session_id": "session-abc",
            "reviews": [],
        }))

        # Mock state
        mock_state = MagicMock()
        mock_state.current_epic = 1
        mock_state.current_story = "1.3"

        security_data = {
            "findings": [{"id": "SEC-001", "severity": "HIGH"}],
            "languages_detected": ["python"],
            "timed_out": False,
            "total_findings": 1,
            "filtered_count": 1,
        }

        from bmad_assist.validation.anonymizer import AnonymizedValidation

        mock_reviews = [
            AnonymizedValidation(
                validator_id="validator-a",
                content="Review content",
                original_ref="ref",
            ),
        ]

        captured_context = {}

        def capture_compile(workflow_id: str, context: Any) -> MagicMock:
            captured_context["resolved_variables"] = context.resolved_variables
            result = MagicMock()
            result.context = "<compiled-prompt>"
            result.token_estimate = 1000
            return result

        with (
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            ) as mock_load_sec,
            patch.object(
                handler, "_get_dv_findings_from_cache",
                return_value=None,
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.compile_workflow",
                side_effect=capture_compile,
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.load_reviews_for_synthesis",
                return_value=(mock_reviews, [], None),
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_paths",
            ) as mock_paths,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_original_cwd",
                return_value=tmp_path,
            ),
        ):
            # Mock security findings load
            mock_report = _make_report(
                findings=[_make_finding(id="SEC-001", severity="HIGH", confidence=0.9)]
            )
            mock_load_sec.return_value = mock_report

            # Mock paths
            mock_paths_obj = MagicMock()
            mock_paths_obj.implementation_artifacts = tmp_path / "_bmad-output" / "impl"
            mock_paths_obj.project_knowledge = tmp_path / "docs"
            mock_paths.return_value = mock_paths_obj

            result = handler.render_prompt(mock_state)

        assert result == "<compiled-prompt>"
        assert "security_findings" in captured_context["resolved_variables"]
        sec_findings = captured_context["resolved_variables"]["security_findings"]
        assert sec_findings is not None
        assert len(sec_findings["findings"]) == 1

    def test_security_findings_none_when_no_cache(self, tmp_path: Path) -> None:
        """render_prompt passes None for security_findings when no cache exists."""
        config = _make_config(security_enabled=True)
        handler = _make_handler(tmp_path, config=config)

        # Set up session cache
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)
        session_file = cache_dir / "code-reviews-session-xyz.json"
        session_file.write_text(json.dumps({
            "session_id": "session-xyz",
            "reviews": [],
        }))

        mock_state = MagicMock()
        mock_state.current_epic = 2
        mock_state.current_story = "2.1"

        from bmad_assist.validation.anonymizer import AnonymizedValidation

        mock_reviews = [
            AnonymizedValidation(
                validator_id="validator-a",
                content="Review content",
                original_ref="ref",
            ),
        ]

        captured_context = {}

        def capture_compile(workflow_id: str, context: Any) -> MagicMock:
            captured_context["resolved_variables"] = context.resolved_variables
            result = MagicMock()
            result.context = "<compiled-prompt-no-sec>"
            result.token_estimate = 500
            return result

        with (
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
                return_value=None,
            ),
            patch.object(
                handler, "_get_dv_findings_from_cache",
                return_value=None,
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.compile_workflow",
                side_effect=capture_compile,
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.load_reviews_for_synthesis",
                return_value=(mock_reviews, [], None),
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_paths",
            ) as mock_paths,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_original_cwd",
                return_value=tmp_path,
            ),
        ):
            mock_paths_obj = MagicMock()
            mock_paths_obj.implementation_artifacts = tmp_path / "_bmad-output" / "impl"
            mock_paths_obj.project_knowledge = tmp_path / "docs"
            mock_paths.return_value = mock_paths_obj

            result = handler.render_prompt(mock_state)

        assert result == "<compiled-prompt-no-sec>"
        assert "security_findings" in captured_context["resolved_variables"]
        assert captured_context["resolved_variables"]["security_findings"] is None


# ============================================================================
# Tests: Timed-out report handling
# ============================================================================


class TestTimedOutReportHandling:
    """Test that timed_out flag is preserved in findings dict."""

    def test_timed_out_true_in_result(self, tmp_path: Path) -> None:
        """timed_out=True in report is reflected in the findings dict."""
        findings = [
            _make_finding(id="SEC-001", severity="HIGH", confidence=0.9),
        ]
        report = _make_report(findings=findings, timed_out=True)
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-timeout")

        assert result is not None
        assert result["timed_out"] is True

    def test_timed_out_false_in_result(self, tmp_path: Path) -> None:
        """timed_out=False in report is reflected in the findings dict."""
        findings = [
            _make_finding(id="SEC-001", severity="HIGH", confidence=0.9),
        ]
        report = _make_report(findings=findings, timed_out=False)
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-ok")

        assert result is not None
        assert result["timed_out"] is False

    def test_timed_out_report_with_no_passing_findings(self, tmp_path: Path) -> None:
        """A timed-out report with no findings above threshold still returns dict."""
        report = _make_report(findings=[], timed_out=True)
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-empty-timeout")

        # No filtered findings but timed_out=True => still returns data
        assert result is not None
        assert result["timed_out"] is True
        assert result["filtered_count"] == 0
        assert result["findings"] == []


# ============================================================================
# Tests: analysis_quality surfaced in synthesis
# ============================================================================


class TestAnalysisQualityInSynthesis:
    """Test that analysis_quality is surfaced to synthesis context."""

    def test_quality_full_no_findings_returns_none(self, tmp_path: Path) -> None:
        """Full quality + no findings → clean scan, return None."""
        report = _make_report(findings=[], analysis_quality="full")
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-clean")

        assert result is None

    def test_quality_degraded_no_findings_returns_data(self, tmp_path: Path) -> None:
        """Degraded quality + no findings → NOT a clean scan, return context."""
        report = _make_report(findings=[], analysis_quality="degraded")
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-degraded")

        assert result is not None
        assert result["analysis_quality"] == "degraded"
        assert result["filtered_count"] == 0

    def test_quality_failed_no_findings_returns_data(self, tmp_path: Path) -> None:
        """Failed quality + no findings → scan failed, return context."""
        report = _make_report(findings=[], analysis_quality="failed")
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-failed")

        assert result is not None
        assert result["analysis_quality"] == "failed"

    def test_quality_included_in_result_dict(self, tmp_path: Path) -> None:
        """analysis_quality is included in the returned dict."""
        findings = [_make_finding(id="SEC-001", confidence=0.9)]
        report = _make_report(findings=findings, analysis_quality="full")
        handler = _make_handler(tmp_path)

        with patch(
            "bmad_assist.core.loop.handlers.code_review_synthesis.load_security_findings_from_cache",
            return_value=report,
        ):
            result = handler._get_security_findings_from_cache("session-with-findings")

        assert result is not None
        assert result["analysis_quality"] == "full"
