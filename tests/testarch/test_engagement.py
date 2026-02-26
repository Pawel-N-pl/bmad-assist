"""Tests for testarch engagement module.

Story 25.12: Loop Configuration & Phase Registration
Tests for:
- should_run_workflow function
- STANDALONE_WORKFLOWS constant
- WORKFLOW_MODE_FIELDS mapping
- Engagement model integration with handlers
"""

from unittest.mock import MagicMock

import pytest

from bmad_assist.testarch.engagement import (
    STANDALONE_WORKFLOWS,
    WORKFLOW_MODE_FIELDS,
    should_run_workflow,
)

# =============================================================================
# Test STANDALONE_WORKFLOWS constant
# =============================================================================


class TestStandaloneWorkflows:
    """Test STANDALONE_WORKFLOWS constant definition."""

    def test_contains_framework(self) -> None:
        """STANDALONE_WORKFLOWS includes 'framework'."""
        assert "framework" in STANDALONE_WORKFLOWS

    def test_contains_ci(self) -> None:
        """STANDALONE_WORKFLOWS includes 'ci'."""
        assert "ci" in STANDALONE_WORKFLOWS

    def test_contains_automate(self) -> None:
        """STANDALONE_WORKFLOWS includes 'automate'."""
        assert "automate" in STANDALONE_WORKFLOWS

    def test_contains_test_design(self) -> None:
        """STANDALONE_WORKFLOWS includes 'test-design'."""
        assert "test-design" in STANDALONE_WORKFLOWS

    def test_contains_nfr_assess(self) -> None:
        """STANDALONE_WORKFLOWS includes 'nfr-assess'."""
        assert "nfr-assess" in STANDALONE_WORKFLOWS

    def test_does_not_contain_atdd(self) -> None:
        """STANDALONE_WORKFLOWS does not include 'atdd' (integrated workflow)."""
        assert "atdd" not in STANDALONE_WORKFLOWS

    def test_does_not_contain_test_review(self) -> None:
        """STANDALONE_WORKFLOWS does not include 'test-review' (integrated workflow)."""
        assert "test-review" not in STANDALONE_WORKFLOWS

    def test_does_not_contain_trace(self) -> None:
        """STANDALONE_WORKFLOWS does not include 'trace' (integrated workflow)."""
        assert "trace" not in STANDALONE_WORKFLOWS

    def test_is_frozen_set(self) -> None:
        """STANDALONE_WORKFLOWS is immutable (set or frozenset)."""
        assert isinstance(STANDALONE_WORKFLOWS, (set, frozenset))


# =============================================================================
# Test WORKFLOW_MODE_FIELDS mapping
# =============================================================================


class TestWorkflowModeFields:
    """Test WORKFLOW_MODE_FIELDS mapping."""

    def test_atdd_maps_to_atdd_mode(self) -> None:
        """'atdd' workflow maps to 'atdd_mode' field."""
        assert WORKFLOW_MODE_FIELDS["atdd"] == "atdd_mode"

    def test_test_review_maps_to_test_review_on_code_complete(self) -> None:
        """'test-review' workflow maps to 'test_review_on_code_complete' field."""
        assert WORKFLOW_MODE_FIELDS["test-review"] == "test_review_on_code_complete"

    def test_trace_maps_to_trace_on_epic_complete(self) -> None:
        """'trace' workflow maps to 'trace_on_epic_complete' field."""
        assert WORKFLOW_MODE_FIELDS["trace"] == "trace_on_epic_complete"

    def test_framework_maps_to_framework_mode(self) -> None:
        """'framework' workflow maps to 'framework_mode' field."""
        assert WORKFLOW_MODE_FIELDS["framework"] == "framework_mode"

    def test_ci_maps_to_ci_mode(self) -> None:
        """'ci' workflow maps to 'ci_mode' field."""
        assert WORKFLOW_MODE_FIELDS["ci"] == "ci_mode"

    def test_test_design_maps_to_test_design_mode(self) -> None:
        """'test-design' workflow maps to 'test_design_mode' field."""
        assert WORKFLOW_MODE_FIELDS["test-design"] == "test_design_mode"

    def test_automate_maps_to_automate_mode(self) -> None:
        """'automate' workflow maps to 'automate_mode' field."""
        assert WORKFLOW_MODE_FIELDS["automate"] == "automate_mode"

    def test_nfr_assess_maps_to_nfr_assess_mode(self) -> None:
        """'nfr-assess' workflow maps to 'nfr_assess_mode' field."""
        assert WORKFLOW_MODE_FIELDS["nfr-assess"] == "nfr_assess_mode"

    def test_all_workflows_mapped(self) -> None:
        """All 8 TEA workflows are mapped."""
        expected = {"atdd", "test-review", "trace", "framework", "ci", "test-design", "automate", "nfr-assess"}
        assert set(WORKFLOW_MODE_FIELDS.keys()) == expected


