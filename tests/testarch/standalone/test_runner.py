"""Tests for StandaloneRunner class.

Story 25.13: TEA Standalone Runner & CLI.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.testarch.standalone.runner import StandaloneRunner

if TYPE_CHECKING:
    pass


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with minimal structure."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def runner(tmp_project: Path) -> StandaloneRunner:
    """Create a StandaloneRunner with temporary project."""
    return StandaloneRunner(project_root=tmp_project)


@pytest.fixture
def runner_with_output(tmp_project: Path, tmp_path: Path) -> StandaloneRunner:
    """Create a StandaloneRunner with custom output directory."""
    output_dir = tmp_path / "custom-output"
    return StandaloneRunner(
        project_root=tmp_project,
        output_dir=output_dir,
    )


@pytest.fixture
def mock_phase_result_ok() -> MagicMock:
    """Create a mock successful PhaseResult."""
    result = MagicMock()
    result.success = True
    result.outputs = {"response": "# Framework Setup\n\nContent here..."}
    result.error = None
    return result


@pytest.fixture
def mock_phase_result_skip() -> MagicMock:
    """Create a mock skipped PhaseResult."""
    result = MagicMock()
    result.success = True
    result.outputs = {"skipped": True, "reason": "framework already exists"}
    result.error = None
    return result


@pytest.fixture
def mock_phase_result_fail() -> MagicMock:
    """Create a mock failed PhaseResult."""
    result = MagicMock()
    result.success = False
    result.outputs = {}
    result.error = "Provider timeout"
    return result


# =============================================================================
# Initialization Tests (3 tests)
# =============================================================================


class TestStandaloneRunnerInit:
    """Tests for StandaloneRunner initialization."""

    def test_init_default_output_dir(self, tmp_project: Path) -> None:
        """Test default output directory is set correctly."""
        runner = StandaloneRunner(project_root=tmp_project)

        assert runner.project_root == tmp_project.resolve()
        expected_output = tmp_project / "_bmad-output" / "standalone"
        assert runner.output_dir == expected_output.resolve()
        assert runner.evidence_output is None
        assert runner.provider_name == "claude-subprocess"

    def test_init_custom_output_dir(self, tmp_project: Path, tmp_path: Path) -> None:
        """Test custom output directory is preserved."""
        custom_output = tmp_path / "my-output"
        runner = StandaloneRunner(
            project_root=tmp_project,
            output_dir=custom_output,
        )

        assert runner.output_dir == custom_output.resolve()

    def test_init_custom_provider(self, tmp_project: Path) -> None:
        """Test custom provider name is set."""
        runner = StandaloneRunner(
            project_root=tmp_project,
            provider_name="gemini",
        )

        assert runner.provider_name == "gemini"


# =============================================================================
# Config Creation Tests (3 tests)
# =============================================================================


class TestConfigCreation:
    """Tests for _create_standalone_config method."""

    def test_create_config_no_existing_file(self, runner: StandaloneRunner) -> None:
        """Test config creation when no bmad-assist.yaml exists."""
        config = runner._create_standalone_config()

        # Should have minimal config with defaults
        assert config.providers.master.provider == "claude-subprocess"
        assert config.providers.master.model == "opus"
        assert config.testarch is not None
        assert config.testarch.engagement_model == "solo"

    def test_create_config_loads_existing(self, tmp_project: Path) -> None:
        """Test config loading when bmad-assist.yaml exists."""
        # Create a config file
        config_path = tmp_project / "bmad-assist.yaml"
        config_path.write_text("""
providers:
  master:
    provider: gemini
    model: gemini-2.0-flash
testarch:
  engagement_model: integrated
