"""Tests for FrameworkHandler (Story 25.9).

These tests verify:
- AC #1: Phase.TEA_FRAMEWORK in state machine (covered by test_state_model.py)
- AC #2: FrameworkHandler class creation
- AC #3: Framework detection logic
- AC #4: Workflow invocation
- AC #5: framework_ran_in_epic tracking
- AC #6: Handler registered in dispatch
- AC #7: Skip when mode=off
- AC #8: Skip when framework already exists
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
    config.testarch.framework_mode = "auto"
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
def handler(mock_config: MagicMock, tmp_path: Path) -> "FrameworkHandler":
    """Create FrameworkHandler instance with mock config."""
    from bmad_assist.testarch.handlers import FrameworkHandler

    return FrameworkHandler(mock_config, tmp_path)


@pytest.fixture
def state_epic_25() -> State:
    """State at epic 25."""
    return State(
        current_epic=25,
        current_story=None,
        current_phase=Phase.TEA_FRAMEWORK,
    )


@pytest.fixture
def state_testarch_epic() -> State:
    """State at testarch epic."""
    return State(
        current_epic="testarch",
        current_story=None,
        current_phase=Phase.TEA_FRAMEWORK,
    )


# =============================================================================
# AC #2: FrameworkHandler class creation
# =============================================================================


class TestFrameworkHandlerCreation:
    """Test FrameworkHandler class creation."""

    def test_handler_created_successfully(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """FrameworkHandler can be instantiated."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        handler = FrameworkHandler(mock_config, tmp_path)
        assert handler is not None
        assert handler.config is mock_config
        assert handler.project_path == tmp_path

    def test_handler_phase_name(self, handler: "FrameworkHandler") -> None:
        """FrameworkHandler.phase_name returns 'tea_framework'."""
        assert handler.phase_name == "tea_framework"


# =============================================================================
# AC #6: Handler registered in dispatch
# =============================================================================


class TestHandlerRegistration:
    """Test FrameworkHandler registered in dispatch."""

    def test_tea_framework_phase_in_workflow_handlers(self) -> None:
        """Phase.TEA_FRAMEWORK has handler in WORKFLOW_HANDLERS."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        assert Phase.TEA_FRAMEWORK in WORKFLOW_HANDLERS

    def test_tea_framework_stub_handler_is_callable(self) -> None:
        """TEA_FRAMEWORK stub handler is callable."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        handler = WORKFLOW_HANDLERS[Phase.TEA_FRAMEWORK]
        assert callable(handler)


# =============================================================================
# AC #7: Skip when mode=off
# =============================================================================


