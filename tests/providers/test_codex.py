"""Unit tests for CodexProvider implementation.

Tests cover the Popen-based Codex provider for Multi-LLM validation with JSON streaming.

Tests cover:
- AC1: CodexProvider extends BaseProvider
- AC2: provider_name returns "codex"
- AC3: default_model returns a valid default model
- AC4: supports_model() always returns True (CLI validates models)
- AC5: invoke() builds correct command with --json flag
- AC6: invoke() returns ProviderResult on success
- AC7: invoke() raises ProviderTimeoutError on timeout
- AC8: invoke() raises ProviderExitCodeError on non-zero exit
- AC9: invoke() raises ProviderError when CLI not found
- AC10: parse_output() extracts response from stdout
- AC11: Package exports CodexProvider
- AC12: Settings file handling
"""

import sys
from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers import BaseProvider, CodexProvider, ProviderResult
from bmad_assist.providers.codex import (
    DEFAULT_TIMEOUT,
    PROMPT_TRUNCATE_LENGTH,
    _truncate_prompt,
)
from .conftest import create_codex_mock_process, make_codex_json_output

# Platform detection for tests
IS_WINDOWS = sys.platform == "win32"


class TestCodexProviderStructure:
    """Test AC1, AC2, AC3: CodexProvider class definition."""

    def test_provider_inherits_from_baseprovider(self) -> None:
        """Test AC1: CodexProvider inherits from BaseProvider."""
        assert issubclass(CodexProvider, BaseProvider)

    def test_provider_has_class_docstring(self) -> None:
        """Test AC1: CodexProvider has docstring explaining its purpose."""
        assert CodexProvider.__doc__ is not None
        assert "codex" in CodexProvider.__doc__.lower()
        assert "subprocess" in CodexProvider.__doc__.lower()

    def test_provider_name_returns_codex(self) -> None:
        """Test AC2: provider_name returns 'codex'."""
        provider = CodexProvider()
        assert provider.provider_name == "codex"

    def test_default_model_returns_valid_model(self) -> None:
        """Test AC3: default_model returns a non-empty string."""
        provider = CodexProvider()
        assert provider.default_model is not None
        assert isinstance(provider.default_model, str)
        assert len(provider.default_model) > 0

    def test_default_model_returns_gpt_5_1_codex_max(self) -> None:
        """Test AC3: default_model returns 'gpt-5.1-codex-max'."""
        provider = CodexProvider()
        assert provider.default_model == "gpt-5.1-codex-max"

    def test_default_model_can_be_overridden_in_subclass(self) -> None:
        """Test AC3: default_model can be overridden via subclass."""

        class CustomProvider(CodexProvider):
            @property
            def default_model(self) -> str | None:
                return "o3"

        provider = CustomProvider()
        assert provider.default_model == "o3"


class TestCodexProviderModels:
    """Test AC4: supports_model() always returns True (CLI validates models)."""

    @pytest.fixture
    def provider(self) -> CodexProvider:
        """Create CodexProvider instance."""
        return CodexProvider()

    def test_supports_model_always_returns_true(self, provider: CodexProvider) -> None:
        """Test AC4: supports_model() always returns True - CLI validates models."""
        # Any model string should return True - validation is delegated to CLI
        assert provider.supports_model("o3") is True
        assert provider.supports_model("o3-mini") is True
        assert provider.supports_model("gpt-4.1") is True
        assert provider.supports_model("any-future-model") is True
        assert provider.supports_model("claude-sonnet") is True  # Even non-OpenAI models
        assert provider.supports_model("unknown") is True

    def test_supports_model_empty_string_returns_true(self, provider: CodexProvider) -> None:
        """Test AC4: supports_model('') returns True - CLI will reject if invalid."""
        assert provider.supports_model("") is True

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        assert CodexProvider.supports_model.__doc__ is not None