""")

        runner = StandaloneRunner(project_root=tmp_project)
        config = runner._create_standalone_config()

        # Should load existing config
        assert config.providers.master.provider == "gemini"
        assert config.providers.master.model == "gemini-2.0-flash"

    def test_create_config_with_custom_provider(self, tmp_project: Path) -> None:
        """Test config creation uses custom provider_name."""
        runner = StandaloneRunner(
            project_root=tmp_project,
            provider_name="codex",
        )
        config = runner._create_standalone_config()

        assert config.providers.master.provider == "codex"


# =============================================================================
# State Creation Tests (2 tests)
# =============================================================================


class TestStateCreation:
    """Tests for _create_standalone_state method."""

    def test_create_state_defaults(self, runner: StandaloneRunner) -> None:
        """Test state creation with proper defaults."""
        state = runner._create_standalone_state()

        assert state.current_epic == "standalone"
        assert state.current_story is None
        assert state.current_phase is None
        assert state.framework_ran_in_epic is False
        assert state.ci_ran_in_epic is False
        assert state.test_design_ran_in_epic is False
        assert state.automate_ran_in_epic is False
        assert state.nfr_assess_ran_in_epic is False
        assert state.epic_setup_complete is False

    def test_state_not_persisted(self, runner: StandaloneRunner) -> None:
        """Test that state is not persisted to disk."""
        state = runner._create_standalone_state()

        # State file should not exist
        state_path = runner.project_root / ".bmad-assist" / "state.yaml"
        assert not state_path.exists()


# =============================================================================
# Paths Initialization Tests (3 tests)
# =============================================================================


class TestPathsInitialization:
    """Tests for _standalone_paths_context method."""

    def test_paths_context_creates_docs_dir(self, tmp_path: Path) -> None:
        """Test that paths context creates docs directory if missing."""
        project = tmp_path / "new-project"
        project.mkdir()
        # Note: docs/ not created yet

        runner = StandaloneRunner(project_root=project)

        with runner._standalone_paths_context():
            docs_dir = project / "docs"
            assert docs_dir.exists()

    def test_paths_context_initializes_paths(self, runner: StandaloneRunner) -> None:
        """Test that paths are properly initialized in context."""
        from bmad_assist.core.paths import get_paths

        with runner._standalone_paths_context():
            paths = get_paths()
            assert paths.project_root == runner.project_root
            assert str(runner.output_dir) in str(paths.output_folder)

    def test_paths_context_resets_on_exit(self, runner: StandaloneRunner) -> None:
        """Test that paths are reset after context exits."""
        # Paths should be None before context
        # (assuming no other test left it initialized)

        with runner._standalone_paths_context():
            pass

        # After context, global instance should be reset
        from bmad_assist.core.paths import _paths_instance as after_instance
        assert after_instance is None


# =============================================================================
# Handler Execution Tests (5 tests)
# =============================================================================


class TestHandlerExecution:
    """Tests for _execute_handler method."""

    def test_execute_handler_success(
        self,
        runner: StandaloneRunner,
        mock_phase_result_ok: MagicMock,
    ) -> None:
        """Test successful handler execution."""
        mock_handler = MagicMock()
        mock_handler.return_value.execute.return_value = mock_phase_result_ok

        with patch.object(runner, "_standalone_paths_context"), patch(
            "bmad_assist.testarch.standalone.runner.StandaloneRunner._save_standalone_report"
        ) as mock_save:
            mock_save.return_value = Path("/tmp/report.md")

            result = runner._execute_handler(mock_handler, "framework")

        assert result["success"] is True
        assert result["output_path"] == Path("/tmp/report.md")
        assert result["error"] is None

    def test_execute_handler_skip(
        self,
        runner: StandaloneRunner,
        mock_phase_result_skip: MagicMock,
    ) -> None:
        """Test handler execution that results in skip."""
        mock_handler = MagicMock()
        mock_handler.return_value.execute.return_value = mock_phase_result_skip

        with patch.object(runner, "_standalone_paths_context"):
            result = runner._execute_handler(mock_handler, "framework")

        assert result["success"] is True
        assert result["output_path"] is None
        assert result["metrics"]["skipped"] is True

    def test_execute_handler_failure(
        self,
        runner: StandaloneRunner,
        mock_phase_result_fail: MagicMock,
    ) -> None:
        """Test handler execution that fails."""
        mock_handler = MagicMock()
        mock_handler.return_value.execute.return_value = mock_phase_result_fail

        with patch.object(runner, "_standalone_paths_context"):
            result = runner._execute_handler(mock_handler, "framework")

        assert result["success"] is False
        assert result["error"] == "Provider timeout"
        assert result["output_path"] is None

    def test_execute_handler_exception(self, runner: StandaloneRunner) -> None:
        """Test handler execution that raises exception."""
        mock_handler = MagicMock()
        mock_handler.return_value.execute.side_effect = RuntimeError("Test error")

        with patch.object(runner, "_standalone_paths_context"):
            result = runner._execute_handler(mock_handler, "framework")

        assert result["success"] is False
        assert "Test error" in result["error"]
        assert result["metrics"] == {}

    def test_execute_handler_applies_extra_fields(
        self,
        runner: StandaloneRunner,
        mock_phase_result_ok: MagicMock,
    ) -> None:
        """Test that extra_state_fields are applied to state.

        Note: Only valid State fields can be set (Pydantic validation).
        This tests the mechanism using a real State field.
        """
        mock_handler = MagicMock()
        mock_handler.return_value.execute.return_value = mock_phase_result_ok

        # Capture the state passed to handler
        captured_state = None

        def capture_execute(state: Any) -> Any:
            nonlocal captured_state
            captured_state = state
            return mock_phase_result_ok

        mock_handler.return_value.execute.side_effect = capture_execute

        with patch.object(runner, "_standalone_paths_context"), patch(
            "bmad_assist.testarch.standalone.runner.StandaloneRunner._save_standalone_report"
        ):
            # Use a valid State field (test_design_ran_in_epic is a bool field)
            runner._execute_handler(
                mock_handler,
                "test-design",
                extra_state_fields={"test_design_ran_in_epic": True},
            )

        # Verify the field was actually applied
        assert captured_state is not None
        assert captured_state.test_design_ran_in_epic is True


# =============================================================================
# Report Saving Tests (2 tests)
# =============================================================================


class TestReportSaving:
    """Tests for _save_standalone_report method."""

    def test_save_report_creates_directory(
        self, runner_with_output: StandaloneRunner
    ) -> None:
        """Test that report saving creates workflow directory."""
        content = "# Test Report\n\nContent here."

        path = runner_with_output._save_standalone_report("framework", content)

        assert path.exists()
        assert path.parent.name == "framework"
        assert "framework-" in path.name
        assert path.suffix == ".md"

    def test_save_report_atomic_write(
        self, runner_with_output: StandaloneRunner
    ) -> None:
        """Test that report saving uses atomic write pattern."""
        content = "# Test Report"

        path = runner_with_output._save_standalone_report("ci", content)

        # File should exist and contain content
        assert path.read_text() == content

        # No temp files should remain
        temp_files = list(path.parent.glob("ci_*.md"))
        assert len(temp_files) == 0


# =============================================================================
# Error Handling Tests (2 tests)
# =============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    def test_unsupported_workflow_raises_error(self, runner: StandaloneRunner) -> None:
        """Test that unsupported workflow raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            runner.run_workflow("invalid-workflow")

        assert "Unsupported workflow" in str(exc_info.value)
        assert "invalid-workflow" in str(exc_info.value)

    def test_handler_exception_captured(self, runner: StandaloneRunner) -> None:
        """Test that handler exceptions are captured in result."""

        class BrokenHandler:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("Initialization failed")

        with patch.object(runner, "_standalone_paths_context"):
            result = runner._execute_handler(BrokenHandler, "framework")

        assert result["success"] is False
        assert "Initialization failed" in result["error"]


