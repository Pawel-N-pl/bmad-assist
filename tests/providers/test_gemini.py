"""Unit tests for GeminiProvider implementation.

Tests cover the Popen-based Gemini provider for Multi-LLM validation with JSON streaming.

Tests cover:
- AC1: GeminiProvider extends BaseProvider
- AC2: provider_name returns "gemini"
- AC3: default_model returns a valid default model
- AC4: supports_model() always returns True (CLI validates models)
- AC5: invoke() builds correct command with --output-format stream-json
- AC6: invoke() returns ProviderResult on success
- AC7: invoke() raises ProviderTimeoutError on timeout
- AC8: invoke() raises ProviderExitCodeError on non-zero exit
- AC9: invoke() raises ProviderError when CLI not found
- AC10: parse_output() extracts response from stdout
- AC11: Package exports GeminiProvider
- AC12: Settings file handling
"""

import concurrent.futures
from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers import BaseProvider, GeminiProvider, ProviderResult
from bmad_assist.providers.gemini import (
    DEFAULT_TIMEOUT,
    PROMPT_TRUNCATE_LENGTH,
    _truncate_prompt,
)
from .conftest import create_gemini_mock_process, make_gemini_json_output


class TestGeminiProviderStructure:
    """Test AC1, AC2, AC3: GeminiProvider class definition."""

    def test_provider_inherits_from_baseprovider(self) -> None:
        """Test AC1: GeminiProvider inherits from BaseProvider."""
        assert issubclass(GeminiProvider, BaseProvider)

    def test_provider_has_class_docstring(self) -> None:
        """Test AC1: GeminiProvider has docstring explaining its purpose."""
        assert GeminiProvider.__doc__ is not None
        assert "gemini" in GeminiProvider.__doc__.lower()
        assert "subprocess" in GeminiProvider.__doc__.lower()

    def test_provider_name_returns_gemini(self) -> None:
        """Test AC2: provider_name returns 'gemini'."""
        provider = GeminiProvider()
        assert provider.provider_name == "gemini"

    def test_default_model_returns_valid_model(self) -> None:
        """Test AC3: default_model returns a non-empty string."""
        provider = GeminiProvider()
        assert provider.default_model is not None
        assert isinstance(provider.default_model, str)
        assert len(provider.default_model) > 0

    def test_default_model_returns_gemini_25_flash(self) -> None:
        """Test AC3: default_model returns 'gemini-2.5-flash'."""
        provider = GeminiProvider()
        assert provider.default_model == "gemini-2.5-flash"

    def test_default_model_can_be_overridden_in_subclass(self) -> None:
        """Test AC3: default_model can be overridden via subclass."""

        class CustomProvider(GeminiProvider):
            @property
            def default_model(self) -> str | None:
                return "gemini-2.5-pro"

        provider = CustomProvider()
        assert provider.default_model == "gemini-2.5-pro"


class TestGeminiProviderModels:
    """Test AC4: supports_model() always returns True (CLI validates models)."""

    @pytest.fixture
    def provider(self) -> GeminiProvider:
        """Create GeminiProvider instance."""
        return GeminiProvider()

    def test_supports_model_always_returns_true(self, provider: GeminiProvider) -> None:
        """Test AC4: supports_model() always returns True - CLI validates models."""
        # Any model string should return True - validation is delegated to CLI
        assert provider.supports_model("gemini-2.5-pro") is True
        assert provider.supports_model("gemini-2.5-flash") is True
        assert provider.supports_model("gemini-2.5-flash-lite") is True
        assert provider.supports_model("any-future-model") is True
        assert provider.supports_model("gpt-4") is True  # Even non-Gemini models
        assert provider.supports_model("unknown") is True

    def test_supports_model_empty_string_returns_true(self, provider: GeminiProvider) -> None:
        """Test AC4: supports_model('') returns True - CLI will reject if invalid."""
        assert provider.supports_model("") is True

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        assert GeminiProvider.supports_model.__doc__ is not None


