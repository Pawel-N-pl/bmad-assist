"""Tests for validation phase handlers.

Story 11.7: Validation Phase Loop Integration
Tests for ValidateStoryHandler and ValidateStorySynthesisHandler.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.config import (
    BenchmarkingConfig,
    Config,
    MasterProviderConfig,
    MultiProviderConfig,
    ProviderConfig,
)
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import Phase, State
from bmad_assist.providers.base import BaseProvider, ProviderResult


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def validation_config(tmp_path: Path) -> Config:
    """Config with multi providers for validation tests."""
    return Config(
        providers=ProviderConfig(
            master=MasterProviderConfig(provider="claude", model="opus-4"),
            multi=[
                MultiProviderConfig(provider="claude", model="sonnet-4"),
                MultiProviderConfig(provider="gemini", model="gemini-2.5-pro"),
            ],
        ),
        timeout=300,
        benchmarking=BenchmarkingConfig(enabled=False),
    )


@pytest.fixture
def project_with_story(tmp_path: Path) -> Path:
    """Create a project with a story file."""
    from bmad_assist.core.paths import init_paths

    # Initialize paths singleton for this test
    paths = init_paths(tmp_path)
    paths.ensure_directories()

    # Create a story file in the new location
    story_file = paths.stories_dir / "11-7-validation-phase-loop-integration.md"
    story_file.write_text("""# Story 11.7: Validation Phase Loop Integration

Status: in-progress
Estimate: 3 SP

## Acceptance Criteria

### AC1: Test AC
**Given** a story exists
**Then** validation should work

## Tasks / Subtasks

- [ ] Task 1: Implement feature
""")

    # Create project_context.md in project knowledge directory
    paths.project_knowledge.mkdir(parents=True, exist_ok=True)
    project_context = paths.project_knowledge / "project-context.md"
    project_context.write_text("# Project Context\n\nTest project.")

    # Create handlers config directory
    handlers_dir = Path.home() / ".bmad-assist" / "handlers"
    handlers_dir.mkdir(parents=True, exist_ok=True)

    # Create minimal handler configs for validation phases
    for phase_name in ["validate_story", "validate_story_synthesis"]:
        config_file = handlers_dir / f"{phase_name}.yaml"
        if not config_file.exists():
            config_file.write_text(f"""prompt_template: "Test prompt for {phase_name}"
