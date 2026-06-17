"""Tests for TestarchBaseHandler."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.config import Config
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.state import State
from bmad_assist.providers.base import ProviderResult
from bmad_assist.testarch.config import (
    EvidenceConfig,
    KnowledgeConfig,
    TestarchConfig,
)
from bmad_assist.testarch.handlers.base import TestarchBaseHandler


class ConcreteHandler(TestarchBaseHandler):
    """Concrete implementation for testing."""

    @property
    def phase_name(self) -> str:
        return "test_phase"

    @property
    def workflow_id(self) -> str:
        return "test-workflow"

    def build_context(self, state: State) -> dict:
        return {}


@pytest.fixture
def mock_config():
    # Use plain MagicMock to avoid spec issues
    config = MagicMock()
    config.testarch = MagicMock(spec=TestarchConfig)
    config.testarch.evidence = EvidenceConfig(
        enabled=True,
        collect_before_step=True,
        storage_path="{implementation_artifacts}/evidence",
    )
    config.testarch.knowledge = KnowledgeConfig(
        playwright_utils=True,
    )

    # Configure providers
    config.providers = MagicMock()
    config.providers.master = MagicMock()
    config.providers.master.provider = "mock-provider"
    config.providers.master.model = "mock-model"
    config.providers.master.display_model = "mock-model"
    # No helper by default (testarch fallback resolver only kicks in
    # when helper is configured and differs from master).
    config.providers.helper = None
    config.timeout = 30
    # timeouts=None → legacy "no retry" path. Individual tests override
    # this to exercise the retry wrapper.
    config.timeouts = None

    return config


@pytest.fixture
def project_path(tmp_path):
    return tmp_path


@pytest.fixture
def handler(mock_config, project_path):
    return ConcreteHandler(mock_config, project_path)


def test_initialization(handler):
    assert handler.phase_name == "test_phase"


# =========================================================================
# Evidence Collection Tests
# =========================================================================

def test_get_evidence_config(handler, mock_config):
    assert handler._get_evidence_config() == mock_config.testarch.evidence
    
    mock_config.testarch = None
    assert handler._get_evidence_config() is None


def test_should_collect_evidence(handler, mock_config):
    assert handler._should_collect_evidence() is True
    
    # Disabled in config
    mock_config.testarch.evidence = EvidenceConfig(enabled=False)
    # Even if enabled is False, the object exists. 
    # Logic: evidence_config.enabled and collect_before_step
    # Default collect_before_step is True.
    assert handler._should_collect_evidence() is False

    # Collect before step False
    mock_config.testarch.evidence = EvidenceConfig(enabled=True, collect_before_step=False)
    assert handler._should_collect_evidence() is False


@patch("bmad_assist.testarch.evidence.get_evidence_collector")
def test_collect_evidence(mock_get_collector, handler, mock_config):
    mock_collector_instance = MagicMock()
    mock_get_collector.return_value = mock_collector_instance
    
    handler._collect_evidence()
    
    mock_get_collector.assert_called_with(handler.project_path)
    mock_collector_instance.collect_all.assert_called_with(mock_config.testarch.evidence)


@patch("bmad_assist.testarch.evidence.get_evidence_collector")
def test_get_evidence_markdown(mock_get_collector, handler):
    mock_collector_instance = MagicMock()
    mock_collector_instance.collect_all.return_value.to_markdown.return_value = "# Evidence"
    mock_get_collector.return_value = mock_collector_instance
    
    markdown = handler._get_evidence_markdown()
    assert markdown == "# Evidence"

    # Test failure
    mock_collector_instance.collect_all.side_effect = Exception("Boom")
    assert handler._get_evidence_markdown() == ""


@patch("bmad_assist.core.paths.get_paths")
def test_save_evidence(mock_get_paths, handler, mock_config):
    mock_paths = MagicMock()
    mock_paths.implementation_artifacts = handler.project_path / "artifacts"
    mock_get_paths.return_value = mock_paths
    
    evidence = MagicMock()
    evidence.to_markdown.return_value = "Evidence Content"
    
    path = handler._save_evidence(evidence, "1.2")
    
    assert path is not None
    assert path.exists()
    assert "Evidence Content" in path.read_text()
    assert path.parent == mock_paths.implementation_artifacts / "evidence"


# =========================================================================
# Knowledge Loading Tests
# =========================================================================

@patch("bmad_assist.testarch.knowledge.get_knowledge_loader")
def test_load_knowledge(mock_get_loader, handler, mock_config):
    mock_loader = MagicMock()
    mock_get_loader.return_value = mock_loader
    mock_loader.load_for_workflow.return_value = "Knowledge Content"

    content = handler._load_knowledge("test-workflow")

    assert content == "Knowledge Content"
    mock_loader.configure.assert_called_with(mock_config.testarch.knowledge)
    mock_loader.load_for_workflow.assert_called_with("test-workflow", {"tea_use_playwright_utils": True})


@patch("bmad_assist.testarch.knowledge.get_knowledge_loader")
def test_load_knowledge_by_tags(mock_get_loader, handler, mock_config):
    mock_loader = MagicMock()
    mock_get_loader.return_value = mock_loader
    mock_loader.load_by_tags.return_value = "Tagged Knowledge Content"

    content = handler._load_knowledge_by_tags(["fixture", "architecture"], ["deprecated"])

    assert content == "Tagged Knowledge Content"
    mock_loader.configure.assert_called_with(mock_config.testarch.knowledge)
    mock_loader.load_by_tags.assert_called_with(["fixture", "architecture"], ["deprecated"])


# =========================================================================
# Mode Checking Tests
# =========================================================================

def test_check_mode(handler, mock_config):
    state = State()

    mock_config.testarch.atdd_mode = "on"
    assert handler._check_mode(state, "atdd_mode") == ("on", True)

    mock_config.testarch.atdd_mode = "off"
    assert handler._check_mode(state, "atdd_mode") == ("off", False)

    mock_config.testarch.atdd_mode = "auto"

    # Use a real field in State
    state.atdd_ran_for_story = True
    assert handler._check_mode(state, "atdd_mode", "atdd_ran_for_story") == ("auto", True)

    state.atdd_ran_for_story = False
    assert handler._check_mode(state, "atdd_mode", "atdd_ran_for_story") == ("auto", False)


# =========================================================================
# Output Extraction Tests
# =========================================================================

def test_extract_numeric_score(handler):
    text = "Quality Score: 85/100"
    patterns = [r"Score: (\d+)"]
    assert handler._extract_numeric_score(text, patterns) == 85
    
    text = "Score: 105/100" # Invalid
    assert handler._extract_numeric_score(text, patterns) is None


def test_extract_with_priority(handler):
    text = "Result: PASS but some CONCERNS"
    options = ["FAIL", "CONCERNS", "PASS"]
    assert handler._extract_with_priority(text, options) == "CONCERNS"


def test_extract_file_path(handler):
    text = "Saved to: output/report.md"
    patterns = [r"to: (.*)"]
    assert handler._extract_file_path(text, patterns) == "output/report.md"


# =========================================================================
# Atomic File Operations Tests
# =========================================================================

def test_save_report(handler, tmp_path):
    output_dir = tmp_path / "reports"
    path = handler._save_report(output_dir, "test", "content", "1.1")
    
    assert path.exists()
    assert path.read_text() == "content"
    assert path.name.startswith("test-1.1-")


# =========================================================================
# State Helpers Tests
# =========================================================================

def test_is_first_story_in_epic(handler):
    state = State(current_story="1.1")
    assert handler._is_first_story_in_epic(state) is True
    
    state = State(current_story="1.2")
    assert handler._is_first_story_in_epic(state) is False

    state = State(current_story="testarch.1")
    assert handler._is_first_story_in_epic(state) is True


def test_get_story_file_path(handler, project_path):
    # Setup
    artifacts = project_path / "_bmad-output" / "implementation-artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "10-2-my-story.md").touch()
    
    state = State(current_epic="10", current_story="10.2")
    
    path = handler._get_story_file_path(state)
    assert path is not None
    assert path.name == "10-2-my-story.md"


# =========================================================================
# Workflow Invocation Tests
# =========================================================================

@patch("bmad_assist.compiler.compile_workflow")
@patch("bmad_assist.providers.get_provider")
def test_invoke_workflow_real(mock_get_provider, mock_compile, handler):
    mock_provider = MagicMock()
    mock_get_provider.return_value = mock_provider

    # Correctly instantiate ProviderResult with all required args
    mock_provider.invoke.return_value = ProviderResult(
        stdout="Success",
        stderr="",
        exit_code=0,
        duration_ms=100,
        model="mock-model",
        command=("mock", "command")
    )

    mock_compiled = MagicMock()
    mock_compile.return_value = mock_compiled

    # Test successful invocation
    result = handler._invoke_workflow(mock_compiled)
    assert isinstance(result, ProviderResult)
    assert result.stdout == "Success"

    # Test failure (Provider invocation error)
    mock_provider.invoke.side_effect = Exception("Fail")
    result = handler._invoke_workflow(mock_compiled)
    assert isinstance(result, PhaseResult)
    assert result.success is False


# =============================================================================
# Generic Workflow Invocation Tests (AC1)
# =============================================================================


class TestInvokeGenericWorkflow:
    """Tests for _invoke_generic_workflow method."""

    @patch("bmad_assist.testarch.handlers.base.get_paths")
    def test_invoke_generic_workflow_success(self, mock_get_paths, handler, tmp_path):
        """Generic workflow invocation succeeds and returns PhaseResult with standardized keys."""
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_get_paths.return_value = mock_paths

        state = State(current_epic=1, current_story="1.1")

        # Mock _compile_workflow and _invoke_workflow
        with patch.object(handler, "_compile_workflow") as mock_compile:
            with patch.object(handler, "_invoke_workflow") as mock_invoke:
                mock_compiled = MagicMock()
                mock_compiled.context = "<compiled>"
                mock_compile.return_value = mock_compiled

                mock_invoke.return_value = ProviderResult(
                    stdout="Quality Score: 85/100",
                    stderr="",
                    exit_code=0,
                    duration_ms=100,
                    model="test",
                    command=("test",),
                )

                # Define extractor
                def extractor(output: str) -> int:
                    return 85

                result = handler._invoke_generic_workflow(
                    workflow_name="testarch-test",
                    state=state,
                    extractor_fn=extractor,
                    report_dir=tmp_path / "reports",
                    report_prefix="test-report",
                    metric_key="quality_score",
                    file_key="report_file",
                )

                assert result.success is True
                assert result.outputs["response"] == "Quality Score: 85/100"
                assert result.outputs["quality_score"] == 85
                assert "report_file" in result.outputs

    @patch("bmad_assist.testarch.handlers.base.get_paths")
    def test_invoke_generic_workflow_provider_error(self, mock_get_paths, handler, tmp_path):
        """Generic workflow returns fail PhaseResult on provider error (exit_code != 0)."""
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_get_paths.return_value = mock_paths

        state = State(current_epic=1, current_story="1.1")

        with patch.object(handler, "_compile_workflow") as mock_compile:
            with patch.object(handler, "_invoke_workflow") as mock_invoke:
                mock_compiled = MagicMock()
                mock_compiled.context = "<compiled prompt>"  # Required for save_prompt
                mock_compile.return_value = mock_compiled

                mock_invoke.return_value = ProviderResult(
                    stdout="",
                    stderr="Provider crashed",
                    exit_code=1,
                    duration_ms=100,
                    model="test",
                    command=("test",),
                )

                result = handler._invoke_generic_workflow(
                    workflow_name="testarch-test",
                    state=state,
                    extractor_fn=lambda x: None,
                    report_dir=tmp_path / "reports",
                    report_prefix="test-report",
                )

                assert result.success is False
                assert "Provider error" in result.error

    @patch("bmad_assist.testarch.handlers.base.get_paths")
    def test_invoke_generic_workflow_phase_result_failure(self, mock_get_paths, handler, tmp_path):
        """Generic workflow returns failure when _invoke_workflow returns PhaseResult.fail()."""
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_get_paths.return_value = mock_paths

        state = State(current_epic=1, current_story="1.1")

        with patch.object(handler, "_compile_workflow") as mock_compile:
            with patch.object(handler, "_invoke_workflow") as mock_invoke:
                mock_compiled = MagicMock()
                mock_compiled.context = "<compiled prompt>"  # Required for save_prompt
                mock_compile.return_value = mock_compiled

                # Return PhaseResult.fail() instead of ProviderResult
                mock_invoke.return_value = PhaseResult.fail("Workflow failed")

                result = handler._invoke_generic_workflow(
                    workflow_name="testarch-test",
                    state=state,
                    extractor_fn=lambda x: None,
                    report_dir=tmp_path / "reports",
                    report_prefix="test-report",
                )

                assert result.success is False
                assert "Workflow failed" in result.error

    @patch("bmad_assist.testarch.handlers.base.get_paths")
    def test_invoke_generic_workflow_exception(self, mock_get_paths, handler, tmp_path):
        """Generic workflow handles exceptions gracefully."""
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_get_paths.return_value = mock_paths

        state = State(current_epic=1, current_story="1.1")

        with patch.object(handler, "_compile_workflow") as mock_compile:
            mock_compile.side_effect = RuntimeError("Compilation failed")

            result = handler._invoke_generic_workflow(
                workflow_name="testarch-test",
                state=state,
                extractor_fn=lambda x: None,
                report_dir=tmp_path / "reports",
                report_prefix="test-report",
            )

            assert result.success is False
            assert "Compilation failed" in result.error

    @patch("bmad_assist.testarch.handlers.base.get_paths")
    def test_invoke_generic_workflow_with_story_id(self, mock_get_paths, handler, tmp_path):
        """Generic workflow uses provided story_id for report filename."""
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_get_paths.return_value = mock_paths

        state = State(current_epic=1, current_story="1.1")

        with patch.object(handler, "_compile_workflow") as mock_compile:
            with patch.object(handler, "_invoke_workflow") as mock_invoke:
                mock_compiled = MagicMock()
                mock_compiled.context = "<compiled prompt>"  # Required for save_prompt
                mock_compile.return_value = mock_compiled

                mock_invoke.return_value = ProviderResult(
                    stdout="Success",
                    stderr="",
                    exit_code=0,
                    duration_ms=100,
                    model="test",
                    command=("test",),
                )

                result = handler._invoke_generic_workflow(
                    workflow_name="testarch-test",
                    state=state,
                    extractor_fn=lambda x: "extracted",
                    report_dir=tmp_path / "reports",
                    report_prefix="custom",
                    story_id="custom-story-id",
                )

                assert result.success is True
                # Report file should contain custom story ID
                assert "custom-story-id" in result.outputs.get("file", "")


# =============================================================================
# Execute with Mode Check Tests (AC2)
# =============================================================================


class TestExecuteWithModeCheck:
    """Tests for _execute_with_mode_check method."""

    def test_mode_not_configured_returns_skipped(self, mock_config, tmp_path):
        """Returns skipped PhaseResult when testarch not configured."""
        mock_config.testarch = None
        handler = ConcreteHandler(mock_config, tmp_path)
        state = State()

        result = handler._execute_with_mode_check(
            state=state,
            mode_field="atdd_mode",
            state_flag=None,
            workflow_fn=lambda s: PhaseResult.ok({"ran": True}),
            mode_output_key="atdd_mode",
            skip_reason_auto="no ATDD ran for story",
        )

        assert result.success is True
        assert result.outputs["skipped"] is True
        assert result.outputs["reason"] == "testarch not configured"
        assert result.outputs["atdd_mode"] == "not_configured"

    def test_mode_off_returns_skipped(self, mock_config, tmp_path):
        """Returns skipped PhaseResult when mode=off."""
        mock_config.testarch.test_mode = "off"
        handler = ConcreteHandler(mock_config, tmp_path)
        state = State()

        result = handler._execute_with_mode_check(
            state=state,
            mode_field="test_mode",
            state_flag=None,
            workflow_fn=lambda s: PhaseResult.ok({"ran": True}),
            mode_output_key="test_mode",
            skip_reason_auto="no tests ran",
        )

        assert result.success is True
        assert result.outputs["skipped"] is True
        assert result.outputs["reason"] == "test_mode=off"
        assert result.outputs["test_mode"] == "off"

    def test_mode_auto_with_false_flag_returns_skipped(self, mock_config, tmp_path):
        """Returns skipped PhaseResult when mode=auto and state flag is False."""
        mock_config.testarch.trace_mode = "auto"
        handler = ConcreteHandler(mock_config, tmp_path)
        state = State(atdd_ran_in_epic=False)

        result = handler._execute_with_mode_check(
            state=state,
            mode_field="trace_mode",
            state_flag="atdd_ran_in_epic",
            workflow_fn=lambda s: PhaseResult.ok({"ran": True}),
            mode_output_key="trace_mode",
            skip_reason_auto="no ATDD ran in epic",
        )

        assert result.success is True
        assert result.outputs["skipped"] is True
        assert result.outputs["reason"] == "no ATDD ran in epic"
        assert result.outputs["trace_mode"] == "auto"

    def test_mode_auto_with_true_flag_calls_workflow(self, mock_config, tmp_path):
        """Calls workflow function when mode=auto and state flag is True."""
        mock_config.testarch.test_mode = "auto"
        handler = ConcreteHandler(mock_config, tmp_path)
        state = State(atdd_ran_for_story=True)

        workflow_called = []
        def workflow_fn(s):
            workflow_called.append(True)
            return PhaseResult.ok({"ran": True})

        result = handler._execute_with_mode_check(
            state=state,
            mode_field="test_mode",
            state_flag="atdd_ran_for_story",
            workflow_fn=workflow_fn,
            mode_output_key="test_mode",
            skip_reason_auto="no tests ran",
        )

        assert result.success is True
        assert len(workflow_called) == 1
        assert result.outputs["ran"] is True
        assert result.outputs["test_mode"] == "auto"

    def test_mode_on_calls_workflow(self, mock_config, tmp_path):
        """Calls workflow function when mode=on."""
        mock_config.testarch.atdd_mode = "on"
        handler = ConcreteHandler(mock_config, tmp_path)
        state = State()

        workflow_called = []
        def workflow_fn(s):
            workflow_called.append(True)
            return PhaseResult.ok({"ran": True})

        result = handler._execute_with_mode_check(
            state=state,
            mode_field="atdd_mode",
            state_flag=None,
            workflow_fn=workflow_fn,
            mode_output_key="atdd_mode",
            skip_reason_auto="no ATDD ran",
        )

        assert result.success is True
        assert len(workflow_called) == 1
        assert result.outputs["ran"] is True
        assert result.outputs["atdd_mode"] == "on"

    def test_workflow_failure_propagates(self, mock_config, tmp_path):
        """Workflow failure is propagated with mode in outputs."""
        mock_config.testarch.test_mode = "on"
        handler = ConcreteHandler(mock_config, tmp_path)
        state = State()

        def workflow_fn(s):
            return PhaseResult.fail("Workflow crashed")

        result = handler._execute_with_mode_check(
            state=state,
            mode_field="test_mode",
            state_flag=None,
            workflow_fn=workflow_fn,
            mode_output_key="test_mode",
            skip_reason_auto="no tests ran",
        )

        assert result.success is False
        assert "Workflow crashed" in result.error

    def test_mode_auto_without_flag_calls_workflow(self, mock_config, tmp_path):
        """Calls workflow when mode=auto and state_flag is None."""
        mock_config.testarch.atdd_mode = "auto"
        handler = ConcreteHandler(mock_config, tmp_path)
        state = State()

        workflow_called = []
        def workflow_fn(s):
            workflow_called.append(True)
            return PhaseResult.ok({"ran": True})

        result = handler._execute_with_mode_check(
            state=state,
            mode_field="atdd_mode",
            state_flag=None,  # No flag to check
            workflow_fn=workflow_fn,
            mode_output_key="atdd_mode",
            skip_reason_auto="no ATDD ran",
        )

        assert result.success is True
        assert len(workflow_called) == 1
        assert result.outputs["ran"] is True

# =============================================================================
# Testarch retry + fallback (Task 14)
# =============================================================================
#
# _invoke_workflow used to call provider.invoke() directly, bypassing
# invoke_with_timeout_retry. That meant a single timeout on e.g.
# opencode/glm-5.1 killed the phase with no retry and no fallback.
# These tests assert the new behavior: retry N times on timeout, then
# fall back to a secondary provider if one is resolved.


from bmad_assist.core.exceptions import ProviderTimeoutError as _ProviderTimeoutError


def _ok_result(stdout: str = "OK", model: str = "mock-model") -> ProviderResult:
    return ProviderResult(
        stdout=stdout,
        stderr="",
        exit_code=0,
        duration_ms=50,
        model=model,
        command=("mock",),
    )


class TestInvokeWorkflowRetryWrapper:
    """_invoke_workflow routes through invoke_with_timeout_retry."""

    def test_no_retries_configured_is_single_attempt(
        self, handler, mock_config
    ) -> None:
        """config.timeouts=None → legacy single-attempt behavior."""
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock-provider"
        mock_provider.invoke.return_value = _ok_result()
        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled/>"

        with patch(
            "bmad_assist.providers.get_provider",
            return_value=mock_provider,
        ):
            result = handler._invoke_workflow(mock_compiled)

        assert isinstance(result, ProviderResult)
        assert mock_provider.invoke.call_count == 1

    def test_retries_on_timeout_then_succeeds(
        self, handler, mock_config
    ) -> None:
        """With retries=2, a timeout + success = 2 total attempts."""
        mock_config.timeouts = MagicMock()
        mock_config.timeouts.get_retries.return_value = 2

        mock_provider = MagicMock()
        mock_provider.provider_name = "mock-provider"
        # First call raises, second succeeds
        mock_provider.invoke.side_effect = [
            _ProviderTimeoutError("slow"),
            _ok_result(),
        ]
        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled/>"

        with patch(
            "bmad_assist.providers.get_provider",
            return_value=mock_provider,
        ):
            result = handler._invoke_workflow(mock_compiled)

        assert isinstance(result, ProviderResult)
        assert mock_provider.invoke.call_count == 2

    def test_retries_exhausted_without_fallback_returns_fail(
        self, handler, mock_config
    ) -> None:
        """Retries exhausted + no fallback → PhaseResult.fail with timeout message."""
        mock_config.timeouts = MagicMock()
        mock_config.timeouts.get_retries.return_value = 1

        mock_provider = MagicMock()
        mock_provider.provider_name = "mock-provider"
        mock_provider.invoke.side_effect = _ProviderTimeoutError("stuck")
        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled/>"

        with patch(
            "bmad_assist.providers.get_provider",
            return_value=mock_provider,
        ):
            result = handler._invoke_workflow(mock_compiled)

        assert isinstance(result, PhaseResult)
        assert result.success is False
        # Error message surfaces the phase name + timeout context
        assert "test_phase" in (result.error or "") or "timeout" in (result.error or "").lower()
        # Primary tried retries+1 times (1 retry = 2 attempts)
        assert mock_provider.invoke.call_count == 2


class TestInvokeWorkflowFallbackResolution:
    """_resolve_testarch_fallback picks the right fallback for each primary."""

    def test_claude_primary_falls_back_to_subprocess(
        self, handler, mock_config
    ) -> None:
        """primary='claude' → ClaudeSubprocessProvider fallback (legacy)."""
        mock_config.providers.master.provider = "claude"
        fn, model, display = handler._resolve_testarch_fallback("claude")
        assert fn is not None
        # Claude fallback reuses the primary model (subprocess path).
        assert model is None
        assert display is None
        # The returned callable is a ClaudeSubprocessProvider.invoke bound method.
        assert "ClaudeSubprocess" in type(fn.__self__).__name__  # type: ignore[attr-defined]

    def test_helper_fallback_when_configured_and_different(
        self, handler, mock_config
    ) -> None:
        """Non-claude primary + helper configured → helper as fallback."""
        mock_config.providers.master.provider = "opencode"
        mock_config.providers.helper = MagicMock()
        mock_config.providers.helper.provider = "claude"
        mock_config.providers.helper.model = "haiku"
        mock_config.providers.helper.display_model = "haiku"

        helper_provider = MagicMock()
        helper_provider.invoke = MagicMock()

        with patch(
            "bmad_assist.providers.get_provider",
            return_value=helper_provider,
        ):
            fn, model, display = handler._resolve_testarch_fallback("opencode")

        assert fn is helper_provider.invoke
        assert model == "haiku"
        assert display == "haiku"

    def test_no_fallback_when_helper_provider_matches_primary(
        self, handler, mock_config
    ) -> None:
        """If helper uses the same provider family as primary → no fallback."""
        mock_config.providers.master.provider = "opencode"
        mock_config.providers.helper = MagicMock()
        mock_config.providers.helper.provider = "opencode"
        mock_config.providers.helper.model = "something-else"

        fn, model, display = handler._resolve_testarch_fallback("opencode")

        assert fn is None
        assert model is None
        assert display is None

    def test_no_fallback_when_helper_unset(self, handler, mock_config) -> None:
        """Helper is None → no fallback."""
        mock_config.providers.master.provider = "opencode"
        mock_config.providers.helper = None
        fn, model, display = handler._resolve_testarch_fallback("opencode")
        assert (fn, model, display) == (None, None, None)


class TestInvokeWorkflowHelperFallbackEndToEnd:
    """Primary timeout exhausted → helper fallback actually invoked."""

    def test_primary_timeout_triggers_helper_fallback(
        self, handler, mock_config
    ) -> None:
        """When primary exhausts retries, helper is invoked with its own model."""
        mock_config.timeouts = MagicMock()
        mock_config.timeouts.get_retries.return_value = 1
        # Set up helper
        mock_config.providers.master.provider = "opencode"
        mock_config.providers.master.model = "glm-5.1"
        mock_config.providers.master.display_model = "glm-5.1"
        mock_config.providers.helper = MagicMock()
        mock_config.providers.helper.provider = "claude"
        mock_config.providers.helper.model = "haiku"
        mock_config.providers.helper.display_model = "haiku"

        primary = MagicMock()
        primary.provider_name = "opencode"
        primary.invoke.side_effect = _ProviderTimeoutError("stuck")

        helper = MagicMock()
        helper.invoke.return_value = _ok_result(stdout="from helper", model="haiku")

        def _get_provider(name: str):
            if name == "opencode":
                return primary
            if name == "claude":
                return helper
            raise AssertionError(f"unexpected provider {name}")

        mock_compiled = MagicMock()
        mock_compiled.context = "<compiled/>"

        with patch(
            "bmad_assist.providers.get_provider",
            side_effect=_get_provider,
        ):
            result = handler._invoke_workflow(mock_compiled)

        # Primary was tried (retries+1 = 2 attempts), fallback took over.
        assert primary.invoke.call_count == 2
        assert helper.invoke.call_count == 1
        # Helper was called with its own model, not the primary model.
        helper_call_kwargs = helper.invoke.call_args.kwargs
        assert helper_call_kwargs["model"] == "haiku"
        assert helper_call_kwargs["display_model"] == "haiku"
        # Result came from helper
        assert isinstance(result, ProviderResult)
        assert result.stdout == "from helper"
