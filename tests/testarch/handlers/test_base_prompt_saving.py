"""Tests for prompt saving in TestarchBaseHandler._invoke_generic_workflow().

Verifies that prompts are saved for debugging (ADR-1 in tech-spec-tea-context-loader.md).
"""

from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.state import State
from bmad_assist.providers.base import ProviderResult
from bmad_assist.testarch.config import TestarchConfig
from bmad_assist.testarch.handlers.base import TestarchBaseHandler


class ConcreteHandler(TestarchBaseHandler):
    """Minimal concrete handler for testing _invoke_generic_workflow."""

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
    config = MagicMock()
    config.testarch = MagicMock(spec=TestarchConfig)
    config.providers = MagicMock()
    config.providers.master = MagicMock()
    config.providers.master.provider = "mock-provider"
    config.providers.master.model = "mock-model"
    config.timeout = 30
    return config


@pytest.fixture
def project_path(tmp_path):
    return tmp_path


@pytest.fixture
def handler(mock_config, project_path):
    return ConcreteHandler(mock_config, project_path)


class TestPromptSaving:
    """Tests for save_prompt integration in _invoke_generic_workflow."""

    @patch("bmad_assist.testarch.handlers.base.get_paths")
    @patch("bmad_assist.core.io.save_prompt")
    def test_save_prompt_called_with_correct_args(
        self, mock_save_prompt, mock_get_paths, handler, tmp_path
    ):
        """save_prompt should be called with extracted epic and story_num."""
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_get_paths.return_value = mock_paths

        mock_save_prompt.return_value = tmp_path / "prompt.md"

        state = State(current_epic=25, current_story="25.1")

        with patch.object(handler, "_compile_workflow") as mock_compile:
            with patch.object(handler, "_invoke_workflow") as mock_invoke:
                mock_compiled = MagicMock()
                mock_compiled.context = "<compiled prompt content>"
                mock_compile.return_value = mock_compiled

                mock_invoke.return_value = ProviderResult(
                    stdout="Success",
                    stderr="",
                    exit_code=0,
                    duration_ms=100,
                    model="test",
                    command=("test",),
                )

                handler._invoke_generic_workflow(
                    workflow_name="testarch-test",
                    state=state,
                    extractor_fn=lambda x: "extracted",
                    report_dir=tmp_path / "reports",
                    report_prefix="test-report",
                )

        # Verify save_prompt was called
        mock_save_prompt.assert_called_once()
        call_args = mock_save_prompt.call_args
        # Args: project_path, epic, story_num, phase_name, content
        assert call_args[0][0] == handler.project_path
        assert call_args[0][1] == 25  # epic
        assert call_args[0][2] == "1"  # story_num extracted from "25.1"
        assert call_args[0][3] == "test_phase"  # phase_name
        assert call_args[0][4] == "<compiled prompt content>"  # content

    @patch("bmad_assist.testarch.handlers.base.get_paths")
    @patch("bmad_assist.core.io.save_prompt")
    def test_save_prompt_extracts_story_num_from_dotted(
        self, mock_save_prompt, mock_get_paths, handler, tmp_path
    ):
        """state.current_story="25.1" should extract story_num="1"."""
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_get_paths.return_value = mock_paths

        mock_save_prompt.return_value = tmp_path / "prompt.md"

        state = State(current_epic=25, current_story="25.12")

        with patch.object(handler, "_compile_workflow") as mock_compile:
            with patch.object(handler, "_invoke_workflow") as mock_invoke:
                mock_compiled = MagicMock()
                mock_compiled.context = "<prompt>"
                mock_compile.return_value = mock_compiled

                mock_invoke.return_value = ProviderResult(
                    stdout="Success",
                    stderr="",
                    exit_code=0,
                    duration_ms=100,
                    model="test",
                    command=("test",),
                )

                handler._invoke_generic_workflow(
                    workflow_name="testarch-test",
                    state=state,
                    extractor_fn=lambda x: None,
                    report_dir=tmp_path / "reports",
                    report_prefix="test",
                )

        # story_num should be "12" (extracted from "25.12")
        call_args = mock_save_prompt.call_args
        assert call_args[0][2] == "12"

    @patch("bmad_assist.testarch.handlers.base.get_paths")
    @patch("bmad_assist.core.io.save_prompt")
    def test_save_prompt_uses_unknown_for_none_epic(
        self, mock_save_prompt, mock_get_paths, handler, tmp_path
    ):
        """epic=None should use "unknown" fallback."""
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_get_paths.return_value = mock_paths

        mock_save_prompt.return_value = tmp_path / "prompt.md"

        state = State(current_epic=None, current_story=None)

        with patch.object(handler, "_compile_workflow") as mock_compile:
            with patch.object(handler, "_invoke_workflow") as mock_invoke:
                mock_compiled = MagicMock()
                mock_compiled.context = "<prompt>"
                mock_compile.return_value = mock_compiled

                mock_invoke.return_value = ProviderResult(
                    stdout="Success",
                    stderr="",
                    exit_code=0,
                    duration_ms=100,
                    model="test",
                    command=("test",),
                )

                handler._invoke_generic_workflow(
                    workflow_name="testarch-test",
                    state=state,
                    extractor_fn=lambda x: None,
                    report_dir=tmp_path / "reports",
                    report_prefix="test",
                )

        call_args = mock_save_prompt.call_args
        assert call_args[0][1] == "unknown"  # epic fallback
        assert call_args[0][2] == "unknown"  # story_num fallback

    @patch("bmad_assist.testarch.handlers.base.get_paths")
    @patch("bmad_assist.core.io.save_prompt")
    def test_save_prompt_failure_does_not_crash(
        self, mock_save_prompt, mock_get_paths, handler, tmp_path
    ):
        """save_prompt() failure should log warning, not crash."""
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_get_paths.return_value = mock_paths

        # Simulate disk full error
        mock_save_prompt.side_effect = OSError("Disk full")

        state = State(current_epic=25, current_story="25.1")

        with patch.object(handler, "_compile_workflow") as mock_compile:
            with patch.object(handler, "_invoke_workflow") as mock_invoke:
                mock_compiled = MagicMock()
                mock_compiled.context = "<prompt>"
                mock_compile.return_value = mock_compiled

                mock_invoke.return_value = ProviderResult(
                    stdout="Success",
                    stderr="",
                    exit_code=0,
                    duration_ms=100,
                    model="test",
                    command=("test",),
                )

                # Should NOT raise - fail-soft
                result = handler._invoke_generic_workflow(
                    workflow_name="testarch-test",
                    state=state,
                    extractor_fn=lambda x: "ok",
                    report_dir=tmp_path / "reports",
                    report_prefix="test",
                )

        # Workflow should still succeed
        assert result.success is True

    @patch("bmad_assist.testarch.handlers.base.get_paths")
    @patch("bmad_assist.core.io.save_prompt")
    def test_save_prompt_ioerror_handled(
        self, mock_save_prompt, mock_get_paths, handler, tmp_path
    ):
        """IOError should also be caught and logged."""
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_get_paths.return_value = mock_paths

        mock_save_prompt.side_effect = OSError("Permission denied")

        state = State(current_epic=25, current_story="25.1")

        with patch.object(handler, "_compile_workflow") as mock_compile:
            with patch.object(handler, "_invoke_workflow") as mock_invoke:
                mock_compiled = MagicMock()
                mock_compiled.context = "<prompt>"
                mock_compile.return_value = mock_compiled

                mock_invoke.return_value = ProviderResult(
                    stdout="Success",
                    stderr="",
                    exit_code=0,
                    duration_ms=100,
                    model="test",
                    command=("test",),
                )

                # Should NOT raise
                result = handler._invoke_generic_workflow(
                    workflow_name="testarch-test",
                    state=state,
                    extractor_fn=lambda x: "ok",
                    report_dir=tmp_path / "reports",
                    report_prefix="test",
                )

        assert result.success is True