class TestGeminiProviderInvoke:
    """Test AC5, AC6: invoke() success cases with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> GeminiProvider:
        """Create GeminiProvider instance."""
        return GeminiProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation with JSON streaming."""
        with patch("bmad_assist.providers.gemini.Popen") as mock:
            mock.return_value = create_gemini_mock_process(
                response_text="Code review complete",
                returncode=0,
            )
            yield mock

    def test_invoke_builds_correct_command_with_stream_json(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke() builds command with --output-format stream-json."""
        provider.invoke("Review code", model="gemini-2.5-flash")

        mock_popen_success.assert_called_once()
        call_args = mock_popen_success.call_args
        command = call_args[0][0]

        # Command should include --output-format stream-json for JSONL streaming
        # Prompt is passed via stdin, not command line (to avoid "Argument list too long")
        assert command == [
            "gemini",
            "-m",
            "gemini-2.5-flash",
            "--output-format",
            "stream-json",
            "--yolo",
        ]

        # Verify prompt was written to stdin
        mock_process = mock_popen_success.return_value
        mock_process.stdin.write.assert_called_once_with("Review code")
        mock_process.stdin.close.assert_called_once()

    def test_invoke_uses_default_model_when_none(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke(model=None) uses default_model ('gemini-2.5-flash')."""
        provider.invoke("Hello", model=None)

        command = mock_popen_success.call_args[0][0]
        # Prompt is passed via stdin, not command line
        assert command == [
            "gemini",
            "-m",
            "gemini-2.5-flash",
            "--output-format",
            "stream-json",
            "--yolo",
        ]

        # Verify prompt was written to stdin
        mock_process = mock_popen_success.return_value
        mock_process.stdin.write.assert_called_once_with("Hello")

    def test_invoke_uses_default_model_when_not_specified(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke() without model arg uses default_model."""
        provider.invoke("Hello")

        command = mock_popen_success.call_args[0][0]
        assert "-m" in command
        model_index = command.index("-m")
        assert command[model_index + 1] == "gemini-2.5-flash"

    def test_invoke_includes_yolo_flag(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke() includes --yolo flag for non-interactive mode."""
        provider.invoke("Hello")

        command = mock_popen_success.call_args[0][0]
        assert "--yolo" in command

    def test_invoke_returns_providerresult_on_success(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: invoke() returns ProviderResult on exit code 0."""
        result = provider.invoke("Hello", model="gemini-2.5-flash", timeout=30)

        assert isinstance(result, ProviderResult)

    def test_invoke_providerresult_has_stdout(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.stdout contains extracted text from JSON stream."""
        result = provider.invoke("Hello")

        # Text is extracted from message events in JSON stream
        assert result.stdout == "Code review complete"

    def test_invoke_providerresult_has_stderr(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.stderr contains captured stderr."""
        result = provider.invoke("Hello")

        assert result.stderr == ""

    def test_invoke_providerresult_has_exit_code(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.exit_code is 0 on success."""
        result = provider.invoke("Hello")

        assert result.exit_code == 0

    def test_invoke_providerresult_has_duration_ms(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.duration_ms is positive integer."""
        result = provider.invoke("Hello")

        assert isinstance(result.duration_ms, int)
        assert result.duration_ms >= 0

    def test_invoke_providerresult_has_model(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.model contains the model used."""
        result = provider.invoke("Hello", model="gemini-2.5-pro")

        assert result.model == "gemini-2.5-pro"

    def test_invoke_providerresult_model_uses_default_when_none(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.model uses default when model=None."""
        result = provider.invoke("Hello", model=None)

        assert result.model == "gemini-2.5-flash"

    def test_invoke_providerresult_has_command_tuple(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.command is tuple of command executed."""
        result = provider.invoke("Hello", model="gemini-2.5-pro")

        assert isinstance(result.command, tuple)
        # Command uses stdin for prompt (not command line args)
        assert result.command == (
            "gemini",
            "-m",
            "gemini-2.5-pro",
            "--output-format",
            "stream-json",
            "--yolo",
        )


class TestGeminiProviderErrors:
    """Test AC7, AC8, AC9: Error handling with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> GeminiProvider:
        """Create GeminiProvider instance."""
        return GeminiProvider()

    def test_invoke_raises_provider_timeout_error_on_timeout(
        self, provider: GeminiProvider
    ) -> None:
        """Test AC7: invoke() raises ProviderTimeoutError on wait timeout."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert "timeout" in str(exc_info.value).lower()

    def test_invoke_timeout_error_includes_truncated_prompt(self, provider: GeminiProvider) -> None:
        """Test AC7: Timeout error includes prompt (truncated if > 100 chars)."""
        long_prompt = "x" * 150

        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke(long_prompt, timeout=5)

            error_msg = str(exc_info.value)
            # Should be truncated
            assert "x" * 100 in error_msg
            assert "..." in error_msg
            # Should NOT contain full prompt
            assert "x" * 150 not in error_msg

    def test_invoke_timeout_error_short_prompt_not_truncated(
        self, provider: GeminiProvider
    ) -> None:
        """Test AC7: Short prompts are not truncated in timeout error."""
        short_prompt = "Hello world"

        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke(short_prompt, timeout=5)

            error_msg = str(exc_info.value)
            assert "Hello world" in error_msg
            assert "..." not in error_msg

    def test_invoke_timeout_exception_includes_partial_result(
        self, provider: GeminiProvider
    ) -> None:
        """Test AC7: Timeout error includes partial_result with collected data."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            # Timeout should include partial result
            assert exc_info.value.partial_result is not None
            assert exc_info.value.partial_result.exit_code == -1

    def test_invoke_raises_exit_code_error_on_nonzero_exit(self, provider: GeminiProvider) -> None:
        """Test AC8: invoke() raises ProviderExitCodeError on non-zero exit code."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                stdout_content="",
                stderr_content="Error: invalid API key",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert "exit code 1" in str(exc_info.value).lower()
            assert exc_info.value.exit_code == 1

    def test_invoke_nonzero_exit_includes_stderr(self, provider: GeminiProvider) -> None:
        """Test AC8: Non-zero exit error includes stderr content."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                stdout_content="",
                stderr_content="Error: invalid API key",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert "invalid API key" in str(exc_info.value)
            # Stderr includes trailing newline from line reading
            assert exc_info.value.stderr.strip() == "Error: invalid API key"

    def test_invoke_nonzero_exit_includes_exit_status(self, provider: GeminiProvider) -> None:
        """Test AC8: Non-zero exit error includes exit_status classification."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                stdout_content="",
                stderr_content="Error",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            from bmad_assist.providers.base import ExitStatus

            assert exc_info.value.exit_status == ExitStatus.ERROR

    def test_invoke_nonzero_exit_includes_command(self, provider: GeminiProvider) -> None:
        """Test AC8: Non-zero exit error includes command tuple."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                stdout_content="",
                stderr_content="Error",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello", model="gemini-2.5-flash")

            # Command uses stdin for prompt (not command line args)
            assert exc_info.value.command == (
                "gemini",
                "-m",
                "gemini-2.5-flash",
                "--output-format",
                "stream-json",
                "--yolo",
            )

    def test_invoke_raises_providererror_when_cli_not_found(self, provider: GeminiProvider) -> None:
        """Test AC9: invoke() raises ProviderError on FileNotFoundError."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("gemini")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            error_msg = str(exc_info.value).lower()
            assert "not found" in error_msg or "path" in error_msg

    def test_invoke_file_not_found_exception_is_chained(self, provider: GeminiProvider) -> None:
        """Test AC9: FileNotFoundError is chained with 'from e'."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("gemini")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, FileNotFoundError)

    def test_invoke_accepts_any_model(self, provider: GeminiProvider) -> None:
        """Test invoke() accepts any model name - CLI validates models."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                response_text="response",
                returncode=0,
            )
            # Any model should be accepted - CLI validates
            result = provider.invoke("Hello", model="gemini-2.5-flash-lite")
            assert result.model == "gemini-2.5-flash-lite"

    def test_invoke_raises_valueerror_on_negative_timeout(self, provider: GeminiProvider) -> None:
        """Test invoke() raises ValueError for negative timeout."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=-1)

        assert "timeout must be positive" in str(exc_info.value).lower()

    def test_invoke_raises_valueerror_on_zero_timeout(self, provider: GeminiProvider) -> None:
        """Test invoke() raises ValueError for zero timeout."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=0)

        assert "timeout must be positive" in str(exc_info.value).lower()


class TestGeminiProviderParseOutput:
    """Test AC10: parse_output() functionality."""

    @pytest.fixture
    def provider(self) -> GeminiProvider:
        """Create GeminiProvider instance."""
        return GeminiProvider()

    def test_parse_output_extracts_stdout(self, provider: GeminiProvider) -> None:
        """Test AC10: parse_output() returns result.stdout.strip()."""
        result = ProviderResult(
            stdout="Code review complete",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="gemini-2.5-flash",
            command=("gemini", "-p", "Review"),
        )

        parsed = provider.parse_output(result)

        assert parsed == "Code review complete"

    def test_parse_output_strips_whitespace(self, provider: GeminiProvider) -> None:
        """Test AC10: parse_output() strips leading/trailing whitespace."""
        result = ProviderResult(
            stdout="  Code review complete  \n",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="gemini-2.5-flash",
            command=("gemini", "-p", "Review"),
        )

        parsed = provider.parse_output(result)

        assert parsed == "Code review complete"

    def test_parse_output_empty_stdout_returns_empty_string(self, provider: GeminiProvider) -> None:
        """Test AC10: parse_output() returns empty string for empty stdout."""
        result = ProviderResult(
            stdout="",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="gemini-2.5-flash",
            command=("gemini", "-p", "Review"),
        )

        parsed = provider.parse_output(result)

        assert parsed == ""

    def test_parse_output_whitespace_only_returns_empty(self, provider: GeminiProvider) -> None:
        """Test AC10: parse_output() returns empty for whitespace-only stdout."""
        result = ProviderResult(
            stdout="   \n\t  ",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="gemini-2.5-flash",
            command=("gemini", "-p", "Review"),
        )

        parsed = provider.parse_output(result)

        assert parsed == ""

    def test_parse_output_has_docstring(self) -> None:
        """Test parse_output() has docstring explaining format."""
        assert GeminiProvider.parse_output.__doc__ is not None
        # Should mention stdout
        doc = GeminiProvider.parse_output.__doc__.lower()
        assert "stdout" in doc


class TestGeminiProviderExports:
    """Test AC11: Package exports GeminiProvider."""

    def test_geminiprovider_exported_from_providers(self) -> None:
        """Test AC11: GeminiProvider can be imported from providers package."""
        from bmad_assist.providers import GeminiProvider as ImportedProvider

        assert ImportedProvider is GeminiProvider

    def test_geminiprovider_in_all(self) -> None:
        """Test AC11: GeminiProvider is in __all__."""
        from bmad_assist import providers

        assert "GeminiProvider" in providers.__all__

    def test_providers_all_has_expected_exports(self) -> None:
        """Test __all__ has expected exports including GeminiProvider."""
        from bmad_assist import providers

        # Should contain BaseProvider, GeminiProvider, ProviderResult
        assert "BaseProvider" in providers.__all__
        assert "GeminiProvider" in providers.__all__
        assert "ProviderResult" in providers.__all__


class TestGeminiProviderSettings:
    """Test AC12: Settings file handling with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> GeminiProvider:
        """Create GeminiProvider instance."""
        return GeminiProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation with JSON streaming."""
        with patch("bmad_assist.providers.gemini.Popen") as mock:
            mock.return_value = create_gemini_mock_process(
                response_text="response",
                returncode=0,
            )
            yield mock

    def test_invoke_with_existing_settings_file(
        self, provider: GeminiProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test AC12: invoke() validates existing settings file."""
        # Create a real settings file
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"key": "value"}')

        # Should not raise
        provider.invoke("Hello", settings_file=settings_path)
        mock_popen_success.assert_called_once()

    def test_invoke_with_missing_settings_file(
        self, provider: GeminiProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test AC12: invoke() gracefully handles missing settings file."""
        settings_path = tmp_path / "nonexistent.json"

        # Should not raise - graceful degradation
        provider.invoke("Hello", settings_file=settings_path)
        mock_popen_success.assert_called_once()

    def test_invoke_without_settings_file(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC12: invoke() works without settings_file."""
        provider.invoke("Hello")
        mock_popen_success.assert_called_once()

    def test_invoke_settings_file_not_passed_to_cli(
        self, provider: GeminiProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test AC12: Settings file is NOT passed to Gemini CLI."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"key": "value"}')

        provider.invoke("Hello", settings_file=settings_path)

        command = mock_popen_success.call_args[0][0]
        # Settings file should not appear in command
        assert str(settings_path) not in command
        assert "--settings" not in command


class TestGeminiProviderUnicode:
    """Test Unicode handling in GeminiProvider with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> GeminiProvider:
        """Create GeminiProvider instance."""
        return GeminiProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation with JSON streaming."""
        with patch("bmad_assist.providers.gemini.Popen") as mock:
            mock.return_value = create_gemini_mock_process(
                response_text="Response with emoji 🎉",
                returncode=0,
            )
            yield mock

    def test_invoke_with_emoji_in_prompt(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles emoji in prompt correctly."""
        result = provider.invoke("Review code 🔍")

        # Prompt is written to stdin, not command line
        mock_process = mock_popen_success.return_value
        mock_process.stdin.write.assert_called_once_with("Review code 🔍")
        assert isinstance(result.stdout, str)

    def test_invoke_with_chinese_characters(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles Chinese characters correctly."""
        result = provider.invoke("代码审查")

        # Prompt is written to stdin, not command line
        mock_process = mock_popen_success.return_value
        mock_process.stdin.write.assert_called_once_with("代码审查")
        assert isinstance(result.stdout, str)

    def test_invoke_with_cyrillic_characters(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles Cyrillic characters correctly."""
        result = provider.invoke("Проверка кода")

        # Prompt is written to stdin, not command line
        mock_process = mock_popen_success.return_value
        mock_process.stdin.write.assert_called_once_with("Проверка кода")
        assert isinstance(result.stdout, str)

    def test_invoke_with_newlines_in_prompt(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles newlines in prompt correctly."""
        prompt = "Line 1\nLine 2\nLine 3"
        result = provider.invoke(prompt)

        # Prompt is written to stdin, not command line
        mock_process = mock_popen_success.return_value
        mock_process.stdin.write.assert_called_once_with(prompt)
        assert isinstance(result.stdout, str)

    def test_invoke_with_special_characters(
        self, provider: GeminiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test invoke() handles special characters correctly."""
        prompt = 'Review: "code" with $pecial ch@rs & <brackets>'
        result = provider.invoke(prompt)

        # Prompt is written to stdin, not command line
        mock_process = mock_popen_success.return_value
        mock_process.stdin.write.assert_called_once_with(prompt)
        assert isinstance(result.stdout, str)

    def test_invoke_handles_replacement_chars_in_output(self, provider: GeminiProvider) -> None:
        """Test invoke() handles Unicode replacement characters in output."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            # Output contains Unicode replacement character (U+FFFD)
            mock_popen.return_value = create_gemini_mock_process(
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
        from bmad_assist.providers import gemini

        assert gemini.__doc__ is not None
        assert "gemini" in gemini.__doc__.lower()

    def test_provider_has_docstring(self) -> None:
        """Test GeminiProvider has docstring."""
        assert GeminiProvider.__doc__ is not None

    def test_provider_name_has_docstring(self) -> None:
        """Test provider_name property has docstring."""
        fget = GeminiProvider.provider_name.fget
        assert fget is not None
        assert fget.__doc__ is not None

    def test_default_model_has_docstring(self) -> None:
        """Test default_model property has docstring."""
        fget = GeminiProvider.default_model.fget
        assert fget is not None
        assert fget.__doc__ is not None

    def test_invoke_has_docstring(self) -> None:
        """Test invoke() has docstring."""
        assert GeminiProvider.invoke.__doc__ is not None

    def test_invoke_has_google_style_docstring(self) -> None:
        """Test invoke() has Google-style docstring."""
        doc = GeminiProvider.invoke.__doc__
        assert doc is not None
        assert "Args:" in doc
        assert "Returns:" in doc
        assert "Raises:" in doc

    def test_parse_output_has_docstring(self) -> None:
        """Test parse_output() has docstring."""
        assert GeminiProvider.parse_output.__doc__ is not None

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        assert GeminiProvider.supports_model.__doc__ is not None


class TestGeminiProviderExitStatusHandling:
    """Test exit status semantic classification with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> GeminiProvider:
        """Create GeminiProvider instance."""
        return GeminiProvider()

    def test_signal_exit_code_137_includes_signal_number(self, provider: GeminiProvider) -> None:
        """Test exit code 137 (SIGKILL) includes signal number in message."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                stdout_content="",
                stderr_content="Killed",
                returncode=137,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert "signal 9" in str(exc_info.value).lower()

    def test_signal_exit_code_143_includes_signal_number(self, provider: GeminiProvider) -> None:
        """Test exit code 143 (SIGTERM) includes signal number in message."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                stdout_content="",
                stderr_content="Terminated",
                returncode=143,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert "signal 15" in str(exc_info.value).lower()

    def test_exit_code_127_not_found(self, provider: GeminiProvider) -> None:
        """Test exit code 127 (command not found) message."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                stdout_content="",
                stderr_content="command not found",
                returncode=127,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            error_msg = str(exc_info.value).lower()
            assert "127" in error_msg
            assert "not found" in error_msg or "path" in error_msg

    def test_exit_code_126_cannot_execute(self, provider: GeminiProvider) -> None:
        """Test exit code 126 (permission denied) message."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                stdout_content="",
                stderr_content="Permission denied",
                returncode=126,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            error_msg = str(exc_info.value).lower()
            assert "126" in error_msg
            assert "permission denied" in error_msg


class TestGeminiProviderThreadSafety:
    """Test thread safety of GeminiProvider with Popen-based streaming."""

    def test_concurrent_invocations_do_not_interfere(self) -> None:
        """Test concurrent invocations are independent (thread safety)."""
        results: list[tuple[int, str]] = []
        errors: list[Exception] = []

        # Patch must be at test level, not inside threads (context managers don't work well with threads)
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            # Configure mock to return different responses based on call order
            def create_mock_for_id(*args: object, **kwargs: object) -> MagicMock:
                # Extract prompt ID from command args
                return create_gemini_mock_process(
                    response_text="Response from mock",
                    returncode=0,
                )

            mock_popen.side_effect = create_mock_for_id

            def invoke_with_id(provider_id: int) -> tuple[int, str]:
                """Invoke GeminiProvider with unique ID."""
                provider = GeminiProvider()
                result = provider.invoke(f"Prompt {provider_id}")
                return (provider_id, result.stdout)

            # Run 10 concurrent invocations
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(invoke_with_id, i) for i in range(10)]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as e:
                        errors.append(e)

        # Verify no errors occurred
        assert len(errors) == 0, f"Errors occurred: {errors}"
        # Verify all results returned
        assert len(results) == 10
        result_ids = [r[0] for r in results]
        assert len(set(result_ids)) == 10  # All unique

    def test_provider_is_stateless(self) -> None:
        """Test provider has no mutable instance state between invocations."""
        provider = GeminiProvider()

        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                response_text="response 1",
                returncode=0,
            )
            result1 = provider.invoke("prompt 1")

            mock_popen.return_value = create_gemini_mock_process(
                response_text="response 2",
                returncode=0,
            )
            result2 = provider.invoke("prompt 2")

        # Results should be independent
        assert result1.stdout == "response 1"
        assert result2.stdout == "response 2"
        # Provider properties unchanged
        assert provider.provider_name == "gemini"


class TestGeminiProviderToolRestrictions:
    """Test Story 22.4: Tool restriction enforcement for validators.

    Tests cover:
    - AC1: Validator with allowed_tools gets prompt-level restriction warning
    - AC1: Edit tool attempts are logged with warnings
    - AC1: Prompt contains tool restriction warning when allowed_tools is set
    """

    @pytest.fixture
    def provider(self) -> GeminiProvider:
        """Create GeminiProvider instance."""
        return GeminiProvider()

    def test_allowed_tools_todowrite_only_adds_prompt_warning(
        self, provider: GeminiProvider
    ) -> None:
        """Test AC1: allowed_tools=['TodoWrite'] injects prompt-level warning."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            # Mock successful process
            mock_process = create_gemini_mock_process(
                response_text="Validation complete",
                returncode=0,
            )
            mock_popen.return_value = mock_process

            # Invoke with tool restrictions (validator mode)
            result = provider.invoke(
                "Please validate this story",
                allowed_tools=["TodoWrite"],
            )

            # Verify invocation succeeded
            assert result.exit_code == 0
            assert "Validation complete" in result.stdout

            # Verify prompt was written with tool restriction warning
            assert mock_process.stdin is not None
            written_prompt = mock_process.stdin.write_args[0]  # type: ignore

            # Check for prompt-level restriction warning
            assert "TOOL ACCESS RESTRICTIONS" in written_prompt
            assert "CODE REVIEWER with LIMITED tool access" in written_prompt
            # Restricted tools are sorted alphabetically
            assert "FORBIDDEN tools" in written_prompt
            assert "Bash" in written_prompt  # One of the restricted tools
            assert "CODE REVIEW REPORT" in written_prompt

    def test_allowed_tools_none_does_not_add_warning(self, provider: GeminiProvider) -> None:
        """Test AC1: allowed_tools=None does NOT inject warning."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_process = create_gemini_mock_process(
                response_text="Response",
                returncode=0,
            )
            mock_popen.return_value = mock_process

            # Invoke without tool restrictions (Master mode)
            result = provider.invoke("Please edit this file")

            assert result.exit_code == 0

            # Verify no warning in prompt
            assert mock_process.stdin is not None
            written_prompt = mock_process.stdin.write_args[0]  # type: ignore
            assert "TOOL ACCESS RESTRICTIONS" not in written_prompt

    def test_allowed_tools_read_only_allows_read_and_todowrite(
        self, provider: GeminiProvider
    ) -> None:
        """Test AC1: allowed_tools=['TodoWrite', 'Read'] allows those tools."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_process = create_gemini_mock_process(
                response_text="Read files and tracked progress",
                returncode=0,
            )
            mock_popen.return_value = mock_process

            # Invoke with Read and TodoWrite allowed (typical validator config)
            result = provider.invoke(
                "Review the code",
                allowed_tools=["TodoWrite", "Read"],
            )

            assert result.exit_code == 0

            # Verify Edit, Write, Bash are listed as restricted
            written_prompt = mock_process.stdin.write_args[0]  # type: ignore
            assert "Edit" in written_prompt
            assert "Write" in written_prompt
            assert "Bash" in written_prompt

    def test_restricted_tool_attempt_logs_warning(
        self, provider: GeminiProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test AC1: Attempting Edit tool with restrictions logs warning."""
        import json

        # Build custom stdout with Edit tool event
        # Use the REAL tool name that Gemini CLI emits: "edit_file"
        edit_event = json.dumps(
            {
                "type": "tool_use",
                "tool_name": "edit_file",  # Real Gemini CLI tool name (not "Edit")
                "parameters": {"file_path": "test.md", "old_string": "old", "new_string": "new"},
            }
        )
        message_event = json.dumps({"type": "message", "role": "assistant", "content": "Done"})
        custom_stdout = f"{edit_event}\n{message_event}\n"

        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            # Create mock process with custom stdout containing Edit tool event
            from .conftest import create_mock_process

            mock_process = create_mock_process(
                stdout_content=custom_stdout,
                returncode=0,
            )
            mock_popen.return_value = mock_process

            # Invoke with tool restrictions (Edit is NOT in allowed_tools)
            # So it will be in restricted_tools = all_common_tools - allowed_tools
            with caplog.at_level("WARNING"):
                result = provider.invoke(
                    "Edit this file",
                    allowed_tools=["TodoWrite"],
                )

            # Verify warning was logged for restricted tool
            assert result.exit_code == 0
            warning_logs = [
                record
                for record in caplog.records
                if "restricted tool" in record.getMessage().lower()
            ]
            assert len(warning_logs) > 0
            # Warning should mention both the real tool name and normalized name
            msg = warning_logs[0].getMessage().lower()
            assert "edit_file" in msg or "edit" in msg

    def test_master_mode_no_restrictions_allows_all_tools(self, provider: GeminiProvider) -> None:
        """Test AC1: Master mode (no allowed_tools) allows all tools."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_process = create_gemini_mock_process(
                response_text="File edited successfully",
                returncode=0,
            )
            mock_popen.return_value = mock_process

            # Invoke in Master mode (no tool restrictions)
            result = provider.invoke("Edit the file to fix issues")

            assert result.exit_code == 0
            # No restriction warning in prompt
            written_prompt = mock_process.stdin.write_args[0]  # type: ignore
            assert "RESTRICTED tool access" not in written_prompt


class TestGeminiProviderQuotaExhaustion:
    """Test QuotaExhaustedError raised on quota stderr patterns."""

    @pytest.fixture
    def provider(self) -> GeminiProvider:
        """Create GeminiProvider instance."""
        return GeminiProvider()

    def test_raises_quota_error_on_gemini_api_stderr(self, provider: GeminiProvider) -> None:
        """Gemini raises QuotaExhaustedError on 'Error when talking to Gemini API'."""
        from bmad_assist.core.exceptions import QuotaExhaustedError

        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                stdout_content="",
                stderr_content="Error when talking to Gemini API",
                returncode=1,
            )

            with pytest.raises(QuotaExhaustedError) as exc_info:
                provider.invoke("Hello", model="gemini-3-pro-preview")

            assert exc_info.value.provider_name == "gemini"
            assert exc_info.value.model == "gemini-3-pro-preview"
            assert "Error when talking to Gemini API" in exc_info.value.stderr

    def test_raises_quota_error_on_resource_exhausted(self, provider: GeminiProvider) -> None:
        """Gemini raises QuotaExhaustedError on 'resource exhausted' stderr."""
        from bmad_assist.core.exceptions import QuotaExhaustedError

        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                stdout_content="",
                stderr_content="RESOURCE_EXHAUSTED: 429 You exceeded your quota",
                returncode=1,
            )

            with pytest.raises(QuotaExhaustedError):
                provider.invoke("Hello")

    def test_non_quota_stderr_raises_exit_code_error(self, provider: GeminiProvider) -> None:
        """Non-quota stderr still raises ProviderExitCodeError."""
        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            mock_popen.return_value = create_gemini_mock_process(
                stdout_content="",
                stderr_content="Syntax error in model config",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError):
                provider.invoke("Hello")

    def test_quota_error_not_retried(self, provider: GeminiProvider) -> None:
        """QuotaExhaustedError is raised immediately, not retried."""
        from bmad_assist.core.exceptions import QuotaExhaustedError

        call_count = 0

        with patch("bmad_assist.providers.gemini.Popen") as mock_popen:
            def track_calls(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return create_gemini_mock_process(
                    stdout_content="",
                    stderr_content="Error when talking to Gemini API",
                    returncode=1,
                )

            mock_popen.side_effect = track_calls

            with pytest.raises(QuotaExhaustedError):
                provider.invoke("Hello")

            # Should only be called once (no retries for quota errors)
            assert call_count == 1
