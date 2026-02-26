"""Tests for CIHandler (Story 25.9).

These tests verify:
- AC #1: Phase.TEA_CI in state machine (covered by test_state_model.py)
- AC #2: CIHandler class creation
- AC #3: CI platform detection logic
- AC #4: Workflow invocation
- AC #5: ci_ran_in_epic tracking
- AC #6: Handler registered in dispatch
- AC #7: Skip when mode=off
- AC #8: Skip when CI already exists
- AC #9: Run when mode=on
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import Phase, State

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock Config with testarch settings."""
    config = MagicMock()
    config.testarch = MagicMock()
    config.testarch.ci_mode = "auto"
    config.testarch.engagement_model = "auto"  # Allow workflows to run
    config.benchmarking = MagicMock()
    config.benchmarking.enabled = False

    # Provider config
    config.providers = MagicMock()
    config.providers.master = MagicMock()
    config.providers.master.provider = "mock-provider"
    config.providers.master.model = "mock-model"
    config.timeout = 30
    return config


@pytest.fixture
def handler(mock_config: MagicMock, tmp_path: Path) -> "CIHandler":
    """Create CIHandler instance with mock config."""
    from bmad_assist.testarch.handlers import CIHandler

    return CIHandler(mock_config, tmp_path)


@pytest.fixture
def state_epic_25() -> State:
    """State at epic 25."""
    return State(
        current_epic=25,
        current_story=None,
        current_phase=Phase.TEA_CI,
    )


@pytest.fixture
def state_testarch_epic() -> State:
    """State at testarch epic."""
    return State(
        current_epic="testarch",
        current_story=None,
        current_phase=Phase.TEA_CI,
    )


# =============================================================================
# AC #2: CIHandler class creation
# =============================================================================


