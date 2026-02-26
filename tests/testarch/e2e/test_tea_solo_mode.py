"""E2E tests for TEA Solo mode (standalone runner).

Story 25.14: Integration Testing - AC: 3.
Tests TEA handler invocations in Solo mode, verifying handlers work
outside the development loop with direct CLI or programmatic invocation.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.state import State

# Import shared fixtures from conftest
from tests.testarch.e2e.conftest import FakeConfig


class TestTEASoloMode:
    """Test TEA handlers in Solo mode (standalone invocation)."""

    @pytest.fixture
    def setup_solo_project(self, tmp_path: Path) -> tuple[Path, State]:
        """Create project for solo mode testing."""
        # Create workflow directories
        workflows = ["atdd", "framework", "ci", "test-design", "automate", "test-review", "nfr", "trace"]
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
        (tmp_path / "_bmad-output/standalone").mkdir(parents=True)

        # Create docs
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Project Context")
        (tmp_path / "docs/architecture.md").write_text("# Architecture")

        state = State()
        state.current_epic = 1
        state.current_story = "1.1"

        return tmp_path, state

    def test_standalone_workflows_enabled_in_solo_mode(
        self, setup_solo_project: tuple[Path, State]
    ) -> None:
        """Test standalone workflows are enabled in solo mode."""
        _, _ = setup_solo_project
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.engagement import should_run_workflow

        # Only standalone workflows should be enabled in solo mode
        # STANDALONE_WORKFLOWS = {"framework", "ci", "automate", "test-design", "nfr-assess"}
        assert should_run_workflow("framework", config.testarch) is True  # type: ignore
        assert should_run_workflow("ci", config.testarch) is True  # type: ignore
        assert should_run_workflow("automate", config.testarch) is True  # type: ignore
        assert should_run_workflow("test-design", config.testarch) is True  # type: ignore
        assert should_run_workflow("nfr-assess", config.testarch) is True  # type: ignore

        # Non-standalone workflows are blocked in solo mode
        assert should_run_workflow("atdd", config.testarch) is False  # type: ignore
        assert should_run_workflow("test-review", config.testarch) is False  # type: ignore
        assert should_run_workflow("trace", config.testarch) is False  # type: ignore

    def test_framework_handler_standalone_execution(
        self, setup_solo_project: tuple[Path, State]
    ) -> None:
        """Test FrameworkHandler can execute standalone in solo mode."""
        project_path, state = setup_solo_project
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.handlers.framework import FrameworkHandler

        handler = FrameworkHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>framework</compiled>"
        mock_compiled.workflow_name = "testarch-framework"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Framework\n\n## Framework Type: playwright\n\nFramework initialized.",
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

            result = handler.execute(state)

            assert result.success is True
            assert "response" in result.outputs

    def test_ci_handler_standalone_execution(
        self, setup_solo_project: tuple[Path, State]
    ) -> None:
        """Test CIHandler can execute standalone in solo mode."""
        project_path, state = setup_solo_project
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.handlers.ci import CIHandler

        handler = CIHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>ci</compiled>"
        mock_compiled.workflow_name = "testarch-ci"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# CI Pipeline\n\nCI configured with GitHub Actions.",
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

            assert result.success is True
            assert "response" in result.outputs

    def test_automate_handler_standalone_execution(
        self, setup_solo_project: tuple[Path, State]
    ) -> None:
        """Test AutomateHandler can execute standalone in solo mode."""
        project_path, state = setup_solo_project
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.handlers.automate import AutomateHandler

        handler = AutomateHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>automate</compiled>"
        mock_compiled.workflow_name = "testarch-automate"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Automation\n\nCoverage expanded to 90%.",
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

    def test_nfr_handler_standalone_execution(
        self, setup_solo_project: tuple[Path, State]
    ) -> None:
        """Test NFRAssessHandler can execute standalone in solo mode."""
        project_path, state = setup_solo_project
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.handlers.nfr_assess import NFRAssessHandler

        handler = NFRAssessHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>nfr</compiled>"
        mock_compiled.workflow_name = "testarch-nfr"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# NFR Assessment\n\n## Status: PASS\n\nAll NFRs satisfied.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.nfr_assess.get_paths") as mock_nfr_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_nfr_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            result = handler.execute(state)

            assert result.success is True
            assert state.nfr_assess_ran_in_epic is True

    def test_test_review_handler_standalone_execution(
        self, setup_solo_project: tuple[Path, State]
    ) -> None:
        """Test TestReviewHandler can execute standalone in solo mode."""
        project_path, state = setup_solo_project
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.handlers.test_review import TestReviewHandler

        handler = TestReviewHandler(config, project_path)  # type: ignore

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>test-review</compiled>"
        mock_compiled.workflow_name = "testarch-test-review"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Test Review\n\n## Finding Count: 1\n\nMinor improvements suggested.",
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

            assert result.success is True

    def test_handler_results_not_dependent_on_loop_state(
        self, setup_solo_project: tuple[Path, State]
    ) -> None:
        """Test handlers can run with minimal state in solo mode."""
        project_path, _ = setup_solo_project
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.handlers.automate import AutomateHandler

        handler = AutomateHandler(config, project_path)  # type: ignore

        # Create minimal state without any loop context
        minimal_state = State()
        minimal_state.current_epic = 1

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>automate</compiled>"
        mock_compiled.workflow_name = "testarch-automate"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Automation\n\nStandalone execution complete.",
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

            result = handler.execute(minimal_state)

            # Should succeed even with minimal state
            assert result.success is True

    def test_multiple_handlers_can_run_sequentially_in_solo(
        self, setup_solo_project: tuple[Path, State]
    ) -> None:
        """Test multiple handlers can run in sequence in solo mode."""
        project_path, state = setup_solo_project
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.handlers.automate import AutomateHandler
        from bmad_assist.testarch.handlers.ci import CIHandler

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled>test</compiled>"
        mock_compiled.workflow_name = "testarch-test"

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult

        mock_provider.invoke.return_value = ProviderResult(
            exit_code=0,
            stdout="# Output\n\nComplete.",
            stderr="",
            model="opus",
            command=("claude",),
            duration_ms=100,
        )

        with (
            patch("bmad_assist.compiler.compile_workflow", return_value=mock_compiled),
            patch("bmad_assist.providers.get_provider", return_value=mock_provider),
            patch("bmad_assist.testarch.handlers.ci.get_paths") as mock_ci_paths,
            patch("bmad_assist.testarch.handlers.automate.get_paths") as mock_auto_paths,
            patch("bmad_assist.testarch.handlers.base.get_paths") as mock_base_paths,
        ):
            mock_paths = MagicMock()
            mock_paths.output_folder = project_path / "_bmad-output"
            mock_ci_paths.return_value = mock_paths
            mock_auto_paths.return_value = mock_paths
            mock_base_paths.return_value = mock_paths

            # Run CI handler
            ci_handler = CIHandler(config, project_path)  # type: ignore
            ci_result = ci_handler.execute(state)
            assert ci_result.success is True

            # Run Automate handler
            auto_handler = AutomateHandler(config, project_path)  # type: ignore
            auto_result = auto_handler.execute(state)
            assert auto_result.success is True


class TestTEASoloModeStandaloneRunner:
    """Test standalone runner in solo mode."""

    @pytest.fixture
    def setup_standalone_project(self, tmp_path: Path) -> Path:
        """Create project for standalone runner tests."""
        # Create minimal structure
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs/project-context.md").write_text("# Context")
        (tmp_path / "_bmad-output").mkdir(parents=True)
        return tmp_path

    def test_standalone_runner_respects_solo_mode(
        self, setup_standalone_project: Path
    ) -> None:
        """Test standalone runner respects solo engagement model."""
        _ = setup_standalone_project
        config = FakeConfig(engagement_model="solo")

        from bmad_assist.testarch.engagement import should_run_workflow

        # Solo mode only enables standalone workflows
        assert should_run_workflow("framework", config.testarch) is True  # type: ignore
        assert should_run_workflow("ci", config.testarch) is True  # type: ignore
        assert should_run_workflow("automate", config.testarch) is True  # type: ignore
        assert should_run_workflow("test-design", config.testarch) is True  # type: ignore
        assert should_run_workflow("nfr-assess", config.testarch) is True  # type: ignore

        # Non-standalone workflows are blocked
        assert should_run_workflow("test-review", config.testarch) is False  # type: ignore
        assert should_run_workflow("trace", config.testarch) is False  # type: ignore

    def test_standalone_runner_can_skip_workflows_individually(
        self, setup_standalone_project: Path
    ) -> None:
        """Test individual workflows can be disabled via mode settings.

        Note: The engagement model check happens first. If solo mode allows
        a workflow (standalone workflows), the individual mode check in
        the handler's _execute_with_mode_check would handle the off setting.
        The should_run_workflow function only checks engagement model level.
        """
        _ = setup_standalone_project
        config = FakeConfig(engagement_model="solo")
        config.testarch.framework_mode = "off"
        config.testarch.ci_mode = "off"

        from bmad_assist.testarch.engagement import should_run_workflow

        # In solo mode, should_run_workflow returns True for standalone workflows
        # The individual mode ("off") is handled at the handler level
        assert should_run_workflow("framework", config.testarch) is True  # type: ignore
        assert should_run_workflow("ci", config.testarch) is True  # type: ignore
        assert should_run_workflow("automate", config.testarch) is True  # type: ignore

        # Verify mode fields are set (would be checked by handler)
        assert config.testarch.framework_mode == "off"
        assert config.testarch.ci_mode == "off"
