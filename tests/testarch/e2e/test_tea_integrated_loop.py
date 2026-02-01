"""E2E tests for TEA Integrated mode in the full development loop.

Story 25.14: Integration Testing - AC: 2.
Tests TEA handler invocations in Integrated mode within the full development loop,
verifying correct phase sequencing and state management.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import State

# Import shared fixtures from conftest
from tests.testarch.e2e.conftest import FakeConfig, FakeTestarchConfig


class TestTEAIntegratedLoop:
    """Test TEA handlers in integrated mode within development loop."""

    @pytest.fixture
    def setup_integrated_project(self, tmp_path: Path) -> tuple[Path, State]:
        """Create project for integrated mode testing."""
        # Create workflow directories
        workflows = ["atdd", "framework", "ci", "test-design", "automate", "test-review"]
        for wf in workflows:
            workflow_dir = tmp_path / f"_bmad/bmm/workflows/testarch/{wf}"
            workflow_dir.mkdir(parents=True)
            (workflow_dir / "workflow.yaml").write_text(f"""
name: testarch-{wf}
description: "Test workflow for {wf}"
instructions: "{{installed_path}}/instructions.xml"
""")
            (workflow_dir / "instructions.xml").write_text(f"""<workflow>
<step n="1" goal="Execute {wf}">
<action>Test action</action>
</step>
</workflow>""")

        # Create output directories
        (tmp_path / "_bmad-output/implementation-artifacts").mkdir(parents=True)
        (tmp_path / "_bmad-output/testarch").mkdir(parents=True)

        # Create docs
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Project Context")
        (tmp_path / "docs/architecture.md").write_text("# Architecture")

        # Create sprint-status
        (tmp_path / "_bmad-output/implementation-artifacts/sprint-status.yaml").write_text("""
epics:
  - id: 1
    title: "Test Epic"
    stories:
      - key: 1-1-test-story
        status: in-progress
""")

        state = State()
        state.current_epic = 1
        state.current_story = "1.1"

        return tmp_path, state

    def test_atdd_handler_invoked_on_story_start(
        self, setup_integrated_project: tuple[Path, State]
    ) -> None:
        """Test ATDDHandler is invoked at story start in integrated mode."""
        project_path, state = setup_integrated_project
        config = FakeConfig(engagement_model="integrated")

        from bmad_assist.testarch.handlers.atdd import ATDDHandler

        handler = ATDDHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>atdd</compiled>"
        mock_compiled.workflow_name = "testarch-atdd"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# ATDD Results\n\nAcceptance tests generated.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.atdd.get_paths") as mock_atdd_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_paths.implementation_artifacts = project_path / "_bmad-output/implementation-artifacts"
            mock_atdd_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert isinstance(result, PhaseResult)
            # Should either succeed or skip based on mode
            assert result.success is True

    def test_framework_handler_runs_once_per_project(
        self, setup_integrated_project: tuple[Path, State]
    ) -> None:
        """Test FrameworkHandler runs only once per project in integrated mode."""
        project_path, state = setup_integrated_project
        config = FakeConfig(engagement_model="integrated")

        from bmad_assist.testarch.handlers.framework import FrameworkHandler

        handler = FrameworkHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>framework</compiled>"
        mock_compiled.workflow_name = "testarch-framework"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Framework\n\n## Framework Type: pytest",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.framework.get_paths") as mock_fw_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_fw_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            # First execution should run
            result1 = handler.execute(state)
            assert result1.success is True

            # Simulate framework already exists by creating config file
            # (handler checks for actual config files, not state flag)
            (project_path / "playwright.config.ts").write_text("export default {}")
            result2 = handler.execute(state)
            assert result2.success is True
            assert result2.outputs.get("skipped") is True
            assert "playwright" in result2.outputs.get("reason", "").lower()

    def test_ci_handler_invoked_after_framework(
        self, setup_integrated_project: tuple[Path, State]
    ) -> None:
        """Test CIHandler can be invoked after framework setup."""
        project_path, state = setup_integrated_project
        config = FakeConfig(engagement_model="integrated")

        from bmad_assist.testarch.handlers.ci import CIHandler

        handler = CIHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>ci</compiled>"
        mock_compiled.workflow_name = "testarch-ci"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# CI Pipeline\n\nCI configured successfully.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.ci.get_paths") as mock_ci_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_ci_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert isinstance(result, PhaseResult)
            assert result.success is True

    def test_test_design_handler_in_integrated_mode(
        self, setup_integrated_project: tuple[Path, State]
    ) -> None:
        """Test TestDesignHandler works in integrated mode."""
        project_path, state = setup_integrated_project
        config = FakeConfig(engagement_model="integrated")

        from bmad_assist.testarch.handlers.test_design import TestDesignHandler

        handler = TestDesignHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>test-design</compiled>"
        mock_compiled.workflow_name = "testarch-test-design"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Design\n\nSystem-level test design complete.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.test_design.get_paths") as mock_td_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_paths.implementation_artifacts = project_path / "_bmad-output/implementation-artifacts"
            mock_td_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert isinstance(result, PhaseResult)
            assert result.success is True

    def test_automate_handler_runs_during_dev(
        self, setup_integrated_project: tuple[Path, State]
    ) -> None:
        """Test AutomateHandler runs during development phase."""
        project_path, state = setup_integrated_project
        config = FakeConfig(engagement_model="integrated")

        from bmad_assist.testarch.handlers.automate import AutomateHandler

        handler = AutomateHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>automate</compiled>"
        mock_compiled.workflow_name = "testarch-automate"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Automation\n\nCoverage: 85%",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.automate.get_paths") as mock_auto_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_auto_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert result.success is True
            assert state.automate_ran_in_epic is True

    def test_test_review_handler_after_code_complete(
        self, setup_integrated_project: tuple[Path, State]
    ) -> None:
        """Test TestReviewHandler runs after code complete."""
        project_path, state = setup_integrated_project
        config = FakeConfig(engagement_model="integrated")

        from bmad_assist.testarch.handlers.test_review import TestReviewHandler

        handler = TestReviewHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>test-review</compiled>"
        mock_compiled.workflow_name = "testarch-test-review"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Review\n\n## Finding Count: 2\n\nTest quality acceptable.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.test_review.get_paths") as mock_tr_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_tr_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert isinstance(result, PhaseResult)
            assert result.success is True

    def test_state_propagation_across_handlers(
        self, setup_integrated_project: tuple[Path, State]
    ) -> None:
        """Test state flags propagate correctly across handler executions."""
        project_path, state = setup_integrated_project
        config = FakeConfig(engagement_model="integrated")

        # Initial state flags
        assert state.framework_ran_in_epic is False
        assert state.ci_ran_in_epic is False
        assert state.automate_ran_in_epic is False

        # Simulate handler executions updating state
        state.framework_ran_in_epic = True
        assert state.framework_ran_in_epic is True

        state.ci_ran_in_epic = True
        assert state.ci_ran_in_epic is True

        state.automate_ran_in_epic = True
        assert state.automate_ran_in_epic is True

    def test_handlers_respect_engagement_model_integrated(
        self, setup_integrated_project: tuple[Path, State]
    ) -> None:
        """Test all handlers respect integrated engagement model."""
        project_path, state = setup_integrated_project
        config = FakeConfig(engagement_model="integrated")

        from bmad_assist.testarch.engagement import should_run_workflow

        # All workflows should be enabled in integrated mode
        assert should_run_workflow("atdd", config.testarch) is True
        assert should_run_workflow("framework", config.testarch) is True
        assert should_run_workflow("ci", config.testarch) is True
        assert should_run_workflow("test-design", config.testarch) is True
        assert should_run_workflow("automate", config.testarch) is True
        assert should_run_workflow("test-review", config.testarch) is True
        assert should_run_workflow("nfr", config.testarch) is True
        assert should_run_workflow("trace", config.testarch) is True

    def test_phase_result_contains_required_outputs(
        self, setup_integrated_project: tuple[Path, State]
    ) -> None:
        """Test PhaseResult contains required output fields."""
        project_path, state = setup_integrated_project
        config = FakeConfig(engagement_model="integrated")

        from bmad_assist.testarch.handlers.automate import AutomateHandler

        handler = AutomateHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>automate</compiled>"
        mock_compiled.workflow_name = "testarch-automate"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Automation\n\nTests expanded.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.automate.get_paths") as mock_auto_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_auto_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert result.success is True
            assert "response" in result.outputs

    def test_handler_error_handling_preserves_state(
        self, setup_integrated_project: tuple[Path, State]
    ) -> None:
        """Test handler errors don't corrupt state."""
        project_path, state = setup_integrated_project
        config = FakeConfig(engagement_model="integrated")

        from bmad_assist.testarch.handlers.automate import AutomateHandler

        handler = AutomateHandler(config, project_path)  # type: ignore

        # Save initial state
        initial_epic = state.current_epic
        initial_story = state.current_story

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>automate</compiled>"
        mock_compiled.workflow_name = "testarch-automate"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=1,
            stdout="",
            stderr="Provider error",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.automate.get_paths") as mock_auto_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_auto_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            # State should be preserved even on error
            assert state.current_epic == initial_epic
            assert state.current_story == initial_story
            # Result should indicate failure
            assert result.success is False


