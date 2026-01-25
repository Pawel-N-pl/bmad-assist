"""Unit tests for CursorAgentProvider implementation.

Tests cover the Popen-based Cursor Agent provider for Multi-LLM validation.

Tests cover:
- AC1: CursorAgentProvider extends BaseProvider
- AC2: provider_name returns "cursor-agent"
- AC3: default_model returns "claude-sonnet-4"
- AC4: supports_model() always returns True (CLI validates models)
- AC5: invoke() builds correct command
- AC6: invoke() returns ProviderResult on success
- AC7: invoke() raises ProviderTimeoutError on timeout
- AC8: invoke() raises ProviderExitCodeError on non-zero exit
- AC9: invoke() raises ProviderError when CLI not found
- AC10: parse_output() extracts response from stdout
- AC11: Settings file handling
- AC12: Retry logic for transient failures
"""

from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers import BaseProvider, ProviderResult
from bmad_assist.providers.cursor_agent import (
    DEFAULT_TIMEOUT,
    PROMPT_TRUNCATE_LENGTH,
    CursorAgentProvider,
    _truncate_prompt,
)

from .conftest import create_cursor_agent_mock_process


class TestCursorAgentProviderStructure:
    """Test AC1, AC2, AC3: CursorAgentProvider class definition."""

    def test_provider_inherits_from_baseprovider(self) -> None:
        """Test AC1: CursorAgentProvider inherits from BaseProvider."""
        assert issubclass(CursorAgentProvider, BaseProvider)

    def test_provider_has_class_docstring(self) -> None:
        """Test AC1: CursorAgentProvider has docstring explaining its purpose."""
        assert CursorAgentProvider.__doc__ is not None
        assert "cursor" in CursorAgentProvider.__doc__.lower()

    def test_provider_name_returns_cursor_agent(self) -> None:
        """Test AC2: provider_name returns 'cursor-agent'."""
        provider = CursorAgentProvider()
        assert provider.provider_name == "cursor-agent"

    def test_default_model_returns_valid_model(self) -> None:
        """Test AC3: default_model returns a non-empty string."""
        provider = CursorAgentProvider()
        assert provider.default_model is not None
        assert isinstance(provider.default_model, str)
        assert len(provider.default_model) > 0

    def test_default_model_returns_claude_sonnet_4(self) -> None:
        """Test AC3: default_model returns 'claude-sonnet-4'."""
        provider = CursorAgentProvider()
        assert provider.default_model == "claude-sonnet-4"


class TestCursorAgentProviderModels:
    """Test AC4: supports_model() always returns True."""

    @pytest.fixture
    def provider(self) -> CursorAgentProvider:
        """Create CursorAgentProvider instance."""
        return CursorAgentProvider()

    def test_supports_model_always_returns_true(self, provider: CursorAgentProvider) -> None:
        """Test AC4: supports_model() always returns True - CLI validates models."""
        assert provider.supports_model("claude-sonnet-4") is True
        assert provider.supports_model("gpt-4o") is True
        assert provider.supports_model("gemini-pro") is True
        assert provider.supports_model("any-model") is True
        assert provider.supports_model("") is True