# =============================================================================
# Test should_run_workflow function
# =============================================================================


class TestShouldRunWorkflowNoneConfig:
    """Test should_run_workflow when config is None (backwards compatible)."""

    def test_returns_true_when_config_is_none(self) -> None:
        """Returns True when config is None (backwards compatible)."""
        result = should_run_workflow("atdd", None)
        assert result is True

    def test_returns_true_for_any_workflow_when_config_none(self) -> None:
        """Returns True for any workflow when config is None (backwards compatible)."""
        for workflow in WORKFLOW_MODE_FIELDS.keys():
            assert should_run_workflow(workflow, None) is True


class TestShouldRunWorkflowEngagementOff:
    """Test should_run_workflow when engagement_model='off'."""

    def test_returns_false_when_engagement_off(self) -> None:
        """Returns False when engagement_model='off'."""
        config = MagicMock()
        config.engagement_model = "off"

        result = should_run_workflow("atdd", config)
        assert result is False

    def test_returns_false_for_all_workflows_when_off(self) -> None:
        """Returns False for all workflows when engagement_model='off'."""
        config = MagicMock()
        config.engagement_model = "off"

        for workflow in WORKFLOW_MODE_FIELDS.keys():
            assert should_run_workflow(workflow, config) is False


class TestShouldRunWorkflowEngagementLite:
    """Test should_run_workflow when engagement_model='lite'.

    Lite mode only enables the 'automate' workflow - not all standalone workflows.
    This is the minimal TEA engagement: just expand test automation coverage.
    """

    def test_returns_true_for_automate_only(self) -> None:
        """Returns True only for 'automate' workflow when engagement_model='lite'."""
        config = MagicMock()
        config.engagement_model = "lite"

        assert should_run_workflow("automate", config) is True

    def test_returns_false_for_other_standalone_workflows(self) -> None:
        """Returns False for other standalone workflows when engagement_model='lite'."""
        config = MagicMock()
        config.engagement_model = "lite"

        other_standalone = {"framework", "ci", "test-design", "nfr-assess"}
        for workflow in other_standalone:
            assert should_run_workflow(workflow, config) is False

    def test_returns_false_for_integrated_workflows(self) -> None:
        """Returns False for integrated workflows when engagement_model='lite'."""
        config = MagicMock()
        config.engagement_model = "lite"

        integrated = {"atdd", "test-review", "trace"}
        for workflow in integrated:
            assert should_run_workflow(workflow, config) is False


class TestShouldRunWorkflowEngagementSolo:
    """Test should_run_workflow when engagement_model='solo'.

    Solo mode enables all standalone workflows but NOT integrated workflows.
    """

    def test_returns_true_for_standalone_workflows(self) -> None:
        """Returns True for standalone workflows when engagement_model='solo'."""
        config = MagicMock()
        config.engagement_model = "solo"

        for workflow in STANDALONE_WORKFLOWS:
            assert should_run_workflow(workflow, config) is True

    def test_returns_false_for_integrated_workflows(self) -> None:
        """Returns False for integrated workflows when engagement_model='solo'."""
        config = MagicMock()
        config.engagement_model = "solo"

        integrated = {"atdd", "test-review", "trace"}
        for workflow in integrated:
            assert should_run_workflow(workflow, config) is False


class TestShouldRunWorkflowEngagementIntegrated:
    """Test should_run_workflow when engagement_model='integrated'."""

    def test_returns_true_for_all_workflows(self) -> None:
        """Returns True for all workflows when engagement_model='integrated'."""
        config = MagicMock()
        config.engagement_model = "integrated"

        for workflow in WORKFLOW_MODE_FIELDS.keys():
            assert should_run_workflow(workflow, config) is True


