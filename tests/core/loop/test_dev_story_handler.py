"""Tests for DevStoryHandler.

Story 14.3: dev-story Loop Handler
Tests for DevStoryHandler - verifies BaseHandler integration works correctly.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.config import Config, MasterProviderConfig, ProviderConfig
from bmad_assist.core.state import Phase, State
from bmad_assist.providers.base import ProviderResult

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def dev_story_config(tmp_path: Path) -> Config:
    """Config with master provider for dev_story tests."""
    return Config(
        providers=ProviderConfig(
            master=MasterProviderConfig(provider="claude", model="opus-4"),
        ),
        timeout=300,
    )


@pytest.fixture
def project_with_story(tmp_path: Path) -> Path:
    """Create a project with a story file for dev_story testing."""
    from bmad_assist.core.paths import init_paths

    # Initialize paths singleton for this test
    paths = init_paths(tmp_path)
    paths.ensure_directories()

    # Create a story file in the new location
    story_file = paths.stories_dir / "14-3-dev-story-loop-handler.md"
    story_file.write_text("""# Story 14.3: dev-story Loop Handler

Status: ready-for-dev
Estimate: 3 SP

## Acceptance Criteria

### AC1: Test AC
**Given** a story exists
**Then** dev-story handler should work

## Tasks / Subtasks

