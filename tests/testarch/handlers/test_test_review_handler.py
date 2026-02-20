"""Tests for TestReviewHandler (testarch-9).

These tests verify:
- AC #1: Phase.TEST_REVIEW in state machine (covered by test_state_model.py)
- AC #2: TestReviewHandler class creation and phase_name
- AC #3: Handler registered in dispatch
- AC #4: Compiler integration (testarch-test-review workflow)
- AC #5: Skip logic (off, auto+no ATDD, not configured)
- AC #6: Quality score extraction from output
- AC #7: Review file saved to test-reviews/ directory
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
    config.testarch.test_review_on_code_complete = "auto"

    config.providers = MagicMock()
    config.providers.master = MagicMock()
    config.providers.master.provider = "claude"
    config.providers.master.model = "opus"
    config.timeout = 30
    return config


@pytest.fixture
def handler(mock_config: MagicMock, tmp_path: Path) -> "TestReviewHandler":
    """Create TestReviewHandler instance with mock config."""
    from bmad_assist.testarch.handlers import TestReviewHandler

    return TestReviewHandler(mock_config, tmp_path)


@pytest.fixture
def state_story_1_1() -> State:
    """State at story 1.1 with ATDD ran."""
    state = State(
        current_epic=1,
        current_story="1.1",
        current_phase=Phase.TEST_REVIEW,
        atdd_ran_for_story=True,
    )
    return state


@pytest.fixture
def state_no_atdd() -> State:
    """State at story 1.2 without ATDD ran."""
    state = State(
        current_epic=1,
        current_story="1.2",
        current_phase=Phase.TEST_REVIEW,
        atdd_ran_for_story=False,
    )
    return state


# =============================================================================
# AC #2: TestReviewHandler class creation
# =============================================================================


class TestTestReviewHandlerCreation:
    """Test TestReviewHandler class creation."""

    def test_handler_created_successfully(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """TestReviewHandler can be instantiated."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        handler = TestReviewHandler(mock_config, tmp_path)
        assert handler is not None
        assert handler.config is mock_config
        assert handler.project_path == tmp_path

    def test_handler_phase_name(self, handler: "TestReviewHandler") -> None:
        """TestReviewHandler.phase_name returns 'test_review'."""
        assert handler.phase_name == "test_review"


# =============================================================================
# AC #3: Handler registered in dispatch
# =============================================================================


class TestHandlerRegistration:
    """Test TestReviewHandler registered in dispatch."""

    def test_test_review_phase_in_workflow_handlers(self) -> None:
        """Phase.TEST_REVIEW has handler in WORKFLOW_HANDLERS."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        assert Phase.TEST_REVIEW in WORKFLOW_HANDLERS

    def test_test_review_stub_handler_is_callable(self) -> None:
        """TEST_REVIEW stub handler is callable."""
        from bmad_assist.core.loop import WORKFLOW_HANDLERS

        handler = WORKFLOW_HANDLERS[Phase.TEST_REVIEW]
        assert callable(handler)


# =============================================================================
# AC #5: Skip when mode=off
# =============================================================================


class TestModeOff:
    """Test test review skipped when mode=off."""

    def test_execute_skips_when_mode_off(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_story_1_1: State
    ) -> None:
        """execute() skips with mode=off."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        mock_config.testarch.test_review_on_code_complete = "off"
        handler = TestReviewHandler(mock_config, tmp_path)

        result = handler.execute(state_story_1_1)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("test_review_mode") == "off"
        assert result.outputs.get("reason") == "test_review_on_code_complete=off"


class TestModeNotConfigured:
    """Test test review skipped when testarch not configured."""

    def test_execute_skips_when_not_configured(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_story_1_1: State
    ) -> None:
        """execute() skips when testarch is None."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        mock_config.testarch = None
        handler = TestReviewHandler(mock_config, tmp_path)

        result = handler.execute(state_story_1_1)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("test_review_mode") == "not_configured"


class TestModeAutoNoATDD:
    """Test test review skipped when mode=auto and no ATDD ran."""

    def test_execute_skips_when_auto_no_atdd(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_no_atdd: State
    ) -> None:
        """execute() skips when mode=auto and atdd_ran_for_story=False."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        mock_config.testarch.test_review_on_code_complete = "auto"
        handler = TestReviewHandler(mock_config, tmp_path)

        result = handler.execute(state_no_atdd)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert result.outputs.get("test_review_mode") == "auto"
        assert result.outputs.get("reason") == "no ATDD ran for story"


