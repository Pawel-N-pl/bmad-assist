"""Tests for TestDesignHandler compiler integration.

Story 25.14: Integration Testing.
Tests the integration between TestDesignHandler and the workflow compiler,
verifying that _invoke_test_design_workflow correctly:
1. Creates CompilerContext with state variables
2. Calls compile_workflow to get the compiled prompt
3. Invokes master provider with the compiled prompt
4. Returns PhaseResult with workflow output
5. Supports both system-level and epic-level test design
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import State
from bmad_assist.testarch.handlers.test_design import TestDesignHandler


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
        self.testarch.test_design_level = kwargs.get("test_design_level", "auto")
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


class TestTestDesignHandlerInvokeWorkflow:
    """Test _invoke_test_design_workflow uses compiler and provider."""

    @pytest.fixture
    def setup_test_design_workflow(self, tmp_path: Path) -> tuple[Path, State]:
        """Create testarch-test-design workflow structure and state."""
        # Create workflow directory
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/test-design"
        workflow_dir.mkdir(parents=True)

        workflow_yaml = workflow_dir / "workflow.yaml"
        workflow_yaml.write_text("""
name: testarch-test-design
description: "Design test strategy"
instructions: "{installed_path}/instructions.xml"
""")

        instructions = workflow_dir / "instructions.xml"
        instructions.write_text("""<workflow>
<step n="1" goal="Design test strategy">
<action>Analyze requirements and design test approach</action>
</step>
</workflow>""")

        # Create output directory
        (tmp_path / "_bmad-output/test-design").mkdir(parents=True)

        # Create docs directory
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Project Context\nRules here.")
        (tmp_path / "docs/architecture.md").write_text("# Architecture\nPatterns here.")

        state = State()
        state.current_epic = 1
        state.current_story = "1.1"

        return tmp_path, state

    def test_invoke_test_design_workflow_calls_compiler(
        self,
        setup_test_design_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_test_design_workflow calls compile_workflow."""
        project_path, state = setup_test_design_workflow
        config = FakeConfig()
        handler = TestDesignHandler(config, project_path)  # type: ignore

        # Mock compile_workflow
        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>test-design</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-test-design"

        # Mock provider
        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Design\n\nTest strategy defined.",
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
                "bmad_assist.testarch.handlers.test_design.get_paths"
            ) as mock_td_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_td_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_test_design_workflow(state, level="system")

            mock_compile.assert_called_once()
            call_args = mock_compile.call_args
            assert call_args[0][0] == "testarch-test-design"
            assert result is not None  # Use result to avoid unused variable warning

    def test_invoke_test_design_workflow_returns_phase_result(
        self,
        setup_test_design_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_test_design_workflow returns PhaseResult."""
        project_path, state = setup_test_design_workflow
        config = FakeConfig()
        handler = TestDesignHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>test-design</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-test-design"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Design\n\nTest strategy defined.",
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
                "bmad_assist.testarch.handlers.test_design.get_paths"
            ) as mock_td_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_td_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_test_design_workflow(state, level="system")

            assert isinstance(result, PhaseResult)
            assert result.success is True
            assert "response" in result.outputs

    def test_invoke_test_design_workflow_extracts_risk_count(
        self,
        setup_test_design_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_test_design_workflow extracts risk count from output."""
        project_path, state = setup_test_design_workflow
        config = FakeConfig()
        handler = TestDesignHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>test-design</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-test-design"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Design\n\n## Risk Assessment\n- Risk 1\n- Risk 2\n- Risk 3",
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
                "bmad_assist.testarch.handlers.test_design.get_paths"
            ) as mock_td_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_td_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_test_design_workflow(state, level="system")

            assert result.success is True
            assert "response" in result.outputs

    def test_invoke_test_design_workflow_updates_state_flag(
        self,
        setup_test_design_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_test_design_workflow updates test_design_ran_in_epic state flag."""
        project_path, state = setup_test_design_workflow
        config = FakeConfig()
        handler = TestDesignHandler(config, project_path)  # type: ignore

        # Verify initial state
        assert state.test_design_ran_in_epic is False

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>test-design</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-test-design"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Design\n\nTest strategy defined.",
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
                "bmad_assist.testarch.handlers.test_design.get_paths"
            ) as mock_td_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_td_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_test_design_workflow(state, level="system")

            assert result.success is True
            assert state.test_design_ran_in_epic is True

    def test_invoke_test_design_workflow_handles_system_level(
        self,
        setup_test_design_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_test_design_workflow works with system level."""
        project_path, state = setup_test_design_workflow
        config = FakeConfig()
        handler = TestDesignHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled-workflow>test-design</compiled-workflow>"
        mock_compiled.workflow_name = "testarch-test-design"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Design\n\nTest strategy defined.",
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
                "bmad_assist.testarch.handlers.test_design.get_paths"
            ) as mock_td_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_td_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_test_design_workflow(state, level="system")

            assert result.success is True
            assert "response" in result.outputs


