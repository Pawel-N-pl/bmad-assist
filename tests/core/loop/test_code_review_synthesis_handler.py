"""Tests for CodeReviewSynthesisHandler.

Story 14.10: Code Review Synthesis Loop Handler

Tests for CodeReviewSynthesisHandler that integrates the code-review-synthesis
compiler with the main development loop.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.config import (
    BenchmarkingConfig,
    Config,
    MasterProviderConfig,
    MultiProviderConfig,
    ProviderConfig,
)
from bmad_assist.core.state import Phase, State
from bmad_assist.providers.base import ProviderResult

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def synthesis_config(tmp_path: Path) -> Config:
    """Config with master provider for synthesis tests."""
    return Config(
        providers=ProviderConfig(
            master=MasterProviderConfig(provider="claude", model="opus-4"),
            multi=[
                MultiProviderConfig(provider="claude", model="sonnet-4"),
                MultiProviderConfig(provider="gemini", model="gemini-2.5-pro"),
            ],
        ),
        timeout=300,
    )


@pytest.fixture
def project_with_story(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a project with a story file.

    Uses tmp_path for all file operations to avoid polluting real HOME.
    """
    from bmad_assist.core.paths import init_paths

    # Initialize paths singleton for this test
    paths = init_paths(tmp_path)
    paths.ensure_directories()

    # Create a story file in the new location
    story_file = paths.stories_dir / "14-10-code-review-synthesis-handler.md"
    story_file.write_text("""# Story 14.10: Code Review Synthesis Handler

Status: in-progress
Estimate: 5 SP

## Acceptance Criteria

### AC1: Handler Exists
**Given** implementation is complete
**Then** handler should function

## Tasks / Subtasks

- [ ] Task 1: Implement feature

## File List

- `src/handler.py`
- `tests/test_handler.py`
""")

    # Create handlers config directory under tmp_path (not real HOME)
    handlers_dir = tmp_path / ".bmad-assist" / "handlers"
    handlers_dir.mkdir(parents=True, exist_ok=True)

    # Create minimal handler config for synthesis phase
    config_file = handlers_dir / "code_review_synthesis.yaml"
    config_file.write_text("""prompt_template: "Test prompt for code_review_synthesis"
provider_type: master
description: "Test handler for code_review_synthesis"
""")

    # Monkeypatch HANDLERS_CONFIG_DIR to use tmp_path
    monkeypatch.setattr(
        "bmad_assist.core.loop.handlers.base.HANDLERS_CONFIG_DIR",
        handlers_dir,
    )

    return tmp_path


@pytest.fixture
def state_for_synthesis() -> State:
    """State with story position set for synthesis."""
    return State(
        current_epic=14,
        current_story="14.10",
        current_phase=Phase.CODE_REVIEW_SYNTHESIS,
    )


@pytest.fixture
def cached_reviews(project_with_story: Path) -> str:
    """Create cached reviews and return session_id."""
    cache_dir = project_with_story / ".bmad-assist" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    session_id = "test-session-abc123"
    cache_file = cache_dir / f"code-reviews-{session_id}.json"
    cache_file.write_text(
        json.dumps(
            {
                "cache_version": 2,  # TIER 2: Required for v2 format
                "session_id": session_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "reviews": [
                    {
                        "reviewer_id": "Reviewer A",
                        "content": "Test review 1",
                        "original_ref": "ref-1",
                    },
                    {
                        "reviewer_id": "Reviewer B",
                        "content": "Test review 2",
                        "original_ref": "ref-2",
                    },
                ],
                "failed_reviewers": [],
                # TIER 2: Required evidence_score data
                "evidence_score": {
                    "total_score": 1.5,
                    "verdict": "PASS",
                    "per_validator": {
                        "Reviewer A": {"score": 2.0, "verdict": "PASS"},
                        "Reviewer B": {"score": 1.0, "verdict": "PASS"},
                    },
                    "findings_summary": {
                        "CRITICAL": 0,
                        "IMPORTANT": 1,
                        "MINOR": 1,
                        "CLEAN_PASS": 4,
                    },
                    "consensus_ratio": 0.5,
                    "total_findings": 2,
                    "consensus_count": 1,
                    "unique_count": 1,
                },
            }
        )
    )

    return session_id


