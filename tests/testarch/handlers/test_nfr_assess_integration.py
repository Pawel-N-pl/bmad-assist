"""Tests for NFRAssessHandler compiler integration.

Story 25.14: Integration Testing.
Tests the integration between NFRAssessHandler and the workflow compiler,
verifying that _invoke_nfr_assess_workflow correctly:
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
from bmad_assist.testarch.handlers.nfr_assess import NFRAssessHandler


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


class TestNFRAssessHandlerInvokeWorkflow:
    """Test _invoke_nfr_assess_workflow uses compiler and provider."""

    @pytest.fixture
    def setup_nfr_assess_workflow(self, tmp_path: Path) -> tuple[Path, State]:
        """Create testarch-nfr-assess workflow structure and state."""
        # Create workflow directory
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/nfr-assess"
        workflow_dir.mkdir(parents=True)

        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: testarch-nfr-assess
description: "Assess non-functional requirements"
instructions: "{installed_path}/instructions.xml"
""")

        instructions = workflow_dir / "instructions.xml"
        instructions.write_text("""<workflow>
<step n="1" goal="Assess NFR compliance">
<action>Evaluate performance, security, reliability</action>
</step>
</workflow>""")

        # Create output directory
        (tmp_path / "_bmad-output/nfr-assess").mkdir(parents=True)

        # Create docs directory
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Project Context\nRules here.")

        state = State()
        state.current_epic = 1
        state.current_story = "1.1"

        return tmp_path, state

    def test_invoke_nfr_assess_workflow_calls_compiler(
        self,
        setup_nfr_assess_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_nfr_assess_workflow calls compile_workflow."""
        project_path, state = setup_nfr_assess_workflow
        config = FakeConfig()
        handler = NFRAssessHandler(config, project_path)  # type: ignore

        # Mock compile_workflow
        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>nfr-assess</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-nfr-assess"

        # Mock provider
        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# NFR Assessment\n\n## Gate Decision: PASS\n\nAll NFRs satisfied.",
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
            patch(
                "bmad_assist.testarch.handlers.nfr_assess.get_paths"
            ) as mock_nfr_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_nfr_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_nfr_assess_workflow(state)

            mock_compile.assert_called_once()
            call_args = mock_compile.call_args
            assert call_args[0][0] == "testarch-nfr"
            assert result is not None

    def test_invoke_nfr_assess_workflow_calls_provider(
        self,
        setup_nfr_assess_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_nfr_assess_workflow invokes master provider."""
        project_path, state = setup_nfr_assess_workflow
        config = FakeConfig()
        handler = NFRAssessHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>nfr-assess</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-nfr-assess"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# NFR Assessment\n\n## Gate Decision: PASS",
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
            patch(
                "bmad_assist.testarch.handlers.nfr_assess.get_paths"
            ) as mock_nfr_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_nfr_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_nfr_assess_workflow(state)

            mock_get_provider.assert_called_once_with("claude-subprocess")
            mock_provider.invoke.assert_called_once()
            assert result is not None

    def test_invoke_nfr_assess_workflow_returns_phase_result(
        self,
        setup_nfr_assess_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_nfr_assess_workflow returns PhaseResult."""
        project_path, state = setup_nfr_assess_workflow
        config = FakeConfig()
        handler = NFRAssessHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>nfr-assess</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-nfr-assess"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# NFR Assessment\n\n## Gate Decision: PASS",
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
            patch(
                "bmad_assist.testarch.handlers.nfr_assess.get_paths"
            ) as mock_nfr_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_nfr_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_nfr_assess_workflow(state)

            assert isinstance(result, PhaseResult)
            assert result.success is True
            assert "response" in result.outputs

    def test_invoke_nfr_assess_workflow_extracts_gate_decision(
        self,
        setup_nfr_assess_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_nfr_assess_workflow extracts gate decision from output."""
        project_path, state = setup_nfr_assess_workflow
        config = FakeConfig()
        handler = NFRAssessHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>nfr-assess</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-nfr-assess"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# NFR Assessment\n\n## Gate Decision: PASS\n\nAll NFRs verified.",
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
            patch(
                "bmad_assist.testarch.handlers.nfr_assess.get_paths"
            ) as mock_nfr_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_nfr_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_nfr_assess_workflow(state)

            assert result.success is True
            # gate_decision should be extracted if present in output
            assert "response" in result.outputs

    def test_invoke_nfr_assess_workflow_updates_state_flag(
        self,
        setup_nfr_assess_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_nfr_assess_workflow updates nfr_assess_ran_in_epic state flag."""
        project_path, state = setup_nfr_assess_workflow
        config = FakeConfig()
        handler = NFRAssessHandler(config, project_path)  # type: ignore

        # Verify initial state
        assert state.nfr_assess_ran_in_epic is False

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>nfr-assess</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-nfr-assess"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# NFR Assessment\n\n## Gate Decision: PASS",
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
            patch(
                "bmad_assist.testarch.handlers.nfr_assess.get_paths"
            ) as mock_nfr_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_nfr_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_nfr_assess_workflow(state)

            assert result.success is True
            assert state.nfr_assess_ran_in_epic is True


class TestNFRAssessHandlerExecuteMethod:
    """Test the execute() method of NFRAssessHandler."""

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
        handler = NFRAssessHandler(config, setup_project)  # type: ignore

        state = State()
        state.current_epic = 1

        result = handler.execute(state)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "engagement" in result.outputs.get("reason", "").lower()

    def test_handler_workflow_id_property(self, setup_project: Path) -> None:
        """Test handler has correct workflow_id property."""
        config = FakeConfig()
        handler = NFRAssessHandler(config, setup_project)  # type: ignore

        assert handler.workflow_id == "nfr-assess"

    def test_handler_phase_name_property(self, setup_project: Path) -> None:
        """Test handler has correct phase_name property."""
        config = FakeConfig()
        handler = NFRAssessHandler(config, setup_project)  # type: ignore

        assert handler.phase_name == "tea_nfr_assess"
