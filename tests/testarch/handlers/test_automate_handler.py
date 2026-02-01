"""Tests for AutomateHandler (Story 25.11).

These tests verify:
- AC #1: Phase.TEA_AUTOMATE in state machine (covered by test_state_model.py)
- AC #2: AutomateHandler class creation
- AC #3: Automation detection logic
- AC #4: Workflow invocation
- AC #5: automate_ran_in_epic tracking
- AC #6: Handler registered in dispatch
- AC #7: Skip when mode=off (default)
- AC #8: Skip when automation already exists
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
    config.testarch.engagement_model = "auto"  # Allow workflows to run
    config.testarch.automate_mode = "off"  # Default is off
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
def handler(mock_config: MagicMock, tmp_path: Path) -> "AutomateHandler":
    """Create AutomateHandler instance with mock config."""
    from bmad_assist.testarch.handlers import AutomateHandler

    return AutomateHandler(mock_config, tmp_path)


@pytest.fixture
def state_epic_25() -> State:
    """State at epic 25."""
    return State(
        current_epic=25,
        current_story=None,
        current_phase=Phase.TEA_AUTOMATE,
    )


@pytest.fixture
def state_testarch_epic() -> State:
    """State at testarch epic."""
    return State(
        current_epic="testarch",
        current_story=None,
        current_phase=Phase.TEA_AUTOMATE,
    )


# =============================================================================
# AC #2: AutomateHandler class creation
# =============================================================================


class TestAutomateHandlerCreation:
    """Test AutomateHandler class creation."""

    def test_handler_created_successfully(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """AutomateHandler can be instantiated."""
        from bmad_assist.testarch.handlers import AutomateHandler

        handler = AutomateHandler(mock_config, tmp_path)
        assert handler is not None
        assert handler.config is mock_config
        assert handler.project_path == tmp_path

    def test_handler_phase_name(self, handler: "AutomateHandler") -> None:
        """AutomateHandler.phase_name returns 'tea_automate'."""
        assert handler.phase_name == "tea_automate"


# =============================================================================
# AC #6: Handler registered in dispatch
# =============================================================================


class TestHandlerRegistration:
    """Test AutomateHandler registered in dispatch."""

    def test_tea_automate_phase_in_workflow_handlers(self) -> None:
        """Phase.TEA_AUTOMATE has handler in WORKFLOW_HANDLERS."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        assert Phase.TEA_AUTOMATE in WORKFLOW_HANDLERS

    def test_tea_automate_stub_handler_is_callable(self) -> None:
        """TEA_AUTOMATE stub handler is callable."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        handler = WORKFLOW_HANDLERS[Phase.TEA_AUTOMATE]
        assert callable(handler)


# =============================================================================
# AC #7: Skip when mode=off (default)
# =============================================================================


class TestModeOff:
    """Test automation skipped when mode=off (default)."""

    def test_execute_skips_when_mode_off(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips with mode=off."""
        from bmad_assist.testarch.handlers import AutomateHandler

        mock_config.testarch.automate_mode = "off"
        handler = AutomateHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("automate_mode") == "off"
        assert result.outputs.get("reason") == "automate_mode=off"