# =============================================================================
# Test CodeReviewSynthesisHandler
# =============================================================================


class TestCodeReviewSynthesisHandler:
    """Tests for CodeReviewSynthesisHandler class."""

    def test_handler_can_be_imported(self) -> None:
        """AC11: Handler can be imported."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        assert CodeReviewSynthesisHandler is not None

    def test_phase_name_returns_correct_value(
        self,
        synthesis_config: Config,
        project_with_story: Path,
    ) -> None:
        """AC11: phase_name returns correct value."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)
        assert handler.phase_name == "code_review_synthesis"

    def test_build_context_returns_expected_variables(
        self,
        synthesis_config: Config,
        project_with_story: Path,
        state_for_synthesis: State,
    ) -> None:
        """AC11: build_context returns expected variables."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)
        context = handler.build_context(state_for_synthesis)

        assert context["epic_num"] == 14
        assert context["story_num"] == "10"
        assert context["story_id"] == "14.10"

    def test_get_session_id_no_cache_dir_returns_none(
        self,
        synthesis_config: Config,
        tmp_path: Path,
    ) -> None:
        """AC11: _get_session_id_from_cache with no cache dir returns None."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, tmp_path)

        session_id = handler._get_session_id_from_cache()
        assert session_id is None

    def test_get_session_id_finds_cached_review_file(
        self,
        synthesis_config: Config,
        project_with_story: Path,
        cached_reviews: str,
    ) -> None:
        """AC11: _get_session_id_from_cache finds cached review file."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)

        session_id = handler._get_session_id_from_cache()
        assert session_id == cached_reviews

    def test_execute_success_with_mocked_provider(
        self,
        synthesis_config: Config,
        project_with_story: Path,
        state_for_synthesis: State,
        cached_reviews: str,
    ) -> None:
        """AC11: execute() success path with mocked provider."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)

        # Mock debugger to be disabled
        mock_debugger = MagicMock()
        mock_debugger.is_enabled = False

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.loop.interactive.get_debugger", return_value=mock_debugger),
            patch("bmad_assist.core.debug_logger.save_prompt"),
        ):
            mock_render.return_value = "<compiled>test synthesis prompt</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout="# Code Review Synthesis\n\nAll reviewers agree the code is good.",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="opus-4",
                command=("claude", "--print"),
            )

            result = handler.execute(state_for_synthesis)

            assert result.success
            assert "response" in result.outputs
            assert "Code Review Synthesis" in result.outputs["response"]

    def test_execute_fails_when_no_session_found(
        self,
        synthesis_config: Config,
        tmp_path: Path,
    ) -> None:
        """AC11: execute() fails when no session found."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, tmp_path)
        state = State(
            current_epic=14,
            current_story="14.10",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
        )

        result = handler.execute(state)

        assert not result.success
        assert result.error is not None
        assert "no code review session" in result.error.lower()

    def test_execute_fails_when_epic_num_or_story_num_missing(
        self,
        synthesis_config: Config,
        project_with_story: Path,
    ) -> None:
        """AC11: execute() fails when epic_num/story_num missing."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)

        # State without epic/story info
        empty_state = State(current_phase=Phase.CODE_REVIEW_SYNTHESIS)

        result = handler.execute(empty_state)

        assert not result.success
        assert result.error is not None
        assert "missing epic_num or story_num" in result.error.lower()

    def test_synthesis_report_saved_with_correct_frontmatter(
        self,
        synthesis_config: Config,
        project_with_story: Path,
        state_for_synthesis: State,
        cached_reviews: str,
    ) -> None:
        """AC11: Synthesis report is saved with correct frontmatter."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)

        # Mock debugger to be disabled
        mock_debugger = MagicMock()
        mock_debugger.is_enabled = False

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.loop.interactive.get_debugger", return_value=mock_debugger),
            patch("bmad_assist.core.debug_logger.save_prompt"),
        ):
            mock_render.return_value = "<compiled>test</compiled>"
            # Synthesis output needs proper markers for report extraction
            synthesis_output = """# Code Review Synthesis

