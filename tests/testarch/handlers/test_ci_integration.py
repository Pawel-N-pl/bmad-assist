"""Tests for CIHandler compiler integration.

Story 25.14: Integration Testing.
Tests the integration between CIHandler and the workflow compiler,
verifying that _invoke_ci_workflow correctly:
1. Creates CompilerContext with state variables
2. Calls compile_workflow to get the compiled prompt
3. Invokes master provider with the compiled prompt
4. Returns PhaseResult with workflow output
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import State
from bmad_assist.testarch.handlers.ci import CIHandler


class FakeConfig:
    """Fake Config for integration testing."""

    def __init__(self, **kwargs: Any) -> None:
        self.providers = MagicMock()
        self.providers.master = MagicMock()
        self.providers.master.provider = kwargs.get("provider", "claude-subprocess")
        self.providers.master.model = kwargs.get("model", "opus")
        self.timeout = kwargs.get("timeout", 120)

        # Testarch config with all mode fields
        self.testarch = MagicMock()
        self.testarch.engagement_model = kwargs.get("engagement_model", "integrated")
        self.testarch.atdd_mode = kwargs.get("atdd_mode", "auto")
        self.testarch.framework_mode = kwargs.get("framework_mode", "auto")
        self.testarch.ci_mode = kwargs.get("ci_mode", "auto")
        self.testarch.test_design_mode = kwargs.get("test_design_mode", "auto")
        self.testarch.automate_mode = kwargs.get("automate_mode", "auto")
        self.testarch.nfr_assess_mode = kwargs.get("nfr_assess_mode", "auto")
        self.testarch.test_review_on_code_complete = kwargs.get("test_review_mode", "auto")
        self.testarch.trace_on_epic_complete = kwargs.get("trace_mode", "auto")
        self.testarch.evidence = MagicMock()
        self.testarch.evidence.enabled = kwargs.get("evidence_enabled", False)
        self.testarch.preflight = None
        self.testarch.eligibility = None

        # Benchmarking config
        self.benchmarking = MagicMock()
        self.benchmarking.enabled = False


class TestCIHandlerInvokeWorkflow:
    """Test _invoke_ci_workflow uses compiler and provider."""

    @pytest.fixture
    def setup_ci_workflow(self, tmp_path: Path) -> tuple[Path, State]:
        """Create testarch-ci workflow structure and state."""
        # Create workflow directory
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/ci"
        workflow_dir.mkdir(parents=True)

        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: testarch-ci
description: "Initialize CI pipeline"
instructions: "{installed_path}/instructions.xml"
""")

        instructions = workflow_dir / "instructions.xml"
        instructions.write_text("""<workflow>
<step n="1" goal="Detect and configure CI platform">
<action>Analyze project structure for existing CI configuration</action>
</step>
</workflow>""")

        # Create output directory
        (tmp_path / "_bmad-output/ci-setup").mkdir(parents=True)

        # Create docs directory
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Project Context\nRules here.")

        state = State()
        state.current_epic = 1
        state.current_story = "1.1"

        return tmp_path, state

    def test_invoke_ci_workflow_calls_compiler(
        self,
        setup_ci_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_ci_workflow calls compile_workflow."""
        project_path, state = setup_ci_workflow
        config = FakeConfig()
        handler = CIHandler(config, project_path)  # type: ignore

        # Mock compile_workflow
        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>ci</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-ci"

        # Mock provider
        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# CI Setup\n\nGitHub Actions configured.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch(
                "bmad_assist.compiler.compile_workflow", return_value=mock_compiled
            ) as mock_compile,
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.ci.get_paths") as mock_ci_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_ci_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_ci_workflow(state)

            mock_compile.assert_called_once()
            call_args = mock_compile.call_args
            assert call_args[0][0] == "testarch-ci"

    def test_invoke_ci_workflow_calls_provider(
        self,
        setup_ci_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_ci_workflow invokes master provider."""
        project_path, state = setup_ci_workflow
        config = FakeConfig()
        handler = CIHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>ci</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-ci"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# CI Setup\n\nGitHub Actions configured.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch(
                "bmad_assist.compiler.compile_workflow", return_value=mock_compiled
            ),
            patch(
                "bmad_assist.providers.get_provider", return_value=mock_provider
            ) as mock_get_provider,
            patch("bmad_assist.testarch.handlers.ci.get_paths") as mock_ci_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_ci_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_ci_workflow(state)

            mock_get_provider.assert_called_once_with("claude-subprocess")
            mock_provider.invoke.assert_called_once()
            call_kwargs = mock_provider.invoke.call_args[1]
            assert call_kwargs["model"] == "opus"

    def test_invoke_ci_workflow_returns_phase_result(
        self,
        setup_ci_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_ci_workflow returns PhaseResult."""
        project_path, state = setup_ci_workflow
        config = FakeConfig()
        handler = CIHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>ci</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-ci"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# CI Setup\n\nGitHub Actions configured.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch(
                "bmad_assist.compiler.compile_workflow", return_value=mock_compiled
            ),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.ci.get_paths") as mock_ci_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_ci_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_ci_workflow(state)

            assert isinstance(result, PhaseResult)
            assert result.success is True
            assert "response" in result.outputs

    def test_invoke_ci_workflow_updates_state_flag(
        self,
        setup_ci_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_ci_workflow updates ci_ran_in_epic state flag."""
        project_path, state = setup_ci_workflow
        config = FakeConfig()
        handler = CIHandler(config, project_path)  # type: ignore

        # Verify initial state
        assert state.ci_ran_in_epic is False

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>ci</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-ci"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# CI Setup\n\nGitHub Actions configured.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch(
                "bmad_assist.compiler.compile_workflow", return_value=mock_compiled
            ),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.ci.get_paths") as mock_ci_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_ci_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_ci_workflow(state)

            assert result.success is True
            assert state.ci_ran_in_epic is True

    def test_invoke_ci_workflow_creates_report_directory(
        self,
        setup_ci_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_ci_workflow creates report directory."""
        project_path, state = setup_ci_workflow
        config = FakeConfig()
        handler = CIHandler(config, project_path)  # type: ignore

        # Remove report dir to verify creation
        report_dir = project_path / "_bmad-output/ci-setup"
        if report_dir.exists():
            import shutil

            shutil.rmtree(report_dir)

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>ci</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-ci"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# CI Setup\n\nGitHub Actions configured.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch(
                "bmad_assist.compiler.compile_workflow", return_value=mock_compiled
            ),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.ci.get_paths") as mock_ci_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_ci_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_ci_workflow(state)

            # Report directory should be created
            assert report_dir.exists()


class TestCIHandlerInvokeWorkflowErrorHandling:
    """Test error handling in _invoke_ci_workflow."""

    @pytest.fixture
    def setup_ci_workflow(self, tmp_path: Path) -> tuple[Path, State]:
        """Create minimal setup for error handling tests."""
        (tmp_path / "_bmad-output").mkdir(parents=True)
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Project Context")

        state = State()
        state.current_epic = 1
        state.current_story = "1.1"

        return tmp_path, state

    def test_invoke_ci_workflow_handles_compiler_error(
        self,
        setup_ci_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_ci_workflow handles CompilerError gracefully."""
        from bmad_assist.core.exceptions import CompilerError

        project_path, state = setup_ci_workflow
        config = FakeConfig()
        handler = CIHandler(config, project_path)  # type: ignore

        with (
            patch(
                "bmad_assist.compiler.compile_workflow",
                side_effect=CompilerError("Test compiler error"),
            ),
            patch("bmad_assist.testarch.handlers.ci.get_paths") as mock_ci_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_ci_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_ci_workflow(state)

            assert result.success is False
            assert result.error is not None
            assert "error" in result.error.lower()


class TestCIHandlerExecuteMethod:
    """Test the execute() method of CIHandler."""

    @pytest.fixture
    def setup_project(self, tmp_path: Path) -> Path:
        """Create minimal project structure."""
        (tmp_path / "_bmad-output").mkdir(parents=True)
        (tmp_path / "docs").mkdir(parents=True)
        return tmp_path

    def test_execute_skips_when_engagement_off(
        self, setup_project: Path
    ) -> None:
        """Test execute skips when engagement_model='off'."""
        config = FakeConfig(engagement_model="off")
        handler = CIHandler(config, setup_project)  # type: ignore

        state = State()
        state.current_epic = 1

        result = handler.execute(state)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "engagement" in result.outputs.get("reason", "").lower()

    def test_execute_skips_when_ci_exists(
        self, setup_project: Path
    ) -> None:
        """Test execute skips when CI already detected."""
        # Create a GitHub Actions workflow
        workflows_dir = setup_project / ".github/workflows"
        workflows_dir.mkdir(parents=True)
        (workflows_dir / "test.yml").write_text("name: test")

        config = FakeConfig()
        handler = CIHandler(config, setup_project)  # type: ignore

        state = State()
        state.current_epic = 1

        result = handler.execute(state)

        assert result.success is True
        assert result.outputs.get("skipped") is True

    def test_handler_workflow_id_property(self, setup_project: Path) -> None:
        """Test handler has correct workflow_id property."""
        config = FakeConfig()
        handler = CIHandler(config, setup_project)  # type: ignore

        assert handler.workflow_id == "ci"

    def test_handler_phase_name_property(self, setup_project: Path) -> None:
        """Test handler has correct phase_name property."""
        config = FakeConfig()
        handler = CIHandler(config, setup_project)  # type: ignore

        assert handler.phase_name == "tea_ci"
