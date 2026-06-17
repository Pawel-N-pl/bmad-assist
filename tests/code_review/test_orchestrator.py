"""Tests for code_review/orchestrator.py.

Story 13.10: Code Review Benchmarking Integration

Tests cover:
- Task 1: Module structure and public API (AC: #1)
- Task 2: Reviewer invocation with metrics (AC: #1, #6)
- Task 10: Unit tests for orchestrator (AC: #1, #2)
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.benchmarking import (
    CollectorContext,
    DeterministicMetrics,
    EvaluatorRole,
    LLMEvaluationRecord,
)
from bmad_assist.code_review.orchestrator import (
    CODE_REVIEW_WORKFLOW_ID,
    CODE_REVIEW_SYNTHESIS_WORKFLOW_ID,
    CodeReviewError,
    CodeReviewPhaseResult,
    InsufficientReviewsError,
    run_code_review_phase,
)
from bmad_assist.core.config import (
    BenchmarkingConfig,
    Config,
    MasterProviderConfig,
    MultiProviderConfig,
    ProviderConfig,
)
from bmad_assist.validation.anonymizer import AnonymizedValidation


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_config() -> Config:
    """Create mock Config with multi providers and master."""
    return Config(
        providers=ProviderConfig(
            master=MasterProviderConfig(provider="claude", model="opus"),
            multi=[
                MultiProviderConfig(provider="gemini", model="gemini-2.5-flash"),
                MultiProviderConfig(provider="codex", model="gpt-4o"),
            ],
        ),
        timeout=300,
        parallel_delay=0.0,
        benchmarking=BenchmarkingConfig(enabled=True),
        workflow_variant="default",
    )


@pytest.fixture
def project_path(tmp_path: Path) -> Path:
    """Create temp project with story file."""
    from bmad_assist.core.paths import init_paths

    # Initialize paths singleton for this test
    paths = init_paths(tmp_path)
    paths.ensure_directories()

    # Create story file in the new location
    story_file = paths.stories_dir / "13-10-code-review-benchmarking-integration.md"
    story_file.write_text("""# Story 13.10: Code Review Benchmarking Integration

## File List