class TestCursorAgentProviderInvoke:
    """Test AC5, AC6: invoke() success cases."""

    @pytest.fixture
    def provider(self) -> CursorAgentProvider:
        """Create CursorAgentProvider instance."""
        return CursorAgentProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation."""
        with patch("bmad_assist.providers.cursor_agent.Popen") as mock:
            mock.return_value = create_cursor_agent_mock_process(
                response_text="Code review complete",
                returncode=0,
            )
            yield mock

    def test_invoke_builds_correct_command(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke() builds command with correct flags."""
        provider.invoke("Review code", model="claude-sonnet-4")

        mock_popen_success.assert_called_once()
        call_args = mock_popen_success.call_args
        command = call_args[0][0]

        assert command[0] == "cursor-agent"
        assert "--print" in command
        assert "--model" in command
        assert "claude-sonnet-4" in command
        assert "--force" in command

    def test_invoke_uses_default_model_when_none(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke(model=None) uses default_model."""
        provider.invoke("Hello", model=None)

        command = mock_popen_success.call_args[0][0]
        assert "claude-sonnet-4" in command

    def test_invoke_returns_providerresult_on_success(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: invoke() returns ProviderResult on exit code 0."""
        result = provider.invoke("Hello", model="claude-sonnet-4", timeout=30)

        assert isinstance(result, ProviderResult)

    def test_invoke_providerresult_has_stdout(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.stdout contains output."""
        result = provider.invoke("Hello")

        assert result.stdout.rstrip("\n") == "Code review complete"

    def test_invoke_providerresult_has_exit_code(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.exit_code is 0 on success."""
        result = provider.invoke("Hello")

        assert result.exit_code == 0

    def test_invoke_providerresult_has_duration_ms(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.duration_ms is positive integer."""
        result = provider.invoke("Hello")

        assert isinstance(result.duration_ms, int)
        assert result.duration_ms >= 0

    def test_invoke_providerresult_has_model(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.model contains the model used."""
        result = provider.invoke("Hello", model="gpt-4o")

        assert result.model == "gpt-4o"

    def test_invoke_providerresult_has_command_tuple(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.command is tuple of command executed."""
        result = provider.invoke("Hello", model="claude-sonnet-4")

        assert isinstance(result.command, tuple)
        assert result.command[0] == "cursor-agent"


class TestCursorAgentProviderErrors:
    """Test AC7, AC8, AC9: Error handling."""

    @pytest.fixture
    def provider(self) -> CursorAgentProvider:
        """Create CursorAgentProvider instance."""
        return CursorAgentProvider()

    def test_invoke_raises_timeout_error(self, provider: CursorAgentProvider) -> None:
        """Test AC7: invoke() raises ProviderTimeoutError on timeout."""
        with patch("bmad_assist.providers.cursor_agent.Popen") as mock_popen:
            mock_popen.return_value = create_cursor_agent_mock_process(
                wait_side_effect=TimeoutExpired(cmd=["cursor-agent"], timeout=5)
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert "timeout" in str(exc_info.value).lower()
            assert exc_info.value.partial_result is not None

    def test_invoke_raises_exit_code_error(self, provider: CursorAgentProvider) -> None:
        """Test AC8: invoke() raises ProviderExitCodeError on non-zero exit."""
        with patch("bmad_assist.providers.cursor_agent.Popen") as mock_popen:
            mock_popen.return_value = create_cursor_agent_mock_process(
                stdout_content="",
                stderr_content="Error: API limit exceeded",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert exc_info.value.exit_code == 1
            assert "API limit exceeded" in str(exc_info.value)

    def test_invoke_raises_provider_error_when_cli_not_found(
        self, provider: CursorAgentProvider
    ) -> None:
        """Test AC9: invoke() raises ProviderError when CLI not found."""
        with patch("bmad_assist.providers.cursor_agent.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("cursor-agent")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert "not found" in str(exc_info.value).lower()

    def test_invoke_invalid_timeout_raises_value_error(
        self, provider: CursorAgentProvider
    ) -> None:
        """Test invoke() raises ValueError for invalid timeout."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=0)

        assert "positive" in str(exc_info.value)

        with pytest.raises(ValueError):
            provider.invoke("Hello", timeout=-1)


class TestCursorAgentProviderSettings:
    """Test AC11: Settings file handling."""

    @pytest.fixture
    def provider(self) -> CursorAgentProvider:
        """Create CursorAgentProvider instance."""
        return CursorAgentProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation."""
        with patch("bmad_assist.providers.cursor_agent.Popen") as mock:
            mock.return_value = create_cursor_agent_mock_process(
                response_text="Response",
                returncode=0,
            )
            yield mock

    def test_invoke_accepts_settings_file(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test invoke() accepts settings_file parameter."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{}")

        provider.invoke("Hello", settings_file=settings_path)
        mock_popen_success.assert_called_once()

    def test_invoke_without_settings_file(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() works without settings_file."""
        provider.invoke("Hello")
        mock_popen_success.assert_called_once()


class TestCursorAgentProviderUnicode:
    """Test Unicode handling in CursorAgentProvider."""

    @pytest.fixture
    def provider(self) -> CursorAgentProvider:
        """Create CursorAgentProvider instance."""
        return CursorAgentProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation."""
        with patch("bmad_assist.providers.cursor_agent.Popen") as mock:
            mock.return_value = create_cursor_agent_mock_process(
                response_text="Response with emoji 🎉",
                returncode=0,
            )
            yield mock

    def test_invoke_with_emoji_in_prompt(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles emoji in prompt correctly."""
        result = provider.invoke("Review code 🔍")

        command = mock_popen_success.call_args[0][0]
        assert "Review code 🔍" in command
        assert isinstance(result.stdout, str)

    def test_invoke_with_chinese_characters(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles Chinese characters correctly."""
        result = provider.invoke("代码审查")

        command = mock_popen_success.call_args[0][0]
        assert "代码审查" in command
        assert isinstance(result.stdout, str)

    def test_invoke_with_special_characters(
        self, provider: CursorAgentProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles special characters correctly."""
        prompt = 'Review: "code" with $pecial ch@rs & <brackets>'
        result = provider.invoke(prompt)

        command = mock_popen_success.call_args[0][0]
        assert prompt in command
        assert isinstance(result.stdout, str)


class TestCursorAgentProviderRetry:
    """Test retry logic for transient failures."""

    @pytest.fixture
    def provider(self) -> CursorAgentProvider:
        """Create CursorAgentProvider instance."""
        return CursorAgentProvider()

    def test_retries_on_empty_stderr_exit_code_1(
        self, provider: CursorAgentProvider
    ) -> None:
        """Test retry logic triggers on empty stderr with exit code 1."""
        call_count = 0

        def make_process():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return create_cursor_agent_mock_process(
                    stdout_content="",
                    stderr_content="",
                    returncode=1,
                )
            return create_cursor_agent_mock_process(
                response_text="Success",
                returncode=0,
            )

        with patch("bmad_assist.providers.cursor_agent.Popen") as mock_popen, \
             patch("bmad_assist.providers.cursor_agent.time.sleep"):
            mock_popen.side_effect = lambda *args, **kwargs: make_process()

            result = provider.invoke("Hello")

            assert call_count == 3
            assert result.exit_code == 0


class TestParseOutput:
    """Test parse_output() method."""

    @pytest.fixture
    def provider(self) -> CursorAgentProvider:
        """Create CursorAgentProvider instance."""
        return CursorAgentProvider()

    def test_parse_output_strips_whitespace(self, provider: CursorAgentProvider) -> None:
        """Test parse_output() strips leading/trailing whitespace."""
        result = ProviderResult(
            stdout="  Response with whitespace  \n",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="claude-sonnet-4",
            command=("cursor-agent",),
        )

        assert provider.parse_output(result) == "Response with whitespace"

    def test_parse_output_empty_string(self, provider: CursorAgentProvider) -> None:
        """Test parse_output() handles empty stdout."""
        result = ProviderResult(
            stdout="",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="claude-sonnet-4",
            command=("cursor-agent",),
        )

        assert provider.parse_output(result) == ""


class TestTruncatePromptHelper:
    """Test _truncate_prompt() helper function."""

    def test_truncate_prompt_short_unchanged(self) -> None:
        """Test short prompts are not truncated."""
        prompt = "Hello"
        result = _truncate_prompt(prompt)

        assert result == "Hello"

    def test_truncate_prompt_over_length_truncated(self) -> None:
        """Test prompts over PROMPT_TRUNCATE_LENGTH are truncated."""
        prompt = "x" * (PROMPT_TRUNCATE_LENGTH + 1)
        result = _truncate_prompt(prompt)

        assert len(result) == PROMPT_TRUNCATE_LENGTH + 3
        assert result.endswith("...")


class TestConstants:
    """Test module constants."""

    def test_default_timeout_is_300(self) -> None:
        """Test DEFAULT_TIMEOUT is 300 seconds."""
        assert DEFAULT_TIMEOUT == 300

    def test_prompt_truncate_length_is_100(self) -> None:
        """Test PROMPT_TRUNCATE_LENGTH is 100."""
        assert PROMPT_TRUNCATE_LENGTH == 100


class TestDocstringsExist:
    """Verify all public methods have docstrings."""

    def test_module_has_docstring(self) -> None:
        """Test module has docstring."""
        from bmad_assist.providers import cursor_agent

        assert cursor_agent.__doc__ is not None
        assert "cursor" in cursor_agent.__doc__.lower()

    def test_provider_has_docstring(self) -> None:
        """Test CursorAgentProvider has docstring."""
        assert CursorAgentProvider.__doc__ is not None

    def test_invoke_has_docstring(self) -> None:
        """Test invoke() has docstring."""
        assert CursorAgentProvider.invoke.__doc__ is not None

    def test_parse_output_has_docstring(self) -> None:
        """Test parse_output() has docstring."""
        assert CursorAgentProvider.parse_output.__doc__ is not None