provider_type: master
description: "Test handler for {phase_name}"
""")

    return tmp_path


@pytest.fixture
def state_for_validation() -> State:
    """State with story position set for validation."""
    return State(
        current_epic=11,
        current_story="11.7",
        current_phase=Phase.VALIDATE_STORY,
    )


# =============================================================================
# Test ValidateStoryHandler
# =============================================================================


class TestValidateStoryHandler:
    """Tests for ValidateStoryHandler class."""

    def test_handler_exists(self) -> None:
        """Handler can be imported."""
        from bmad_assist.core.loop.handlers.validate_story import (
            ValidateStoryHandler,
        )

        assert ValidateStoryHandler is not None

    def test_phase_name(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """phase_name returns correct value."""
        from bmad_assist.core.loop.handlers.validate_story import (
            ValidateStoryHandler,
        )

        handler = ValidateStoryHandler(validation_config, project_with_story)
        assert handler.phase_name == "validate_story"

    def test_build_context(
        self,
        validation_config: Config,
        project_with_story: Path,
        state_for_validation: State,
    ) -> None:
        """build_context returns story info."""
        from bmad_assist.core.loop.handlers.validate_story import (
            ValidateStoryHandler,
        )

        handler = ValidateStoryHandler(validation_config, project_with_story)
        context = handler.build_context(state_for_validation)

        assert context["epic_num"] == 11
        assert context["story_num"] == "7"
        assert context["story_id"] == "11.7"

    def test_execute_success(
        self,
        validation_config: Config,
        project_with_story: Path,
        state_for_validation: State,
    ) -> None:
        """execute() returns success with session_id on success."""
        from bmad_assist.core.loop.handlers.validate_story import (
            ValidateStoryHandler,
        )

        handler = ValidateStoryHandler(validation_config, project_with_story)

        # Setup mock result
        from bmad_assist.validation import AnonymizedValidation
        from bmad_assist.validation.orchestrator import ValidationPhaseResult

        mock_result = ValidationPhaseResult(
            anonymized_validations=[
                AnonymizedValidation(
                    validator_id="Validator A",
                    content="Test validation",
                    original_ref="ref-1",
                ),
                AnonymizedValidation(
                    validator_id="Validator B",
                    content="Test validation 2",
                    original_ref="ref-2",
                ),
            ],
            session_id="test-session-123",
            validation_count=2,
            validators=["claude-sonnet-4", "gemini-2.5-pro"],
            failed_validators=[],
        )

        async def mock_run_phase(*args: Any, **kwargs: Any) -> ValidationPhaseResult:
            return mock_result

        # Mock the orchestrator - patch run_async_with_timeout to bypass async
        with (
            patch(
                "bmad_assist.core.async_utils.run_async_with_timeout"
            ) as mock_run_async,
            patch(
                "bmad_assist.core.loop.handlers.validate_story.save_validations_for_synthesis"
            ) as mock_save,
        ):
            mock_run_async.return_value = mock_result
            # save_validations_for_synthesis now receives session_id from result
            mock_save.return_value = None  # Return value not used anymore

            result = handler.execute(state_for_validation)

            assert result.success
            assert "session_id" in result.outputs
            # session_id now comes from ValidationPhaseResult, not save_validations_for_synthesis
            assert result.outputs["session_id"] == "test-session-123"
            assert result.outputs["validation_count"] == 2
            # Verify save was called with the session_id from result
            mock_save.assert_called_once()
            call_kwargs = mock_save.call_args
            assert call_kwargs[1]["session_id"] == "test-session-123"

    def test_execute_missing_story_info(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """execute() returns failure when story info missing."""
        from bmad_assist.core.loop.handlers.validate_story import (
            ValidateStoryHandler,
        )

        handler = ValidateStoryHandler(validation_config, project_with_story)

        # State without story info
        empty_state = State(current_phase=Phase.VALIDATE_STORY)

        result = handler.execute(empty_state)

        assert not result.success
        assert "missing" in result.error.lower()

    def test_execute_insufficient_validations(
        self,
        validation_config: Config,
        project_with_story: Path,
        state_for_validation: State,
    ) -> None:
        """execute() returns failure when not enough validations."""
        from bmad_assist.core.loop.handlers.validate_story import (
            ValidateStoryHandler,
        )
        from bmad_assist.validation.orchestrator import InsufficientValidationsError

        handler = ValidateStoryHandler(validation_config, project_with_story)

        with patch(
            "bmad_assist.core.loop.handlers.validate_story.run_validation_phase"
        ) as mock_run:
            mock_run.side_effect = InsufficientValidationsError(count=1, minimum=2)

            result = handler.execute(state_for_validation)

            assert not result.success
            assert "Insufficient" in result.error


# =============================================================================
# Test ValidateStorySynthesisHandler
# =============================================================================


class TestValidateStorySynthesisHandler:
    """Tests for ValidateStorySynthesisHandler class."""

    def test_handler_exists(self) -> None:
        """Handler can be imported."""
        from bmad_assist.core.loop.handlers.validate_story_synthesis import (
            ValidateStorySynthesisHandler,
        )

        assert ValidateStorySynthesisHandler is not None

    def test_phase_name(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """phase_name returns correct value."""
        from bmad_assist.core.loop.handlers.validate_story_synthesis import (
            ValidateStorySynthesisHandler,
        )

        handler = ValidateStorySynthesisHandler(validation_config, project_with_story)
        assert handler.phase_name == "validate_story_synthesis"

    def test_get_session_id_no_cache_dir(
        self,
        validation_config: Config,
        tmp_path: Path,
    ) -> None:
        """_get_session_id_from_state returns None when no cache dir."""
        from bmad_assist.core.loop.handlers.validate_story_synthesis import (
            ValidateStorySynthesisHandler,
        )

        handler = ValidateStorySynthesisHandler(validation_config, tmp_path)
        state = State()

        session_id = handler._get_session_id_from_state(state)
        assert session_id is None

    def test_get_session_id_from_cache_file(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """_get_session_id_from_state finds cached validation file."""
        from bmad_assist.core.loop.handlers.validate_story_synthesis import (
            ValidateStorySynthesisHandler,
        )

        # Create cache file (directory may already exist from paths.ensure_directories())
        cache_dir = project_with_story / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_file = cache_dir / "validations-test-session-abc123.json"
        cache_file.write_text(
            json.dumps(
                {
                    "cache_version": 2,  # TIER 2: Required for v2 format
                    "session_id": "test-session-abc123",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "validations": [],
                    "failed_validators": [],
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

        handler = ValidateStorySynthesisHandler(validation_config, project_with_story)
        state = State()

        session_id = handler._get_session_id_from_state(state)
        assert session_id == "test-session-abc123"

    def test_execute_no_session(
        self,
        validation_config: Config,
        tmp_path: Path,
    ) -> None:
        """execute() fails when no validation session found."""
        from bmad_assist.core.loop.handlers.validate_story_synthesis import (
            ValidateStorySynthesisHandler,
        )

        handler = ValidateStorySynthesisHandler(validation_config, tmp_path)
        state = State(
            current_epic=11,
            current_story="11.7",
            current_phase=Phase.VALIDATE_STORY_SYNTHESIS,
        )

        result = handler.execute(state)

        assert not result.success
        assert "no validation session" in result.error.lower() or "cannot" in result.error.lower()

    def test_execute_success(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """execute() returns success when synthesis completes."""
        from bmad_assist.core.loop.handlers.validate_story_synthesis import (
            ValidateStorySynthesisHandler,
        )

        handler = ValidateStorySynthesisHandler(validation_config, project_with_story)

        # Create cache file with validations (directory may already exist)
        cache_dir = project_with_story / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_file = cache_dir / "validations-test-session-xyz.json"
        cache_file.write_text(
            json.dumps(
                {
                    "cache_version": 2,  # TIER 2: Required for v2 format
                    "session_id": "test-session-xyz",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "validations": [
                        {
                            "validator_id": "Validator A",
                            "content": "Test 1",
                            "original_ref": "ref-1",
                        },
                        {
                            "validator_id": "Validator B",
                            "content": "Test 2",
                            "original_ref": "ref-2",
                        },
                    ],
                    "failed_validators": [],
                    "evidence_score": {
                        "total_score": 1.5,
                        "verdict": "PASS",
                        "per_validator": {
                            "Validator A": {"score": 2.0, "verdict": "PASS"},
                            "Validator B": {"score": 1.0, "verdict": "PASS"},
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

        state = State(
            current_epic=11,
            current_story="11.7",
            current_phase=Phase.VALIDATE_STORY_SYNTHESIS,
        )

        # Mock compiler and provider
        with (
            patch.object(handler, "render_prompt") as mock_render,
            patch.object(handler, "invoke_provider") as mock_invoke,
        ):
            mock_render.return_value = "<compiled>test synthesis prompt</compiled>"
            mock_invoke.return_value = ProviderResult(
                stdout=(
                    "## Synthesis Summary\n\n"
                    "6 validators analyzed the story. After cross-referencing with "
                    "project context and acceptance criteria:\n\n"
                    "## Issues Verified\n\n"
                    "### Critical\n"
                    "- Missing input validation on booking endpoint\n\n"
                    "## Issues Dismissed\n\n"
                    "- False positive: naming convention from Validator B\n\n"
                    "## Changes Applied\n\n"
                    "Applied fix for critical input validation issue.\n"
                ),
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="opus-4",
                command=("claude", "--print"),
            )

            result = handler.execute(state)

            assert result.success
            assert "response" in result.outputs
            assert "Synthesis Summary" in result.outputs["response"]


# =============================================================================
# Test integration between handlers
# =============================================================================


class TestValidationHandlerIntegration:
    """Tests for data passing between validation handlers."""

    def test_session_id_passed_between_handlers(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """Session ID from validate handler is found by synthesis handler."""
        from bmad_assist.core.loop.handlers.validate_story import (
            ValidateStoryHandler,
        )
        from bmad_assist.core.loop.handlers.validate_story_synthesis import (
            ValidateStorySynthesisHandler,
        )
        from bmad_assist.validation.orchestrator import (
            save_validations_for_synthesis,
        )
        from bmad_assist.validation import AnonymizedValidation

        # Simulate what validate handler does - save validations
        validations = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Test content",
                original_ref="ref-1",
            ),
            AnonymizedValidation(
                validator_id="Validator B",
                content="Test content 2",
                original_ref="ref-2",
            ),
        ]

        saved_session = save_validations_for_synthesis(
            validations,
            project_with_story,
        )

        # Now synthesis handler should find it
        synthesis_handler = ValidateStorySynthesisHandler(
            validation_config,
            project_with_story,
        )

        state = State(
            current_epic=11,
            current_story="11.7",
            current_phase=Phase.VALIDATE_STORY_SYNTHESIS,
        )

        found_session = synthesis_handler._get_session_id_from_state(state)

        assert found_session == saved_session