# =============================================================================
# AC #6: Quality score extraction
# =============================================================================


class TestQualityScoreExtraction:
    """Test quality score extraction from output."""

    def test_extract_quality_score_simple(self, handler: "TestReviewHandler") -> None:
        """Extract score from 'Quality Score: 87/100'."""
        output = "Test Quality Review\n\nQuality Score: 87/100 (A - Good)"
        score = handler._extract_quality_score(output)
        assert score == 87

    def test_extract_quality_score_bold(self, handler: "TestReviewHandler") -> None:
        """Extract score from '**Quality Score**: 78/100'."""
        output = "## Summary\n\n**Quality Score**: 78/100 (B - Acceptable)"
        score = handler._extract_quality_score(output)
        assert score == 78

    def test_extract_quality_score_with_parens(self, handler: "TestReviewHandler") -> None:
        """Extract score from '92/100 (A+ - Excellent)'."""
        output = "Final verdict: 92/100 (A+ - Excellent)"
        score = handler._extract_quality_score(output)
        assert score == 92

    def test_extract_quality_score_not_found(self, handler: "TestReviewHandler") -> None:
        """Return None when score not found."""
        output = "Test review completed successfully."
        score = handler._extract_quality_score(output)
        assert score is None

    def test_extract_quality_score_out_of_range(self, handler: "TestReviewHandler") -> None:
        """Return None for score > 100."""
        output = "Quality Score: 150/100"
        score = handler._extract_quality_score(output)
        assert score is None


# =============================================================================
# AC #4: Compiler integration
# =============================================================================


class TestCompilerIntegration:
    """Test testarch-test-review compiler can be loaded."""

    def test_compiler_loads_successfully(self) -> None:
        """testarch-test-review compiler can be loaded."""
        from bmad_assist.compiler.core import get_workflow_compiler

        compiler = get_workflow_compiler("testarch-test-review")
        assert compiler is not None
        assert compiler.workflow_name == "testarch-test-review"

    def test_compiler_required_files(self) -> None:
        """Compiler declares required files."""
        from bmad_assist.compiler.core import get_workflow_compiler

        compiler = get_workflow_compiler("testarch-test-review")
        files = compiler.get_required_files()
        assert isinstance(files, list)
        assert any("project_context" in f or "project-context" in f for f in files)


# =============================================================================
# Mode checking logic
# =============================================================================


