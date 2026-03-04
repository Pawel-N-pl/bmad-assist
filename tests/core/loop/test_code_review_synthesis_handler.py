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
# Constants
# =============================================================================

# Realistic synthesis output for mocks (must exceed MIN_SYNTHESIS_CHARS=200)
_MOCK_SYNTHESIS_OUTPUT = (
    "## Synthesis Summary\n\n"
    "6 reviewers analyzed the implementation. After cross-referencing with story "
    "acceptance criteria and project context:\n\n"
    "## Issues Verified\n\n"
    "### Critical\n"
    "- Missing input validation on user endpoint\n\n"
    "### High\n"
    "- Error handling incomplete in service layer\n\n"
    "## Issues Dismissed\n\n"
    "- False positive: style preferences from Reviewer C\n\n"
    "## Changes Applied\n\n"
    "Applied fixes for critical input validation issue.\n"
)

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

    def test_get_session_id_recovers_from_story_reports_when_cache_missing(
        self,
        synthesis_config: Config,
        project_with_story: Path,
    ) -> None:
        """Session discovery should fall back to code-review markdown reports."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )
        from bmad_assist.core.paths import get_paths

        paths = get_paths()
        report_path = paths.code_reviews_dir / "code-review-14-10-a-20260219T051055Z.md"
        report_path.write_text(
            "---\n"
            "session_id: recovered-session\n"
            "reviewer_id: Validator A\n"
            "role_id: a\n"
            "epic: 14\n"
            "story: '10'\n"
            "---\n\n"
            "# Review\n\n"
            "Recovered review content.\n",
            encoding="utf-8",
        )

        handler = CodeReviewSynthesisHandler(synthesis_config, project_with_story)

        session_id = handler._get_session_id_from_cache(14, "10")
        assert session_id == "recovered-session"

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

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.debug_logger.save_prompt"),
        ):
            mock_render.return_value = "<compiled>test synthesis prompt</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout=_MOCK_SYNTHESIS_OUTPUT,
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="opus-4",
                command=("claude", "--print"),
            )

            result = handler.execute(state_for_synthesis)

            assert result.success
            assert "response" in result.outputs
            assert "Synthesis Summary" in result.outputs["response"]

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

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
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

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
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
                stdout=_MOCK_SYNTHESIS_OUTPUT,
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

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
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
                stdout=_MOCK_SYNTHESIS_OUTPUT,
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

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.debug_logger.save_prompt"),
            patch("bmad_assist.benchmarking.storage.save_evaluation_record") as mock_save,
        ):
            mock_render.return_value = "<compiled>test</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout=_MOCK_SYNTHESIS_OUTPUT,
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

        # Track the record passed to save_evaluation_record
        saved_record: LLMEvaluationRecord | None = None

        def capture_record(record: LLMEvaluationRecord, base_dir: Path) -> Path:
            nonlocal saved_record
            saved_record = record
            return base_dir / "test-record.yaml"

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.debug_logger.save_prompt"),
            patch(
                "bmad_assist.benchmarking.storage.save_evaluation_record",
                side_effect=capture_record,
            ),
        ):
            mock_render.return_value = "<compiled>test</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout=_MOCK_SYNTHESIS_OUTPUT,
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

        # Track the record passed to save_evaluation_record
        saved_record: LLMEvaluationRecord | None = None

        def capture_record(record: LLMEvaluationRecord, base_dir: Path) -> Path:
            nonlocal saved_record
            saved_record = record
            return base_dir / "test-record.yaml"

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.debug_logger.save_prompt"),
            patch(
                "bmad_assist.benchmarking.storage.save_evaluation_record",
                side_effect=capture_record,
            ),
        ):
            mock_render.return_value = "<compiled>test</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout=_MOCK_SYNTHESIS_OUTPUT,
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

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
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


# =============================================================================
# Test Adaptive Synthesis Prompt Compression Pipeline
# =============================================================================


class TestCompressionPipelineIntegration:
    """Integration tests for the adaptive synthesis prompt compression pipeline.

    Tests the render_prompt() compression flow in CodeReviewSynthesisHandler:
    1. Token estimation and step decision
    2. Step 0: skip_source_files in resolved_variables
    3. Step 1: pre_extract_reviews invocation
    4. Step 2: progressive_synthesize invocation
    5. Fallback behavior on extraction failure
    6. Compression metrics storage
    7. Benchmarking integration with compression metrics
    """

    @pytest.fixture
    def mock_reviews(self) -> list:
        """Create test AnonymizedValidation instances."""
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        return [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="Review A content with findings and issues.",
                original_ref="ref-a",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="Review B content with suggestions.",
                original_ref="ref-b",
            ),
            AnonymizedValidation(
                validator_id="Reviewer C",
                content="Review C content clean pass.",
                original_ref="ref-c",
            ),
        ]

    @pytest.fixture
    def extracted_reviews(self) -> list:
        """Create extracted (compressed) AnonymizedValidation instances."""
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        return [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="Extracted A: issue1, issue2",
                original_ref="ref-a",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="Extracted B: suggestion1",
                original_ref="ref-b",
            ),
            AnonymizedValidation(
                validator_id="Reviewer C",
                content="Extracted C: clean",
                original_ref="ref-c",
            ),
        ]

    @pytest.fixture
    def progressive_reviews(self) -> list:
        """Create progressively synthesized AnonymizedValidation instances."""
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        return [
            AnonymizedValidation(
                validator_id="Consolidated Findings (3 reviewers)",
                content="All findings merged.",
                original_ref="meta-synthesis",
            ),
        ]

    @pytest.fixture
    def compression_handler(
        self,
        synthesis_config: Config,
        project_with_story: Path,
    ):
        """Create a CodeReviewSynthesisHandler for compression tests."""
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        return CodeReviewSynthesisHandler(synthesis_config, project_with_story)

    @pytest.fixture
    def compression_state(self) -> State:
        """State for compression pipeline tests."""
        return State(
            current_epic=14,
            current_story="14.10",
            current_phase=Phase.CODE_REVIEW_SYNTHESIS,
        )

    def _mock_compiled_workflow(self):
        """Create a mock CompiledWorkflow return value."""
        from bmad_assist.compiler.types import CompiledWorkflow

        return CompiledWorkflow(
            workflow_name="code-review-synthesis",
            mission="Synthesize code reviews",
            context="<compiled>mock synthesis prompt</compiled>",
            variables={},
            instructions="",
            output_template="",
            token_estimate=5000,
        )

    def test_render_prompt_passthrough_no_compression(
        self,
        compression_handler,
        compression_state: State,
        project_with_story: Path,
        mock_reviews: list,
    ) -> None:
        """No compression when total tokens are under budget.

        Verify that when estimate_synthesis_tokens returns a value below
        the token budget, no extraction calls are made, the original
        anonymized_reviews are passed to the compiler unchanged, and
        compression_steps_applied is an empty list.
        """
        compiled = self._mock_compiled_workflow()

        with (
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.load_reviews_for_synthesis"
            ) as mock_load,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.compile_workflow"
            ) as mock_compile,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_base_context_tokens"
            ) as mock_base_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_synthesis_tokens"
            ) as mock_total_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.decide_compression_steps"
            ) as mock_decide,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.pre_extract_reviews"
            ) as mock_pre_extract,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_paths"
            ) as mock_get_paths,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_original_cwd",
                return_value=project_with_story,
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis."
                "load_security_findings_from_cache",
                return_value=None,
            ),
        ):
            mock_load.return_value = (mock_reviews, [], None)
            mock_base_tokens.return_value = 10_000
            mock_total_tokens.return_value = 50_000  # Under default budget of 120K
            mock_decide.return_value = []  # No compression needed

            mock_paths = MagicMock()
            mock_paths.implementation_artifacts = project_with_story / "_bmad-output"
            mock_paths.project_knowledge = project_with_story / "docs"
            mock_get_paths.return_value = mock_paths

            mock_compile.return_value = compiled

            # Create a cache file so _get_session_id_from_cache finds it
            cache_dir = project_with_story / ".bmad-assist" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "code-reviews-passthrough-session.json"
            cache_file.write_text(
                json.dumps({
                    "cache_version": 2,
                    "session_id": "passthrough-session",
                    "timestamp": "2026-02-20T00:00:00Z",
                    "reviews": [],
                    "failed_reviewers": [],
                    "evidence_score": None,
                })
            )

            result = compression_handler.render_prompt(compression_state)

            # Verify no extraction calls were made
            mock_pre_extract.assert_not_called()

            # Verify original reviews passed to compiler unchanged
            compile_call_args = mock_compile.call_args
            compiler_context = compile_call_args[0][1]  # Second positional arg
            assert compiler_context.resolved_variables["anonymized_reviews"] is mock_reviews

            # Verify compression metrics
            assert compression_handler._compression_metrics["compression_steps_applied"] == []
            assert result == compiled.context

    def test_render_prompt_step0_sets_skip_source_files(
        self,
        compression_handler,
        compression_state: State,
        project_with_story: Path,
        mock_reviews: list,
    ) -> None:
        """Step 0 sets skip_source_files=True when base context exceeds limit.

        Verify that when estimate_base_context_tokens returns a value
        above base_context_limit, skip_source_files=True is set in the
        resolved_variables passed to compile_workflow.
        """
        compiled = self._mock_compiled_workflow()

        with (
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.load_reviews_for_synthesis"
            ) as mock_load,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.compile_workflow"
            ) as mock_compile,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_base_context_tokens"
            ) as mock_base_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_synthesis_tokens"
            ) as mock_total_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.decide_compression_steps"
            ) as mock_decide,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_paths"
            ) as mock_get_paths,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_original_cwd",
                return_value=project_with_story,
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis."
                "load_security_findings_from_cache",
                return_value=None,
            ),
        ):
            mock_load.return_value = (mock_reviews, [], None)
            # Base tokens exceeds base_context_limit (default 40K)
            mock_base_tokens.return_value = 50_000
            # Total tokens under budget so step1 not triggered (only step0)
            mock_total_tokens.return_value = 80_000
            mock_decide.return_value = ["step0"]  # Only step0

            mock_paths = MagicMock()
            mock_paths.implementation_artifacts = project_with_story / "_bmad-output"
            mock_paths.project_knowledge = project_with_story / "docs"
            mock_get_paths.return_value = mock_paths

            mock_compile.return_value = compiled

            cache_dir = project_with_story / ".bmad-assist" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "code-reviews-step0-session.json"
            cache_file.write_text(
                json.dumps({
                    "cache_version": 2,
                    "session_id": "step0-session",
                    "timestamp": "2026-02-20T00:00:00Z",
                    "reviews": [],
                    "failed_reviewers": [],
                    "evidence_score": None,
                })
            )

            compression_handler.render_prompt(compression_state)

            # Verify skip_source_files=True in resolved_variables
            compile_call_args = mock_compile.call_args
            compiler_context = compile_call_args[0][1]
            assert compiler_context.resolved_variables["skip_source_files"] is True

            # Verify step0 in metrics
            assert "step0" in compression_handler._compression_metrics["compression_steps_applied"]

    def test_render_prompt_step1_calls_pre_extract(
        self,
        compression_handler,
        compression_state: State,
        project_with_story: Path,
        mock_reviews: list,
        extracted_reviews: list,
    ) -> None:
        """Step 1 calls pre_extract_reviews when total tokens exceed budget.

        Verify that pre_extract_reviews is called with correct arguments
        and compressed reviews are passed to the compiler.
        """
        compiled = self._mock_compiled_workflow()

        with (
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.load_reviews_for_synthesis"
            ) as mock_load,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.compile_workflow"
            ) as mock_compile,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_base_context_tokens"
            ) as mock_base_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_synthesis_tokens"
            ) as mock_total_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.decide_compression_steps"
            ) as mock_decide,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.pre_extract_reviews"
            ) as mock_pre_extract,
            patch(
                "bmad_assist.providers.registry.get_provider"
            ) as mock_get_provider,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_paths"
            ) as mock_get_paths,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_original_cwd",
                return_value=project_with_story,
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis."
                "load_security_findings_from_cache",
                return_value=None,
            ),
        ):
            mock_load.return_value = (mock_reviews, [], None)
            mock_base_tokens.return_value = 10_000
            # First call: total > budget; second call (after extraction): under budget
            mock_total_tokens.side_effect = [150_000, 80_000]
            mock_decide.return_value = ["step1"]

            mock_pre_extract.return_value = extracted_reviews

            mock_provider = MagicMock()
            mock_get_provider.return_value = mock_provider

            mock_paths = MagicMock()
            mock_paths.implementation_artifacts = project_with_story / "_bmad-output"
            mock_paths.project_knowledge = project_with_story / "docs"
            mock_get_paths.return_value = mock_paths

            mock_compile.return_value = compiled

            cache_dir = project_with_story / ".bmad-assist" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "code-reviews-step1-session.json"
            cache_file.write_text(
                json.dumps({
                    "cache_version": 2,
                    "session_id": "step1-session",
                    "timestamp": "2026-02-20T00:00:00Z",
                    "reviews": [],
                    "failed_reviewers": [],
                    "evidence_score": None,
                })
            )

            compression_handler.render_prompt(compression_state)

            # Verify pre_extract_reviews was called
            mock_pre_extract.assert_called_once()
            call_kwargs = mock_pre_extract.call_args
            assert call_kwargs[1]["reviews"] is mock_reviews

            # Verify extracted reviews passed to compiler
            compile_call_args = mock_compile.call_args
            compiler_context = compile_call_args[0][1]
            assert compiler_context.resolved_variables["anonymized_reviews"] is extracted_reviews

    def test_render_prompt_step1_skip_step2_when_under_budget(
        self,
        compression_handler,
        compression_state: State,
        project_with_story: Path,
        mock_reviews: list,
        extracted_reviews: list,
    ) -> None:
        """Step 2 (progressive_synthesize) is NOT called when step 1 reduces tokens below budget.

        Verify that after pre_extract_reviews reduces the token count
        below the budget, progressive_synthesize is not called.
        """
        compiled = self._mock_compiled_workflow()

        with (
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.load_reviews_for_synthesis"
            ) as mock_load,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.compile_workflow"
            ) as mock_compile,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_base_context_tokens"
            ) as mock_base_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_synthesis_tokens"
            ) as mock_total_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.decide_compression_steps"
            ) as mock_decide,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.pre_extract_reviews"
            ) as mock_pre_extract,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.progressive_synthesize"
            ) as mock_progressive,
            patch(
                "bmad_assist.providers.registry.get_provider"
            ) as mock_get_provider,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_paths"
            ) as mock_get_paths,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_original_cwd",
                return_value=project_with_story,
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis."
                "load_security_findings_from_cache",
                return_value=None,
            ),
        ):
            mock_load.return_value = (mock_reviews, [], None)
            mock_base_tokens.return_value = 10_000
            # First call: total > budget; second call (after step1): under budget
            mock_total_tokens.side_effect = [150_000, 80_000]
            mock_decide.return_value = ["step1"]

            mock_pre_extract.return_value = extracted_reviews

            mock_provider = MagicMock()
            mock_get_provider.return_value = mock_provider

            mock_paths = MagicMock()
            mock_paths.implementation_artifacts = project_with_story / "_bmad-output"
            mock_paths.project_knowledge = project_with_story / "docs"
            mock_get_paths.return_value = mock_paths

            mock_compile.return_value = compiled

            cache_dir = project_with_story / ".bmad-assist" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "code-reviews-skip-step2-session.json"
            cache_file.write_text(
                json.dumps({
                    "cache_version": 2,
                    "session_id": "skip-step2-session",
                    "timestamp": "2026-02-20T00:00:00Z",
                    "reviews": [],
                    "failed_reviewers": [],
                    "evidence_score": None,
                })
            )

            compression_handler.render_prompt(compression_state)

            # Step 1 was called
            mock_pre_extract.assert_called_once()
            # Step 2 should NOT be called since tokens dropped below budget
            mock_progressive.assert_not_called()

    def test_render_prompt_step1_plus_step2(
        self,
        compression_handler,
        compression_state: State,
        project_with_story: Path,
        mock_reviews: list,
        extracted_reviews: list,
        progressive_reviews: list,
    ) -> None:
        """Step 2 (progressive_synthesize) IS called when step 1 still exceeds budget.

        Verify that when pre_extract_reviews does not reduce tokens
        below the budget, progressive_synthesize is called.
        """
        compiled = self._mock_compiled_workflow()

        with (
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.load_reviews_for_synthesis"
            ) as mock_load,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.compile_workflow"
            ) as mock_compile,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_base_context_tokens"
            ) as mock_base_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_synthesis_tokens"
            ) as mock_total_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.decide_compression_steps"
            ) as mock_decide,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.pre_extract_reviews"
            ) as mock_pre_extract,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.progressive_synthesize"
            ) as mock_progressive,
            patch(
                "bmad_assist.providers.registry.get_provider"
            ) as mock_get_provider,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_paths"
            ) as mock_get_paths,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_original_cwd",
                return_value=project_with_story,
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis."
                "load_security_findings_from_cache",
                return_value=None,
            ),
        ):
            mock_load.return_value = (mock_reviews, [], None)
            mock_base_tokens.return_value = 10_000
            # First: total > budget; after step1: still > budget; after step2: under budget
            mock_total_tokens.side_effect = [150_000, 130_000, 50_000]
            mock_decide.return_value = ["step1"]

            mock_pre_extract.return_value = extracted_reviews
            mock_progressive.return_value = progressive_reviews

            mock_provider = MagicMock()
            mock_get_provider.return_value = mock_provider

            mock_paths = MagicMock()
            mock_paths.implementation_artifacts = project_with_story / "_bmad-output"
            mock_paths.project_knowledge = project_with_story / "docs"
            mock_get_paths.return_value = mock_paths

            mock_compile.return_value = compiled

            cache_dir = project_with_story / ".bmad-assist" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "code-reviews-step1-step2-session.json"
            cache_file.write_text(
                json.dumps({
                    "cache_version": 2,
                    "session_id": "step1-step2-session",
                    "timestamp": "2026-02-20T00:00:00Z",
                    "reviews": [],
                    "failed_reviewers": [],
                    "evidence_score": None,
                })
            )

            compression_handler.render_prompt(compression_state)

            # Both step 1 and step 2 were called
            mock_pre_extract.assert_called_once()
            mock_progressive.assert_called_once()

            # Verify progressive reviews passed to compiler
            compile_call_args = mock_compile.call_args
            compiler_context = compile_call_args[0][1]
            assert (
                compiler_context.resolved_variables["anonymized_reviews"]
                is progressive_reviews
            )

    def test_render_prompt_extraction_failure_fallback(
        self,
        compression_handler,
        compression_state: State,
        project_with_story: Path,
        mock_reviews: list,
    ) -> None:
        """Extraction failure falls back to raw reviews with [RAW] prefix.

        When pre_extract_reviews returns reviews with [RAW] prefix
        (internal fallback), the handler should still complete
        successfully and pass those reviews to the compiler.
        """
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        # Simulate pre_extract_reviews fallback: [RAW] prefixed reviews
        raw_fallback_reviews = [
            AnonymizedValidation(
                validator_id="[RAW] Reviewer A",
                content="Review A content with findings and issues.",
                original_ref="ref-a",
            ),
            AnonymizedValidation(
                validator_id="[RAW] Reviewer B",
                content="Review B content with suggestions.",
                original_ref="ref-b",
            ),
            AnonymizedValidation(
                validator_id="[RAW] Reviewer C",
                content="Review C content clean pass.",
                original_ref="ref-c",
            ),
        ]

        compiled = self._mock_compiled_workflow()

        with (
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.load_reviews_for_synthesis"
            ) as mock_load,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.compile_workflow"
            ) as mock_compile,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_base_context_tokens"
            ) as mock_base_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_synthesis_tokens"
            ) as mock_total_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.decide_compression_steps"
            ) as mock_decide,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.pre_extract_reviews"
            ) as mock_pre_extract,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.progressive_synthesize"
            ) as mock_progressive,
            patch(
                "bmad_assist.providers.registry.get_provider"
            ) as mock_get_provider,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_paths"
            ) as mock_get_paths,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_original_cwd",
                return_value=project_with_story,
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis."
                "load_security_findings_from_cache",
                return_value=None,
            ),
        ):
            mock_load.return_value = (mock_reviews, [], None)
            mock_base_tokens.return_value = 10_000
            # First call: over budget; second (after fallback): still over; third (after prog): ok
            mock_total_tokens.side_effect = [150_000, 150_000, 80_000]
            mock_decide.return_value = ["step1"]

            # pre_extract_reviews returns raw fallback reviews (mimics internal failure handling)
            mock_pre_extract.return_value = raw_fallback_reviews

            # progressive_synthesize returns the fallback reviews as-is (further processing)
            mock_progressive.return_value = raw_fallback_reviews

            mock_provider = MagicMock()
            mock_get_provider.return_value = mock_provider

            mock_paths = MagicMock()
            mock_paths.implementation_artifacts = project_with_story / "_bmad-output"
            mock_paths.project_knowledge = project_with_story / "docs"
            mock_get_paths.return_value = mock_paths

            mock_compile.return_value = compiled

            cache_dir = project_with_story / ".bmad-assist" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "code-reviews-fallback-session.json"
            cache_file.write_text(
                json.dumps({
                    "cache_version": 2,
                    "session_id": "fallback-session",
                    "timestamp": "2026-02-20T00:00:00Z",
                    "reviews": [],
                    "failed_reviewers": [],
                    "evidence_score": None,
                })
            )

            result = compression_handler.render_prompt(compression_state)

            # Handler should complete successfully
            assert result == compiled.context

            # Verify fallback reviews were passed to compiler
            compile_call_args = mock_compile.call_args
            compiler_context = compile_call_args[0][1]
            reviews_in_context = compiler_context.resolved_variables["anonymized_reviews"]
            # Check that [RAW] prefix is preserved (indicating fallback)
            assert all(
                r.validator_id.startswith("[RAW]") for r in reviews_in_context
            )

    def test_compression_metrics_stored(
        self,
        compression_handler,
        compression_state: State,
        project_with_story: Path,
        mock_reviews: list,
        extracted_reviews: list,
    ) -> None:
        """After render_prompt, compression metrics dict has all expected keys.

        Verify that self._compression_metrics contains:
        - compression_steps_applied
        - original_token_estimate
        - compressed_token_estimate
        - extraction_llm_calls
        - extraction_duration_ms
        """
        compiled = self._mock_compiled_workflow()

        with (
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.load_reviews_for_synthesis"
            ) as mock_load,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.compile_workflow"
            ) as mock_compile,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_base_context_tokens"
            ) as mock_base_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.estimate_synthesis_tokens"
            ) as mock_total_tokens,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.decide_compression_steps"
            ) as mock_decide,
            patch(
                "bmad_assist.core.loop.handlers.synthesis_utils.pre_extract_reviews"
            ) as mock_pre_extract,
            patch(
                "bmad_assist.providers.registry.get_provider"
            ) as mock_get_provider,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_paths"
            ) as mock_get_paths,
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis.get_original_cwd",
                return_value=project_with_story,
            ),
            patch(
                "bmad_assist.core.loop.handlers.code_review_synthesis."
                "load_security_findings_from_cache",
                return_value=None,
            ),
        ):
            mock_load.return_value = (mock_reviews, [], None)
            mock_base_tokens.return_value = 10_000
            # First call (initial): 150K; second call (after step1): 80K
            mock_total_tokens.side_effect = [150_000, 80_000]
            mock_decide.return_value = ["step1"]

            mock_pre_extract.return_value = extracted_reviews

            mock_provider = MagicMock()
            mock_get_provider.return_value = mock_provider

            mock_paths = MagicMock()
            mock_paths.implementation_artifacts = project_with_story / "_bmad-output"
            mock_paths.project_knowledge = project_with_story / "docs"
            mock_get_paths.return_value = mock_paths

            mock_compile.return_value = compiled

            cache_dir = project_with_story / ".bmad-assist" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "code-reviews-metrics-session.json"
            cache_file.write_text(
                json.dumps({
                    "cache_version": 2,
                    "session_id": "metrics-session",
                    "timestamp": "2026-02-20T00:00:00Z",
                    "reviews": [],
                    "failed_reviewers": [],
                    "evidence_score": None,
                })
            )

            compression_handler.render_prompt(compression_state)

            # Verify all expected keys exist in compression_metrics
            metrics = compression_handler._compression_metrics
            assert "compression_steps_applied" in metrics
            assert "original_token_estimate" in metrics
            assert "compressed_token_estimate" in metrics
            assert "extraction_llm_calls" in metrics
            assert "extraction_duration_ms" in metrics

            # Verify values are reasonable
            assert metrics["compression_steps_applied"] == ["step1"]
            assert metrics["original_token_estimate"] == 150_000
            assert metrics["compressed_token_estimate"] == 80_000
            assert metrics["extraction_llm_calls"] == 1  # ceil(3 reviews / 5 batch_size) = 1
            assert isinstance(metrics["extraction_duration_ms"], int)
            assert metrics["extraction_duration_ms"] >= 0

    def test_benchmarking_includes_compression_metrics(
        self,
        project_with_story: Path,
        compression_state: State,
        cached_reviews: str,
        mock_reviews: list,
        extracted_reviews: list,
    ) -> None:
        """Benchmarking record includes compression metrics in custom dict.

        Verify that when _save_synthesizer_record is called after
        render_prompt with compression, the compression metrics
        are included in the record's custom dict.
        """
        from bmad_assist.benchmarking.schema import LLMEvaluationRecord
        from bmad_assist.core.loop.handlers.code_review_synthesis import (
            CodeReviewSynthesisHandler,
        )

        config_with_benchmarking = Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(provider="claude", model="opus-4"),
                multi=[],
            ),
            timeout=300,
            benchmarking=BenchmarkingConfig(enabled=True),
        )

        handler = CodeReviewSynthesisHandler(config_with_benchmarking, project_with_story)

        # Manually set compression metrics (as render_prompt would)
        handler._compression_metrics = {
            "compression_steps_applied": ["step0", "step1"],
            "original_token_estimate": 200_000,
            "compressed_token_estimate": 90_000,
            "extraction_llm_calls": 2,
            "extraction_duration_ms": 5500,
        }

        # Track the record passed to save_evaluation_record
        saved_record: LLMEvaluationRecord | None = None

        def capture_record(record: LLMEvaluationRecord, base_dir: Path) -> Path:
            nonlocal saved_record
            saved_record = record
            return base_dir / "test-record.yaml"

        compiled = self._mock_compiled_workflow()

        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
            patch("bmad_assist.core.debug_logger.save_prompt"),
            patch(
                "bmad_assist.benchmarking.storage.save_evaluation_record",
                side_effect=capture_record,
            ),
        ):
            mock_render.return_value = compiled.context
            mock_invoke.return_value = ProviderResult(
                stdout=_MOCK_SYNTHESIS_OUTPUT,
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="opus-4",
                command=("claude", "--print"),
            )

            result = handler.execute(compression_state)

            assert result.success

            # Verify compression metrics are in the saved record
            assert saved_record is not None
            assert saved_record.custom is not None
            assert saved_record.custom.get("compression_steps_applied") == ["step0", "step1"]
            assert saved_record.custom.get("original_token_estimate") == 200_000
            assert saved_record.custom.get("compressed_token_estimate") == 90_000
            assert saved_record.custom.get("extraction_llm_calls") == 2
            assert saved_record.custom.get("extraction_duration_ms") == 5500
            # Standard custom fields should also be present
            assert saved_record.custom.get("phase") == "code-review-synthesis"
            assert saved_record.custom.get("reviewer_count") == 2  # from cached_reviews fixture