- `src/bmad_assist/code_review/__init__.py`
- `src/bmad_assist/code_review/orchestrator.py`
- `tests/code_review/test_orchestrator.py`
""")

    return tmp_path


# ============================================================================
# Task 1: Module Structure Tests (AC: #1)
# ============================================================================


class TestModuleExports:
    """Test module has correct exports."""

    def test_code_review_workflow_id_constant(self) -> None:
        """Test CODE_REVIEW_WORKFLOW_ID constant is defined."""
        assert CODE_REVIEW_WORKFLOW_ID == "code-review"

    def test_code_review_synthesis_workflow_id_constant(self) -> None:
        """Test CODE_REVIEW_SYNTHESIS_WORKFLOW_ID constant is defined."""
        assert CODE_REVIEW_SYNTHESIS_WORKFLOW_ID == "code-review-synthesis"

    def test_code_review_phase_result_dataclass(self) -> None:
        """Test CodeReviewPhaseResult is defined with required fields."""
        result = CodeReviewPhaseResult(
            anonymized_reviews=[],
            session_id="test-session",
            review_count=0,
            reviewers=[],
            failed_reviewers=[],
            evaluation_records=[],
        )
        assert result.session_id == "test-session"
        assert result.review_count == 0

    def test_code_review_error_exception(self) -> None:
        """Test CodeReviewError exception is defined."""
        error = CodeReviewError("test error")
        assert str(error) == "test error"

    def test_insufficient_reviews_error_exception(self) -> None:
        """Test InsufficientReviewsError exception is defined."""
        error = InsufficientReviewsError(count=1, minimum=2)
        assert error.count == 1
        assert error.minimum == 2


# ============================================================================
# Task 10: Unit Tests for Orchestrator (AC: #1, #2)
# ============================================================================


class TestRunCodeReviewPhaseWorkflowId:
    """Test run_code_review_phase creates records with correct workflow.id (AC: #2)."""

    def test_creates_records_with_code_review_workflow_id(
        self,
        mock_config: Config,
        project_path: Path,
    ) -> None:
        """Test that evaluation records have workflow.id = 'code-review'."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "<!-- CODE_REVIEW_REPORT_START -->\n# Review\n## Findings\nNo issues\n<!-- CODE_REVIEW_REPORT_END -->"
        mock_result.stderr = None
        mock_result.model = "test-model"
        mock_result.provider_session_id = "session-123"
        mock_result.termination_reason = None

        mock_provider = MagicMock()
        mock_provider.invoke.return_value = mock_result

        with (
            patch(
                "bmad_assist.code_review.orchestrator.get_provider",
                return_value=mock_provider,
            ),
            patch(
                "bmad_assist.code_review.orchestrator._compile_code_review_prompt",
                return_value="compiled prompt",
            ),
            patch(
                "bmad_assist.code_review.orchestrator.should_collect_benchmarking",
                return_value=True,
            ),
            patch(
                "bmad_assist.code_review.orchestrator.collect_deterministic_metrics",
                return_value=MagicMock(spec=DeterministicMetrics),
            ),
            patch(
                "bmad_assist.code_review.orchestrator._run_parallel_extraction",
                return_value=[MagicMock()],
            ),
            patch(
                "bmad_assist.code_review.orchestrator._finalize_evaluation_record",
                return_value=MagicMock(spec=LLMEvaluationRecord),
            ),
        ):
            result = asyncio.run(
                run_code_review_phase(
                    config=mock_config,
                    project_path=project_path,
                    epic_num=13,
                    story_num=10,
                )
            )

        # Verify result structure
        assert result.session_id
        assert result.review_count >= 2  # At least 2 reviewers required


class TestRunCodeReviewPhaseDeterministicMetrics:
    """Test deterministic metrics are collected per reviewer (AC: #1)."""

    def test_collects_deterministic_metrics(
        self,
        mock_config: Config,
        project_path: Path,
    ) -> None:
        """Test that deterministic metrics are collected for each reviewer."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "# Code Review\n## Findings\n- Issue 1\n- Issue 2"
        mock_result.stderr = None
        mock_result.model = "test-model"
        mock_result.provider_session_id = "session-123"
        mock_result.termination_reason = None

        mock_provider = MagicMock()
        mock_provider.invoke.return_value = mock_result

        collect_calls: list[tuple[str, CollectorContext]] = []

        def mock_collect(content: str, context: CollectorContext) -> DeterministicMetrics:
            collect_calls.append((content, context))
            return MagicMock(spec=DeterministicMetrics)

        with (
            patch(
                "bmad_assist.code_review.orchestrator.get_provider",
                return_value=mock_provider,
            ),
            patch(
                "bmad_assist.code_review.orchestrator._compile_code_review_prompt",
                return_value="compiled prompt",
            ),
            patch(
                "bmad_assist.code_review.orchestrator.should_collect_benchmarking",
                return_value=True,
            ),
            patch(
                "bmad_assist.code_review.orchestrator.collect_deterministic_metrics",
                side_effect=mock_collect,
            ),
            patch(
                "bmad_assist.code_review.orchestrator._run_parallel_extraction",
                return_value=[],
            ),
        ):
            result = asyncio.run(
                run_code_review_phase(
                    config=mock_config,
                    project_path=project_path,
                    epic_num=13,
                    story_num=10,
                )
            )

        # Each reviewer should have metrics collected
        # 2 multi + 1 master = 3 total reviewers
        assert len(collect_calls) == 3


class TestRunCodeReviewPhaseHandleFailures:
    """Test handling of failed reviewers (AC: #1)."""

    def test_handles_failed_reviewers_gracefully(
        self,
        mock_config: Config,
        project_path: Path,
    ) -> None:
        """Test that failed reviewers are tracked but don't block the phase."""
        call_count = 0

        def mock_invoke(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # First reviewer fails
                mock_result.exit_code = 1
                mock_result.stderr = "Error occurred"
                mock_result.stdout = ""
            else:
                # Others succeed
                mock_result.exit_code = 0
                mock_result.stdout = "# Review\n## Findings\nLooks good"
                mock_result.stderr = None
            mock_result.model = "test-model"
            mock_result.provider_session_id = f"session-{call_count}"
            mock_result.termination_reason = None
            return mock_result

        mock_provider = MagicMock()
        mock_provider.invoke.side_effect = mock_invoke

        with (
            patch(
                "bmad_assist.code_review.orchestrator.get_provider",
                return_value=mock_provider,
            ),
            patch(
                "bmad_assist.code_review.orchestrator._compile_code_review_prompt",
                return_value="compiled prompt",
            ),
            patch(
                "bmad_assist.code_review.orchestrator.should_collect_benchmarking",
                return_value=False,
            ),
        ):
            result = asyncio.run(
                run_code_review_phase(
                    config=mock_config,
                    project_path=project_path,
                    epic_num=13,
                    story_num=10,
                )
            )

        # Should have at least 2 successful (master + one multi)
        assert result.review_count >= 2
        assert len(result.failed_reviewers) == 1


class TestRunCodeReviewPhaseInsufficientReviewers:
    """Test insufficient reviewers raises error."""

    def test_raises_insufficient_reviews_error(
        self,
        project_path: Path,
    ) -> None:
        """Test InsufficientReviewsError when fewer than 2 reviewers succeed."""
        # Config with only 1 multi provider
        config = Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(provider="claude", model="opus"),
                multi=[],  # No multi providers
            ),
            timeout=300,
            parallel_delay=0.0,
            benchmarking=BenchmarkingConfig(enabled=False),
        )

        def mock_invoke(*args, **kwargs):
            # All providers fail
            mock_result = MagicMock()
            mock_result.exit_code = 1
            mock_result.stderr = "Error"
            mock_result.stdout = ""
            mock_result.model = "test"
            mock_result.provider_session_id = "session"
            mock_result.termination_reason = None
            return mock_result

        mock_provider = MagicMock()
        mock_provider.invoke.side_effect = mock_invoke

        with (
            patch(
                "bmad_assist.code_review.orchestrator.get_provider",
                return_value=mock_provider,
            ),
            patch(
                "bmad_assist.code_review.orchestrator._compile_code_review_prompt",
                return_value="compiled prompt",
            ),
        ):
            with pytest.raises(InsufficientReviewsError) as exc_info:
                asyncio.run(
                    run_code_review_phase(
                        config=config,
                        project_path=project_path,
                        epic_num=13,
                        story_num=10,
                    )
                )

            assert exc_info.value.count < exc_info.value.minimum


# ============================================================================
# Provider-error log cleanliness (Task 16)
# ============================================================================
#
# _invoke_reviewer used to log full tracebacks on ANY exception, including
# expected provider-layer failures like auth errors or quota exhaustion.
# On a multi-LLM run, that meant ~50 lines of stack trace per reviewer
# failure — useless noise that drowned real diagnostics. The fix splits
# the handler so ProviderError → clean message, other exceptions → keep
# the traceback (since those indicate actual bugs).


import logging

from bmad_assist.code_review.orchestrator import _invoke_reviewer
from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers.base import ExitStatus


class TestInvokeReviewerErrorLogging:
    """_invoke_reviewer logs provider errors cleanly, other errors with traceback."""

    @pytest.fixture
    def mock_provider(self) -> MagicMock:
        provider = MagicMock()
        provider.provider_name = "mock-provider"
        return provider

    async def _invoke(self, provider: MagicMock) -> tuple:
        return await _invoke_reviewer(
            provider=provider,
            prompt="<compiled/>",
            timeout=60,
            reviewer_id="mock-reviewer",
            model="mock-model",
            timeout_retries=None,
            display_model="mock-display",
        )

    @pytest.mark.asyncio
    async def test_provider_exit_code_error_logged_without_traceback(
        self,
        mock_provider: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Auth errors (ProviderExitCodeError) log clean single-line warning."""
        mock_provider.invoke.side_effect = ProviderExitCodeError(
            "Cursor Agent CLI failed with exit code 1: "
            "Error: Authentication required. Please run 'agent login' first.",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
            stderr="Authentication required",
            stdout="",
            command=("cursor-agent",),
        )

        with caplog.at_level(
            logging.WARNING, logger="bmad_assist.code_review.orchestrator"
        ):
            reviewer_id, output, metrics, error_msg = await self._invoke(mock_provider)

        assert reviewer_id == "mock-reviewer"
        assert output is None
        assert metrics is None
        assert error_msg is not None
        assert "Authentication required" in error_msg
        # No traceback dumped — caplog records have exc_info=None
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warnings, "expected at least one warning log"
        provider_warnings = [
            r for r in warnings if "mock-reviewer failed" in r.getMessage()
        ]
        assert provider_warnings, "expected the 'Reviewer X failed' warning"
        assert all(
            r.exc_info is None for r in provider_warnings
        ), "ProviderError should log WITHOUT traceback"

    @pytest.mark.asyncio
    async def test_provider_timeout_error_logged_without_traceback(
        self,
        mock_provider: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """ProviderTimeoutError also gets clean logging (no exc_info)."""
        mock_provider.invoke.side_effect = ProviderTimeoutError(
            "OpenCode CLI timeout after 1800s: ..."
        )

        with caplog.at_level(
            logging.WARNING, logger="bmad_assist.code_review.orchestrator"
        ):
            _, _, _, error_msg = await self._invoke(mock_provider)

        assert error_msg is not None
        provider_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and "failed" in r.getMessage()
        ]
        assert provider_warnings
        assert all(r.exc_info is None for r in provider_warnings)

    @pytest.mark.asyncio
    async def test_provider_error_base_class_logged_without_traceback(
        self,
        mock_provider: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Any ProviderError subclass — the handler catches the base class."""
        mock_provider.invoke.side_effect = ProviderError("Network disconnected")

        with caplog.at_level(
            logging.WARNING, logger="bmad_assist.code_review.orchestrator"
        ):
            _, _, _, error_msg = await self._invoke(mock_provider)

        assert error_msg is not None
        assert "Network disconnected" in error_msg
        provider_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and "failed" in r.getMessage()
        ]
        assert provider_warnings
        assert all(r.exc_info is None for r in provider_warnings)

    @pytest.mark.asyncio
    async def test_unexpected_exception_keeps_traceback(
        self,
        mock_provider: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Non-Provider exceptions (bugs) must still log with traceback."""
        mock_provider.invoke.side_effect = RuntimeError("surprise bug")

        with caplog.at_level(
            logging.WARNING, logger="bmad_assist.code_review.orchestrator"
        ):
            _, _, _, error_msg = await self._invoke(mock_provider)

        assert error_msg is not None
        provider_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and "failed" in r.getMessage()
        ]
        assert provider_warnings
        # Unexpected exceptions retain exc_info for debuggability.
        assert any(
            r.exc_info is not None for r in provider_warnings
        ), "RuntimeError should log WITH traceback"