class TestCIHandlerCreation:
    """Test CIHandler class creation."""

    def test_handler_created_successfully(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """CIHandler can be instantiated."""
        from bmad_assist.testarch.handlers import CIHandler

        handler = CIHandler(mock_config, tmp_path)
        assert handler is not None
        assert handler.config is mock_config
        assert handler.project_path == tmp_path

    def test_handler_phase_name(self, handler: "CIHandler") -> None:
        """CIHandler.phase_name returns 'tea_ci'."""
        assert handler.phase_name == "tea_ci"


# =============================================================================
# AC #6: Handler registered in dispatch
# =============================================================================


class TestHandlerRegistration:
    """Test CIHandler registered in dispatch."""

    def test_tea_ci_phase_in_workflow_handlers(self) -> None:
        """Phase.TEA_CI has handler in WORKFLOW_HANDLERS."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        assert Phase.TEA_CI in WORKFLOW_HANDLERS

    def test_tea_ci_stub_handler_is_callable(self) -> None:
        """TEA_CI stub handler is callable."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        handler = WORKFLOW_HANDLERS[Phase.TEA_CI]
        assert callable(handler)


# =============================================================================
# AC #7: Skip when mode=off
# =============================================================================


class TestModeOff:
    """Test CI skipped when mode=off."""

    def test_execute_skips_when_mode_off(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips with mode=off."""
        from bmad_assist.testarch.handlers import CIHandler

        mock_config.testarch.ci_mode = "off"
        handler = CIHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("ci_mode") == "off"
        assert result.outputs.get("reason") == "ci_mode=off"


class TestModeNotConfigured:
    """Test CI skipped when testarch not configured."""

    def test_execute_skips_when_not_configured(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips when testarch is None."""
        from bmad_assist.testarch.handlers import CIHandler

        mock_config.testarch = None
        handler = CIHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("ci_mode") == "not_configured"


# =============================================================================
# AC #3: CI platform detection logic
# =============================================================================


class TestCIDetection:
    """Test _detect_existing_ci method."""

    def test_detects_github_actions(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Detects GitHub Actions workflow."""
        from bmad_assist.testarch.handlers import CIHandler

        github_dir = tmp_path / ".github" / "workflows"
        github_dir.mkdir(parents=True)
        (github_dir / "ci.yml").write_text("name: CI")
        handler = CIHandler(mock_config, tmp_path)

        result = handler._detect_existing_ci()
        assert result == "github"

    def test_detects_gitlab_ci(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Detects GitLab CI."""
        from bmad_assist.testarch.handlers import CIHandler

        (tmp_path / ".gitlab-ci.yml").write_text("stages: []")
        handler = CIHandler(mock_config, tmp_path)

        result = handler._detect_existing_ci()
        assert result == "gitlab"

    def test_detects_circleci(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Detects CircleCI."""
        from bmad_assist.testarch.handlers import CIHandler

        circleci_dir = tmp_path / ".circleci"
        circleci_dir.mkdir()
        (circleci_dir / "config.yml").write_text("version: 2.1")
        handler = CIHandler(mock_config, tmp_path)

        result = handler._detect_existing_ci()
        assert result == "circleci"

    def test_detects_azure_pipelines(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Detects Azure Pipelines."""
        from bmad_assist.testarch.handlers import CIHandler

        (tmp_path / "azure-pipelines.yml").write_text("trigger: []")
        handler = CIHandler(mock_config, tmp_path)

        result = handler._detect_existing_ci()
        assert result == "azure"

    def test_detects_jenkins(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Detects Jenkinsfile."""
        from bmad_assist.testarch.handlers import CIHandler

        (tmp_path / "Jenkinsfile").write_text("pipeline {}")
        handler = CIHandler(mock_config, tmp_path)

        result = handler._detect_existing_ci()
        assert result == "jenkins"

    def test_returns_none_when_no_ci(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns None when no CI config found."""
        from bmad_assist.testarch.handlers import CIHandler

        handler = CIHandler(mock_config, tmp_path)

        result = handler._detect_existing_ci()
        assert result is None

    def test_github_takes_priority(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """GitHub Actions detection takes priority."""
        from bmad_assist.testarch.handlers import CIHandler

        github_dir = tmp_path / ".github" / "workflows"
        github_dir.mkdir(parents=True)
        (github_dir / "ci.yml").write_text("name: CI")
        (tmp_path / ".gitlab-ci.yml").write_text("stages: []")
        handler = CIHandler(mock_config, tmp_path)

        result = handler._detect_existing_ci()
        assert result == "github"


# =============================================================================
# AC #8: Skip when CI already exists
# =============================================================================


class TestSkipWhenExists:
    """Test skipping when CI already exists."""

    def test_execute_skips_when_github_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips when GitHub Actions exists."""
        from bmad_assist.testarch.handlers import CIHandler

        github_dir = tmp_path / ".github" / "workflows"
        github_dir.mkdir(parents=True)
        (github_dir / "ci.yml").write_text("name: CI")
        mock_config.testarch.ci_mode = "auto"
        handler = CIHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("ci_platform") == "github"
        assert "already exists" in result.outputs.get("reason", "").lower()

    def test_execute_skips_when_gitlab_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips when GitLab CI exists."""
        from bmad_assist.testarch.handlers import CIHandler

        (tmp_path / ".gitlab-ci.yml").write_text("stages: []")
        mock_config.testarch.ci_mode = "auto"
        handler = CIHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("ci_platform") == "gitlab"


# =============================================================================
# AC #9: Run when mode=on
# =============================================================================


class TestModeOn:
    """Test CI runs in mode=on when no existing CI."""

    def test_execute_invokes_workflow_when_mode_on(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() invokes workflow when mode=on and no existing CI."""
        from bmad_assist.testarch.handlers import CIHandler

        mock_config.testarch.ci_mode = "on"
        handler = CIHandler(mock_config, tmp_path)

        with patch.object(handler, "_invoke_ci_workflow") as mock_invoke:
            mock_invoke.return_value = PhaseResult.ok(
                {"response": "ok", "ci_platform": "github"}
            )

            result = handler.execute(state_epic_25)

        mock_invoke.assert_called_once()
        assert result.success is True

    def test_execute_skips_even_mode_on_when_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() still skips when mode=on but CI exists."""
        from bmad_assist.testarch.handlers import CIHandler

        github_dir = tmp_path / ".github" / "workflows"
        github_dir.mkdir(parents=True)
        (github_dir / "ci.yml").write_text("name: CI")
        mock_config.testarch.ci_mode = "on"
        handler = CIHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "already exists" in result.outputs.get("reason", "").lower()


# =============================================================================
# AC #4: Workflow invocation
# =============================================================================


class TestWorkflowInvocation:
    """Test _invoke_ci_workflow method."""

    def test_invoke_returns_error_when_paths_not_initialized(
        self, handler: "CIHandler", state_epic_25: State
    ) -> None:
        """Returns error PhaseResult when paths singleton not initialized."""
        result = handler._invoke_ci_workflow(state_epic_25)

        assert result.success is False
        assert "Paths not initialized" in result.error


# =============================================================================
# AC #5: ci_ran_in_epic tracking
# =============================================================================


class TestEpicTracking:
    """Test ci_ran_in_epic state tracking."""

    def test_ci_ran_in_epic_set_on_success(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """ci_ran_in_epic is set to True on successful workflow."""
        from bmad_assist.testarch.handlers import CIHandler

        mock_config.testarch.ci_mode = "on"
        handler = CIHandler(mock_config, tmp_path)

        assert state_epic_25.ci_ran_in_epic is False

        # Mock get_paths and _invoke_generic_workflow so the full path
        # through _invoke_ci_workflow runs including state update
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with (
            patch("bmad_assist.testarch.handlers.ci.get_paths", return_value=mock_paths),
            patch.object(handler, "_invoke_generic_workflow") as mock_invoke,
        ):
            mock_invoke.return_value = PhaseResult.ok({"response": "ok"})

            handler.execute(state_epic_25)

        assert state_epic_25.ci_ran_in_epic is True

    def test_ci_ran_in_epic_not_set_on_skip(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """ci_ran_in_epic is NOT set when CI is skipped."""
        from bmad_assist.testarch.handlers import CIHandler

        mock_config.testarch.ci_mode = "off"
        handler = CIHandler(mock_config, tmp_path)

        handler.execute(state_epic_25)

        assert state_epic_25.ci_ran_in_epic is False

    def test_ci_ran_in_epic_not_set_when_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """ci_ran_in_epic is NOT set when CI already exists."""
        from bmad_assist.testarch.handlers import CIHandler

        github_dir = tmp_path / ".github" / "workflows"
        github_dir.mkdir(parents=True)
        (github_dir / "ci.yml").write_text("name: CI")
        mock_config.testarch.ci_mode = "auto"
        handler = CIHandler(mock_config, tmp_path)

        handler.execute(state_epic_25)

        assert state_epic_25.ci_ran_in_epic is False


# =============================================================================
# Mode checking
# =============================================================================


class TestModeChecking:
    """Test _check_mode helper with ci_mode."""

    def test_check_ci_mode_off(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('off', False) for mode=off."""
        from bmad_assist.testarch.handlers import CIHandler

        mock_config.testarch.ci_mode = "off"
        handler = CIHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "ci_mode")
        assert mode == "off"
        assert should_check is False

    def test_check_ci_mode_on(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('on', True) for mode=on."""
        from bmad_assist.testarch.handlers import CIHandler

        mock_config.testarch.ci_mode = "on"
        handler = CIHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "ci_mode")
        assert mode == "on"
        assert should_check is True

    def test_check_ci_mode_auto(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('auto', True) for mode=auto."""
        from bmad_assist.testarch.handlers import CIHandler

        mock_config.testarch.ci_mode = "auto"
        handler = CIHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "ci_mode")
        assert mode == "auto"
        assert should_check is True


# =============================================================================
# CI platform extraction
# =============================================================================


class TestCIPlatformExtraction:
    """Test _extract_ci_platform method."""

    def test_extract_github(self, handler: "CIHandler") -> None:
        """Extracts 'github' from output."""
        output = "Setting up GitHub Actions workflow"
        result = handler._extract_ci_platform(output)
        assert result == "github"

    def test_extract_gitlab(self, handler: "CIHandler") -> None:
        """Extracts 'gitlab' from output."""
        output = "Initializing GitLab CI pipeline"
        result = handler._extract_ci_platform(output)
        assert result == "gitlab"

    def test_extract_circleci(self, handler: "CIHandler") -> None:
        """Extracts 'circleci' from output."""
        output = "Creating CircleCI configuration"
        result = handler._extract_ci_platform(output)
        assert result == "circleci"

    def test_extract_azure(self, handler: "CIHandler") -> None:
        """Extracts 'azure' from output."""
        output = "Setting up Azure Pipelines"
        result = handler._extract_ci_platform(output)
        assert result == "azure"

    def test_extract_jenkins(self, handler: "CIHandler") -> None:
        """Extracts 'jenkins' from output."""
        output = "Creating Jenkins pipeline"
        result = handler._extract_ci_platform(output)
        assert result == "jenkins"

    def test_extract_none_when_not_found(self, handler: "CIHandler") -> None:
        """Returns None when no CI platform in output."""
        output = "Some generic build setup"
        result = handler._extract_ci_platform(output)
        assert result is None


# =============================================================================
# Context building
# =============================================================================


class TestContextBuilding:
    """Test build_context method."""

    def test_build_context_returns_dict(
        self, handler: "CIHandler", state_epic_25: State
    ) -> None:
        """build_context returns a dictionary."""
        context = handler.build_context(state_epic_25)
        assert isinstance(context, dict)

    def test_build_context_contains_epic_num(
        self, handler: "CIHandler", state_epic_25: State
    ) -> None:
        """build_context includes epic_num."""
        context = handler.build_context(state_epic_25)
        # _build_common_context includes epic_num from state.current_epic
        assert "epic_num" in context
        assert context["epic_num"] == 25