class TestShouldRunWorkflowEngagementAuto:
    """Test should_run_workflow when engagement_model='auto'."""

    def test_returns_true_for_all_workflows(self) -> None:
        """Returns True for all workflows when engagement_model='auto' (default)."""
        config = MagicMock()
        config.engagement_model = "auto"

        for workflow in WORKFLOW_MODE_FIELDS.keys():
            assert should_run_workflow(workflow, config) is True


class TestShouldRunWorkflowUnknownWorkflow:
    """Test should_run_workflow with unknown workflow IDs."""

    def test_returns_true_for_unknown_workflow_when_not_off(self) -> None:
        """Returns True for unknown workflow when engagement not 'off'."""
        config = MagicMock()
        config.engagement_model = "auto"

        result = should_run_workflow("unknown-workflow", config)
        assert result is True

    def test_returns_false_for_unknown_workflow_when_off(self) -> None:
        """Returns False for unknown workflow when engagement_model='off'."""
        config = MagicMock()
        config.engagement_model = "off"

        result = should_run_workflow("unknown-workflow", config)
        assert result is False


# =============================================================================
# Test TestarchConfig engagement_model field
# =============================================================================


class TestTestarchConfigEngagementModel:
    """Test engagement_model field in TestarchConfig."""

    def test_default_value_is_auto(self) -> None:
        """engagement_model defaults to 'auto'."""
        from bmad_assist.testarch.config import TestarchConfig

        config = TestarchConfig()
        assert config.engagement_model == "auto"

    def test_accepts_off(self) -> None:
        """engagement_model accepts 'off' value."""
        from bmad_assist.testarch.config import TestarchConfig

        config = TestarchConfig(engagement_model="off")
        assert config.engagement_model == "off"

    def test_accepts_lite(self) -> None:
        """engagement_model accepts 'lite' value."""
        from bmad_assist.testarch.config import TestarchConfig

        config = TestarchConfig(engagement_model="lite")
        assert config.engagement_model == "lite"

    def test_accepts_solo(self) -> None:
        """engagement_model accepts 'solo' value."""
        from bmad_assist.testarch.config import TestarchConfig

        config = TestarchConfig(engagement_model="solo")
        assert config.engagement_model == "solo"

    def test_accepts_integrated(self) -> None:
        """engagement_model accepts 'integrated' value."""
        from bmad_assist.testarch.config import TestarchConfig

        config = TestarchConfig(engagement_model="integrated")
        assert config.engagement_model == "integrated"

    def test_rejects_invalid_value(self) -> None:
        """engagement_model rejects invalid values."""
        from pydantic import ValidationError

        from bmad_assist.testarch.config import TestarchConfig

        with pytest.raises(ValidationError) as exc_info:
            TestarchConfig(engagement_model="invalid")  # type: ignore[arg-type]
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("engagement_model",) for e in errors)


class TestEngagementModelConsistencyValidation:
    """Test engagement_model consistency validation with mode fields."""

    def test_warns_when_off_but_atdd_mode_on(self, caplog: pytest.LogCaptureFixture) -> None:
        """Logs warning when engagement_model='off' but atdd_mode='on'."""
        import logging

        from bmad_assist.testarch.config import TestarchConfig

        with caplog.at_level(logging.WARNING):
            TestarchConfig(engagement_model="off", atdd_mode="on")

        # Check for warning about ignored modes
        assert any("ignored" in r.message.lower() for r in caplog.records)

    def test_no_warning_for_lite_mode(self, caplog: pytest.LogCaptureFixture) -> None:
        """No warning for engagement_model='lite' (only 'off' triggers warnings)."""
        import logging

        from bmad_assist.testarch.config import TestarchConfig

        with caplog.at_level(logging.WARNING):
            TestarchConfig(engagement_model="lite", trace_on_epic_complete="on")

        # No warnings - only 'off' mode triggers consistency warnings
        assert not any("ignored" in r.message.lower() for r in caplog.records)

    def test_no_warning_for_consistent_config(self, caplog: pytest.LogCaptureFixture) -> None:
        """No warning when engagement_model and mode fields are consistent."""
        import logging

        from bmad_assist.testarch.config import TestarchConfig

        with caplog.at_level(logging.WARNING):
            TestarchConfig(engagement_model="integrated", atdd_mode="on")

        # No warnings about inconsistency
        assert not any("ignored" in r.message.lower() for r in caplog.records)