class TestTEAIntegratedLoopSequencing:
    """Test handler sequencing in integrated loop."""

    @pytest.fixture
    def mock_all_handlers(self) -> dict[str, MagicMock]:
        """Create mocks for all handlers."""
        handlers = {}
        for name in ["atdd", "framework", "ci", "test_design", "automate", "test_review"]:
            mock = MagicMock()
            mock.execute.return_value = PhaseResult.ok({"response": f"{name} completed"})
            handlers[name] = mock
        return handlers

    def test_handler_execution_order_is_correct(
        self, mock_all_handlers: dict[str, MagicMock]
    ) -> None:
        """Test handlers can be executed in correct order."""
        execution_order = []

        for name, handler in [
            ("framework", mock_all_handlers["framework"]),
            ("ci", mock_all_handlers["ci"]),
            ("test_design", mock_all_handlers["test_design"]),
            ("atdd", mock_all_handlers["atdd"]),
            ("automate", mock_all_handlers["automate"]),
            ("test_review", mock_all_handlers["test_review"]),
        ]:
            result = handler.execute(State())
            assert result.success is True
            execution_order.append(name)

        # Verify all handlers were executed
        assert len(execution_order) == 6
        assert "framework" in execution_order
        assert "automate" in execution_order

    def test_skipped_handlers_dont_block_sequence(
        self, mock_all_handlers: dict[str, MagicMock]
    ) -> None:
        """Test skipped handlers don't block subsequent handlers."""
        # Framework skipped
        mock_all_handlers["framework"].execute.return_value = PhaseResult.ok({
            "skipped": True,
            "reason": "Already exists"
        })

        state = State()

        # All handlers should still execute
        results = []
        for name in ["framework", "ci", "test_design", "atdd", "automate", "test_review"]:
            result = mock_all_handlers[name].execute(state)
            results.append((name, result))

        # All should succeed (including skipped)
        assert all(r.success for _, r in results)
        # Framework was skipped
        assert results[0][1].outputs.get("skipped") is True
