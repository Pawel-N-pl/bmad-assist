"""Tests for TestDesignHandler (Story 25.10).

These tests verify:
- AC #1: Phase.TEA_TEST_DESIGN in state machine (covered by test_state_model.py)
- AC #2: TestDesignHandler class creation
- AC #3: System-level output detection
- AC #4: Epic-level output detection
- AC #5: Extraction function delegation (covered by test_extraction.py)
- AC #6: TestarchConfig test_design_mode and test_design_level fields
- AC #7: test_design_ran_in_epic state flag
- AC #8: Handler registered in dispatch
- AC #9: Handler exported from testarch.handlers
- AC #10: Comprehensive tests (this file)
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
    config.testarch.test_design_mode = "auto"
    config.testarch.test_design_level = "auto"
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
def handler(mock_config: MagicMock, tmp_path: Path) -> "TestDesignHandler":
    """Create TestDesignHandler instance with mock config."""
    from bmad_assist.testarch.handlers import TestDesignHandler

    return TestDesignHandler(mock_config, tmp_path)


@pytest.fixture
def state_epic_25() -> State:
    """State at epic 25."""
    return State(
        current_epic=25,
        current_story=None,
        current_phase=Phase.TEA_TEST_DESIGN,
    )


@pytest.fixture
def state_epic_1() -> State:
    """State at first epic."""
    return State(
        current_epic=1,
        current_story=None,
        current_phase=Phase.TEA_TEST_DESIGN,
    )


@pytest.fixture
def state_testarch_epic() -> State:
    """State at testarch epic."""
    return State(
        current_epic="testarch",
        current_story=None,
        current_phase=Phase.TEA_TEST_DESIGN,
    )


# =============================================================================
# AC #2: TestDesignHandler class creation
# =============================================================================


class TestTestDesignHandlerCreation:
    """Test TestDesignHandler class creation."""

    def test_handler_created_successfully(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """TestDesignHandler can be instantiated."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        handler = TestDesignHandler(mock_config, tmp_path)
        assert handler is not None
        assert handler.config is mock_config
        assert handler.project_path == tmp_path

    def test_handler_phase_name(self, handler: "TestDesignHandler") -> None:
        """TestDesignHandler.phase_name returns 'tea_test_design'."""
        assert handler.phase_name == "tea_test_design"


# =============================================================================
# AC #8: Handler registered in dispatch
# =============================================================================


class TestHandlerRegistration:
    """Test TestDesignHandler registered in dispatch."""

    def test_tea_test_design_phase_in_workflow_handlers(self) -> None:
        """Phase.TEA_TEST_DESIGN has handler in WORKFLOW_HANDLERS."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        assert Phase.TEA_TEST_DESIGN in WORKFLOW_HANDLERS

    def test_tea_test_design_stub_handler_is_callable(self) -> None:
        """TEA_TEST_DESIGN stub handler is callable."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        handler = WORKFLOW_HANDLERS[Phase.TEA_TEST_DESIGN]
        assert callable(handler)


# =============================================================================
# AC #9: Handler exported from testarch.handlers
# =============================================================================


class TestHandlerExport:
    """Test TestDesignHandler exported from testarch.handlers."""

    def test_handler_in_exports(self) -> None:
        """TestDesignHandler is in testarch.handlers exports."""
        from bmad_assist.testarch import handlers

        assert hasattr(handlers, "TestDesignHandler")

    def test_handler_in_all(self) -> None:
        """TestDesignHandler is in __all__."""
        from bmad_assist.testarch.handlers import __all__

        assert "TestDesignHandler" in __all__


# =============================================================================
# AC #6: Mode checking (off/auto/on)
# =============================================================================