# =============================================================================
# Test handler engagement checks
# =============================================================================


class TestHandlerEngagementCheck:
    """Test handler _check_engagement_model method."""

    @pytest.fixture
    def mock_config(self) -> MagicMock:
        """Create mock config with testarch settings."""
        config = MagicMock()
        config.testarch = MagicMock()
        config.testarch.engagement_model = "auto"
        config.testarch.atdd_mode = "auto"
        config.benchmarking = MagicMock()
        config.benchmarking.enabled = False
        config.providers = MagicMock()
        config.providers.master = MagicMock()
        config.providers.master.provider = "mock"
        config.providers.master.model = "mock"
        config.timeout = 30
        return config

    def test_atdd_handler_has_workflow_id(self, mock_config: MagicMock, tmp_path) -> None:
        """ATDDHandler has workflow_id property."""
        from bmad_assist.testarch.handlers import ATDDHandler

        handler = ATDDHandler(mock_config, tmp_path)
        assert handler.workflow_id == "atdd"

    def test_test_review_handler_has_workflow_id(self, mock_config: MagicMock, tmp_path) -> None:
        """TestReviewHandler has workflow_id property."""
        from bmad_assist.testarch.handlers import TestReviewHandler

        handler = TestReviewHandler(mock_config, tmp_path)
        assert handler.workflow_id == "test-review"

    def test_trace_handler_has_workflow_id(self, mock_config: MagicMock, tmp_path) -> None:
        """TraceHandler has workflow_id property."""
        from bmad_assist.testarch.handlers import TraceHandler

        handler = TraceHandler(mock_config, tmp_path)
        assert handler.workflow_id == "trace"

    def test_framework_handler_has_workflow_id(self, mock_config: MagicMock, tmp_path) -> None:
        """FrameworkHandler has workflow_id property."""
        from bmad_assist.testarch.handlers import FrameworkHandler

        handler = FrameworkHandler(mock_config, tmp_path)
        assert handler.workflow_id == "framework"

    def test_ci_handler_has_workflow_id(self, mock_config: MagicMock, tmp_path) -> None:
        """CIHandler has workflow_id property."""
        from bmad_assist.testarch.handlers import CIHandler

        handler = CIHandler(mock_config, tmp_path)
        assert handler.workflow_id == "ci"

    def test_test_design_handler_has_workflow_id(self, mock_config: MagicMock, tmp_path) -> None:
        """TestDesignHandler has workflow_id property."""
        from bmad_assist.testarch.handlers import TestDesignHandler

        handler = TestDesignHandler(mock_config, tmp_path)
        assert handler.workflow_id == "test-design"

    def test_automate_handler_has_workflow_id(self, mock_config: MagicMock, tmp_path) -> None:
        """AutomateHandler has workflow_id property."""
        from bmad_assist.testarch.handlers import AutomateHandler

        handler = AutomateHandler(mock_config, tmp_path)
        assert handler.workflow_id == "automate"

    def test_nfr_assess_handler_has_workflow_id(self, mock_config: MagicMock, tmp_path) -> None:
        """NFRAssessHandler has workflow_id property."""
        from bmad_assist.testarch.handlers import NFRAssessHandler

        handler = NFRAssessHandler(mock_config, tmp_path)
        assert handler.workflow_id == "nfr-assess"