class TestCodexProviderInvoke:
    """Test AC5, AC6: invoke() success cases with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> CodexProvider:
        """Create CodexProvider instance."""
        return CodexProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation with JSON streaming."""
        with patch("bmad_assist.providers.codex.Popen") as mock:
            mock.return_value = create_codex_mock_process(
                response_text="Code review complete",
                returncode=0,
            )
            yield mock

    def test_invoke_builds_correct_command_with_json_flag(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke() builds command with --json flag for streaming."""
        provider.invoke("Review code", model="o3-mini")

        mock_popen_success.assert_called_once()
        call_args = mock_popen_success.call_args
        command = call_args[0][0]

        # For short prompts, uses direct command passing (cross-platform)
        assert command[0] == "codex"
        assert "exec" in command
        assert "--json" in command
        assert "--full-auto" in command
        assert "-m" in command
        assert "o3-mini" in command

    def test_invoke_uses_default_model_when_none(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke(model=None) uses default_model ('gpt-5.1-codex-max')."""
        provider.invoke("Hello", model=None)

        command = mock_popen_success.call_args[0][0]
        # For short prompts, uses direct command passing
        assert command[0] == "codex"
        assert "-m" in command
        model_idx = command.index("-m")
        assert command[model_idx + 1] == "gpt-5.1-codex-max"

    def test_invoke_uses_default_model_when_not_specified(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke() without model arg uses default_model."""
        provider.invoke("Hello")

        command = mock_popen_success.call_args[0][0]
        # For short prompts, uses direct command passing
        assert command[0] == "codex"
        assert "-m" in command
        model_idx = command.index("-m")
        assert command[model_idx + 1] == "gpt-5.1-codex-max"

    def test_invoke_returns_providerresult_on_success(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: invoke() returns ProviderResult on exit code 0."""
        result = provider.invoke("Hello", model="o3-mini", timeout=30)

        assert isinstance(result, ProviderResult)

    def test_invoke_providerresult_has_stdout(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.stdout contains extracted text from JSON stream."""
        result = provider.invoke("Hello")

        # Text is extracted from item.completed agent_message in JSON stream
        assert result.stdout == "Code review complete"

    def test_invoke_providerresult_has_stderr(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.stderr contains captured stderr."""
        result = provider.invoke("Hello")

        assert result.stderr == ""

    def test_invoke_providerresult_has_exit_code(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.exit_code is 0 on success."""
        result = provider.invoke("Hello")

        assert result.exit_code == 0

    def test_invoke_providerresult_has_duration_ms(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.duration_ms is positive integer."""
        result = provider.invoke("Hello")

        assert isinstance(result.duration_ms, int)
        assert result.duration_ms >= 0

    def test_invoke_providerresult_has_model(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.model contains the model used."""
        result = provider.invoke("Hello", model="gpt-4.1")

        assert result.model == "gpt-4.1"

    def test_invoke_providerresult_model_uses_default_when_none(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.model uses default when model=None."""
        result = provider.invoke("Hello", model=None)

        assert result.model == "gpt-5.1-codex-max"

    def test_invoke_providerresult_has_command_tuple(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.command is tuple of command executed."""
        result = provider.invoke("Hello", model="o3")

        assert isinstance(result.command, tuple)
        # For short prompts, uses direct command passing
        assert result.command[0] == "codex"
        assert "-m" in result.command
        assert "o3" in result.command


class TestCodexProviderErrors:
    """Test AC7, AC8, AC9: Error handling with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> CodexProvider:
        """Create CodexProvider instance."""
        return CodexProvider()

    def test_invoke_raises_provider_timeout_error_on_timeout(self, provider: CodexProvider) -> None:
        """Test AC7: invoke() raises ProviderTimeoutError on wait timeout."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                wait_side_effect=TimeoutExpired(cmd=["codex"], timeout=5)
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert "timeout" in str(exc_info.value).lower()

    def test_invoke_timeout_error_includes_truncated_prompt(self, provider: CodexProvider) -> None:
        """Test AC7: Timeout error includes prompt (truncated if > 100 chars)."""
        long_prompt = "x" * 150

        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                wait_side_effect=TimeoutExpired(cmd=["codex"], timeout=5)
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke(long_prompt, timeout=5)

            error_msg = str(exc_info.value)
            # Should be truncated
            assert "x" * 100 in error_msg
            assert "..." in error_msg
            # Should NOT contain full prompt
            assert "x" * 150 not in error_msg

    def test_invoke_timeout_error_short_prompt_not_truncated(self, provider: CodexProvider) -> None:
        """Test AC7: Short prompts are not truncated in timeout error."""
        short_prompt = "Hello world"

        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                wait_side_effect=TimeoutExpired(cmd=["codex"], timeout=5)
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke(short_prompt, timeout=5)

            error_msg = str(exc_info.value)
            assert "Hello world" in error_msg
            assert "..." not in error_msg

    def test_invoke_timeout_exception_includes_partial_result(
        self, provider: CodexProvider
    ) -> None:
        """Test AC7: Timeout error includes partial_result with collected data."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                wait_side_effect=TimeoutExpired(cmd=["codex"], timeout=5)
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            # Timeout should include partial result
            assert exc_info.value.partial_result is not None
            assert exc_info.value.partial_result.exit_code == -1

    def test_invoke_raises_exit_code_error_on_nonzero_exit(self, provider: CodexProvider) -> None:
        """Test AC8: invoke() raises ProviderExitCodeError on non-zero exit code."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                stdout_content="",
                stderr_content="Error: API rate limit exceeded",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert "exit code 1" in str(exc_info.value).lower()
            assert exc_info.value.exit_code == 1

    def test_invoke_nonzero_exit_includes_stderr(self, provider: CodexProvider) -> None:
        """Test AC8: Non-zero exit error includes stderr content."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                stdout_content="",
                stderr_content="Error: API rate limit exceeded",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert "API rate limit exceeded" in str(exc_info.value)
            # Stderr includes trailing newline from line reading
            assert exc_info.value.stderr.strip() == "Error: API rate limit exceeded"

    def test_invoke_nonzero_exit_includes_exit_status(self, provider: CodexProvider) -> None:
        """Test AC8: Non-zero exit error includes exit_status classification."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                stdout_content="",
                stderr_content="Error",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            from bmad_assist.providers.base import ExitStatus

            assert exc_info.value.exit_status == ExitStatus.ERROR

    def test_invoke_nonzero_exit_includes_command(self, provider: CodexProvider) -> None:
        """Test AC8: Non-zero exit error includes command tuple."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                stdout_content="",
                stderr_content="Error",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello", model="o3-mini")

            # For short prompts, uses direct command passing
            assert exc_info.value.command[0] == "codex"
            assert "-m" in exc_info.value.command
            assert "o3-mini" in exc_info.value.command

    def test_invoke_raises_providererror_when_cli_not_found(self, provider: CodexProvider) -> None:
        """Test AC9: invoke() raises ProviderError on FileNotFoundError."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("codex")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            error_msg = str(exc_info.value).lower()
            assert "not found" in error_msg or "path" in error_msg

    def test_invoke_file_not_found_exception_is_chained(self, provider: CodexProvider) -> None:
        """Test AC9: FileNotFoundError is chained with 'from e'."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("codex")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, FileNotFoundError)

    def test_invoke_accepts_any_model(self, provider: CodexProvider) -> None:
        """Test invoke() accepts any model name - CLI validates models."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                response_text="response",
                returncode=0,
            )
            # Any model should be accepted - CLI validates
            result = provider.invoke("Hello", model="o5-turbo")
            assert result.model == "o5-turbo"

    def test_invoke_raises_valueerror_on_negative_timeout(self, provider: CodexProvider) -> None:
        """Test invoke() raises ValueError for negative timeout."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=-1)

        assert "timeout must be positive" in str(exc_info.value).lower()

    def test_invoke_raises_valueerror_on_zero_timeout(self, provider: CodexProvider) -> None:
        """Test invoke() raises ValueError for zero timeout."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=0)

        assert "timeout must be positive" in str(exc_info.value).lower()


class TestCodexProviderParseOutput:
    """Test AC10: parse_output() functionality."""

    @pytest.fixture
    def provider(self) -> CodexProvider:
        """Create CodexProvider instance."""
        return CodexProvider()

    def test_parse_output_extracts_stdout(self, provider: CodexProvider) -> None:
        """Test AC10: parse_output() returns result.stdout.strip()."""
        result = ProviderResult(
            stdout="Code review complete",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="o3-mini",
            command=("codex", "exec", "Review"),
        )

        parsed = provider.parse_output(result)

        assert parsed == "Code review complete"

    def test_parse_output_strips_whitespace(self, provider: CodexProvider) -> None:
        """Test AC10: parse_output() strips leading/trailing whitespace."""
        result = ProviderResult(
            stdout="  Code review complete  \n",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="o3-mini",
            command=("codex", "exec", "Review"),
        )

        parsed = provider.parse_output(result)

        assert parsed == "Code review complete"

    def test_parse_output_empty_stdout_returns_empty_string(self, provider: CodexProvider) -> None:
        """Test AC10: parse_output() returns empty string for empty stdout."""
        result = ProviderResult(
            stdout="",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="o3-mini",
            command=("codex", "exec", "Review"),
        )

        parsed = provider.parse_output(result)

        assert parsed == ""

    def test_parse_output_whitespace_only_returns_empty(self, provider: CodexProvider) -> None:
        """Test AC10: parse_output() returns empty for whitespace-only stdout."""
        result = ProviderResult(
            stdout="   \n\t  ",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="o3-mini",
            command=("codex", "exec", "Review"),
        )

        parsed = provider.parse_output(result)

        assert parsed == ""

    def test_parse_output_has_docstring(self) -> None:
        """Test parse_output() has docstring explaining format."""
        assert CodexProvider.parse_output.__doc__ is not None
        # Should mention stdout
        doc = CodexProvider.parse_output.__doc__.lower()
        assert "stdout" in doc


class TestCodexProviderExports:
    """Test AC11: Package exports CodexProvider."""

    def test_codexprovider_exported_from_providers(self) -> None:
        """Test AC11: CodexProvider can be imported from providers package."""
        from bmad_assist.providers import CodexProvider as ImportedProvider

        assert ImportedProvider is CodexProvider

    def test_codexprovider_in_all(self) -> None:
        """Test AC11: CodexProvider is in __all__."""
        from bmad_assist import providers

        assert "CodexProvider" in providers.__all__

    def test_providers_all_has_expected_exports(self) -> None:
        """Test __all__ has expected exports including CodexProvider."""
        from bmad_assist import providers

        # Should contain BaseProvider, CodexProvider, ProviderResult
        assert "BaseProvider" in providers.__all__
        assert "CodexProvider" in providers.__all__
        assert "ProviderResult" in providers.__all__


class TestCodexProviderSettings:
    """Test AC12: Settings file handling with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> CodexProvider:
        """Create CodexProvider instance."""
        return CodexProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation with JSON streaming."""
        with patch("bmad_assist.providers.codex.Popen") as mock:
            mock.return_value = create_codex_mock_process(
                response_text="response",
                returncode=0,
            )
            yield mock

    def test_invoke_with_existing_settings_file(
        self, provider: CodexProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test AC12: invoke() validates existing settings file."""
        # Create a real settings file
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"key": "value"}')

        # Should not raise
        provider.invoke("Hello", settings_file=settings_path)
        mock_popen_success.assert_called_once()

    def test_invoke_with_missing_settings_file(
        self, provider: CodexProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test AC12: invoke() gracefully handles missing settings file."""
        settings_path = tmp_path / "nonexistent.json"

        # Should not raise - graceful degradation
        provider.invoke("Hello", settings_file=settings_path)
        mock_popen_success.assert_called_once()

    def test_invoke_without_settings_file(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC12: invoke() works without settings_file."""
        provider.invoke("Hello")
        mock_popen_success.assert_called_once()


class TestCodexProviderUnicode:
    """Test Unicode handling in CodexProvider with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> CodexProvider:
        """Create CodexProvider instance."""
        return CodexProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation with JSON streaming."""
        with patch("bmad_assist.providers.codex.Popen") as mock:
            mock.return_value = create_codex_mock_process(
                response_text="Response with emoji 🎉",
                returncode=0,
            )
            yield mock

    def test_invoke_with_emoji_in_prompt(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles emoji in prompt correctly."""
        result = provider.invoke("Review code 🔍")

        # For short prompts, uses direct command passing
        command = mock_popen_success.call_args[0][0]
        assert command[0] == "codex"
        assert "Review code 🔍" in command
        assert isinstance(result.stdout, str)

    def test_invoke_with_chinese_characters(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles Chinese characters correctly."""
        result = provider.invoke("代码审查")

        # For short prompts, uses direct command passing
        command = mock_popen_success.call_args[0][0]
        assert command[0] == "codex"
        assert "代码审查" in command
        assert isinstance(result.stdout, str)

    def test_invoke_with_cyrillic_characters(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles Cyrillic characters correctly."""
        result = provider.invoke("Проверка кода")

        # For short prompts, uses direct command passing
        command = mock_popen_success.call_args[0][0]
        assert command[0] == "codex"
        assert "Проверка кода" in command
        assert isinstance(result.stdout, str)

    def test_invoke_with_newlines_in_prompt(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles newlines in prompt correctly."""
        prompt = "Line 1\nLine 2\nLine 3"
        result = provider.invoke(prompt)

        # For short prompts, uses direct command passing
        command = mock_popen_success.call_args[0][0]
        assert command[0] == "codex"
        assert prompt in command
        assert isinstance(result.stdout, str)

    def test_invoke_with_special_characters(
        self, provider: CodexProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles special characters correctly."""
        prompt = 'Review: "code" with $pecial ch@rs & <brackets>'
        result = provider.invoke(prompt)

        # For short prompts, uses direct command passing
        command = mock_popen_success.call_args[0][0]
        assert command[0] == "codex"
        assert prompt in command
        assert isinstance(result.stdout, str)

    def test_invoke_handles_replacement_chars_in_output(self, provider: CodexProvider) -> None:
        """Test invoke() handles Unicode replacement characters in output."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            # Output contains Unicode replacement character (U+FFFD)
            mock_popen.return_value = create_codex_mock_process(
                response_text="Response with \ufffd replacement",
                returncode=0,
            )

            result = provider.invoke("Hello")

            # Should preserve replacement char in output
            assert "\ufffd" in result.stdout
            assert "Response with" in result.stdout
            assert isinstance(result.stdout, str)


class TestTruncatePromptHelper:
    """Test _truncate_prompt() helper function."""

    def test_truncate_prompt_short_unchanged(self) -> None:
        """Test short prompts are not truncated."""
        prompt = "Hello"
        result = _truncate_prompt(prompt)

        assert result == "Hello"

    def test_truncate_prompt_exact_length_unchanged(self) -> None:
        """Test prompts at exactly PROMPT_TRUNCATE_LENGTH are not truncated."""
        prompt = "x" * PROMPT_TRUNCATE_LENGTH
        result = _truncate_prompt(prompt)

        assert result == prompt
        assert "..." not in result

    def test_truncate_prompt_over_length_truncated(self) -> None:
        """Test prompts over PROMPT_TRUNCATE_LENGTH are truncated."""
        prompt = "x" * (PROMPT_TRUNCATE_LENGTH + 1)
        result = _truncate_prompt(prompt)

        assert len(result) == PROMPT_TRUNCATE_LENGTH + 3  # +3 for "..."
        assert result.endswith("...")
        assert result.startswith("x" * PROMPT_TRUNCATE_LENGTH)


class TestConstants:
    """Test module constants."""

    def test_default_timeout_is_300(self) -> None:
        """Test DEFAULT_TIMEOUT is 300 seconds (5 minutes)."""
        assert DEFAULT_TIMEOUT == 300

    def test_prompt_truncate_length_is_100(self) -> None:
        """Test PROMPT_TRUNCATE_LENGTH is 100."""
        assert PROMPT_TRUNCATE_LENGTH == 100


class TestDocstringsExist:
    """Verify all public methods have docstrings."""

    def test_module_has_docstring(self) -> None:
        """Test module has docstring."""
        from bmad_assist.providers import codex

        assert codex.__doc__ is not None
        assert "codex" in codex.__doc__.lower()

    def test_provider_has_docstring(self) -> None:
        """Test CodexProvider has docstring."""
        assert CodexProvider.__doc__ is not None

    def test_provider_name_has_docstring(self) -> None:
        """Test provider_name property has docstring."""
        fget = CodexProvider.provider_name.fget
        assert fget is not None
        assert fget.__doc__ is not None

    def test_default_model_has_docstring(self) -> None:
        """Test default_model property has docstring."""
        fget = CodexProvider.default_model.fget
        assert fget is not None
        assert fget.__doc__ is not None

    def test_invoke_has_docstring(self) -> None:
        """Test invoke() has docstring."""
        assert CodexProvider.invoke.__doc__ is not None

    def test_invoke_has_google_style_docstring(self) -> None:
        """Test invoke() has Google-style docstring."""
        doc = CodexProvider.invoke.__doc__
        assert doc is not None
        assert "Args:" in doc
        assert "Returns:" in doc
        assert "Raises:" in doc

    def test_parse_output_has_docstring(self) -> None:
        """Test parse_output() has docstring."""
        assert CodexProvider.parse_output.__doc__ is not None

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        assert CodexProvider.supports_model.__doc__ is not None


class TestCodexProviderExitStatusHandling:
    """Test exit status semantic classification with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> CodexProvider:
        """Create CodexProvider instance."""
        return CodexProvider()

    def test_signal_exit_code_137_includes_signal_number(self, provider: CodexProvider) -> None:
        """Test exit code 137 (SIGKILL) includes signal number in message."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                stdout_content="",
                stderr_content="Killed",
                returncode=137,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert "signal 9" in str(exc_info.value).lower()

    def test_exit_code_127_not_found(self, provider: CodexProvider) -> None:
        """Test exit code 127 (command not found) message."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                stdout_content="",
                stderr_content="command not found",
                returncode=127,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            error_msg = str(exc_info.value).lower()
            assert "127" in error_msg
            assert "not found" in error_msg or "path" in error_msg

    def test_exit_code_126_cannot_execute(self, provider: CodexProvider) -> None:
        """Test exit code 126 (permission denied) message."""
        with patch("bmad_assist.providers.codex.Popen") as mock_popen:
            mock_popen.return_value = create_codex_mock_process(
                stdout_content="",
                stderr_content="Permission denied",
                returncode=126,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            error_msg = str(exc_info.value).lower()
            assert "126" in error_msg
            assert "permission denied" in error_msg
