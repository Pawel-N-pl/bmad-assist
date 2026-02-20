"""Tests for ATDDHandler compiler integration.

Tests the integration between ATDDHandler and the ATDDCompiler,
verifying that _invoke_atdd_workflow correctly:
1. Creates CompilerContext with state variables
2. Calls compile_workflow to get the compiled prompt
3. Invokes master provider with the compiled prompt
4. Returns PhaseResult with workflow output
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import State
from bmad_assist.testarch.handlers.atdd import ATDDHandler


class FakeConfig:
    """Fake Config for testing."""

    def __init__(self) -> None:
        self.providers = MagicMock()
        self.providers.master = MagicMock()
        self.providers.master.provider = "claude-subprocess"
        self.providers.master.model = "opus"
        self.timeout = 120
        self.testarch = MagicMock()
        self.testarch.atdd_mode = "on"
        self.testarch.preflight = None
        self.testarch.eligibility = None


class TestATDDHandlerInvokeWorkflow:
    """Test _invoke_atdd_workflow uses compiler and provider."""

    @pytest.fixture
    def setup_atdd_workflow(self, tmp_path: Path) -> tuple[Path, State]:
        """Create testarch-atdd workflow structure and state."""
        # Create workflow directory
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/atdd"
        workflow_dir.mkdir(parents=True)

        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: testarch-atdd
description: \"Generate failing acceptance tests before implementation\"
instructions: \"{installed_path}/instructions.xml\"
template: \"{installed_path}/atdd-checklist-template.md\"
variables:
  test_dir: \"{project-root}/tests\"
default_output_file: \"{output_folder}/atdd-checklist-{story_id}.md\"
""")

        instructions = workflow_dir / "instructions.xml"
        instructions.write_text("""<workflow>
<step n=\"1\" goal=\"Analyze story acceptance criteria\">
<action>Read story file and extract acceptance criteria</action>
</step>
</workflow>""")

        template = workflow_dir / "atdd-checklist-template.md"
        template.write_text("# ATDD Checklist for {{story_id}}")

        # Create story file
        stories_dir = tmp_path / "_bmad-output/sprint-artifacts"
        stories_dir.mkdir(parents=True)
        story_file = stories_dir / "testarch-1-test-story.md"
        story_file.write_text("""
# Story testarch.1: Test Story

## Acceptance Criteria
1. AC1: First criterion
""")

        # Create project context
        output_dir = tmp_path / "_bmad-output"
        project_context = output_dir / "project-context.md"
        project_context.write_text("# Project Context\nRules here...")

        # Create state
        state = State()
        state.current_epic = "testarch"
        state.current_story = "testarch.1"

        return tmp_path, state

    def test_invoke_atdd_workflow_calls_compiler(
        self,
        setup_atdd_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_atdd_workflow calls compile_workflow."""
        project_path, state = setup_atdd_workflow
        config = FakeConfig()
        handler = ATDDHandler(config, project_path)  # type: ignore

        # Mock compile_workflow
        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-prompt>test</compiled-prompt>"
        mock_compiled.workflow_name = "testarch-atdd"

        # Mock provider
        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult
        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="ATDD tests generated successfully",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100
        )

        with (
            patch(
                "bmad_assist.compiler.compile_workflow", return_value=mock_compiled
            ) as mock_compile,
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.atdd.get_paths") as mock_atdd_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_atdd_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_atdd_workflow(state)

            # Verify compile_workflow was called
            mock_compile.assert_called_once()
            call_args = mock_compile.call_args
            assert call_args[0][0] == "testarch-atdd"

    def test_invoke_atdd_workflow_calls_provider(
        self,
        setup_atdd_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_atdd_workflow invokes master provider."""
        project_path, state = setup_atdd_workflow
        config = FakeConfig()
        handler = ATDDHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-prompt>test</compiled-prompt>"
        mock_compiled.workflow_name = "testarch-atdd"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult
        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="ATDD tests generated successfully",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100
        )

        with (
            patch(
                "bmad_assist.compiler.compile_workflow", return_value=mock_compiled
            ),
            patch(
                "bmad_assist.providers.get_provider", return_value=mock_provider
            ) as mock_get_provider,
            patch("bmad_assist.testarch.handlers.atdd.get_paths") as mock_atdd_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_atdd_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_atdd_workflow(state)

            # Verify get_provider was called with correct provider name
            mock_get_provider.assert_called_once_with("claude-subprocess")

            # Verify provider.invoke was called
            mock_provider.invoke.assert_called_once()
            call_kwargs = mock_provider.invoke.call_args[1]
            assert call_kwargs["model"] == "opus"

    def test_invoke_atdd_workflow_returns_phase_result(
        self,
        setup_atdd_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_atdd_workflow returns PhaseResult."""
        project_path, state = setup_atdd_workflow
        config = FakeConfig()
        handler = ATDDHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-prompt>test</compiled-prompt>"
        mock_compiled.workflow_name = "testarch-atdd"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult
        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="ATDD tests generated successfully",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100
        )

        with (
            patch(
                "bmad_assist.compiler.compile_workflow", return_value=mock_compiled
            ),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.atdd.get_paths") as mock_atdd_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_atdd_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_atdd_workflow(state)

            assert isinstance(result, PhaseResult)
            assert result.success is True
            assert "response" in result.outputs


class TestATDDHandlerInvokeWorkflowErrorHandling:
    """Test error handling in _invoke_atdd_workflow."""

    @pytest.fixture
    def setup_atdd_workflow(self, tmp_path: Path) -> tuple[Path, State]:
        """Create minimal setup for error handling tests."""
        stories_dir = tmp_path / "_bmad-output/sprint-artifacts"
        stories_dir.mkdir(parents=True)
        story_file = stories_dir / "testarch-1-test-story.md"
        story_file.write_text("# Story\n## Acceptance Criteria\n1. AC1")

        output_dir = tmp_path / "_bmad-output"
        project_context = output_dir / "project-context.md"
        project_context.write_text("# Project Context")

        state = State()
        state.current_epic = "testarch"
        state.current_story = "testarch.1"

        return tmp_path, state

    def test_invoke_atdd_workflow_handles_compiler_error(
        self,
        setup_atdd_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_atdd_workflow handles CompilerError gracefully."""
        from bmad_assist.core.exceptions import CompilerError

        project_path, state = setup_atdd_workflow
        config = FakeConfig()
        handler = ATDDHandler(config, project_path)  # type: ignore

        with (
            patch(
                "bmad_assist.compiler.compile_workflow",
                side_effect=CompilerError("Test compiler error"),
            ),
            patch("bmad_assist.testarch.handlers.atdd.get_paths") as mock_atdd_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_atdd_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_atdd_workflow(state)

            assert result.success is False
            assert result.error is not None
            assert "error" in result.error.lower()

    def test_invoke_atdd_workflow_handles_provider_error(
        self,
        setup_atdd_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_atdd_workflow handles provider error."""
        project_path, state = setup_atdd_workflow
        config = FakeConfig()
        handler = ATDDHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-prompt>test</compiled-prompt>"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult
        mock_provider.invoke.return_value = ProviderResult(
            exit_code=1,
            stdout="",
            stderr="Provider execution failed",
            model="opus",
            command=("claude",),
            duration_ms=100
        )

        with (
            patch(
                "bmad_assist.compiler.compile_workflow", return_value=mock_compiled
            ),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.atdd.get_paths") as mock_atdd_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_atdd_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_atdd_workflow(state)

            assert result.success is False
            assert result.error is not None
            assert "error" in result.error.lower()


class TestATDDHandlerChecklistExtraction:
    """Test _extract_checklist_path method."""

    def test_extract_checklist_path_finds_atdd_checklist(self, tmp_path: Path) -> None:
        """Test extraction of atdd-checklist path from output."""
        config = FakeConfig()
        handler = ATDDHandler(config, tmp_path)  # type: ignore

        output = "ATDD checklist saved to: /path/to/atdd-checklist-1.1.md"
        result = handler._extract_checklist_path(output)

        assert result == "/path/to/atdd-checklist-1.1.md"

    def test_extract_checklist_path_finds_bare_path(self, tmp_path: Path) -> None:
        """Test extraction when path appears without context."""
        config = FakeConfig()
        handler = ATDDHandler(config, tmp_path)  # type: ignore

        output = "Generated tests. File: /output/atdd-checklist-testarch.1.md"
        result = handler._extract_checklist_path(output)

        assert result is not None
        assert "atdd-checklist" in result

    def test_extract_checklist_path_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """Test returns None when no checklist path in output."""
        config = FakeConfig()
        handler = ATDDHandler(config, tmp_path)  # type: ignore

        output = "ATDD tests generated successfully. No files written."
        result = handler._extract_checklist_path(output)

        assert result is None