class TestHandlerSkipsWhenEngagementOff:
    """Test handlers skip when engagement_model='off'."""

    @pytest.fixture
    def mock_config_engagement_off(self) -> MagicMock:
        """Create mock config with engagement_model='off'."""
        config = MagicMock()
        config.testarch = MagicMock()
        config.testarch.engagement_model = "off"
        config.testarch.atdd_mode = "on"
        config.testarch.test_review_on_code_complete = "on"
        config.testarch.trace_on_epic_complete = "on"
        config.testarch.framework_mode = "on"
        config.testarch.ci_mode = "on"
        config.testarch.test_design_mode = "on"
        config.testarch.automate_mode = "on"
        config.testarch.nfr_assess_mode = "on"
        config.benchmarking = MagicMock()
        config.benchmarking.enabled = False
        config.providers = MagicMock()
        config.providers.master = MagicMock()
        config.providers.master.provider = "mock"
        config.providers.master.model = "mock"
        config.timeout = 30
        return config

    def test_atdd_skips_when_engagement_off(self, mock_config_engagement_off: MagicMock, tmp_path) -> None:
        """ATDDHandler skips when engagement_model='off'."""
        from bmad_assist.core.state import Phase, State
        from bmad_assist.testarch.handlers import ATDDHandler

        handler = ATDDHandler(mock_config_engagement_off, tmp_path)
        state = State(current_epic=1, current_story="1.1", current_phase=Phase.ATDD)

        result = handler.execute(state)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "engagement" in result.outputs.get("reason", "").lower()

    def test_trace_skips_when_engagement_off(self, mock_config_engagement_off: MagicMock, tmp_path) -> None:
        """TraceHandler skips when engagement_model='off'."""
        from bmad_assist.core.state import Phase, State
        from bmad_assist.testarch.handlers import TraceHandler

        handler = TraceHandler(mock_config_engagement_off, tmp_path)
        state = State(current_epic=1, current_story="1.1", current_phase=Phase.TRACE)

        result = handler.execute(state)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "engagement" in result.outputs.get("reason", "").lower()


class TestHandlerSkipsIntegratedWhenEngagementLite:
    """Test integrated workflow handlers skip when engagement_model='lite'."""

    @pytest.fixture
    def mock_config_engagement_lite(self) -> MagicMock:
        """Create mock config with engagement_model='lite'."""
        config = MagicMock()
        config.testarch = MagicMock()
        config.testarch.engagement_model = "lite"
        config.testarch.atdd_mode = "on"
        config.testarch.test_review_on_code_complete = "on"
        config.testarch.trace_on_epic_complete = "on"
        config.testarch.framework_mode = "on"
        config.testarch.ci_mode = "on"
        config.testarch.test_design_mode = "on"
        config.testarch.automate_mode = "on"
        config.testarch.nfr_assess_mode = "on"
        config.benchmarking = MagicMock()
        config.benchmarking.enabled = False
        config.providers = MagicMock()
        config.providers.master = MagicMock()
        config.providers.master.provider = "mock"
        config.providers.master.model = "mock"
        config.timeout = 30
        return config

    def test_atdd_skips_when_engagement_lite(self, mock_config_engagement_lite: MagicMock, tmp_path) -> None:
        """ATDDHandler (integrated) skips when engagement_model='lite'."""
        from bmad_assist.core.state import Phase, State
        from bmad_assist.testarch.handlers import ATDDHandler

        handler = ATDDHandler(mock_config_engagement_lite, tmp_path)
        state = State(current_epic=1, current_story="1.1", current_phase=Phase.ATDD)

        result = handler.execute(state)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "engagement" in result.outputs.get("reason", "").lower()

    def test_trace_skips_when_engagement_lite(self, mock_config_engagement_lite: MagicMock, tmp_path) -> None:
        """TraceHandler (integrated) skips when engagement_model='lite'."""
        from bmad_assist.core.state import Phase, State
        from bmad_assist.testarch.handlers import TraceHandler

        handler = TraceHandler(mock_config_engagement_lite, tmp_path)
        state = State(current_epic=1, current_story="1.1", current_phase=Phase.TRACE)

        result = handler.execute(state)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "engagement" in result.outputs.get("reason", "").lower()

    def test_test_review_skips_when_engagement_lite(self, mock_config_engagement_lite: MagicMock, tmp_path) -> None:
        """TestReviewHandler (integrated) skips when engagement_model='lite'."""
        from bmad_assist.core.state import Phase, State
        from bmad_assist.testarch.handlers import TestReviewHandler

        handler = TestReviewHandler(mock_config_engagement_lite, tmp_path)
        state = State(current_epic=1, current_story="1.1", current_phase=Phase.TEST_REVIEW)

        result = handler.execute(state)

        assert result.success is True
        assert result.outputs.get("skipped") is True
        assert "engagement" in result.outputs.get("reason", "").lower()
