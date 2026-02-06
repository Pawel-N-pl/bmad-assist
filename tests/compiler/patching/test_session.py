"""Tests for LLM session orchestrator."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bmad_assist.compiler.patching.config import reset_patcher_config
from bmad_assist.compiler.patching.session import (
    PatchSession,
    extract_workflow_from_response,
)
from bmad_assist.compiler.patching.types import TransformResult
from bmad_assist.core.exceptions import PatchError
from bmad_assist.providers.base import BaseProvider, ProviderResult


@pytest.fixture(autouse=True)
def reset_config() -> None:
    """Reset patcher config before each test."""
    reset_patcher_config()


class MockProvider(BaseProvider):
    """Mock provider for testing."""

    def __init__(self, responses: list[str] | None = None) -> None:
        """Initialize with predefined responses."""
        self.responses = responses or []
        self.call_index = 0
        self.prompts: list[str] = []
        self.disable_tools_calls: list[bool] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    def invoke(
        self,
        prompt: str,
        *,
        model: str | None = None,
        display_model: str | None = None,
        timeout: int | None = None,
        settings_file: Path | None = None,
        cwd: Path | None = None,
        disable_tools: bool = False,
        no_cache: bool = False,
    ) -> ProviderResult:
        self.prompts.append(prompt)
        self.disable_tools_calls.append(disable_tools)
        if self.call_index < len(self.responses):
            response = self.responses[self.call_index]
            self.call_index += 1
            return ProviderResult(
                stdout=response,
                stderr="",
                exit_code=0,
                duration_ms=100,
                model=model,
                command=("mock",),
            )
        raise RuntimeError("No more mock responses")

    def parse_output(self, result: ProviderResult) -> str:
        return result.stdout

    def supports_model(self, model: str) -> bool:
        return True


class TestExtractWorkflowFromResponse:
    """Tests for workflow extraction from LLM response."""

    def test_extract_transformed_document_tag(self) -> None:
        """Test extracting content from transformed-document tags."""
        response = """Here's the modified document:

<transformed-document>
<step n="1">Modified content</step>
</transformed-document>

That completes the transformation."""

        result = extract_workflow_from_response(response)

        assert "<step n=" in result
        assert "Modified content" in result

    def test_extract_workflow_tag_fallback(self) -> None:
        """Test extracting from workflow tags as fallback."""
        response = """<workflow>
<step n="1">Content</step>
</workflow>"""

        result = extract_workflow_from_response(response)

        assert "<step n=" in result
        assert "Content" in result

    def test_extract_no_tag_returns_none(self) -> None:
        """Test that missing tags returns None."""
        response = "Here's some text without the proper tags."

        result = extract_workflow_from_response(response)

        assert result is None

    def test_extract_preserves_content(self) -> None:
        """Test that content is preserved exactly."""
        content = """<step n="1">
  <action>First action</action>
