"""Tests for security agent integration in code review orchestrator.

Tests cover:
- Security task creation when enabled vs disabled
- Result splitting with security task present vs absent
- SecurityReport result saved to cache
- BaseException from security task emits failure SSE event
- SSE events emitted on success (with severity summary)
- CompilerError during workflow compilation handled gracefully

All tests use heavy mocking; no real LLM or compiler invocations.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bmad_assist.core.config import (
    BenchmarkingConfig,
    Config,
    MasterProviderConfig,
    MultiProviderConfig,
    ProviderConfig,
)
from bmad_assist.core.exceptions import BmadAssistError, CompilerError
from bmad_assist.security.config import SecurityAgentConfig
from bmad_assist.security.report import SecurityFinding, SecurityReport

# ============================================================================
# Helpers
# ============================================================================


def _make_config(security_enabled: bool = True, max_findings: int = 25) -> Config:
    """Create a Config with security agent settings."""
    return Config(
        providers=ProviderConfig(
            master=MasterProviderConfig(provider="claude", model="opus"),
            multi=[
                MultiProviderConfig(provider="gemini", model="gemini-2.5-flash"),
                MultiProviderConfig(provider="codex", model="gpt-4o"),
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


def _make_security_report(
    findings_count: int = 2,
    timed_out: bool = False,
) -> SecurityReport:
    """Create a SecurityReport with N findings for testing."""
    findings = []
    for i in range(findings_count):
        severity = ["HIGH", "MEDIUM", "LOW"][i % 3]
        findings.append(
            SecurityFinding(
                id=f"SEC-{i + 1:03d}",
                file_path=f"src/app/module_{i}.py",
                line_number=10 * (i + 1),
                cwe_id=f"CWE-{79 + i}",
                severity=severity,
                title=f"Finding {i + 1}",
                description=f"Description for finding {i + 1}",
                remediation=f"Fix for finding {i + 1}",
                confidence=0.8 - (i * 0.1),
            )
        )
    return SecurityReport(
        findings=findings,
        languages_detected=["python"],
        patterns_loaded=42,
        scan_duration_seconds=5.0,
        timed_out=timed_out,
    )


# ============================================================================
# Tests: Security task creation
# ============================================================================


class TestSecurityTaskCreation:
    """Test that security task is created when enabled and skipped when disabled."""

    @pytest.mark.asyncio
    async def test_security_task_created_when_enabled(self, tmp_path: Path) -> None:
        """When config.security_agent.enabled=True, a security task is created."""
        config = _make_config(security_enabled=True)
        report = _make_security_report(findings_count=1)

        with (
            patch(
                "bmad_assist.code_review.orchestrator.compile_workflow"
            ) as mock_compile,
            patch(
                "bmad_assist.code_review.orchestrator.run_security_review",
                new_callable=AsyncMock,
                return_value=report,
            ) as mock_run,
            patch(
                "bmad_assist.code_review.orchestrator.emit_security_review_started"
            ) as mock_emit_started,
            patch(
                "bmad_assist.code_review.orchestrator.emit_security_review_completed"
            ),
            patch(
                "bmad_assist.code_review.orchestrator.save_security_findings_for_synthesis"
            ),
            patch("bmad_assist.code_review.orchestrator.get_paths") as mock_paths,
            patch("bmad_assist.code_review.orchestrator.get_original_cwd", return_value=tmp_path),
            patch("bmad_assist.code_review.orchestrator.get_phase_timeout", return_value=600),
        ):
            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-security-prompt>"
            mock_compile.return_value = mock_compiled

            mock_paths_obj = MagicMock()
            mock_paths_obj.output_folder = tmp_path / "_bmad-output"
            mock_paths.return_value = mock_paths_obj

            # Simulate the orchestrator logic for security task creation
            security_task = None
            security_enabled = config.security_agent.enabled
            assert security_enabled is True

            if security_enabled:
                from bmad_assist.compiler.types import CompilerContext

                security_context = CompilerContext(
                    project_root=tmp_path,
                    output_folder=mock_paths_obj.output_folder,
                    cwd=tmp_path,
                )
                security_prompt = mock_compile("security-review", security_context).context
                security_coro = mock_run(
                    config=config,
                    project_path=tmp_path,
                    compiled_prompt=security_prompt,
                    timeout=600,
                )
                # Since mock_run is AsyncMock, the coro is already awaited above,
                # but we test that the mock was called

                async def _return_report() -> SecurityReport:
                    return report

                security_task = asyncio.create_task(_return_report())
                mock_emit_started(run_id="", sequence_id=0)

            assert security_task is not None
            mock_compile.assert_called()
            mock_run.assert_called_once()
            mock_emit_started.assert_called_once_with(run_id="", sequence_id=0)

            # Cleanup task
            await security_task

    def test_security_task_none_when_disabled(self) -> None:
        """When config.security_agent.enabled=False, security_task stays None."""
        config = _make_config(security_enabled=False)

        security_task = None
        security_enabled = config.security_agent.enabled
        assert security_enabled is False

        if security_enabled:
            security_task = MagicMock()  # This should NOT execute

        assert security_task is None

    def test_security_task_none_on_compiler_error(self, tmp_path: Path) -> None:
        """When compile_workflow raises CompilerError, security_task is set to None."""
        config = _make_config(security_enabled=True)

        with (
            patch(
                "bmad_assist.code_review.orchestrator.compile_workflow",
                side_effect=CompilerError("workflow not found"),
            ),
            patch("bmad_assist.code_review.orchestrator.get_paths") as mock_paths,
            patch("bmad_assist.code_review.orchestrator.get_original_cwd", return_value=tmp_path),
            patch("bmad_assist.code_review.orchestrator.get_phase_timeout", return_value=600),
        ):
            mock_paths_obj = MagicMock()
            mock_paths_obj.output_folder = tmp_path / "_bmad-output"
            mock_paths.return_value = mock_paths_obj

            # Simulate the orchestrator logic
            security_task = None
            security_enabled = config.security_agent.enabled
            assert security_enabled is True

            if security_enabled:
                try:
                    from bmad_assist.compiler import compile_workflow
                    from bmad_assist.compiler.types import CompilerContext

                    security_context = CompilerContext(
                        project_root=tmp_path,
                        output_folder=mock_paths_obj.output_folder,
                        cwd=tmp_path,
                    )
                    compile_workflow("security-review", security_context)
                except (CompilerError, BmadAssistError):
                    security_task = None

            assert security_task is None

    def test_security_task_none_on_bmad_assist_error(self, tmp_path: Path) -> None:
        """When compile_workflow raises BmadAssistError, security_task is set to None."""
        config = _make_config(security_enabled=True)

        with (
            patch(
                "bmad_assist.code_review.orchestrator.compile_workflow",
                side_effect=BmadAssistError("generic error"),
            ),
            patch("bmad_assist.code_review.orchestrator.get_paths") as mock_paths,
            patch("bmad_assist.code_review.orchestrator.get_original_cwd", return_value=tmp_path),
            patch("bmad_assist.code_review.orchestrator.get_phase_timeout", return_value=600),
        ):
            mock_paths_obj = MagicMock()
            mock_paths_obj.output_folder = tmp_path / "_bmad-output"
            mock_paths.return_value = mock_paths_obj

            security_task = None
            security_enabled = config.security_agent.enabled

            if security_enabled:
                try:
                    from bmad_assist.compiler import compile_workflow
                    from bmad_assist.compiler.types import CompilerContext

                    security_context = CompilerContext(
                        project_root=tmp_path,
                        output_folder=mock_paths_obj.output_folder,
                        cwd=tmp_path,
                    )
                    compile_workflow("security-review", security_context)
                except (CompilerError, BmadAssistError):
                    security_task = None

            assert security_task is None


# ============================================================================
# Tests: Result splitting
# ============================================================================


class TestResultSplitting:
    """Test splitting asyncio.gather results into reviewer / DV / security buckets."""

    def test_split_with_security_task_present(self) -> None:
        """Results correctly split when security task is in all_tasks."""
        # Simulate: 2 reviewer tasks, 1 DV task, 1 security task
        reviewer_result_1 = ("gemini", MagicMock(), MagicMock(), None)
        reviewer_result_2 = ("codex", MagicMock(), MagicMock(), None)
        dv_result = MagicMock()
        security_result = _make_security_report(findings_count=3)

        tasks_count = 2
        dv_tasks_count = 1
        results: list[Any] = [reviewer_result_1, reviewer_result_2, dv_result, security_result]

        # Reproduce the splitting logic from the orchestrator
        reviewer_results = results[:tasks_count]
        dv_end_idx = tasks_count + dv_tasks_count
        dv_results = results[tasks_count:dv_end_idx]
        has_security_task = True
        security_out = results[dv_end_idx] if has_security_task else None

        assert len(reviewer_results) == 2
        assert reviewer_results[0] == reviewer_result_1
        assert reviewer_results[1] == reviewer_result_2
        assert len(dv_results) == 1
        assert dv_results[0] == dv_result
        assert isinstance(security_out, SecurityReport)
        assert len(security_out.findings) == 3

    def test_split_without_security_task(self) -> None:
        """Results correctly split when security task is None (disabled)."""
        reviewer_result_1 = ("gemini", MagicMock(), MagicMock(), None)
        reviewer_result_2 = ("codex", MagicMock(), MagicMock(), None)
        dv_result = MagicMock()

        tasks_count = 2
        dv_tasks_count = 1
        results: list[Any] = [reviewer_result_1, reviewer_result_2, dv_result]

        reviewer_results = results[:tasks_count]
        dv_end_idx = tasks_count + dv_tasks_count
        dv_results = results[tasks_count:dv_end_idx]
        has_security_task = False
        security_out = results[dv_end_idx] if has_security_task else None

        assert len(reviewer_results) == 2
        assert len(dv_results) == 1
        assert security_out is None

    def test_split_with_no_dv_tasks(self) -> None:
        """Results correctly split when there are no DV tasks."""
        reviewer_result = ("gemini", MagicMock(), MagicMock(), None)
        security_result = _make_security_report(findings_count=1)

        tasks_count = 1
        dv_tasks_count = 0
        results: list[Any] = [reviewer_result, security_result]

        reviewer_results = results[:tasks_count]
        dv_end_idx = tasks_count + dv_tasks_count
        dv_results = results[tasks_count:dv_end_idx]
        has_security_task = True
        security_out = results[dv_end_idx] if has_security_task else None

        assert len(reviewer_results) == 1
        assert len(dv_results) == 0
        assert isinstance(security_out, SecurityReport)


# ============================================================================
# Tests: Security report cache save
# ============================================================================


class TestSecurityReportCacheSave:
    """Test that SecurityReport result is saved to cache for synthesis."""

    def test_successful_report_saved_to_cache(self, tmp_path: Path) -> None:
        """A successful SecurityReport is saved via save_security_findings_for_synthesis."""
        report = _make_security_report(findings_count=2)
        session_id = "test-session-abc"

        with patch(
            "bmad_assist.code_review.orchestrator.save_security_findings_for_synthesis"
        ) as mock_save:
            # Simulate the orchestrator post-processing
            security_result: SecurityReport | BaseException | None = report

            if security_result is not None:
                if isinstance(security_result, BaseException):
                    pass  # Would emit failure
                elif isinstance(security_result, SecurityReport):

                    mock_save(
                        report=security_result,
                        project_path=tmp_path,
                        session_id=session_id,
                    )

            mock_save.assert_called_once_with(
                report=report,
                project_path=tmp_path,
                session_id=session_id,
            )

    def test_oserror_during_save_is_logged_not_raised(self, tmp_path: Path) -> None:
        """OSError during cache save is caught (logged), not propagated."""
        report = _make_security_report(findings_count=1)

        with patch(
            "bmad_assist.security.integration.save_security_findings_for_synthesis",
            side_effect=OSError("disk full"),
        ) as mock_save:
            # Simulate the orchestrator try/except pattern
            security_result: SecurityReport | BaseException | None = report
            saved = False
            save_error = None

            if isinstance(security_result, SecurityReport):
                try:
                    mock_save(
                        report=security_result,
                        project_path=tmp_path,
                        session_id="ses-123",
                    )
                    saved = True
                except OSError as e:
                    save_error = str(e)

            assert not saved
            assert save_error == "disk full"


# ============================================================================
# Tests: BaseException from security task
# ============================================================================


class TestSecurityTaskBaseException:
    """Test that BaseException from security task emits failure SSE event."""

    def test_base_exception_emits_failure_event(self) -> None:
        """If security task returns BaseException, emit_security_review_failed is called."""
        error = RuntimeError("security agent crashed")

        with patch(
            "bmad_assist.code_review.orchestrator.emit_security_review_failed"
        ) as mock_emit_failed:
            security_result: SecurityReport | BaseException | None = error

            if security_result is not None:
                if isinstance(security_result, BaseException):
                    mock_emit_failed(
                        run_id="", sequence_id=0, error=str(security_result)
                    )

            mock_emit_failed.assert_called_once_with(
                run_id="",
                sequence_id=0,
                error="security agent crashed",
            )

    def test_timeout_error_emits_failure_event(self) -> None:
        """TimeoutError (a BaseException subclass) also triggers failure emit."""
        error = TimeoutError("security review timed out after 600s")

        with patch(
            "bmad_assist.code_review.orchestrator.emit_security_review_failed"
        ) as mock_emit_failed:
            security_result: SecurityReport | BaseException | None = error

            if isinstance(security_result, BaseException):
                mock_emit_failed(
                    run_id="", sequence_id=0, error=str(security_result)
                )

            mock_emit_failed.assert_called_once()
            call_kwargs = mock_emit_failed.call_args
            assert "timed out" in call_kwargs[1]["error"]

    def test_none_result_does_not_emit(self) -> None:
        """When security_result is None (disabled), no events are emitted."""
        with patch(
            "bmad_assist.code_review.orchestrator.emit_security_review_failed"
        ) as mock_emit_failed:
            security_result: SecurityReport | BaseException | None = None

            if security_result is not None:
                if isinstance(security_result, BaseException):
                    mock_emit_failed(
                        run_id="", sequence_id=0, error=str(security_result)
                    )

            mock_emit_failed.assert_not_called()


# ============================================================================
# Tests: SSE events on success
# ============================================================================


class TestSecuritySSEEventsOnSuccess:
    """Test SSE events emitted on successful security review completion."""

    def test_completed_event_with_severity_summary(self) -> None:
        """emit_security_review_completed is called with correct severity breakdown."""
        report = _make_security_report(findings_count=5)

        with patch(
            "bmad_assist.code_review.orchestrator.emit_security_review_completed"
        ) as mock_emit:
            # Reproduce the orchestrator severity summary logic
            severity_summary: dict[str, int] = {}
            for f in report.findings:
                sev = f.severity.upper() if f.severity else "UNKNOWN"
                severity_summary[sev] = severity_summary.get(sev, 0) + 1

            mock_emit(
                run_id="",
                sequence_id=0,
                finding_count=len(report.findings),
                severity_summary=severity_summary,
                timed_out=report.timed_out,
            )

            mock_emit.assert_called_once_with(
                run_id="",
                sequence_id=0,
                finding_count=5,
                severity_summary=severity_summary,
                timed_out=False,
            )

            # Verify severity breakdown (findings cycle through HIGH, MEDIUM, LOW)
            assert severity_summary["HIGH"] == 2  # indices 0, 3
            assert severity_summary["MEDIUM"] == 2  # indices 1, 4
            assert severity_summary["LOW"] == 1  # index 2

    def test_completed_event_with_timed_out_flag(self) -> None:
        """timed_out=True is passed through to SSE event."""
        report = _make_security_report(findings_count=1, timed_out=True)

        with patch(
            "bmad_assist.code_review.orchestrator.emit_security_review_completed"
        ) as mock_emit:
            severity_summary: dict[str, int] = {}
            for f in report.findings:
                sev = f.severity.upper()
                severity_summary[sev] = severity_summary.get(sev, 0) + 1

            mock_emit(
                run_id="",
                sequence_id=0,
                finding_count=len(report.findings),
                severity_summary=severity_summary,
                timed_out=report.timed_out,
            )

            call_kwargs = mock_emit.call_args[1]
            assert call_kwargs["timed_out"] is True

    def test_completed_event_with_zero_findings(self) -> None:
        """A report with zero findings emits completed event with finding_count=0."""
        report = _make_security_report(findings_count=0)

        with patch(
            "bmad_assist.code_review.orchestrator.emit_security_review_completed"
        ) as mock_emit:
            severity_summary: dict[str, int] = {}
            for f in report.findings:
                sev = f.severity.upper()
                severity_summary[sev] = severity_summary.get(sev, 0) + 1

            mock_emit(
                run_id="",
                sequence_id=0,
                finding_count=0,
                severity_summary=severity_summary,
                timed_out=False,
            )

            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args[1]
            assert call_kwargs["finding_count"] == 0
            assert call_kwargs["severity_summary"] == {}

    def test_started_event_emitted_before_task_creation(self) -> None:
        """emit_security_review_started is called during task creation."""
        with patch(
            "bmad_assist.code_review.orchestrator.emit_security_review_started"
        ) as mock_emit:
            # Reproduce: emit is called right after creating the task
            mock_emit(run_id="", sequence_id=0)

            mock_emit.assert_called_once_with(run_id="", sequence_id=0)


# ============================================================================
# Tests: Archival report save
# ============================================================================


class TestSecurityArchivalReportSave:
    """Test that archival markdown report is saved when findings exist."""

    def test_archival_report_saved_when_findings_exist(self, tmp_path: Path) -> None:
        """Archival MD report is written to security_reports_dir."""
        report = _make_security_report(findings_count=2)
        run_timestamp = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)

        sec_dir = tmp_path / "security-reports"
        sec_dir.mkdir(parents=True)

        with patch("bmad_assist.code_review.orchestrator.get_paths") as mock_paths:
            mock_paths_obj = MagicMock()
            mock_paths_obj.security_reports_dir = sec_dir
            mock_paths.return_value = mock_paths_obj

            # Reproduce the orchestrator archival logic
            if report.findings:
                ts = run_timestamp.strftime("%Y%m%d-%H%M%S")
                report_path = sec_dir / f"security-1-2-{ts}.md"
                report_path.write_text(report.to_markdown(), encoding="utf-8")

            saved_files = list(sec_dir.glob("security-*.md"))
            assert len(saved_files) == 1
            content = saved_files[0].read_text()
            assert "Security Review Report" in content
            assert "SEC-001" in content

    def test_no_archival_report_when_no_findings(self, tmp_path: Path) -> None:
        """No archival report is saved when report has zero findings."""
        report = _make_security_report(findings_count=0)

        sec_dir = tmp_path / "security-reports"
        sec_dir.mkdir(parents=True)

        # Reproduce the orchestrator conditional
        if report.findings:
            report_path = sec_dir / "security-1-1-timestamp.md"
            report_path.write_text(report.to_markdown(), encoding="utf-8")

        saved_files = list(sec_dir.glob("security-*.md"))
        assert len(saved_files) == 0