class TestModeCheckingLogic:
    """Test _check_mode with test_review config."""

    def test_mode_off_returns_false(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """mode=off returns ('off', False)."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        mock_config.testarch.test_review_on_code_complete = "off"
        handler = TestReviewHandler(mock_config, tmp_path)
        state = State()

        mode, should_run = handler._check_mode(state, "test_review_on_code_complete")

        assert mode == "off"
        assert should_run is False

    def test_mode_on_returns_true(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """mode=on returns ('on', True)."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        mock_config.testarch.test_review_on_code_complete = "on"
        handler = TestReviewHandler(mock_config, tmp_path)
        state = State()

        mode, should_run = handler._check_mode(state, "test_review_on_code_complete")

        assert mode == "on"
        assert should_run is True

    def test_mode_auto_with_atdd_returns_true(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_story_1_1: State
    ) -> None:
        """mode=auto with atdd_ran_for_story=True returns ('auto', True)."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        mock_config.testarch.test_review_on_code_complete = "auto"
        handler = TestReviewHandler(mock_config, tmp_path)

        mode, should_run = handler._check_mode(
            state_story_1_1, "test_review_on_code_complete", "atdd_ran_for_story"
        )

        assert mode == "auto"
        assert should_run is True

    def test_mode_auto_without_atdd_returns_false(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
        state_no_atdd: State
    ) -> None:
        """mode=auto with atdd_ran_for_story=False returns ('auto', False)."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        mock_config.testarch.test_review_on_code_complete = "auto"
        handler = TestReviewHandler(mock_config, tmp_path)

        mode, should_run = handler._check_mode(
            state_no_atdd, "test_review_on_code_complete", "atdd_ran_for_story"
        )

        assert mode == "auto"
        assert should_run is False

    def test_not_configured_returns_false(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """testarch=None returns ('not_configured', False)."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        mock_config.testarch = None
        handler = TestReviewHandler(mock_config, tmp_path)
        state = State()

        mode, should_run = handler._check_mode(state, "test_review_on_code_complete")

        assert mode == "not_configured"
        assert should_run is False


# =============================================================================
# Workflow invocation (mocked)
# =============================================================================


class TestWorkflowInvocation:
    """Test workflow invocation with mocked dependencies."""

    @patch("bmad_assist.compiler.compile_workflow")
    @patch("bmad_assist.providers.get_provider")
    @patch("bmad_assist.testarch.handlers.test_review.get_paths")
    @patch("bmad_assist.testarch.handlers.base.get_paths") # Patch base too
    def test_execute_invokes_workflow_when_mode_on(
        self,
        mock_base_get_paths: MagicMock,
        mock_handler_get_paths: MagicMock,
        mock_get_provider: MagicMock,
        mock_compile: MagicMock,
        mock_config: MagicMock,
        tmp_path: Path,
        state_story_1_1: State,
    ) -> None:
        """execute() invokes workflow when mode=on."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        # Setup mocks
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        # Return same paths for both calls
        mock_base_get_paths.return_value = mock_paths
        mock_handler_get_paths.return_value = mock_paths

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled prompt>"
        mock_compile.return_value = mock_compiled

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult
        mock_provider.invoke.return_value = ProviderResult(
            stdout="Quality Score: 85/100 (A - Good)",
            exit_code=0,
            model="opus",
            provider_session_id="sess-123",
            command=("claude",),
            duration_ms=100,
            stderr=""
        )
        mock_get_provider.return_value = mock_provider

        # Configure mode=on
        mock_config.testarch.test_review_on_code_complete = "on"
        handler = TestReviewHandler(mock_config, tmp_path)

        result = handler.execute(state_story_1_1)

        assert result.success is True
        assert result.outputs.get("quality_score") == 85
        mock_compile.assert_called_once()

    @patch("bmad_assist.compiler.compile_workflow")
    @patch("bmad_assist.providers.get_provider")
    @patch("bmad_assist.testarch.handlers.test_review.get_paths")
    @patch("bmad_assist.testarch.handlers.base.get_paths") # Patch base too
    def test_execute_saves_review_file(
        self,
        mock_base_get_paths: MagicMock,
        mock_handler_get_paths: MagicMock,
        mock_get_provider: MagicMock,
        mock_compile: MagicMock,
        mock_config: MagicMock,
        tmp_path: Path,
        state_story_1_1: State,
    ) -> None:
        """execute() saves review file to test-reviews/ directory."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        # Setup mocks
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_base_get_paths.return_value = mock_paths
        mock_handler_get_paths.return_value = mock_paths

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled prompt>"
        mock_compile.return_value = mock_compiled

        mock_provider = MagicMock()
        from bmad_assist.providers.base import ProviderResult
        mock_provider.invoke.return_value = ProviderResult(
            stdout="# Test Review\n\nQuality Score: 90/100",
            exit_code=0,
            model="opus",
            provider_session_id="sess-123",
            command=("claude",),
            duration_ms=100,
            stderr=""
        )
        mock_get_provider.return_value = mock_provider

        # Configure mode=on
        mock_config.testarch.test_review_on_code_complete = "on"
        handler = TestReviewHandler(mock_config, tmp_path)

        result = handler.execute(state_story_1_1)

        assert result.success is True
        review_file = result.outputs.get("review_file")
        assert review_file is not None
        assert "test-review" in review_file
        assert Path(review_file).exists()


# =============================================================================
# State model tests
# =============================================================================


class TestPhaseInStateModel:
    """Test Phase.TEST_REVIEW is in state model."""

    def test_test_review_phase_exists(self) -> None:
        """Phase.TEST_REVIEW exists."""
        assert hasattr(Phase, "TEST_REVIEW")
        assert Phase.TEST_REVIEW.value == "test_review"

    def test_test_review_phase_is_valid(self) -> None:
        """TEST_REVIEW phase is a valid Phase enum value.

        Note: In configurable loop architecture, the phase sequence comes from LoopConfig.
        TEST_REVIEW is a testarch phase and may not be in DEFAULT_LOOP_CONFIG.story,
        but it should still be a valid Phase enum value.
        """
        from bmad_assist.core.state import Phase

        # TEST_REVIEW is a valid Phase enum
        assert Phase.TEST_REVIEW in Phase
        assert Phase.TEST_REVIEW.value == "test_review"