class TestModeNotConfigured:
    """Test automation skipped when testarch not configured."""

    def test_execute_skips_when_not_configured(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips when testarch is None."""
        from bmad_assist.testarch.handlers import AutomateHandler

        mock_config.testarch = None
        handler = AutomateHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("automate_mode") == "not_configured"


# =============================================================================
# AC #3: Automation detection logic
# =============================================================================


class TestAutomationDetection:
    """Test _detect_existing_automation method."""

    def test_detects_automation_summary_in_subdirectory(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Detects automation-summary.md in automation/ subdirectory."""
        from bmad_assist.testarch.handlers import AutomateHandler

        # Create output folder with automation subdirectory
        automation_dir = tmp_path / "automation"
        automation_dir.mkdir(parents=True)
        (automation_dir / "automation-summary.md").write_text("# Automation Summary")

        mock_config.testarch.automate_mode = "on"
        handler = AutomateHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with patch("bmad_assist.testarch.handlers.automate.get_paths", return_value=mock_paths):
            exists, path = handler._detect_existing_automation()

        assert exists is True
        assert path is not None
        assert "automation-summary.md" in str(path)

    def test_returns_false_when_no_automation(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Returns (False, None) when no automation summary found."""
        from bmad_assist.testarch.handlers import AutomateHandler

        handler = AutomateHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with patch("bmad_assist.testarch.handlers.automate.get_paths", return_value=mock_paths):
            exists, path = handler._detect_existing_automation()

        assert exists is False
        assert path is None

    def test_returns_false_when_paths_not_initialized(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Returns (False, None) when paths not initialized."""
        from bmad_assist.testarch.handlers import AutomateHandler

        handler = AutomateHandler(mock_config, tmp_path)

        # Don't mock get_paths - let it fail
        exists, path = handler._detect_existing_automation()

        assert exists is False
        assert path is None


# =============================================================================
# AC #8: Skip when automation already exists
# =============================================================================


class TestSkipWhenExists:
    """Test skipping when automation already exists."""

    def test_execute_skips_when_automation_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips when automation summary exists."""
        from bmad_assist.testarch.handlers import AutomateHandler

        # Create output folder with automation subdirectory
        automation_dir = tmp_path / "automation"
        automation_dir.mkdir(parents=True)
        (automation_dir / "automation-summary.md").write_text("# Automation Summary")

        mock_config.testarch.automate_mode = "on"
        handler = AutomateHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with patch("bmad_assist.testarch.handlers.automate.get_paths", return_value=mock_paths):
            result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "already exists" in result.outputs.get("reason", "")


# =============================================================================
# AC #9: Run when mode=on
# =============================================================================


class TestModeOn:
    """Test automation runs in mode=on when no existing automation."""

    def test_execute_invokes_workflow_when_mode_on(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() invokes workflow when mode=on and no existing automation."""
        from bmad_assist.testarch.handlers import AutomateHandler

        mock_config.testarch.automate_mode = "on"
        handler = AutomateHandler(mock_config, tmp_path)

        with patch.object(handler, "_invoke_automate_workflow") as mock_invoke:
            mock_invoke.return_value = PhaseResult.ok(
                {"response": "ok", "automation_status": "PASS"}
            )

            result = handler.execute(state_epic_25)

        mock_invoke.assert_called_once()
        assert result.success is True

    def test_execute_skips_even_mode_on_when_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() still skips when mode=on but automation exists."""
        from bmad_assist.testarch.handlers import AutomateHandler

        # Create output folder with automation subdirectory
        automation_dir = tmp_path / "automation"
        automation_dir.mkdir(parents=True)
        (automation_dir / "automation-summary.md").write_text("# Automation Summary")

        mock_config.testarch.automate_mode = "on"
        handler = AutomateHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with patch("bmad_assist.testarch.handlers.automate.get_paths", return_value=mock_paths):
            result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "already exists" in result.outputs.get("reason", "")


# =============================================================================
# AC #4: Workflow invocation
# =============================================================================


class TestWorkflowInvocation:
    """Test _invoke_automate_workflow method."""

    def test_invoke_returns_error_when_paths_not_initialized(
        self, handler: "AutomateHandler", state_epic_25: State
    ) -> None:
        """Returns error PhaseResult when paths singleton not initialized."""
        result = handler._invoke_automate_workflow(state_epic_25)

        assert result.success is False
        assert "Paths not initialized" in result.error

    def test_invoke_calls_generic_workflow(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """_invoke_automate_workflow uses _invoke_generic_workflow."""
        from bmad_assist.testarch.handlers import AutomateHandler

        mock_config.testarch.automate_mode = "on"
        handler = AutomateHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with (
            patch("bmad_assist.testarch.handlers.automate.get_paths", return_value=mock_paths),
            patch.object(handler, "_invoke_generic_workflow") as mock_invoke,
        ):
            mock_invoke.return_value = PhaseResult.ok(
                {"response": "ok", "automation_status": "PASS"}
            )

            result = handler._invoke_automate_workflow(state_epic_25)

        mock_invoke.assert_called_once()
        assert "testarch-automate" in str(mock_invoke.call_args)


# =============================================================================
# AC #5: automate_ran_in_epic tracking
# =============================================================================


class TestEpicTracking:
    """Test automate_ran_in_epic state tracking."""

    def test_automate_ran_in_epic_set_on_success(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """automate_ran_in_epic is set to True on successful workflow."""
        from bmad_assist.testarch.handlers import AutomateHandler

        mock_config.testarch.automate_mode = "on"
        handler = AutomateHandler(mock_config, tmp_path)

        assert state_epic_25.automate_ran_in_epic is False

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with (
            patch("bmad_assist.testarch.handlers.automate.get_paths", return_value=mock_paths),
            patch.object(handler, "_invoke_generic_workflow") as mock_invoke,
        ):
            mock_invoke.return_value = PhaseResult.ok({"response": "ok"})

            handler.execute(state_epic_25)

        assert state_epic_25.automate_ran_in_epic is True

    def test_automate_ran_in_epic_not_set_on_skip(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """automate_ran_in_epic is NOT set when automation is skipped."""
        from bmad_assist.testarch.handlers import AutomateHandler

        mock_config.testarch.automate_mode = "off"
        handler = AutomateHandler(mock_config, tmp_path)

        handler.execute(state_epic_25)

        assert state_epic_25.automate_ran_in_epic is False

    def test_automate_ran_in_epic_not_set_when_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """automate_ran_in_epic is NOT set when automation already exists."""
        from bmad_assist.testarch.handlers import AutomateHandler

        # Create output folder with automation subdirectory
        automation_dir = tmp_path / "automation"
        automation_dir.mkdir(parents=True)
        (automation_dir / "automation-summary.md").write_text("# Automation Summary")

        mock_config.testarch.automate_mode = "on"
        handler = AutomateHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with patch("bmad_assist.testarch.handlers.automate.get_paths", return_value=mock_paths):
            handler.execute(state_epic_25)

        assert state_epic_25.automate_ran_in_epic is False


# =============================================================================
# Mode checking
# =============================================================================


class TestModeChecking:
    """Test _check_mode helper with automate_mode."""

    def test_check_automate_mode_off(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('off', False) for mode=off."""
        from bmad_assist.testarch.handlers import AutomateHandler

        mock_config.testarch.automate_mode = "off"
        handler = AutomateHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "automate_mode")
        assert mode == "off"
        assert should_check is False

    def test_check_automate_mode_on(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('on', True) for mode=on."""
        from bmad_assist.testarch.handlers import AutomateHandler

        mock_config.testarch.automate_mode = "on"
        handler = AutomateHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "automate_mode")
        assert mode == "on"
        assert should_check is True

    def test_check_automate_mode_auto(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('auto', True) for mode=auto."""
        from bmad_assist.testarch.handlers import AutomateHandler

        mock_config.testarch.automate_mode = "auto"
        handler = AutomateHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "automate_mode")
        assert mode == "auto"
        assert should_check is True


# =============================================================================
# Extraction function delegation
# =============================================================================


class TestExtractionDelegation:
    """Test extraction function delegation."""

    def test_extract_automation_outputs_returns_dict(
        self, handler: "AutomateHandler"
    ) -> None:
        """_extract_automation_outputs returns dict with expected keys."""
        output = "Automation Status: PASS\nTotal Tests: 42"
        result = handler._extract_automation_outputs(output)

        assert isinstance(result, dict)
        assert "automation_status" in result
        assert "test_count" in result

    def test_extract_automation_outputs_passes_values(
        self, handler: "AutomateHandler"
    ) -> None:
        """_extract_automation_outputs extracts correct values."""
        output = "Automation Status: PARTIAL\nTotal Tests: 15"
        result = handler._extract_automation_outputs(output)

        assert result["automation_status"] == "PARTIAL"
        assert result["test_count"] == 15

    def test_extract_automation_outputs_handles_empty(
        self, handler: "AutomateHandler"
    ) -> None:
        """_extract_automation_outputs handles empty output."""
        result = handler._extract_automation_outputs("")

        assert result["automation_status"] is None
        assert result["test_count"] is None


# =============================================================================
# Context building
# =============================================================================


class TestContextBuilding:
    """Test build_context method."""

    def test_build_context_returns_dict(
        self, handler: "AutomateHandler", state_epic_25: State
    ) -> None:
        """build_context returns a dictionary."""
        context = handler.build_context(state_epic_25)
        assert isinstance(context, dict)

    def test_build_context_contains_epic_num(
        self, handler: "AutomateHandler", state_epic_25: State
    ) -> None:
        """build_context includes epic_num."""
        context = handler.build_context(state_epic_25)
        # _build_common_context includes epic_num from state.current_epic
        assert "epic_num" in context
        assert context["epic_num"] == 25