# =============================================================================
# Workflow Method Tests (5 tests - one per workflow)
# =============================================================================


class TestWorkflowMethods:
    """Tests for individual workflow run methods."""

    @patch("bmad_assist.testarch.standalone.runner.StandaloneRunner._execute_handler")
    def test_run_framework(
        self,
        mock_execute: MagicMock,
        runner: StandaloneRunner,
    ) -> None:
        """Test run_framework calls correct handler."""
        mock_execute.return_value = {"success": True}

        result = runner.run_framework(mode="validate")

        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        # First positional arg is handler class
        from bmad_assist.testarch.handlers import FrameworkHandler
        assert call_args[0][0] == FrameworkHandler
        assert call_args[0][1] == "framework"

    @patch("bmad_assist.testarch.standalone.runner.StandaloneRunner._execute_handler")
    def test_run_ci_with_mode(
        self,
        mock_execute: MagicMock,
        runner: StandaloneRunner,
    ) -> None:
        """Test run_ci passes ci_mode via testarch_overrides."""
        mock_execute.return_value = {"success": True}

        runner.run_ci(ci_platform="github", mode="create")

        call_kwargs = mock_execute.call_args[1]
        # ci_mode should be "on" for create mode
        assert call_kwargs["testarch_overrides"]["ci_mode"] == "on"

    @patch("bmad_assist.testarch.standalone.runner.StandaloneRunner._execute_handler")
    def test_run_test_design_with_level(
        self,
        mock_execute: MagicMock,
        runner: StandaloneRunner,
    ) -> None:
        """Test run_test_design passes level via testarch_overrides."""
        mock_execute.return_value = {"success": True}

        runner.run_test_design(level="epic", mode="create")

        call_kwargs = mock_execute.call_args[1]
        # Level is passed via testarch config
        assert call_kwargs["testarch_overrides"]["test_design_level"] == "epic"
        assert call_kwargs["testarch_overrides"]["test_design_mode"] == "on"

    @patch("bmad_assist.testarch.standalone.runner.StandaloneRunner._execute_handler")
    def test_run_automate_with_mode(
        self,
        mock_execute: MagicMock,
        runner: StandaloneRunner,
    ) -> None:
        """Test run_automate passes automate_mode via testarch_overrides."""
        mock_execute.return_value = {"success": True}

        runner.run_automate(component="auth", mode="create")

        call_kwargs = mock_execute.call_args[1]
        # automate_mode should be "on" for standalone execution
        assert call_kwargs["testarch_overrides"]["automate_mode"] == "on"

    @patch("bmad_assist.testarch.standalone.runner.StandaloneRunner._execute_handler")
    def test_run_nfr_assess_with_mode(
        self,
        mock_execute: MagicMock,
        runner: StandaloneRunner,
    ) -> None:
        """Test run_nfr_assess passes nfr_assess_mode via testarch_overrides."""
        mock_execute.return_value = {"success": True}

        runner.run_nfr_assess(category="security", mode="create")

        call_kwargs = mock_execute.call_args[1]
        # nfr_assess_mode should be "on" for standalone execution
        assert call_kwargs["testarch_overrides"]["nfr_assess_mode"] == "on"


