"""E2E tests for TEA Lite mode.

Story 25.14: Integration Testing - AC: 4.
Tests TEA handler invocations in Lite mode, verifying that only
the automate workflow is enabled while others are blocked.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.state import State

# Import shared fixtures from conftest
from tests.testarch.e2e.conftest import FakeConfig


class TestTEALiteMode:
    """Test TEA handlers in Lite mode (automate only)."""

    @pytest.fixture
    def setup_lite_project(self, tmp_path: Path) -> tuple[Path, State]:
        """Create project for lite mode testing."""
        # Create workflow directory for automate only
        workflow_dir = tmp_path / "_bmad/bmm/workflows/testarch/automate"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yaml").write_text("""
name: testarch-automate
description: "Test automation workflow"
instructions: "{installed_path}/instructions.xml"
""")
        (workflow_dir / "instructions.xml").write_text("""<workflow>
<step n="1" goal="Automate tests">
<action>Expand test coverage</action>
</step>
</workflow>""")

        # Create output directories
        (tmp_path / "_bmad-output/implementation-artifacts").mkdir(parents=True)
        (tmp_path / "_bmad-output/testarch").mkdir(parents=True)

        # Create docs
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Project Context")

        state = State()
        state.current_epic = 1
        state.current_story = "1.1"

        return tmp_path, state

    def test_only_automate_enabled_in_lite_mode(
        self, setup_lite_project: tuple[Path, State]
    ) -> None:
        """Test only automate workflow is enabled in lite mode."""
        _, _ = setup_lite_project
        config = FakeConfig(engagement_model="lite")

        from bmad_assist.testarch.engagement import should_run_workflow

        # Only automate should be enabled in lite mode
        assert should_run_workflow("automate", config.testarch) is True  # type: ignore

        # All other workflows should be blocked
        assert should_run_workflow("atdd", config.testarch) is False  # type: ignore
        assert should_run_workflow("framework", config.testarch) is False  # type: ignore
        assert should_run_workflow("ci", config.testarch) is False  # type: ignore
        assert should_run_workflow("test-design", config.testarch) is False  # type: ignore
        assert should_run_workflow("test-review", config.testarch) is False  # type: ignore
        assert should_run_workflow("nfr-assess", config.testarch) is False  # type: ignore
        assert should_run_workflow("trace", config.testarch) is False  # type: ignore

    def test_automate_handler_executes_in_lite_mode(
        self, setup_lite_project: tuple[Path, State]
    ) -> None:
        """Test AutomateHandler can execute in lite mode."""
        project_path, state = setup_lite_project
        config = FakeConfig(engagement_model="lite")

        from bmad_assist.testarch.handlers.automate import AutomateHandler

        handler = AutomateHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>automate</compiled>"
        mock_compiled.workflow_name = "testarch-automate"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Automation\n\nCoverage expanded to 80%.",
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

    def test_framework_handler_skipped_in_lite_mode(
        self, setup_lite_project: tuple[Path, State]
    ) -> None:
        """Test FrameworkHandler is skipped in lite mode."""
        project_path, state = setup_lite_project
        config = FakeConfig(engagement_model="lite")

        from bmad_assist.testarch.handlers.framework import FrameworkHandler

        handler = FrameworkHandler(config, project_path)  # type: ignore

        with (
            patch("bmad_assist.testarch.handlers.framework.get_paths") as mock_fw_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_fw_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert result.success is True
            assert result.outputs.get("skipped") is True
            assert "engagement" in result.outputs.get("reason", "").lower()

    def test_ci_handler_skipped_in_lite_mode(
        self, setup_lite_project: tuple[Path, State]
    ) -> None:
        """Test CIHandler is skipped in lite mode."""
        project_path, state = setup_lite_project
        config = FakeConfig(engagement_model="lite")

        from bmad_assist.testarch.handlers.ci import CIHandler

        handler = CIHandler(config, project_path)  # type: ignore

        with (
            patch("bmad_assist.testarch.handlers.ci.get_paths") as mock_ci_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_ci_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert result.success is True
            assert result.outputs.get("skipped") is True
            assert "engagement" in result.outputs.get("reason", "").lower()

    def test_test_review_handler_skipped_in_lite_mode(
        self, setup_lite_project: tuple[Path, State]
    ) -> None:
        """Test TestReviewHandler is skipped in lite mode."""
        project_path, state = setup_lite_project
        config = FakeConfig(engagement_model="lite")

        from bmad_assist.testarch.handlers.test_review import TestReviewHandler

        handler = TestReviewHandler(config, project_path)  # type: ignore

        with (
            patch("bmad_assist.testarch.handlers.test_review.get_paths") as mock_tr_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_tr_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert result.success is True
            assert result.outputs.get("skipped") is True


class TestTEALiteModeMinimalOverhead:
    """Test lite mode provides minimal overhead."""

    @pytest.fixture
    def setup_minimal_project(self, tmp_path: Path) -> Path:
        """Create minimal project for lite mode."""
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")
        (tmp_path / "_bmad-output").mkdir(parents=True)
        return tmp_path

    def test_lite_mode_reduces_handler_invocations(
        self, setup_minimal_project: Path
    ) -> None:
        """Test lite mode only invokes necessary handlers."""
        _ = setup_minimal_project
        config = FakeConfig(engagement_model="lite")

        from bmad_assist.testarch.engagement import should_run_workflow

        enabled_count = 0
        disabled_count = 0

        for workflow_id in [
            "atdd", "framework", "ci", "test-design",
            "automate", "test-review", "nfr-assess", "trace"
        ]:
            if should_run_workflow(workflow_id, config.testarch):  # type: ignore
                enabled_count += 1
            else:
                disabled_count += 1

        # Only 1 workflow (automate) should be enabled
        assert enabled_count == 1
        assert disabled_count == 7

    def test_lite_mode_state_flag_updates_correctly(
        self, setup_minimal_project: Path
    ) -> None:
        """Test state flags update correctly in lite mode."""
        project_path = setup_minimal_project
        config = FakeConfig(engagement_model="lite")
        state = State()
        state.current_epic = 1

        # Create automate workflow
        workflow_dir = project_path / "_bmad/bmm/workflows/testarch/automate"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yaml").write_text("""
name: testarch-automate
description: "Test automation"
instructions: "{installed_path}/instructions.xml"
""")
        (workflow_dir / "instructions.xml").write_text("<workflow></workflow>")

        from bmad_assist.testarch.handlers.automate import AutomateHandler

        handler = AutomateHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>automate</compiled>"
        mock_compiled.workflow_name = "testarch-automate"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Automation\n\nComplete.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        # Verify initial state
        assert state.automate_ran_in_epic is False

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

            # Other flags should remain false (handlers skipped)
            assert state.framework_ran_in_epic is False
            assert state.ci_ran_in_epic is False