## Summary

This is a synthesis of code reviews.

<!-- METRICS_JSON_START -->
{"total_issues": 5, "severity": {"critical": 1, "major": 2, "minor": 2}}
<!-- METRICS_JSON_END -->

## Recommendations

- Fix the critical issue first
"""
            mock_invoke.return_value = ProviderResult(
                stdout=synthesis_output,
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="opus-4",
                command=("claude", "--print"),
            )

            handler.execute(state_for_synthesis)

            # Check report was saved in new paths location
            from bmad_assist.core.paths import get_paths

            paths = get_paths()
            # Report filename includes timestamp: synthesis-{epic}-{story}-{timestamp}.md
            synthesis_files = list(paths.code_reviews_dir.glob("synthesis-14-10-*.md"))
            assert len(synthesis_files) == 1, f"Expected 1 synthesis file, found {len(synthesis_files)}"
            report_path = synthesis_files[0]

            content = report_path.read_text()
            assert "---" in content  # Frontmatter markers
            assert "session_id:" in content
            assert "master_reviewer:" in content
            assert "reviewers_used:" in content
            assert "epic: 14" in content
            # Story number may be quoted or unquoted in YAML
            assert "story:" in content and "10" in content
            assert "duration_ms:" in content
            assert "generated_at:" in content

    def test_benchmarking_record_saved_when_enabled(
        self,
        synthesis_config: Config,
        project_with_story: Path,
        state_for_synthesis: State,
        cached_reviews: str,
    ) -> None:
        """AC11: Benchmarking record is saved when enabled."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)

        # Mock debugger to be disabled
        mock_debugger = MagicMock()
        mock_debugger.is_enabled = False

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.loop.interactive.get_debugger", return_value=mock_debugger),
            patch("bmad_assist.core.debug_logger.save_prompt"),
            patch(
                "bmad_assist.validation.benchmarking_integration.should_collect_benchmarking"
            ) as mock_should_collect,
            patch("bmad_assist.benchmarking.storage.save_evaluation_record") as mock_save_record,
            patch(
                "bmad_assist.validation.benchmarking_integration.create_synthesizer_record"
            ) as mock_create_record,
        ):
            mock_should_collect.return_value = True
            mock_render.return_value = "<compiled>test</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout="# Synthesis",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="opus-4",
                command=("claude", "--print"),
            )

            # Create a mock record
            mock_record = MagicMock()
            mock_record.custom = None
            mock_record.model_copy.return_value = mock_record
            mock_create_record.return_value = mock_record

            handler.execute(state_for_synthesis)

            # Verify benchmarking was called
            mock_should_collect.assert_called_once_with(synthesis_config)
            mock_create_record.assert_called_once()
            mock_save_record.assert_called_once()

    def test_benchmarking_errors_dont_fail_synthesis(
        self,
        synthesis_config: Config,
        project_with_story: Path,
        state_for_synthesis: State,
        cached_reviews: str,
    ) -> None:
        """AC11: Benchmarking errors don't fail synthesis."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)

        # Mock debugger to be disabled
        mock_debugger = MagicMock()
        mock_debugger.is_enabled = False

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.loop.interactive.get_debugger", return_value=mock_debugger),
            patch("bmad_assist.core.debug_logger.save_prompt"),
            patch(
                "bmad_assist.validation.benchmarking_integration.should_collect_benchmarking"
            ) as mock_should_collect,
            patch(
                "bmad_assist.validation.benchmarking_integration.create_synthesizer_record"
            ) as mock_create_record,
        ):
            mock_should_collect.return_value = True
            mock_render.return_value = "<compiled>test</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout="# Synthesis",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="opus-4",
                command=("claude", "--print"),
            )

            # Make benchmarking raise an exception
            mock_create_record.side_effect = RuntimeError("Benchmarking failed!")

            result = handler.execute(state_for_synthesis)

            # Synthesis should still succeed
            assert result.success

    def test_benchmarking_skipped_when_disabled(
        self,
        project_with_story: Path,
        state_for_synthesis: State,
        cached_reviews: str,
    ) -> None:
        """AC7: Benchmarking skipped when disabled.

        Story 14.11: Verify _save_synthesizer_record() returns early
        with debug log when benchmarking is disabled.
        """
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        # Create config with benchmarking explicitly disabled
        config_disabled = Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(provider="claude", model="opus-4"),
                multi=[],
            ),
            timeout=300,
            benchmarking=BenchmarkingConfig(enabled=False),
        )

        handler = CodeReviewSynthesisHandler(config_disabled, project_with_story)

        # Mock debugger to be disabled
        mock_debugger = MagicMock()
        mock_debugger.is_enabled = False

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.loop.interactive.get_debugger", return_value=mock_debugger),
            patch("bmad_assist.core.debug_logger.save_prompt"),
            patch("bmad_assist.benchmarking.storage.save_evaluation_record") as mock_save,
        ):
            mock_render.return_value = "<compiled>test</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout="# Synthesis",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="opus-4",
                command=("claude", "--print"),
            )

            result = handler.execute(state_for_synthesis)

            # Synthesis should succeed
            assert result.success

            # save_evaluation_record should NOT be called when benchmarking disabled
            mock_save.assert_not_called()

    def test_custom_metrics_include_phase_and_reviewer_count(
        self,
        project_with_story: Path,
        state_for_synthesis: State,
        cached_reviews: str,
    ) -> None:
        """AC4: Custom metrics include phase and reviewer_count.

        Story 14.11: Verify record.custom contains:
        - phase: "code-review-synthesis"
        - reviewer_count: len(anonymized_reviews)
        """
        from bmad_assist.benchmarking.schema import LLMEvaluationRecord
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        # Create config with benchmarking enabled (default is True, but explicit is better)
        config_with_benchmarking = Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(provider="claude", model="opus-4"),
                multi=[],
            ),
            timeout=300,
            benchmarking=BenchmarkingConfig(enabled=True),
        )

        handler = CodeReviewSynthesisHandler(config_with_benchmarking, project_with_story)

        # Mock debugger to be disabled
        mock_debugger = MagicMock()
        mock_debugger.is_enabled = False

        # Track the record passed to save_evaluation_record
        saved_record: LLMEvaluationRecord | None = None

        def capture_record(record: LLMEvaluationRecord, base_dir: Path) -> Path:
            nonlocal saved_record
            saved_record = record
            return base_dir / "test-record.yaml"

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.loop.interactive.get_debugger", return_value=mock_debugger),
            patch("bmad_assist.core.debug_logger.save_prompt"),
            patch(
                "bmad_assist.benchmarking.storage.save_evaluation_record",
                side_effect=capture_record,
            ),
        ):
            mock_render.return_value = "<compiled>test</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout="# Synthesis\n\nReviewers agreed.",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="opus-4",
                command=("claude", "--print"),
            )

            result = handler.execute(state_for_synthesis)

            # Synthesis should succeed
            assert result.success

            # Verify custom metrics were saved
            assert saved_record is not None
            assert saved_record.custom is not None
            assert saved_record.custom.get("phase") == "code-review-synthesis"
            # cached_reviews fixture creates 2 reviews
            assert saved_record.custom.get("reviewer_count") == 2

    def test_workflow_variant_defaults_to_default(
        self,
        project_with_story: Path,
        state_for_synthesis: State,
        cached_reviews: str,
    ) -> None:
        """AC5: Workflow variant defaults to 'default' when config uses default value.

        Story 14.11: Verify workflow.variant propagation.
        Config.workflow_variant defaults to "default" (not None).
        """
        from bmad_assist.benchmarking.schema import LLMEvaluationRecord
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        # Create config with benchmarking enabled - workflow_variant uses default "default"
        config_with_default_variant = Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(provider="claude", model="opus-4"),
                multi=[],
            ),
            timeout=300,
            benchmarking=BenchmarkingConfig(enabled=True),
            # workflow_variant not specified - uses default "default"
        )

        handler = CodeReviewSynthesisHandler(config_with_default_variant, project_with_story)

        # Mock debugger to be disabled
        mock_debugger = MagicMock()
        mock_debugger.is_enabled = False

        # Track the record passed to save_evaluation_record
        saved_record: LLMEvaluationRecord | None = None

        def capture_record(record: LLMEvaluationRecord, base_dir: Path) -> Path:
            nonlocal saved_record
            saved_record = record
            return base_dir / "test-record.yaml"

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.loop.interactive.get_debugger", return_value=mock_debugger),
            patch("bmad_assist.core.debug_logger.save_prompt"),
            patch(
                "bmad_assist.benchmarking.storage.save_evaluation_record",
                side_effect=capture_record,
            ),
        ):
            mock_render.return_value = "<compiled>test</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout="# Synthesis",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="opus-4",
                command=("claude", "--print"),
            )

            result = handler.execute(state_for_synthesis)

            # Synthesis should succeed
            assert result.success

            # Verify workflow variant defaults to "default"
            assert saved_record is not None
            assert saved_record.workflow.variant == "default"

    def test_interactive_debugger_integration(
        self,
        synthesis_config: Config,
        project_with_story: Path,
        state_for_synthesis: State,
        cached_reviews: str,
    ) -> None:
        """AC11: Interactive debugger integration."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)

        # Mock debugger that returns False (user quit)
        mock_debugger = MagicMock()
        mock_debugger.is_enabled = True
        mock_debugger.run_debug_loop.return_value = False

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.loop.interactive.get_debugger", return_value=mock_debugger),
            patch("bmad_assist.core.debug_logger.save_prompt"),
        ):
            mock_render.return_value = "<compiled>test</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout="# Synthesis",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="opus-4",
                command=("claude", "--print"),
            )

            result = handler.execute(state_for_synthesis)

            # Should fail with user interrupted message
            assert not result.success
            assert result.error is not None
            assert "User interrupted" in result.error

            # Verify debugger was called
            mock_debugger.run_debug_loop.assert_called_once()

    def test_execute_fails_on_provider_error(
        self,
        synthesis_config: Config,
        project_with_story: Path,
        state_for_synthesis: State,
        cached_reviews: str,
    ) -> None:
        """AC10: Provider exit_code != 0 returns PhaseResult.fail()."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)

        # Mock debugger to be disabled
        mock_debugger = MagicMock()
        mock_debugger.is_enabled = False

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.loop.interactive.get_debugger", return_value=mock_debugger),
            patch("bmad_assist.core.debug_logger.save_prompt"),
        ):
            mock_render.return_value = "<compiled>test</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout="",
                stderr="Provider crashed with error",
                exit_code=1,
                duration_ms=1000,
                model="opus-4",
                command=("claude", "--print"),
            )

            result = handler.execute(state_for_synthesis)

            assert not result.success
            assert result.error is not None
            assert "Provider crashed" in result.error or "exited with code" in result.error

    def test_execute_fails_on_empty_reviews(
        self,
        synthesis_config: Config,
        project_with_story: Path,
        state_for_synthesis: State,
    ) -> None:
        """AC10: Empty reviews returns PhaseResult.fail()."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)

        # Create cache file with empty reviews (v2 format)
        cache_dir = project_with_story / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        session_id = "test-session-empty"
        cache_file = cache_dir / f"code-reviews-{session_id}.json"
        cache_file.write_text(
            json.dumps(
                {
                    "cache_version": 2,
                    "session_id": session_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "reviews": [],
                    "failed_reviewers": [],
                    "evidence_score": {
                        "total_score": 0.0,
                        "verdict": "PASS",
                        "per_validator": {},
                        "findings_summary": {
                            "CRITICAL": 0,
                            "IMPORTANT": 0,
                            "MINOR": 0,
                            "CLEAN_PASS": 0,
                        },
                        "consensus_ratio": 0.0,
                        "total_findings": 0,
                        "consensus_count": 0,
                        "unique_count": 0,
                    },
                }
            )
        )

        result = handler.execute(state_for_synthesis)

        assert not result.success
        assert result.error is not None
        assert "no code reviews" in result.error.lower()