# =============================================================================
# Integration Tests
# =============================================================================


class TestRunWorkflowRouting:
    """Tests for run_workflow routing."""

    @patch("bmad_assist.testarch.standalone.runner.StandaloneRunner.run_framework")
    def test_run_workflow_routes_to_framework(
        self,
        mock_method: MagicMock,
        runner: StandaloneRunner,
    ) -> None:
        """Test run_workflow routes to run_framework."""
        runner.run_workflow("framework")
        mock_method.assert_called_once()

    @patch("bmad_assist.testarch.standalone.runner.StandaloneRunner.run_ci")
    def test_run_workflow_routes_to_ci(
        self,
        mock_method: MagicMock,
        runner: StandaloneRunner,
    ) -> None:
        """Test run_workflow routes to run_ci."""
        runner.run_workflow("ci")
        mock_method.assert_called_once()

    @patch("bmad_assist.testarch.standalone.runner.StandaloneRunner.run_test_design")
    def test_run_workflow_routes_to_test_design(
        self,
        mock_method: MagicMock,
        runner: StandaloneRunner,
    ) -> None:
        """Test run_workflow routes to run_test_design."""
        runner.run_workflow("test-design")
        mock_method.assert_called_once()

    def test_supported_workflows_constant(self, runner: StandaloneRunner) -> None:
        """Test SUPPORTED_WORKFLOWS matches engagement module."""
        from bmad_assist.testarch.engagement import STANDALONE_WORKFLOWS

        assert runner.SUPPORTED_WORKFLOWS == STANDALONE_WORKFLOWS