class TestTestDesignHandlerErrorHandling:
    """Test error handling in TestDesignHandler."""

    @pytest.fixture
    def setup_test_design_workflow(self, tmp_path: Path) -> tuple[Path, State]:
        """Create minimal setup for error handling tests."""
        (tmp_path / "_bmad-output").mkdir(parents=True)
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Project Context")

        state = State()
        state.current_epic = 1
        state.current_story = "1.1"

        return tmp_path, state

    def test_invoke_test_design_workflow_handles_compiler_error(
        self,
        setup_test_design_workflow: tuple[Path, State],
    ) -> None:
        """Test _invoke_test_design_workflow handles CompilerError gracefully."""
        from bmad_assist.core.exceptions import CompilerError

        project_path, state = setup_test_design_workflow
        config = FakeConfig()
        handler = TestDesignHandler(config, project_path)  # type: ignore

        with (
            patch(
                "bmad_assist.compiler.compile_workflow",
                side_effect=CompilerError("Test compiler error"),
            ),
            patch(
                "bmad_assist.testarch.handlers.test_design.get_paths"
            ) as mock_td_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_td_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler._invoke_test_design_workflow(state, level="system")

            assert result.success is False
            assert result.error is not None
            assert "error" in result.error.lower()


class TestTestDesignHandlerExecuteMethod:
    """Test the execute() method of TestDesignHandler."""

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
        handler = TestDesignHandler(config, setup_project)  # type: ignore

        state = State()
        state.current_epic = 1

        result = handler.execute(state)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "engagement" in result.outputs.get("reason", "").lower()

    def test_handler_workflow_id_property(self, setup_project: Path) -> None:
        """Test handler has correct workflow_id property."""
        config = FakeConfig()
        handler = TestDesignHandler(config, setup_project)  # type: ignore

        assert handler.workflow_id == "test-design"

    def test_handler_phase_name_property(self, setup_project: Path) -> None:
        """Test handler has correct phase_name property."""
        config = FakeConfig()
        handler = TestDesignHandler(config, setup_project)  # type: ignore

        assert handler.phase_name == "tea_test_design"

    def test_execute_skips_when_system_level_output_exists(
        self, setup_project: Path
    ) -> None:
        """Test execute skips when system-level test design already exists."""
        # Create existing system-level output files in output_folder root
        # (handler checks paths.output_folder / "test-design-architecture.md")
        output_folder = setup_project / "_bmad-output"
        output_folder.mkdir(parents=True, exist_ok=True)
        (output_folder / "test-design-architecture.md").write_text("# Test Design")
        (output_folder / "test-design-qa.md").write_text("# QA Plan")

        # Configure to force system-level detection
        config = FakeConfig()
        config.testarch.test_design_level = "system"  # Force system level
        handler = TestDesignHandler(config, setup_project)  # type: ignore

        state = State()
        state.current_epic = 1

        # Need to mock get_paths since execute calls it (both in handler and base)
        with (
            patch(
                "bmad_assist.testarch.handlers.test_design.get_paths"
            ) as mock_td_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = setup_project / "_bmad-output"
            mock_td_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "system-level test-design already exists" in result.outputs.get("reason", "")