</step>"""
        response = f"<transformed-document>{content}</transformed-document>"

        result = extract_workflow_from_response(response)

        assert result is not None
        assert result.strip() == content.strip()


class TestPatchSession:
    """Tests for PatchSession class."""

    def test_session_init(self) -> None:
        """Test session initialization."""
        instructions = ["Remove step 1"]
        session = PatchSession(
            workflow_content="<workflow/>",
            instructions=instructions,
            provider=MockProvider(),
        )

        assert session.workflow_content == "<workflow/>"
        assert len(session.instructions) == 1

    def test_session_run_success(self) -> None:
        """Test successful session run."""
        instructions = ["Remove step 1"]
        provider = MockProvider(
            responses=["<transformed-document><step n='2'/></transformed-document>"]
        )

        session = PatchSession(
            workflow_content="<step n='1'/><step n='2'/>",
            instructions=instructions,
            provider=provider,
        )

        result_workflow, results = session.run()

        assert "<step n='2'/>" in result_workflow
        assert len(results) == 1
        assert results[0].success is True
        # Verify tools were disabled
        assert provider.disable_tools_calls[0] is True

    def test_session_run_multiple_instructions(self) -> None:
        """Test session with multiple instructions."""
        instructions = [
            "Remove step 1",
            "Simplify step 2",
        ]
        provider = MockProvider(
            responses=["<transformed-document><step n='2'>Simplified</step></transformed-document>"]
        )

        session = PatchSession(
            workflow_content="<step n='1'/><step n='2'>Original</step>",
            instructions=instructions,
            provider=provider,
        )

        result_workflow, results = session.run()

        # Single LLM call for all instructions
        assert len(provider.prompts) == 1
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_session_prompt_includes_all_instructions(self) -> None:
        """Test that prompt includes all instructions."""
        instructions = [
            "Remove step 1",
            "Simplify the instructions",
        ]
        provider = MockProvider(
            responses=["<transformed-document><modified/></transformed-document>"]
        )

        session = PatchSession(
            workflow_content="<original/>",
            instructions=instructions,
            provider=provider,
        )

        session.run()

        # Check prompt contains both instructions
        assert len(provider.prompts) == 1
        prompt = provider.prompts[0]
        assert "Remove step 1" in prompt
        assert "Simplify the instructions" in prompt

    def test_session_retries_on_missing_tag(self) -> None:
        """Test that session retries when tag is missing."""
        instructions = ["Remove step"]
        provider = MockProvider(
            responses=[
                "Response without proper tag",
                "<transformed-document><modified/></transformed-document>",
            ]
        )

        session = PatchSession(
            workflow_content="<original/>",
            instructions=instructions,
            provider=provider,
        )

        result_workflow, results = session.run()

        assert len(provider.prompts) == 2
        assert "<modified/>" in result_workflow
        assert results[0].success is True

    def test_session_fails_after_retries(self) -> None:
        """Test that session fails after retries exhausted."""
        instructions = ["Remove step"]
        provider = MockProvider(
            responses=[
                "Bad response 1",
                "Bad response 2",
            ]
        )

        session = PatchSession(
            workflow_content="<original/>",
            instructions=instructions,
            provider=provider,
        )

        result_workflow, results = session.run()

        assert len(results) == 1
        assert results[0].success is False
        assert (
            "transformed-document" in results[0].reason.lower()
            or "tag" in results[0].reason.lower()
        )

    def test_session_detects_no_change(self) -> None:
        """Test that session detects when LLM returns unchanged content."""
        original = "<step/>"
        instructions = ["Remove something"]
        provider = MockProvider(
            responses=[
                f"<transformed-document>{original}</transformed-document>",
                "<transformed-document><modified/></transformed-document>",
            ]
        )

        session = PatchSession(
            workflow_content=original,
            instructions=instructions,
            provider=provider,
        )

        result_workflow, results = session.run()

        # Should retry when no change detected
        assert len(provider.prompts) == 2
        assert results[0].success is True

    def test_session_uses_timeout_and_disable_tools(self) -> None:
        """Test that session passes timeout and disable_tools to provider."""
        instructions = ["Remove step"]
        provider = MagicMock(spec=BaseProvider)
        provider.parse_output.return_value = (
            "<transformed-document><modified/></transformed-document>"
        )
        provider.invoke.return_value = ProviderResult(
            stdout="<transformed-document><modified/></transformed-document>",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model=None,
            command=("mock",),
        )

        session = PatchSession(
            workflow_content="<original/>",
            instructions=instructions,
            provider=provider,
            timeout=120,
        )

        session.run()

        provider.invoke.assert_called_once()
        call_kwargs = provider.invoke.call_args[1]
        assert call_kwargs.get("timeout") == 120
        assert call_kwargs.get("disable_tools") is True


class TestPatchSessionErrors:
    """Tests for error handling in PatchSession."""

    def test_session_raises_on_empty_instructions(self) -> None:
        """Test that session raises error for empty instructions list."""
        with pytest.raises(PatchError) as exc_info:
            PatchSession(
                workflow_content="<workflow/>",
                instructions=[],
                provider=MockProvider(),
            )

        assert "empty" in str(exc_info.value).lower()

    def test_session_raises_on_empty_workflow(self) -> None:
        """Test that session raises error for empty workflow content."""
        with pytest.raises(PatchError) as exc_info:
            PatchSession(
                workflow_content="",
                instructions=["Remove step"],
                provider=MockProvider(),
            )

        assert "empty" in str(exc_info.value).lower()

    def test_session_handles_provider_error(self) -> None:
        """Test that session handles provider errors gracefully."""
        instructions = ["Remove step"]

        provider = MagicMock(spec=BaseProvider)
        provider.invoke.side_effect = RuntimeError("Provider crashed")

        session = PatchSession(
            workflow_content="<workflow/>",
            instructions=instructions,
            provider=provider,
        )

        result_workflow, results = session.run()

        assert len(results) == 1
        assert results[0].success is False
        assert "Provider" in results[0].reason or "error" in results[0].reason.lower()