# =============================================================================
# Test data passing from CODE_REVIEW handler
# =============================================================================


class TestCodeReviewSynthesisIntegration:
    """Tests for data passing between CODE_REVIEW and CODE_REVIEW_SYNTHESIS handlers."""

    def test_session_id_passed_from_code_review(
        self,
        synthesis_config: Config,
        project_with_story: Path,
    ) -> None:
        """AC11: Session ID from CODE_REVIEW handler is found by synthesis handler."""
        from bmad_assist.code_review.orchestrator import save_reviews_for_synthesis
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        # Simulate what CODE_REVIEW handler does - save reviews
        reviews = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="Code looks good",
                original_ref="ref-1",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="Minor issues found",
                original_ref="ref-2",
            ),
        ]

        saved_session = save_reviews_for_synthesis(
            reviews,
            project_with_story,
        )

        # Now synthesis handler should find it
        synthesis_handler = CodeReviewSynthesisHandler(
            synthesis_config,
            project_with_story,
        )

        found_session = synthesis_handler._get_session_id_from_cache()

        assert found_session == saved_session

    def test_load_reviews_for_synthesis(
        self,
        synthesis_config: Config,
        project_with_story: Path,
    ) -> None:
        """Test reviews can be loaded after being saved."""
        from bmad_assist.code_review.orchestrator import (
            load_reviews_for_synthesis,
            save_reviews_for_synthesis,
        )
        from bmad_assist.validation.anonymizer import AnonymizedValidation
        from bmad_assist.validation.evidence_score import (
            EvidenceScoreAggregate,
            Severity,
            Verdict,
        )

        # Save reviews with evidence score (required for v2 cache)
        reviews = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="Test content 1",
                original_ref="ref-1",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="Test content 2",
                original_ref="ref-2",
            ),
        ]

        evidence = EvidenceScoreAggregate(
            total_score=1.5,
            verdict=Verdict.PASS,
            per_validator_scores={"Reviewer A": 2.0, "Reviewer B": 1.0},
            per_validator_verdicts={
                "Reviewer A": Verdict.PASS,
                "Reviewer B": Verdict.PASS,
            },
            findings_by_severity={
                Severity.CRITICAL: 0,
                Severity.IMPORTANT: 1,
                Severity.MINOR: 0,
            },
            total_findings=1,
            total_clean_passes=4,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.0,
        )

        session_id = save_reviews_for_synthesis(
            reviews, project_with_story, evidence_aggregate=evidence
        )

        # Load reviews - TIER 2: returns tuple of (reviews, failed_reviewer_ids, evidence_data)
        loaded, failed_ids, evidence_data = load_reviews_for_synthesis(
            session_id, project_with_story
        )

        assert len(loaded) == 2
        assert loaded[0].validator_id == "Reviewer A"
        assert loaded[0].content == "Test content 1"
        assert loaded[1].validator_id == "Reviewer B"
        assert loaded[1].content == "Test content 2"
        assert failed_ids == []  # No failures in this test
        assert evidence_data is not None