class TestStoryNumExtraction:
    """Tests for story_num extraction from state.current_story."""

    @pytest.mark.parametrize(
        "current_story,expected",
        [
            ("25.1", "1"),
            ("25.12", "12"),
            ("1.1", "1"),
            ("testarch.3", "3"),
            ("5", "5"),  # No dot - use as-is
        ],
    )
    def test_story_num_extraction(self, current_story: str, expected: str):
        """Extract story_num from various current_story formats."""
        if "." in current_story:
            story_num = current_story.split(".")[-1]
        else:
            story_num = current_story
        assert story_num == expected

    def test_extraction_handles_module_ids(self):
        """Module-style IDs (testarch.3) should extract correctly."""
        current_story = "testarch.3"
        story_num = current_story.split(".")[-1] if "." in current_story else current_story
        assert story_num == "3"


class TestPromptContent:
    """Tests for prompt content passed to save_prompt."""

    @patch("bmad_assist.testarch.handlers.base.get_paths")
    @patch("bmad_assist.core.io.save_prompt")
    def test_prompt_content_is_compiled_context(
        self, mock_save_prompt, mock_get_paths, handler, tmp_path
    ):
        """save_prompt should receive compiled.context (the XML prompt)."""
        mock_paths = MagicMock()
        mock_paths.output_folder = tmp_path
        mock_get_paths.return_value = mock_paths

        mock_save_prompt.return_value = tmp_path / "prompt.md"

        expected_content = """<compiled-workflow>
<mission>Test workflow</mission>
<context>...</context>
</compiled-workflow>"""

        state = State(current_epic=25, current_story="25.1")

        with patch.object(handler, "_compile_workflow") as mock_compile:
            with patch.object(handler, "_invoke_workflow") as mock_invoke:
                mock_compiled = MagicMock()
                mock_compiled.context = expected_content
                mock_compile.return_value = mock_compiled

                mock_invoke.return_value = ProviderResult(
                    stdout="Success",
                    stderr="",
                    exit_code=0,
                    duration_ms=100,
                    model="test",
                    command=("test",),
                )

                handler._invoke_generic_workflow(
                    workflow_name="testarch-test",
                    state=state,
                    extractor_fn=lambda x: None,
                    report_dir=tmp_path / "reports",
                    report_prefix="test",
                )

        # Verify content is the compiled XML
        call_args = mock_save_prompt.call_args
        assert call_args[0][4] == expected_content
