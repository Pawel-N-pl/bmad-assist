"""
Tests for TraceHandler compiler integration.

Tests the integration between TraceHandler and the TraceCompiler,
verifying that _invoke_trace_workflow correctly:
1. Creates CompilerContext with state variables
2. Calls compile_workflow to get the compiled prompt
3. Invokes master provider with the compiled prompt
4. Creates traceability directory and saves trace file
5. Returns PhaseResult with trace_file path and gate_decision
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import State
from bmad_assist.testarch.handlers.trace import TraceHandler


class FakeConfig:
    """Fake Config for testing."""

    def __init__(self) -> None:
        self.providers = MagicMock()
        self.providers.master = MagicMock()
        self.providers.master.provider = "claude-subprocess"
        self.providers.master.model = "opus"
        self.timeout = 120
        self.testarch = MagicMock()
        self.testarch.trace_on_epic_complete = "on"


class TestTraceHandlerInvokeWorkflow:
    """Test _invoke_trace_workflow uses compiler and provider."""

    @pytest.fixture
    def setup_trace_workflow(self, tmp_path: Path) -> tuple[Path, State]:
        """Create testarch-trace workflow structure and state."""
        # Create workflow directory
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/trace"
        workflow_dir.mkdir(parents=True)

        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: testarch-trace
description: "Generate requirements-to-tests traceability matrix"
instructions: "{installed_path}/instructions.xml"
template: "{installed_path}/trace-template.md"
variables:
  test_dir: "{project-root}/tests"
  source_dir: "{project-root}/src"
  gate_type: "epic"
default_output_file: "{output_folder}/traceability-matrix.md"
""")

        instructions = workflow_dir / "instructions.xml"
        instructions.write_text("""<workflow>
<step n="1" goal="Build traceability matrix">
<action>Map tests to requirements</action>
</step>
</workflow>""")

        template = workflow_dir / "trace-template.md"
        template.write_text("# Traceability Matrix for Epic {{epic_num}}")

        # Create epic file
        epics_dir = tmp_path / "_bmad-output/epics"
        epics_dir.mkdir(parents=True)
        epic_file = epics_dir / "epic-testarch.md"
        epic_file.write_text("# Epic testarch\n## Stories")

        # Create project context
        output_dir = tmp_path / "_bmad-output"
        project_context = output_dir / "project-context.md"
        project_context.write_text("# Project Context\nRules here...")

        # Create traceability directory (handler will create if missing)
        traceability_dir = output_dir / "traceability"
        traceability_dir.mkdir(parents=True)

        # Create state
        state = State()
        state.current_epic = "testarch"
        state.atdd_ran_in_epic = True

        return tmp_path, state

    def test_invoke_trace_workflow_calls_compiler(
        self,
        setup_trace_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_trace_workflow calls compile_workflow."""
        project_path, state = setup_trace_workflow
        config = FakeConfig()
        handler = TraceHandler(config, project_path)  # type: ignore

        # Mock compile_workflow
        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-prompt>test</compiled-prompt>"
        mock_compiled.workflow_name = "testarch-trace"

        # Mock provider
        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult
        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="## Gate Decision: PASS\nTests traced successfully",
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
            patch("bmad_assist.testarch.handlers.trace.get_paths") as mock_trace_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_trace_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_trace_workflow(state)

            # Verify compile_workflow was called
            mock_compile.assert_called_once()
            call_args = mock_compile.call_args
            assert call_args[0][0] == "testarch-trace"

    def test_invoke_trace_workflow_calls_provider(
        self,
        setup_trace_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_trace_workflow invokes master provider."""
        project_path, state = setup_trace_workflow
        config = FakeConfig()
        handler = TraceHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-prompt>test</compiled-prompt>"
        mock_compiled.workflow_name = "testarch-trace"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult
        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="## Gate Decision: PASS\nTests traced successfully",
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
            patch("bmad_assist.testarch.handlers.trace.get_paths") as mock_trace_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_trace_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_trace_workflow(state)

            # Verify get_provider was called with correct provider name
            mock_get_provider.assert_called_once_with("claude-subprocess")

            # Verify provider.invoke was called
            mock_provider.invoke.assert_called_once()
            call_kwargs = mock_provider.invoke.call_args[1]
            assert call_kwargs["model"] == "opus"

    def test_invoke_trace_workflow_returns_phase_result_with_gate(
        self,
        setup_trace_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_trace_workflow returns PhaseResult with gate_decision."""
        project_path, state = setup_trace_workflow
        config = FakeConfig()
        handler = TraceHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-prompt>test</compiled-prompt>"
        mock_compiled.workflow_name = "testarch-trace"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult
        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="## Gate Decision: PASS\nAll tests mapped successfully",
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
            patch("bmad_assist.testarch.handlers.trace.get_paths") as mock_trace_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_paths,
        ):
            mock_paths.return_value.output_folder = project_path / "_bmad-output"
            mock_trace_paths.return_value.output_folder = project_path / "_bmad-output"

            result = handler._invoke_trace_workflow(state)

            assert isinstance(result, PhaseResult)
            assert result.success is True
            assert "response" in result.outputs
            assert "gate_decision" in result.outputs
            assert result.outputs["gate_decision"] == "PASS"

    def test_invoke_trace_workflow_creates_traceability_directory(
        self,
        setup_trace_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_trace_workflow creates traceability directory."""
        project_path, state = setup_trace_workflow
        config = FakeConfig()
        handler = TraceHandler(config, project_path)  # type: ignore

        # Remove traceability dir if exists
        traceability_dir = project_path / "_bmad-output/traceability"
        if traceability_dir.exists():
            import shutil

            shutil.rmtree(traceability_dir)

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-prompt>test</compiled-prompt>"
        mock_compiled.workflow_name = "testarch-trace"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult
        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="## Gate Decision: PASS\nTests mapped",
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
            patch("bmad_assist.testarch.handlers.trace.get_paths") as mock_trace_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_paths,
        ):
            mock_paths.return_value.output_folder = project_path / "_bmad-output"
            mock_trace_paths.return_value.output_folder = project_path / "_bmad-output"

            result = handler._invoke_trace_workflow(state)

            # Verify directory was created
            assert traceability_dir.exists()

    def test_invoke_trace_workflow_saves_trace_file(
        self,
        setup_trace_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_trace_workflow saves trace file with atomic write."""
        project_path, state = setup_trace_workflow
        config = FakeConfig()
        handler = TraceHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-prompt>test</compiled-prompt>"
        mock_compiled.workflow_name = "testarch-trace"

        provider_output = "## Gate Decision: PASS\n# Traceability Matrix\nTest content"
        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult
        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout=provider_output,
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
            patch("bmad_assist.testarch.handlers.trace.get_paths") as mock_trace_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_paths,
        ):
            mock_paths.return_value.output_folder = project_path / "_bmad-output"
            mock_trace_paths.return_value.output_folder = project_path / "_bmad-output"

            result = handler._invoke_trace_workflow(state)

            # Verify trace file was saved
            assert result.success is True
            assert "trace_file" in result.outputs
            trace_file = result.outputs["trace_file"]
            if trace_file:
                assert Path(trace_file).exists()


class TestTraceHandlerInvokeWorkflowErrorHandling:
    """Test error handling in _invoke_trace_workflow."""

    @pytest.fixture
    def setup_trace_workflow(self, tmp_path: Path) -> tuple[Path, State]:
        """Create minimal setup for error handling tests."""
        output_dir = tmp_path / "_bmad-output"
        output_dir.mkdir(parents=True)
        project_context = output_dir / "project-context.md"
        project_context.write_text("# Project Context")

        state = State()
        state.current_epic = "testarch"
        state.atdd_ran_in_epic = True

        return tmp_path, state

    def test_invoke_trace_workflow_handles_compiler_error(
        self,
        setup_trace_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_trace_workflow handles CompilerError gracefully."""
        from bmad_assist.core.exceptions import CompilerError

        project_path, state = setup_trace_workflow
        config = FakeConfig()
        handler = TraceHandler(config, project_path)  # type: ignore

        with (
            patch(
                "bmad_assist.compiler.compile_workflow",
                side_effect=CompilerError("Test compiler error"),
            ),
            patch("bmad_assist.testarch.handlers.trace.get_paths") as mock_trace_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_trace_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_trace_workflow(state)

            assert result.success is False
            assert result.error is not None
            assert "error" in result.error.lower()

    def test_invoke_trace_workflow_handles_provider_error(
        self,
        setup_trace_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_trace_workflow handles provider error."""
        project_path, state = setup_trace_workflow
        config = FakeConfig()
        handler = TraceHandler(config, project_path)  # type: ignore

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
            patch("bmad_assist.testarch.handlers.trace.get_paths") as mock_trace_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_trace_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_trace_workflow(state)

            assert result.success is False
            assert result.error is not None
            assert "error" in result.error.lower()