class TestModeOff:
    """Test test design skipped when mode=off."""

    def test_execute_skips_when_mode_off(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips with mode=off."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        mock_config.testarch.test_design_mode = "off"
        handler = TestDesignHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("test_design_mode") == "off"
        assert result.outputs.get("reason") == "test_design_mode=off"


class TestModeNotConfigured:
    """Test test design skipped when testarch not configured."""

    def test_execute_skips_when_not_configured(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips when testarch is None."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        mock_config.testarch = None
        handler = TestDesignHandler(mock_config, tmp_path)

        result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("test_design_mode") == "not_configured"


class TestModeOn:
    """Test test design runs in mode=on when no existing design."""

    def test_execute_invokes_workflow_when_mode_on(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() invokes workflow when mode=on and no existing design."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        mock_config.testarch.test_design_mode = "on"
        handler = TestDesignHandler(mock_config, tmp_path)

        with patch.object(handler, "_invoke_test_design_workflow") as mock_invoke:
            mock_invoke.return_value = PhaseResult.ok(
                {"response": "ok", "design_level": "epic"}
            )

            result = handler.execute(state_epic_25)

        mock_invoke.assert_called_once()
        assert result.success is True


# =============================================================================
# Level detection (system vs epic)
# =============================================================================


class TestLevelDetection:
    """Test _detect_design_level method."""

    def test_level_system_when_no_sprint_status(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_1: State
    ) -> None:
        """Returns 'system' when no sprint-status.yaml exists."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        handler = TestDesignHandler(mock_config, tmp_path)

        # Mock get_paths to return path without sprint-status
        mock_paths = MagicMock()
        mock_paths.implementation_artifacts = tmp_path / "artifacts"
        mock_paths.output_folder = tmp_path

        with patch(
            "bmad_assist.testarch.handlers.test_design.get_paths",
            return_value=mock_paths,
        ):
            level = handler._detect_design_level(state_epic_1)

        assert level == "system"

    def test_level_epic_when_system_output_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """Returns 'epic' when system output already exists."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        handler = TestDesignHandler(mock_config, tmp_path)

        # Create sprint-status and system output
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "sprint-status.yaml").write_text("entries: []")
        (tmp_path / "test-design-architecture.md").write_text("# System Design")

        mock_paths = MagicMock()
        mock_paths.implementation_artifacts = artifacts_dir
        mock_paths.output_folder = tmp_path

        with patch(
            "bmad_assist.testarch.handlers.test_design.get_paths",
            return_value=mock_paths,
        ):
            level = handler._detect_design_level(state_epic_25)

        assert level == "epic"

    def test_level_system_when_config_override(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """Returns 'system' when test_design_level config is set to 'system'."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        mock_config.testarch.test_design_level = "system"
        handler = TestDesignHandler(mock_config, tmp_path)

        level = handler._detect_design_level(state_epic_25)

        assert level == "system"

    def test_level_epic_when_config_override(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_1: State
    ) -> None:
        """Returns 'epic' when test_design_level config is set to 'epic'."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        mock_config.testarch.test_design_level = "epic"
        handler = TestDesignHandler(mock_config, tmp_path)

        level = handler._detect_design_level(state_epic_1)

        assert level == "epic"


# =============================================================================
# AC #3: System-level output detection
# =============================================================================


class TestSystemLevelOutputDetection:
    """Test _has_system_level_output method."""

    def test_returns_false_when_no_output(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Returns False when no system-level output exists."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        handler = TestDesignHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with patch(
            "bmad_assist.testarch.handlers.test_design.get_paths",
            return_value=mock_paths,
        ):
            result = handler._has_system_level_output()

        assert result is False

    def test_returns_true_when_architecture_exists(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Returns True when BOTH test-design-architecture.md AND test-design-qa.md exist (AC3)."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        # AC3: System-level creates TWO documents - both must exist
        (tmp_path / "test-design-architecture.md").write_text("# Architecture")
        (tmp_path / "test-design-qa.md").write_text("# QA")
        handler = TestDesignHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with patch(
            "bmad_assist.testarch.handlers.test_design.get_paths",
            return_value=mock_paths,
        ):
            result = handler._has_system_level_output()

        assert result is True


# =============================================================================
# AC #4: Epic-level output detection
# =============================================================================


class TestEpicLevelOutputDetection:
    """Test _has_epic_level_output method."""

    def test_returns_false_when_no_output(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Returns False when no epic-level output exists."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        handler = TestDesignHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with patch(
            "bmad_assist.testarch.handlers.test_design.get_paths",
            return_value=mock_paths,
        ):
            result = handler._has_epic_level_output(25)

        assert result is False

    def test_returns_true_when_epic_output_exists(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Returns True when test-design-epic-{N}.md exists."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        test_designs_dir = tmp_path / "test-designs"
        test_designs_dir.mkdir(parents=True)
        (test_designs_dir / "test-design-epic-25.md").write_text("# Epic 25")

        handler = TestDesignHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with patch(
            "bmad_assist.testarch.handlers.test_design.get_paths",
            return_value=mock_paths,
        ):
            result = handler._has_epic_level_output(25)

        assert result is True

    def test_returns_true_for_string_epic_id(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Returns True for string epic ID like 'testarch'."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        test_designs_dir = tmp_path / "test-designs"
        test_designs_dir.mkdir(parents=True)
        (test_designs_dir / "test-design-epic-testarch.md").write_text("# Testarch")

        handler = TestDesignHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with patch(
            "bmad_assist.testarch.handlers.test_design.get_paths",
            return_value=mock_paths,
        ):
            result = handler._has_epic_level_output("testarch")

        assert result is True


# =============================================================================
# Skip when output exists
# =============================================================================


class TestSkipWhenSystemOutputExists:
    """Test skipping when system-level output already exists."""

    def test_execute_skips_when_system_output_exists_forced_system_level(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_1: State
    ) -> None:
        """execute() skips when system-level design already exists and level forced to system."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        # Create system output (BOTH files per AC3)
        (tmp_path / "test-design-architecture.md").write_text("# System Design")
        (tmp_path / "test-design-qa.md").write_text("# QA")

        # Force system level via config to test system skip path
        mock_config.testarch.test_design_mode = "auto"
        mock_config.testarch.test_design_level = "system"
        handler = TestDesignHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with patch(
            "bmad_assist.testarch.handlers.test_design.get_paths",
            return_value=mock_paths,
        ):
            result = handler.execute(state_epic_1)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("design_level") == "system"
        assert "already exists" in result.outputs.get("reason", "")

    def test_execute_skips_when_system_output_exists_first_epic_no_sprint(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_1: State
    ) -> None:
        """execute() skips when system-level design already exists (no sprint-status)."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        # Create system output but NO sprint-status (first-time project)
        # AC3: Both files required for skip
        (tmp_path / "test-design-architecture.md").write_text("# System Design")
        (tmp_path / "test-design-qa.md").write_text("# QA")

        mock_config.testarch.test_design_mode = "auto"
        mock_config.testarch.test_design_level = "auto"  # Auto detection
        handler = TestDesignHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.implementation_artifacts = tmp_path / "artifacts"  # Does not exist
        mock_paths.output_folder = tmp_path

        with patch(
            "bmad_assist.testarch.handlers.test_design.get_paths",
            return_value=mock_paths,
        ):
            result = handler.execute(state_epic_1)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("design_level") == "system"
        assert "already exists" in result.outputs.get("reason", "")


class TestSkipWhenEpicOutputExists:
    """Test skipping when epic-level output already exists."""

    def test_execute_skips_when_epic_output_exists(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """execute() skips when epic-level design already exists."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        # Create sprint-status, system output, and epic output
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "sprint-status.yaml").write_text("entries: []")
        (tmp_path / "test-design-architecture.md").write_text("# System Design")
        test_designs_dir = tmp_path / "test-designs"
        test_designs_dir.mkdir(parents=True)
        (test_designs_dir / "test-design-epic-25.md").write_text("# Epic 25")

        mock_config.testarch.test_design_mode = "auto"
        handler = TestDesignHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.implementation_artifacts = artifacts_dir
        mock_paths.output_folder = tmp_path

        with patch(
            "bmad_assist.testarch.handlers.test_design.get_paths",
            return_value=mock_paths,
        ):
            result = handler.execute(state_epic_25)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("design_level") == "epic"
        assert "already exists" in result.outputs.get("reason", "")


# =============================================================================
# Workflow invocation with mock provider
# =============================================================================


class TestWorkflowInvocation:
    """Test _invoke_test_design_workflow method."""

    def test_invoke_returns_error_when_paths_not_initialized(
        self, handler: "TestDesignHandler", state_epic_25: State
    ) -> None:
        """Returns error PhaseResult when paths singleton not initialized."""
        result = handler._invoke_test_design_workflow(state_epic_25, "epic")

        assert result.success is False
        assert "Paths not initialized" in result.error

    def test_invoke_system_level_uses_correct_report_dir(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_1: State
    ) -> None:
        """System-level invocation uses output_folder as report dir."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        handler = TestDesignHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with (
            patch(
                "bmad_assist.testarch.handlers.test_design.get_paths",
                return_value=mock_paths,
            ),
            patch.object(handler, "_invoke_generic_workflow") as mock_invoke,
        ):
            mock_invoke.return_value = PhaseResult.ok({"response": "ok"})

            handler._invoke_test_design_workflow(state_epic_1, "system")

        # Verify report_dir is output_folder (not test-designs subdir)
        call_args = mock_invoke.call_args
        assert call_args.kwargs["report_dir"] == tmp_path
        assert call_args.kwargs["story_id"] == "architecture"

    def test_invoke_epic_level_uses_test_designs_subdir(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """Epic-level invocation uses test-designs subdirectory as report dir."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        handler = TestDesignHandler(mock_config, tmp_path)

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path

        with (
            patch(
                "bmad_assist.testarch.handlers.test_design.get_paths",
                return_value=mock_paths,
            ),
            patch.object(handler, "_invoke_generic_workflow") as mock_invoke,
        ):
            mock_invoke.return_value = PhaseResult.ok({"response": "ok"})

            handler._invoke_test_design_workflow(state_epic_25, "epic")

        # Verify report_dir is test-designs subdir
        call_args = mock_invoke.call_args
        assert call_args.kwargs["report_dir"] == tmp_path / "test-designs"
        assert call_args.kwargs["story_id"] == "epic-25"


# =============================================================================
# AC #7: State flag updates
# =============================================================================


class TestStateFlagUpdates:
    """Test test_design_ran_in_epic state flag updates."""

    def test_flag_set_on_success(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """test_design_ran_in_epic is set to True on successful workflow."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        mock_config.testarch.test_design_mode = "on"
        handler = TestDesignHandler(mock_config, tmp_path)

        assert state_epic_25.test_design_ran_in_epic is False

        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_paths.implementation_artifacts = tmp_path / "artifacts"

        with (
            patch(
                "bmad_assist.testarch.handlers.test_design.get_paths",
                return_value=mock_paths,
            ),
            patch.object(handler, "_invoke_generic_workflow") as mock_invoke,
        ):
            mock_invoke.return_value = PhaseResult.ok({"response": "ok"})

            handler.execute(state_epic_25)

        assert state_epic_25.test_design_ran_in_epic is True

    def test_flag_not_set_on_skip(
        self, mock_config: MagicMock, tmp_path: Path, state_epic_25: State
    ) -> None:
        """test_design_ran_in_epic is NOT set when test design is skipped."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        mock_config.testarch.test_design_mode = "off"
        handler = TestDesignHandler(mock_config, tmp_path)

        handler.execute(state_epic_25)

        assert state_epic_25.test_design_ran_in_epic is False


# =============================================================================
# Extraction function delegation
# =============================================================================


class TestExtractionDelegation:
    """Test that extraction delegates to centralized functions."""

    def test_extract_design_outputs_uses_central_functions(
        self, handler: "TestDesignHandler"
    ) -> None:
        """_extract_design_outputs delegates to extract_design_level and extract_risk_count."""
        output = "Epic-level test design complete. Total Risks: 5"

        result = handler._extract_design_outputs(output)

        assert result["design_level"] == "epic"
        assert result["risk_count"] == 5

    def test_extract_design_outputs_returns_none_for_missing(
        self, handler: "TestDesignHandler"
    ) -> None:
        """_extract_design_outputs returns None for missing values."""
        output = "Test plan generated."

        result = handler._extract_design_outputs(output)

        assert result["design_level"] is None
        assert result["risk_count"] is None


# =============================================================================
# Context building
# =============================================================================


class TestContextBuilding:
    """Test build_context method."""

    def test_build_context_returns_dict(
        self, handler: "TestDesignHandler", state_epic_25: State
    ) -> None:
        """build_context returns a dictionary."""
        context = handler.build_context(state_epic_25)
        assert isinstance(context, dict)

    def test_build_context_contains_epic_num(
        self, handler: "TestDesignHandler", state_epic_25: State
    ) -> None:
        """build_context includes epic_num."""
        context = handler.build_context(state_epic_25)
        # _build_common_context includes epic_num from state.current_epic
        assert "epic_num" in context
        assert context["epic_num"] == 25


# =============================================================================
# Mode checking
# =============================================================================


class TestModeChecking:
    """Test _check_mode helper with test_design_mode."""

    def test_check_test_design_mode_off(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Returns ('off', False) for mode=off."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        mock_config.testarch.test_design_mode = "off"
        handler = TestDesignHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "test_design_mode")
        assert mode == "off"
        assert should_check is False

    def test_check_test_design_mode_on(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Returns ('on', True) for mode=on."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        mock_config.testarch.test_design_mode = "on"
        handler = TestDesignHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "test_design_mode")
        assert mode == "on"
        assert should_check is True

    def test_check_test_design_mode_auto(
        self, mock_config: MagicMock, tmp_path: Path
    ) -> None:
        """Returns ('auto', True) for mode=auto."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        mock_config.testarch.test_design_mode = "auto"
        handler = TestDesignHandler(mock_config, tmp_path)

        mode, should_check = handler._check_mode(State(), "test_design_mode")
        assert mode == "auto"
        assert should_check is True
