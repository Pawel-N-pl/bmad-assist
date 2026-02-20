"""Unit tests for OpenCodeProvider implementation.

Tests cover the Popen-based OpenCode provider for Multi-LLM validation with JSON streaming.

Tests cover:
- AC1: OpenCodeProvider extends BaseProvider
- AC2: provider_name returns "opencode"
- AC3: default_model returns valid model with 'provider/model' format
- AC4: supports_model() validates model format (must contain '/')
- AC5: invoke() builds correct command with --format json
- AC6: invoke() returns ProviderResult on success
- AC7: invoke() raises ProviderTimeoutError on timeout
- AC8: invoke() raises ProviderExitCodeError on non-zero exit
- AC9: invoke() raises ProviderError when CLI not found
- AC10: parse_output() extracts response from stdout
- AC11: Package exports OpenCodeProvider
- AC12: Tool restriction prompt injection
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers import BaseProvider, OpenCodeProvider, ProviderResult
from bmad_assist.providers.opencode import (
    DEFAULT_TIMEOUT,
    PROMPT_TRUNCATE_LENGTH,
    _truncate_prompt,
)

from .conftest import create_opencode_mock_process


class TestOpenCodeProviderStructure:
    """Test AC1, AC2, AC3: OpenCodeProvider class definition."""

    def test_provider_inherits_from_baseprovider(self) -> None:
        """Test AC1: OpenCodeProvider inherits from BaseProvider."""
        assert issubclass(OpenCodeProvider, BaseProvider)

    def test_provider_has_class_docstring(self) -> None:
        """Test AC1: OpenCodeProvider has docstring explaining its purpose."""
        assert OpenCodeProvider.__doc__ is not None
        assert "opencode" in OpenCodeProvider.__doc__.lower()
        assert "subprocess" in OpenCodeProvider.__doc__.lower()

    def test_provider_name_returns_opencode(self) -> None:
        """Test AC2: provider_name returns 'opencode'."""
        provider = OpenCodeProvider()
        assert provider.provider_name == "opencode"

    def test_default_model_returns_valid_format(self) -> None:
        """Test AC3: default_model returns a model with valid 'provider/model' format."""
        provider = OpenCodeProvider()
        assert provider.default_model is not None
        assert "/" in provider.default_model

    def test_default_model_returns_opencode_claude_sonnet_4(self) -> None:
        """Test AC3: default_model returns 'opencode/claude-sonnet-4'."""
        provider = OpenCodeProvider()
        assert provider.default_model == "opencode/claude-sonnet-4"


class TestOpenCodeProviderModels:
    """Test AC4: supports_model() validation (format-based, not hardcoded list)."""

    @pytest.fixture
    def provider(self) -> OpenCodeProvider:
        """Create OpenCodeProvider instance."""
        return OpenCodeProvider()

    def test_supports_model_any_provider_slash_model_format(self, provider: OpenCodeProvider) -> None:
        """Test AC4: supports_model() accepts any 'provider/model' format."""
        # OpenCode is a router - it should accept any provider/model format
        assert provider.supports_model("opencode/claude-sonnet-4") is True
        assert provider.supports_model("xai/grok-3") is True
        assert provider.supports_model("zai-coding-plan/glm-4.7") is True
        assert provider.supports_model("any-provider/any-model") is True
        assert provider.supports_model("foo/bar") is True

    def test_supports_model_gpt4_returns_false(self, provider: OpenCodeProvider) -> None:
        """Test AC4: supports_model('gpt-4') returns False (no slash)."""
        assert provider.supports_model("gpt-4") is False

    def test_supports_model_no_slash_returns_false(self, provider: OpenCodeProvider) -> None:
        """Test AC4: supports_model without slash returns False."""
        assert provider.supports_model("claude-sonnet-4") is False

    def test_supports_model_empty_string_returns_false(self, provider: OpenCodeProvider) -> None:
        """Test AC4: supports_model('') returns False."""
        assert provider.supports_model("") is False

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        assert OpenCodeProvider.supports_model.__doc__ is not None
        assert "model" in OpenCodeProvider.supports_model.__doc__.lower()


class TestOpenCodeProviderInvoke:
    """Test AC5, AC6: invoke() success cases with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> OpenCodeProvider:
        """Create OpenCodeProvider instance."""
        return OpenCodeProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation with JSON streaming."""
        with patch("bmad_assist.providers.opencode.Popen") as mock:
            mock.return_value = create_opencode_mock_process(
                response_text="Code review complete",
                returncode=0,
            )
            yield mock

    def test_invoke_builds_correct_command_with_format_json(
        self, provider: OpenCodeProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke() builds command with --format json."""
        provider.invoke("Review code", model="opencode/claude-sonnet-4")

        mock_popen_success.assert_called_once()
        call_args = mock_popen_success.call_args
        command = call_args[0][0]

        # Command should include --format json for JSONL streaming
        assert command == [
            "opencode",
            "run",
            "-m",
            "opencode/claude-sonnet-4",
            "--format",
            "json",
        ]

        # Verify prompt was written to stdin
        mock_process = mock_popen_success.return_value
        mock_process.stdin.write.assert_called_once_with("Review code")
        mock_process.stdin.close.assert_called_once()

    def test_invoke_uses_default_model_when_none(
        self, provider: OpenCodeProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke(model=None) uses default_model."""
        provider.invoke("Hello", model=None)

        command = mock_popen_success.call_args[0][0]
        assert command == [
            "opencode",
            "run",
            "-m",
            "opencode/claude-sonnet-4",
            "--format",
            "json",
        ]

    def test_invoke_returns_providerresult_on_success(
        self, provider: OpenCodeProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: invoke() returns ProviderResult on exit code 0."""
        result = provider.invoke("Hello", model="opencode/claude-sonnet-4", timeout=30)

        assert isinstance(result, ProviderResult)

    def test_invoke_providerresult_has_stdout(
        self, provider: OpenCodeProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.stdout contains extracted text from JSON stream."""
        result = provider.invoke("Hello")

        # Text is extracted from text events in JSON stream
        assert result.stdout == "Code review complete"

    def test_invoke_providerresult_has_exit_code(
        self, provider: OpenCodeProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.exit_code is 0 on success."""
        result = provider.invoke("Hello")

        assert result.exit_code == 0

    def test_invoke_providerresult_has_duration_ms(
        self, provider: OpenCodeProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.duration_ms is positive integer."""
        result = provider.invoke("Hello")

        assert isinstance(result.duration_ms, int)
        assert result.duration_ms >= 0

    def test_invoke_providerresult_has_model(
        self, provider: OpenCodeProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.model contains the model used."""
        result = provider.invoke("Hello", model="xai/grok-3")

        assert result.model == "xai/grok-3"

    def test_invoke_providerresult_has_command_tuple(
        self, provider: OpenCodeProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.command is tuple of command executed."""
        result = provider.invoke("Hello", model="opencode/claude-sonnet-4")

        assert isinstance(result.command, tuple)
        assert result.command == (
            "opencode",
            "run",
            "-m",
            "opencode/claude-sonnet-4",
            "--format",
            "json",
        )


class TestOpenCodeProviderErrors:
    """Test AC7, AC8, AC9: Error handling with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> OpenCodeProvider:
        """Create OpenCodeProvider instance."""
        return OpenCodeProvider()

    def test_invoke_raises_provider_timeout_error_on_timeout(
        self, provider: OpenCodeProvider
    ) -> None:
        """Test AC7: invoke() raises ProviderTimeoutError on wait timeout."""
        with patch("bmad_assist.providers.opencode.Popen") as mock_popen:
            mock_popen.return_value = create_opencode_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert "timeout" in str(exc_info.value).lower()

    def test_invoke_timeout_error_includes_truncated_prompt(self, provider: OpenCodeProvider) -> None:
        """Test AC7: Timeout error includes prompt (truncated if > 100 chars)."""
        long_prompt = "x" * 150

        with patch("bmad_assist.providers.opencode.Popen") as mock_popen:
            mock_popen.return_value = create_opencode_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke(long_prompt, timeout=5)

            error_msg = str(exc_info.value)
            assert "x" * 100 in error_msg
            assert "..." in error_msg

    def test_invoke_timeout_exception_includes_partial_result(
        self, provider: OpenCodeProvider
    ) -> None:
        """Test AC7: Timeout error includes partial_result with collected data."""
        with patch("bmad_assist.providers.opencode.Popen") as mock_popen:
            mock_popen.return_value = create_opencode_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert exc_info.value.partial_result is not None
            assert exc_info.value.partial_result.exit_code == -1

    def test_invoke_raises_exit_code_error_on_nonzero_exit(self, provider: OpenCodeProvider) -> None:
        """Test AC8: invoke() raises ProviderExitCodeError on non-zero exit code."""
        with patch("bmad_assist.providers.opencode.Popen") as mock_popen:
            mock_popen.return_value = create_opencode_mock_process(
                stdout_content="",
                stderr_content="Error: API quota exceeded",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert "exit code 1" in str(exc_info.value).lower()
            assert exc_info.value.exit_code == 1

    def test_invoke_nonzero_exit_includes_stderr(self, provider: OpenCodeProvider) -> None:
        """Test AC8: Non-zero exit error includes stderr content."""
        with patch("bmad_assist.providers.opencode.Popen") as mock_popen:
            mock_popen.return_value = create_opencode_mock_process(
                stdout_content="",
                stderr_content="Error: API quota exceeded",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert "API quota exceeded" in str(exc_info.value)

    def test_invoke_raises_providererror_when_cli_not_found(self, provider: OpenCodeProvider) -> None:
        """Test AC9: invoke() raises ProviderError on FileNotFoundError."""
        with patch("bmad_assist.providers.opencode.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("opencode")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            error_msg = str(exc_info.value).lower()
            assert "not found" in error_msg or "path" in error_msg

    def test_invoke_file_not_found_exception_is_chained(self, provider: OpenCodeProvider) -> None:
        """Test AC9: FileNotFoundError is chained with 'from e'."""
        with patch("bmad_assist.providers.opencode.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("opencode")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, FileNotFoundError)

    def test_invoke_raises_providererror_on_invalid_model_format(
        self, provider: OpenCodeProvider
    ) -> None:
        """Test invoke() validates model format and raises ProviderError for invalid format."""
        with pytest.raises(ProviderError) as exc_info:
            provider.invoke("Hello", model="gpt-4")

        error_msg = str(exc_info.value).lower()
        assert "invalid model format" in error_msg
        assert "gpt-4" in error_msg

    def test_invoke_raises_valueerror_on_negative_timeout(self, provider: OpenCodeProvider) -> None:
        """Test invoke() raises ValueError for negative timeout."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=-1)

        assert "timeout must be positive" in str(exc_info.value).lower()

    def test_invoke_raises_valueerror_on_zero_timeout(self, provider: OpenCodeProvider) -> None:
        """Test invoke() raises ValueError for zero timeout."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=0)

        assert "timeout must be positive" in str(exc_info.value).lower()


class TestOpenCodeProviderParseOutput:
    """Test AC10: parse_output() functionality."""

    @pytest.fixture
    def provider(self) -> OpenCodeProvider:
        """Create OpenCodeProvider instance."""
        return OpenCodeProvider()

    def test_parse_output_extracts_stdout(self, provider: OpenCodeProvider) -> None:
        """Test AC10: parse_output() returns result.stdout.strip()."""
        result = ProviderResult(
            stdout="Code review complete",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="opencode/claude-sonnet-4",
            command=("opencode", "run", "-m", "model"),
        )

        parsed = provider.parse_output(result)

        assert parsed == "Code review complete"

    def test_parse_output_strips_whitespace(self, provider: OpenCodeProvider) -> None:
        """Test AC10: parse_output() strips leading/trailing whitespace."""
        result = ProviderResult(
            stdout="  Code review complete  \n",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="opencode/claude-sonnet-4",
            command=("opencode", "run", "-m", "model"),
        )

        parsed = provider.parse_output(result)

        assert parsed == "Code review complete"

    def test_parse_output_empty_stdout_returns_empty_string(self, provider: OpenCodeProvider) -> None:
        """Test AC10: parse_output() returns empty string for empty stdout."""
        result = ProviderResult(
            stdout="",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="opencode/claude-sonnet-4",
            command=("opencode", "run", "-m", "model"),
        )

        parsed = provider.parse_output(result)

        assert parsed == ""


class TestOpenCodeProviderExports:
    """Test AC11: Package exports OpenCodeProvider."""

    def test_opencodeprovider_exported_from_providers(self) -> None:
        """Test AC11: OpenCodeProvider can be imported from providers package."""
        from bmad_assist.providers import OpenCodeProvider as ImportedProvider

        assert ImportedProvider is OpenCodeProvider

    def test_opencodeprovider_in_all(self) -> None:
        """Test AC11: OpenCodeProvider is in __all__."""
        from bmad_assist import providers

        assert "OpenCodeProvider" in providers.__all__


class TestOpenCodeProviderSettings:
    """Test settings file handling."""

    @pytest.fixture
    def provider(self) -> OpenCodeProvider:
        """Create OpenCodeProvider instance."""
        return OpenCodeProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation."""
        with patch("bmad_assist.providers.opencode.Popen") as mock:
            mock.return_value = create_opencode_mock_process(
                response_text="response",
                returncode=0,
            )
            yield mock

    def test_invoke_with_existing_settings_file(
        self, provider: OpenCodeProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test invoke() validates existing settings file."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"key": "value"}')

        provider.invoke("Hello", settings_file=settings_path)
        mock_popen_success.assert_called_once()

    def test_invoke_with_missing_settings_file(
        self, provider: OpenCodeProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test invoke() gracefully handles missing settings file."""
        settings_path = tmp_path / "nonexistent.json"

        provider.invoke("Hello", settings_file=settings_path)
        mock_popen_success.assert_called_once()

    def test_invoke_settings_file_not_passed_to_cli(
        self, provider: OpenCodeProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test settings file is NOT passed to OpenCode CLI."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"key": "value"}')

        provider.invoke("Hello", settings_file=settings_path)

        command = mock_popen_success.call_args[0][0]
        assert str(settings_path) not in command
        assert "--settings" not in command


class TestOpenCodeProviderToolRestrictions:
    """Test AC12: Tool restriction enforcement for validators."""

    @pytest.fixture
    def provider(self) -> OpenCodeProvider:
        """Create OpenCodeProvider instance."""
        return OpenCodeProvider()

    def test_allowed_tools_todowrite_only_adds_prompt_warning(
        self, provider: OpenCodeProvider
    ) -> None:
        """Test AC12: allowed_tools=['TodoWrite'] injects prompt-level warning."""
        with patch("bmad_assist.providers.opencode.Popen") as mock_popen:
            mock_process = create_opencode_mock_process(
                response_text="Validation complete",
                returncode=0,
            )
            mock_popen.return_value = mock_process

            result = provider.invoke(
                "Please validate this story",
                allowed_tools=["TodoWrite"],
            )

            assert result.exit_code == 0

            # Verify prompt was written with tool restriction warning
            assert mock_process.stdin is not None
            written_prompt = mock_process.stdin.write_args[0]  # type: ignore

            assert "TOOL ACCESS RESTRICTIONS" in written_prompt
            assert "CODE REVIEWER with LIMITED tool access" in written_prompt
            assert "FORBIDDEN tools" in written_prompt
            assert "Bash" in written_prompt

    def test_allowed_tools_none_does_not_add_warning(self, provider: OpenCodeProvider) -> None:
        """Test AC12: allowed_tools=None does NOT inject warning."""
        with patch("bmad_assist.providers.opencode.Popen") as mock_popen:
            mock_process = create_opencode_mock_process(
                response_text="Response",
                returncode=0,
            )
            mock_popen.return_value = mock_process

            result = provider.invoke("Please edit this file")

            assert result.exit_code == 0

            assert mock_process.stdin is not None
            written_prompt = mock_process.stdin.write_args[0]  # type: ignore
            assert "TOOL ACCESS RESTRICTIONS" not in written_prompt

    def test_restricted_tool_attempt_logs_warning(
        self, provider: OpenCodeProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test AC12: Attempting Edit tool with restrictions logs warning."""
        import json

        edit_event = json.dumps(
            {
                "type": "tool_use",
                "part": {
                    "tool": "edit",
                    "state": {"input": {"file_path": "test.md"}},
                },
            }
        )
        text_event = json.dumps({"type": "text", "part": {"type": "text", "text": "Done"}})
        custom_stdout = f"{edit_event}\n{text_event}\n"

        with patch("bmad_assist.providers.opencode.Popen") as mock_popen:
            from .conftest import create_mock_process

            mock_process = create_mock_process(
                stdout_content=custom_stdout,
                returncode=0,
            )
            mock_popen.return_value = mock_process

            with caplog.at_level("WARNING"):
                result = provider.invoke(
                    "Edit this file",
                    allowed_tools=["TodoWrite"],
                )

            assert result.exit_code == 0
            warning_logs = [
                record
                for record in caplog.records
                if "restricted tool" in record.getMessage().lower()
            ]
            assert len(warning_logs) > 0


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

        assert len(result) == PROMPT_TRUNCATE_LENGTH + 3
        assert result.endswith("...")


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
        from bmad_assist.providers import opencode

        assert opencode.__doc__ is not None
        assert "opencode" in opencode.__doc__.lower()

    def test_provider_has_docstring(self) -> None:
        """Test OpenCodeProvider has docstring."""
        assert OpenCodeProvider.__doc__ is not None

    def test_invoke_has_docstring(self) -> None:
        """Test invoke() has docstring."""
        assert OpenCodeProvider.invoke.__doc__ is not None

    def test_invoke_has_google_style_docstring(self) -> None:
        """Test invoke() has Google-style docstring."""
        doc = OpenCodeProvider.invoke.__doc__
        assert doc is not None
        assert "Args:" in doc
        assert "Returns:" in doc
        assert "Raises:" in doc

    def test_parse_output_has_docstring(self) -> None:
        """Test parse_output() has docstring."""
        assert OpenCodeProvider.parse_output.__doc__ is not None

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        assert OpenCodeProvider.supports_model.__doc__ is not None