class TestModeOff:
    """Test framework skipped when mode=off."""

    def test_execute_skips_when_mode_off(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips with mode=off."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        mock_config.testarch.framework_mode = "off"
        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("framework_mode") == "off"
        assert result.outputs.get("reason") == "framework_mode=off"


class TestModeNotConfigured:
    """Test framework skipped when testarch not configured."""

    def test_execute_skips_when_not_configured(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips when testarch is None."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        mock_config.testarch = None
        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("framework_mode") == "not_configured"


# =============================================================================
# AC #3: Framework detection logic
# =============================================================================


class TestFrameworkDetection:
    """Test _detect_existing_framework method."""

    def test_detects_playwright_config_ts(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Detects playwright.config.ts."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        (tmp_path / "playwright.config.ts").write_text("export default {}")
        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler._detect_existing_framework()
        assert result == "playwright"

    def test_detects_playwright_config_js(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Detects playwright.config.js."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        (tmp_path / "playwright.config.js").write_text("module.exports = {}")
        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler._detect_existing_framework()
        assert result == "playwright"

    def test_detects_cypress_config_ts(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Detects cypress.config.ts."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        (tmp_path / "cypress.config.ts").write_text("export default {}")
        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler._detect_existing_framework()
        assert result == "cypress"

    def test_detects_cypress_config_js(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Detects cypress.config.js."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        (tmp_path / "cypress.config.js").write_text("module.exports = {}")
        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler._detect_existing_framework()
        assert result == "cypress"

    def test_detects_cypress_config_mjs(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Detects cypress.config.mjs."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        (tmp_path / "cypress.config.mjs").write_text("export default {}")
        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler._detect_existing_framework()
        assert result == "cypress"

    def test_returns_none_when_no_framework(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns None when no framework config found."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler._detect_existing_framework()
        assert result is None

    def test_playwright_takes_priority_over_cypress(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Playwright detection takes priority over Cypress."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        (tmp_path / "playwright.config.ts").write_text("export default {}")
        (tmp_path / "cypress.config.ts").write_text("export default {}")
        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler._detect_existing_framework()
        assert result == "playwright"


# =============================================================================
# AC #8: Skip when framework already exists
# =============================================================================


class TestSkipWhenExists:
    """Test skipping when framework already exists."""

    def test_execute_skips_when_playwright_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips when Playwright config exists."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        (tmp_path / "playwright.config.ts").write_text("export default {}")
        mock_config.testarch.framework_mode = "auto"
        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("framework_type") == "playwright"
        assert "already exists" in result.outputs.get("reason", "")

    def test_execute_skips_when_cypress_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips when Cypress config exists."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        (tmp_path / "cypress.config.ts").write_text("export default {}")
        mock_config.testarch.framework_mode = "auto"
        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("framework_type") == "cypress"
        assert "already exists" in result.outputs.get("reason", "")


# =============================================================================
# AC #9: Run when mode=on
# =============================================================================


class TestModeOn:
    """Test framework runs in mode=on when no existing framework."""

    def test_execute_invokes_workflow_when_mode_on(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() invokes workflow when mode=on and no existing framework."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        mock_config.testarch.framework_mode = "on"
        handler = FrameworkHandler(mock_config, tmp_path)

        with patch.object(handler, "_invoke_framework_workflow") as mock_invoke:
            mock_invoke.return_value = PhaseResult.ok(
                {"response": "ok", "framework_type": "playwright"}
            )

            result = handler.execute(state_epic_25)

        mock_invoke.assert_called_once()
        assert result.success is True

    def test_execute_skips_even_mode_on_when_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() still skips when mode=on but framework exists."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        (tmp_path / "playwright.config.ts").write_text("export default {}")
        mock_config.testarch.framework_mode = "on"
        handler = FrameworkHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "already exists" in result.outputs.get("reason", "")


# =============================================================================
# AC #4: Workflow invocation
# =============================================================================


class TestWorkflowInvocation:
    """Test _invoke_framework_workflow method."""

    def test_invoke_returns_error_when_paths_not_initialized(
        self, handler: "FrameworkHandler", state_epic_25: State
    ) -> None:
        """Returns error PhaseResult when paths singleton not initialized."""
        result = handler._invoke_framework_workflow(state_epic_25)

        assert result.success is False
        assert "Paths not initialized" in result.error


# =============================================================================
# AC #5: framework_ran_in_epic tracking
# =============================================================================


class TestEpicTracking:
    """Test framework_ran_in_epic state tracking."""

    def test_framework_ran_in_epic_set_on_success(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """framework_ran_in_epic is set to True on successful workflow."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        mock_config.testarch.framework_mode = "on"
        handler = FrameworkHandler(mock_config, tmp_path)

        assert state_epic_25.framework_ran_in_epic is False

        # Mock get_paths and _invoke_generic_workflow so the full path
        # through _invoke_framework_workflow runs including state update
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with (
            patch("bmad_assist.testarch.handlers.framework.get_paths", return_value=mock_paths),
            patch.object(handler, "_invoke_generic_workflow") as mock_invoke,
        ):
            mock_invoke.return_value = PhaseResult.ok({"response": "ok"})

            handler.execute(state_epic_25)

        assert state_epic_25.framework_ran_in_epic is True

    def test_framework_ran_in_epic_not_set_on_skip(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """framework_ran_in_epic is NOT set when framework is skipped."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        mock_config.testarch.framework_mode = "off"
        handler = FrameworkHandler(mock_config, tmp_path)

        handler.execute(state_epic_25)

        assert state_epic_25.framework_ran_in_epic is False

    def test_framework_ran_in_epic_not_set_when_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """framework_ran_in_epic is NOT set when framework already exists."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        (tmp_path / "playwright.config.ts").write_text("export default {}")
        mock_config.testarch.framework_mode = "auto"
        handler = FrameworkHandler(mock_config, tmp_path)

        handler.execute(state_epic_25)

        assert state_epic_25.framework_ran_in_epic is False


# =============================================================================
# Mode checking
# =============================================================================


class TestModeChecking:
    """Test _check_mode helper with framework_mode."""

    def test_check_framework_mode_off(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('off', False) for mode=off."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        mock_config.testarch.framework_mode = "off"
        handler = FrameworkHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "framework_mode")
        assert mode == "off"
        assert should_check is False

    def test_check_framework_mode_on(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('on', True) for mode=on."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        mock_config.testarch.framework_mode = "on"
        handler = FrameworkHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "framework_mode")
        assert mode == "on"
        assert should_check is True

    def test_check_framework_mode_auto(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Returns ('auto', True) for mode=auto."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        mock_config.testarch.framework_mode = "auto"
        handler = FrameworkHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "framework_mode")
        assert mode == "auto"
        assert should_check is True


# =============================================================================
# Framework type extraction
# =============================================================================


class TestFrameworkTypeExtraction:
    """Test _extract_framework_type method."""

    def test_extract_playwright(self, handler: "FrameworkHandler") -> None:
        """Extracts 'playwright' from output."""
        output = "Setting up Playwright for E2E testing"
        result = handler._extract_framework_type(output)
        assert result == "playwright"

    def test_extract_cypress(self, handler: "FrameworkHandler") -> None:
        """Extracts 'cypress' from output."""
        output = "Initializing Cypress test framework"
        result = handler._extract_framework_type(output)
        assert result == "cypress"

    def test_extract_none_when_not_found(self, handler: "FrameworkHandler") -> None:
        """Returns None when no framework type in output."""
        output = "Some generic test setup"
        result = handler._extract_framework_type(output)
        assert result is None


# =============================================================================
# Context building
# =============================================================================


class TestContextBuilding:
    """Test build_context method."""

    def test_build_context_returns_dict(
        self, handler: "FrameworkHandler", state_epic_25: State
    ) -> None:
        """build_context returns a dictionary."""
        context = handler.build_context(state_epic_25)
        assert isinstance(context, dict)

    def test_build_context_contains_epic_num(
        self, handler: "FrameworkHandler", state_epic_25: State
    ) -> None:
        """build_context includes epic_num."""
        context = handler.build_context(state_epic_25)
        # _build_common_context includes epic_num from state.current_epic
        assert "epic_num" in context
        assert context["epic_num"] == 25
