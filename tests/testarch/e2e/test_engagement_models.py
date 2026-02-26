"""E2E tests for TEA engagement models.

Story 25.14: Integration Testing - AC: 5.
Tests all engagement model configurations (off, lite, solo, integrated, auto)
and verifies correct workflow enablement/blocking behavior.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.state import State

# Import shared fixtures from conftest
from tests.testarch.e2e.conftest import FakeConfig

# All workflow IDs for testing
ALL_WORKFLOWS = [
    "atdd",
    "framework",
    "ci",
    "test-design",
    "automate",
    "test-review",
    "nfr-assess",
    "trace",
]

# Standalone workflows (enabled in solo mode)
STANDALONE_WORKFLOWS = {"framework", "ci", "automate", "test-design", "nfr-assess"}


class TestEngagementModelOff:
    """Test engagement_model='off' disables all workflows."""

    def test_all_workflows_disabled_when_off(self) -> None:
        """Test all workflows are disabled when engagement_model='off'."""
        config = FakeConfig(engagement_model="off")

        from bmad_assist.testarch.engagement import should_run_workflow

        for workflow_id in ALL_WORKFLOWS:
            assert should_run_workflow(workflow_id, config.testarch) is False  # type: ignore

    def test_handler_skips_with_engagement_reason(self, tmp_path: Path) -> None:
        """Test handlers skip with engagement reason when off."""
        config = FakeConfig(engagement_model="off")
        state = State()
        state.current_epic = 1

        # Create minimal project structure
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")
        (tmp_path / "_bmad-output").mkdir(parents=True)

        from bmad_assist.testarch.handlers.automate import AutomateHandler

        handler = AutomateHandler(config, tmp_path)  # type: ignore

        with (
            patch("bmad_assist.testarch.handlers.automate.get_paths") as mock_auto_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = tmp_path / "_bmad-output"
            mock_auto_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert result.success is True
            assert result.outputs.get("skipped") is True
            assert "engagement" in result.outputs.get("reason", "").lower()


class TestEngagementModelLite:
    """Test engagement_model='lite' enables only automate."""

    def test_only_automate_enabled_in_lite(self) -> None:
        """Test only automate is enabled in lite mode."""
        config = FakeConfig(engagement_model="lite")

        from bmad_assist.testarch.engagement import should_run_workflow

        # Only automate should be enabled
        assert should_run_workflow("automate", config.testarch) is True  # type: ignore

        # All others should be disabled
        for workflow_id in ALL_WORKFLOWS:
            if workflow_id != "automate":
                assert should_run_workflow(workflow_id, config.testarch) is False  # type: ignore


class TestEngagementModelSolo:
    """Test engagement_model='solo' enables standalone workflows."""

    def test_standalone_workflows_enabled_in_solo(self) -> None:
        """Test standalone workflows are enabled in solo mode."""
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.engagement import should_run_workflow

        # Standalone workflows should be enabled
        for workflow_id in STANDALONE_WORKFLOWS:
            assert should_run_workflow(workflow_id, config.testarch) is True  # type: ignore

    def test_non_standalone_workflows_disabled_in_solo(self) -> None:
        """Test non-standalone workflows are disabled in solo mode."""
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.engagement import should_run_workflow

        non_standalone = set(ALL_WORKFLOWS) - STANDALONE_WORKFLOWS
        for workflow_id in non_standalone:
            assert should_run_workflow(workflow_id, config.testarch) is False  # type: ignore


class TestEngagementModelIntegrated:
    """Test engagement_model='integrated' enables all workflows."""

    def test_all_workflows_enabled_in_integrated(self) -> None:
        """Test all workflows are enabled in integrated mode."""
        config = FakeConfig(engagement_model="integrated")

        from bmad_assist.testarch.engagement import should_run_workflow

        for workflow_id in ALL_WORKFLOWS:
            assert should_run_workflow(workflow_id, config.testarch) is True  # type: ignore


class TestEngagementModelAuto:
    """Test engagement_model='auto' defers to individual modes."""

    def test_auto_mode_allows_all_workflows(self) -> None:
        """Test auto mode allows all workflows at engagement level."""
        config = FakeConfig(engagement_model="auto")

        from bmad_assist.testarch.engagement import should_run_workflow

        # Auto mode returns True for all at engagement level
        # Individual mode checks happen at handler level
        for workflow_id in ALL_WORKFLOWS:
            assert should_run_workflow(workflow_id, config.testarch) is True  # type: ignore

    def test_auto_mode_respects_none_config(self) -> None:
        """Test auto mode returns True when config is None (backwards compat)."""
        from bmad_assist.testarch.engagement import should_run_workflow

        for workflow_id in ALL_WORKFLOWS:
            assert should_run_workflow(workflow_id, None) is True


class TestEngagementModelTransitions:
    """Test transitions between engagement models."""

    @pytest.fixture
    def setup_project(self, tmp_path: Path) -> tuple[Path, State]:
        """Create project structure for testing."""
        # Create automate workflow
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/automate"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yaml").write_text("""
name: testarch-automate
description: "Automate workflow"
instructions: "{installed_path}/instructions.xml"
""")
        (workflow_dir / "instructions.xml").write_text("<workflow></workflow>")

        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")
        (tmp_path / "_bmad-output").mkdir(parents=True)

        state = State()
        state.current_epic = 1

        return tmp_path, state

    def test_changing_engagement_model_affects_workflows(
        self, setup_project: tuple[Path, State]
    ) -> None:
        """Test changing engagement model affects workflow enablement."""
        project_path, state = setup_project

        from bmad_assist.testarch.engagement import should_run_workflow

        # Start with off
        config_off = FakeConfig(engagement_model="off")
        assert should_run_workflow("automate", config_off.testarch) is False  # type: ignore

        # Change to lite
        config_lite = FakeConfig(engagement_model="lite")
        assert should_run_workflow("automate", config_lite.testarch) is True  # type: ignore
        assert should_run_workflow("framework", config_lite.testarch) is False  # type: ignore

        # Change to solo
        config_solo = FakeConfig(engagement_model="solo")
        assert should_run_workflow("automate", config_solo.testarch) is True  # type: ignore
        assert should_run_workflow("framework", config_solo.testarch) is True  # type: ignore
        assert should_run_workflow("atdd", config_solo.testarch) is False  # type: ignore

        # Change to integrated
        config_integrated = FakeConfig(engagement_model="integrated")
        for wf in ALL_WORKFLOWS:
            assert should_run_workflow(wf, config_integrated.testarch) is True  # type: ignore

    def test_handler_respects_dynamic_engagement_model(
        self, setup_project: tuple[Path, State]
    ) -> None:
        """Test handler respects engagement model at execution time."""
        project_path, state = setup_project

        from bmad_assist.testarch.handlers.automate import AutomateHandler

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>automate</compiled>"
        mock_compiled.workflow_name = "testarch-automate"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Output",
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

            # With engagement off, should skip
            config_off = FakeConfig(engagement_model="off")
            handler_off = AutomateHandler(config_off, project_path)  # type: ignore
            result_off = handler_off.execute(state)
            assert result_off.outputs.get("skipped") is True

            # With engagement lite, should run
            config_lite = FakeConfig(engagement_model="lite")
            handler_lite = AutomateHandler(config_lite, project_path)  # type: ignore
            result_lite = handler_lite.execute(state)
            assert result_lite.success is True
            assert result_lite.outputs.get("skipped") is not True


class TestEngagementModelEdgeCases:
    """Test edge cases for engagement model handling."""

    def test_invalid_engagement_model_treated_as_auto(self) -> None:
        """Test invalid engagement model is treated as auto."""
        config = FakeConfig()
        config.testarch.engagement_model = "invalid_model"

        from bmad_assist.testarch.engagement import should_run_workflow

        # Invalid model falls through to default True
        for workflow_id in ALL_WORKFLOWS:
            assert should_run_workflow(workflow_id, config.testarch) is True  # type: ignore

    def test_empty_engagement_model_treated_as_auto(self) -> None:
        """Test empty engagement model is treated as auto."""
        config = FakeConfig()
        config.testarch.engagement_model = ""

        from bmad_assist.testarch.engagement import should_run_workflow

        # Empty model falls through to default True
        for workflow_id in ALL_WORKFLOWS:
            assert should_run_workflow(workflow_id, config.testarch) is True  # type: ignore

    def test_unknown_workflow_id(self) -> None:
        """Test unknown workflow ID behavior."""
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.engagement import should_run_workflow

        # Unknown workflow is not in STANDALONE_WORKFLOWS
        assert should_run_workflow("unknown-workflow", config.testarch) is False  # type: ignore

        # In integrated mode, unknown workflow is allowed
        config_integrated = FakeConfig(engagement_model="integrated")
        assert should_run_workflow("unknown-workflow", config_integrated.testarch) is True  # type: ignore