- [ ] Task 1: Implement feature
""")

    # Create project_context.md (required by compiler)
    paths.project_knowledge.mkdir(parents=True, exist_ok=True)
    project_context = paths.project_knowledge / "project-context.md"
    project_context.write_text("# Project Context\n\nTest project.")

    return tmp_path


@pytest.fixture
def state_for_dev_story() -> State:
    """State with story position set for dev_story."""
    return State(
        current_epic=14,
        current_story="14.3",
        current_phase=Phase.DEV_STORY,
    )


# =============================================================================
# Test DevStoryHandler Basic Properties
# =============================================================================


class TestDevStoryHandlerBasics:
    """Test DevStoryHandler basic properties (AC: #1)."""

    def test_handler_exists(self) -> None:
        """Handler can be imported."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        assert DevStoryHandler is not None

    def test_phase_name(
        self,
        dev_story_config: Config,
        project_with_story: Path,
    ) -> None:
        """phase_name returns 'dev_story' (Subtask 2.2)."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(dev_story_config, project_with_story)
        assert handler.phase_name == "dev_story"

    def test_build_context(
        self,
        dev_story_config: Config,
        project_with_story: Path,
        state_for_dev_story: State,
    ) -> None:
        """build_context returns common context from _build_common_context() (Subtask 2.3)."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(dev_story_config, project_with_story)
        context = handler.build_context(state_for_dev_story)

        # Verify all common context variables
        assert context["epic_num"] == 14
        assert context["story_num"] == "3"
        assert context["story_id"] == "14.3"
        assert context["project_path"] == str(project_with_story)


# =============================================================================
# Test Inherited render_prompt() and Compiler Integration
# =============================================================================


class TestDevStoryCompilerIntegration:
    """Test inherited render_prompt() calls compiler for dev-story (AC: #2, #8)."""

    def test_render_prompt_uses_compiler(
        self,
        dev_story_config: Config,
        project_with_story: Path,
        state_for_dev_story: State,
    ) -> None:
        """Inherited render_prompt() calls compile_workflow for 'dev-story' (Subtask 2.4)."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(dev_story_config, project_with_story)

        # Mock compile_workflow - must patch at the import location in _try_compile_workflow
        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>test dev-story prompt</compiled>"
        mock_compiled.token_estimate = 5000

        with patch("bmad_assist.compiler.compile_workflow") as mock_compile:
            mock_compile.return_value = mock_compiled

            prompt = handler.render_prompt(state_for_dev_story)

            # Verify compiler was called with correct workflow name
            mock_compile.assert_called_once()
            call_args = mock_compile.call_args
            assert call_args[0][0] == "dev-story"  # workflow name converted from dev_story

            # Verify prompt contains compiled content
            assert "<compiled>" in prompt

    def test_render_prompt_injects_git_intelligence(
        self,
        dev_story_config: Config,
        project_with_story: Path,
        state_for_dev_story: State,
    ) -> None:
        """Inherited render_prompt() injects git intelligence if patch defines it (Subtask 2.9)."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(dev_story_config, project_with_story)

        # Mock compile_workflow and _inject_git_intelligence
        mock_compiled = MagicMock()
        mock_compiled.context = "<workflow-context>original</workflow-context>"
        mock_compiled.token_estimate = 5000

        # Long return value for git intelligence injection
        git_injected_prompt = (
            "<workflow-context>\n"
            "<git-intelligence>test git</git-intelligence>\n"
            "original</workflow-context>"
        )

        with (
            patch("bmad_assist.compiler.compile_workflow") as mock_compile,
            patch.object(
                handler, "_inject_git_intelligence", return_value=git_injected_prompt
            ) as mock_inject,
        ):
            mock_compile.return_value = mock_compiled

            prompt = handler.render_prompt(state_for_dev_story)

            # Verify git intelligence was injected
            mock_inject.assert_called_once()
            assert "git-intelligence" in prompt


# =============================================================================
# Test Debug Links Mode
# =============================================================================


class TestDevStoryDebugLinksMode:
    """Test BMAD_DEBUG_LINKS=1 enables links-only mode (AC: #2, Subtask 2.8)."""

    def test_debug_links_mode(
        self,
        dev_story_config: Config,
        project_with_story: Path,
        state_for_dev_story: State,
    ) -> None:
        """BMAD_DEBUG_LINKS=1 passes links_only=True to compiler (Subtask 2.8)."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(dev_story_config, project_with_story)

        # Mock compile_workflow to capture context
        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>links only</compiled>"
        mock_compiled.token_estimate = 100

        with (
            patch.dict("os.environ", {"BMAD_DEBUG_LINKS": "1"}),
            patch("bmad_assist.compiler.compile_workflow") as mock_compile,
        ):
            mock_compile.return_value = mock_compiled

            handler.render_prompt(state_for_dev_story)

            # Verify links_only was passed
            call_args = mock_compile.call_args
            context = call_args[0][1]  # Second positional arg is context
            assert context.links_only is True


# =============================================================================
# Test Inherited execute() Success/Failure
# =============================================================================


class TestDevStoryExecute:
    """Test inherited execute() returns PhaseResult (AC: #4, #7)."""

    def test_execute_returns_success(
        self,
        dev_story_config: Config,
        project_with_story: Path,
        state_for_dev_story: State,
    ) -> None:
        """execute() returns PhaseResult.ok on success (Subtask 2.5)."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(dev_story_config, project_with_story)

        with (
            patch.object(handler, "render_prompt", return_value="<compiled>test</compiled>"),
            patch.object(
                handler,
                "invoke_provider",
                return_value=ProviderResult(
                    stdout="Story implemented successfully",
                    stderr="",
                    exit_code=0,
                    duration_ms=60000,
                    model="opus-4",
                    command=("claude", "--print"),
                ),
            ),
        ):
            result = handler.execute(state_for_dev_story)

            assert result.success
            assert "response" in result.outputs
            assert "Story implemented" in result.outputs["response"]
            assert result.outputs["model"] == "opus-4"
            assert result.outputs["duration_ms"] == 60000

    def test_execute_returns_failure_on_nonzero_exit(
        self,
        dev_story_config: Config,
        project_with_story: Path,
        state_for_dev_story: State,
    ) -> None:
        """execute() returns PhaseResult.fail on non-zero exit code (Subtask 2.6)."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(dev_story_config, project_with_story)

        with (
            patch.object(handler, "render_prompt", return_value="<compiled>test</compiled>"),
            patch.object(
                handler,
                "invoke_provider",
                return_value=ProviderResult(
                    stdout="",
                    stderr="Provider error: timeout",
                    exit_code=1,
                    duration_ms=30000,
                    model="opus-4",
                    command=("claude", "--print"),
                ),
            ),
        ):
            result = handler.execute(state_for_dev_story)

            assert not result.success
            assert result.error is not None
            assert "timeout" in result.error.lower() or "exit" in result.error.lower()

    def test_execute_handles_config_error(
        self,
        dev_story_config: Config,
        project_with_story: Path,
        state_for_dev_story: State,
    ) -> None:
        """execute() returns PhaseResult.fail on ConfigError (AC: #7)."""
        from bmad_assist.core.exceptions import ConfigError
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(dev_story_config, project_with_story)

        with patch.object(handler, "render_prompt", side_effect=ConfigError("Missing config")):
            result = handler.execute(state_for_dev_story)

            assert not result.success
            assert result.error is not None
            assert "Missing config" in result.error

    def test_execute_handles_general_exception(
        self,
        dev_story_config: Config,
        project_with_story: Path,
        state_for_dev_story: State,
    ) -> None:
        """execute() returns PhaseResult.fail on general Exception (AC: #7)."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(dev_story_config, project_with_story)

        with patch.object(handler, "render_prompt", side_effect=RuntimeError("Unexpected error")):
            result = handler.execute(state_for_dev_story)

            assert not result.success
            assert result.error is not None
            assert "Handler error" in result.error


# =============================================================================
# Test No Additional Overrides Needed
# =============================================================================


class TestDevStoryHandlerNoOverrides:
    """Verify DevStoryHandler has no additional overrides (AC: #1)."""

    def test_no_execute_override(self) -> None:
        """DevStoryHandler does not override execute()."""
        from bmad_assist.core.loop.handlers.base import BaseHandler
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        # Check that execute is inherited, not overridden
        assert DevStoryHandler.execute is BaseHandler.execute

    def test_no_render_prompt_override(self) -> None:
        """DevStoryHandler does not override render_prompt()."""
        from bmad_assist.core.loop.handlers.base import BaseHandler
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        # Check that render_prompt is inherited, not overridden
        assert DevStoryHandler.render_prompt is BaseHandler.render_prompt

    def test_only_required_abstract_methods_implemented(self) -> None:
        """DevStoryHandler only implements required abstract methods plus timing."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        # Get methods defined in DevStoryHandler (not inherited)
        defined_methods = [
            name
            for name, value in DevStoryHandler.__dict__.items()
            if callable(value) or isinstance(value, property)
        ]

        # Should have phase_name, build_context, and optional timing properties
        expected = {"phase_name", "build_context", "track_timing", "timing_workflow_id"}
        actual = {name for name in defined_methods if not name.startswith("_")}

        assert actual == expected, f"Extra methods: {actual - expected}"


# =============================================================================
# Test Timing Tracking Integration
# =============================================================================


class TestDevStoryTimingTracking:
    """Test timing tracking for dev-story workflow."""

    @pytest.fixture
    def config_with_benchmarking_enabled(self, tmp_path: Path) -> Config:
        """Config with benchmarking enabled."""
        from bmad_assist.core.config import BenchmarkingConfig

        return Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(provider="claude", model="opus-4"),
            ),
            timeout=300,
            benchmarking=BenchmarkingConfig(enabled=True),
        )

    @pytest.fixture
    def config_with_benchmarking_disabled(self, tmp_path: Path) -> Config:
        """Config with benchmarking disabled."""
        from bmad_assist.core.config import BenchmarkingConfig

        return Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(provider="claude", model="opus-4"),
            ),
            timeout=300,
            benchmarking=BenchmarkingConfig(enabled=False),
        )

    def test_track_timing_enabled(self) -> None:
        """DevStoryHandler has track_timing = True."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        config = Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(provider="claude", model="opus"),
            ),
        )
        handler = DevStoryHandler(config, Path("/tmp"))
        assert handler.track_timing is True

    def test_timing_workflow_id(self) -> None:
        """DevStoryHandler has timing_workflow_id = 'dev-story'."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        config = Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(provider="claude", model="opus"),
            ),
        )
        handler = DevStoryHandler(config, Path("/tmp"))
        assert handler.timing_workflow_id == "dev-story"

    def test_execute_saves_timing_when_enabled(
        self,
        config_with_benchmarking_enabled: Config,
        project_with_story: Path,
        state_for_dev_story: State,
    ) -> None:
        """execute() saves timing record when benchmarking enabled."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(config_with_benchmarking_enabled, project_with_story)

        with (
            patch.object(handler, "render_prompt", return_value="<compiled>test</compiled>"),
            patch.object(
                handler,
                "invoke_provider",
                return_value=ProviderResult(
                    stdout="Story completed",
                    stderr="",
                    exit_code=0,
                    duration_ms=5000,
                    model="opus",
                    command=("claude",),
                ),
            ),
            patch("bmad_assist.benchmarking.master_tracking.save_master_timing") as mock_save,
        ):
            result = handler.execute(state_for_dev_story)

            assert result.success
            mock_save.assert_called_once()
            call_kwargs = mock_save.call_args[1]
            assert call_kwargs["workflow_id"] == "dev-story"
            assert call_kwargs["epic_num"] == state_for_dev_story.current_epic
            assert call_kwargs["output"] == "Story completed"

    def test_execute_skips_timing_when_disabled(
        self,
        config_with_benchmarking_disabled: Config,
        project_with_story: Path,
        state_for_dev_story: State,
    ) -> None:
        """execute() skips timing when benchmarking disabled."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(config_with_benchmarking_disabled, project_with_story)

        with (
            patch.object(handler, "render_prompt", return_value="<compiled>test</compiled>"),
            patch.object(
                handler,
                "invoke_provider",
                return_value=ProviderResult(
                    stdout="Story completed",
                    stderr="",
                    exit_code=0,
                    duration_ms=5000,
                    model="opus",
                    command=("claude",),
                ),
            ),
            patch("bmad_assist.benchmarking.master_tracking.save_master_timing") as mock_save,
        ):
            result = handler.execute(state_for_dev_story)

            assert result.success
            mock_save.assert_not_called()

    def test_execute_skips_timing_on_failure(
        self,
        config_with_benchmarking_enabled: Config,
        project_with_story: Path,
        state_for_dev_story: State,
    ) -> None:
        """execute() skips timing when phase fails."""
        from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler

        handler = DevStoryHandler(config_with_benchmarking_enabled, project_with_story)

        with (
            patch.object(handler, "render_prompt", return_value="<compiled>test</compiled>"),
            patch.object(
                handler,
                "invoke_provider",
                return_value=ProviderResult(
                    stdout="",
                    stderr="Error occurred",
                    exit_code=1,
                    duration_ms=1000,
                    model="opus",
                    command=("claude",),
                ),
            ),
            patch("bmad_assist.benchmarking.master_tracking.save_master_timing") as mock_save,
        ):
            result = handler.execute(state_for_dev_story)

            assert not result.success
            mock_save.assert_not_called()
