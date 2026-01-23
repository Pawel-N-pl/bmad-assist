"""Unit tests for AmpProvider implementation.

Tests cover the Popen-based Amp provider for Multi-LLM validation with JSON streaming.

Tests cover:
- AC1: AmpProvider extends BaseProvider
- AC2: provider_name returns "amp"
- AC3: default_model returns a valid default mode
- AC4: supports_model() always returns True (CLI validates modes)
- AC5: invoke() builds correct command with -x --stream-json
- AC6: invoke() returns ProviderResult on success
- AC7: invoke() raises ProviderTimeoutError on timeout
- AC8: invoke() raises ProviderExitCodeError on non-zero exit
- AC9: invoke() raises ProviderError when CLI not found
- AC10: parse_output() extracts response from stdout
- AC11: Package exports AmpProvider
- AC12: Tool restriction prompt injection
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
from bmad_assist.providers import AmpProvider, BaseProvider, ProviderResult
from bmad_assist.providers.amp import (
    DEFAULT_TIMEOUT,
    PROMPT_TRUNCATE_LENGTH,
    _truncate_prompt,
)
from .conftest import create_amp_mock_process, make_amp_json_output


class TestAmpProviderStructure:
    """Test AC1, AC2, AC3: AmpProvider class definition."""

    def test_provider_inherits_from_baseprovider(self) -> None:
        """Test AC1: AmpProvider inherits from BaseProvider."""
        assert issubclass(AmpProvider, BaseProvider)

    def test_provider_has_class_docstring(self) -> None:
        """Test AC1: AmpProvider has docstring explaining its purpose."""
        assert AmpProvider.__doc__ is not None
        assert "amp" in AmpProvider.__doc__.lower()
        assert "subprocess" in AmpProvider.__doc__.lower()

    def test_provider_name_returns_amp(self) -> None:
        """Test AC2: provider_name returns 'amp'."""
        provider = AmpProvider()
        assert provider.provider_name == "amp"

    def test_default_model_returns_valid_mode(self) -> None:
        """Test AC3: default_model returns a non-empty string."""
        provider = AmpProvider()
        assert provider.default_model is not None
        assert isinstance(provider.default_model, str)
        assert len(provider.default_model) > 0

    def test_default_model_returns_smart(self) -> None:
        """Test AC3: default_model returns 'smart'."""
        provider = AmpProvider()
        assert provider.default_model == "smart"


class TestAmpProviderModels:
    """Test AC4: supports_model() always returns True (CLI validates modes)."""

    @pytest.fixture
    def provider(self) -> AmpProvider:
        """Create AmpProvider instance."""
        return AmpProvider()

    def test_supports_model_always_returns_true(self, provider: AmpProvider) -> None:
        """Test AC4: supports_model() always returns True - CLI validates modes."""
        # Any mode string should return True - validation is delegated to CLI
        assert provider.supports_model("smart") is True
        assert provider.supports_model("rush") is True
        assert provider.supports_model("free") is True
        assert provider.supports_model("any-future-mode") is True
        assert provider.supports_model("gpt-4") is True  # Even non-Amp modes
        assert provider.supports_model("opus") is True

    def test_supports_model_empty_string_returns_true(self, provider: AmpProvider) -> None:
        """Test AC4: supports_model('') returns True - CLI will reject if invalid."""
        assert provider.supports_model("") is True

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        assert AmpProvider.supports_model.__doc__ is not None


class TestAmpProviderInvoke:
    """Test AC5, AC6: invoke() success cases with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> AmpProvider:
        """Create AmpProvider instance."""
        return AmpProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation with JSON streaming."""
        with patch("bmad_assist.providers.amp.Popen") as mock:
            mock.return_value = create_amp_mock_process(
                response_text="Code review complete",
                returncode=0,
            )
            yield mock

    def test_invoke_builds_correct_command_with_stream_json(
        self, provider: AmpProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke() builds command with -x --stream-json."""
        provider.invoke("Review code", model="smart")

        mock_popen_success.assert_called_once()
        call_args = mock_popen_success.call_args
        command = call_args[0][0]

        # Command should include -x --stream-json for execute mode with JSON streaming
        assert command == [
            "amp",
            "-m",
            "smart",
            "-x",
            "--stream-json",
        ]

        # Verify prompt was written to stdin
        mock_process = mock_popen_success.return_value
        mock_process.stdin.write.assert_called_once_with("Review code")
        mock_process.stdin.close.assert_called_once()

    def test_invoke_uses_default_model_when_none(
        self, provider: AmpProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke(model=None) uses default_model ('smart')."""
        provider.invoke("Hello", model=None)

        command = mock_popen_success.call_args[0][0]
        assert command == [
            "amp",
            "-m",
            "smart",
            "-x",
            "--stream-json",
        ]

    def test_invoke_uses_rush_mode(
        self, provider: AmpProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: invoke() with rush mode builds correct command."""
        provider.invoke("Hello", model="rush")

        command = mock_popen_success.call_args[0][0]
        assert "-m" in command
        assert "rush" in command

    def test_invoke_returns_providerresult_on_success(
        self, provider: AmpProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: invoke() returns ProviderResult on exit code 0."""
        result = provider.invoke("Hello", model="smart", timeout=30)

        assert isinstance(result, ProviderResult)

    def test_invoke_providerresult_has_stdout(
        self, provider: AmpProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.stdout contains extracted text from JSON stream."""
        result = provider.invoke("Hello")

        # Text is extracted from assistant events in JSON stream
        assert result.stdout == "Code review complete"

    def test_invoke_providerresult_has_exit_code(
        self, provider: AmpProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.exit_code is 0 on success."""
        result = provider.invoke("Hello")

        assert result.exit_code == 0

    def test_invoke_providerresult_has_duration_ms(
        self, provider: AmpProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.duration_ms is positive integer."""
        result = provider.invoke("Hello")

        assert isinstance(result.duration_ms, int)
        assert result.duration_ms >= 0

    def test_invoke_providerresult_has_model(
        self, provider: AmpProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.model contains the mode used."""
        result = provider.invoke("Hello", model="rush")

        assert result.model == "rush"

    def test_invoke_providerresult_has_command_tuple(
        self, provider: AmpProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC6: ProviderResult.command is tuple of command executed."""
        result = provider.invoke("Hello", model="smart")

        assert isinstance(result.command, tuple)
        assert result.command == (
            "amp",
            "-m",
            "smart",
            "-x",
            "--stream-json",
        )


class TestAmpProviderErrors:
    """Test AC7, AC8, AC9: Error handling with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> AmpProvider:
        """Create AmpProvider instance."""
        return AmpProvider()

    def test_invoke_raises_provider_timeout_error_on_timeout(
        self, provider: AmpProvider
    ) -> None:
        """Test AC7: invoke() raises ProviderTimeoutError on wait timeout."""
        with patch("bmad_assist.providers.amp.Popen") as mock_popen:
            mock_popen.return_value = create_amp_mock_process(
                wait_side_effect=TimeoutExpired(cmd=["amp"], timeout=5)
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert "timeout" in str(exc_info.value).lower()

    def test_invoke_timeout_error_includes_truncated_prompt(self, provider: AmpProvider) -> None:
        """Test AC7: Timeout error includes prompt (truncated if > 100 chars)."""
        long_prompt = "x" * 150

        with patch("bmad_assist.providers.amp.Popen") as mock_popen:
            mock_popen.return_value = create_amp_mock_process(
                wait_side_effect=TimeoutExpired(cmd=["amp"], timeout=5)
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke(long_prompt, timeout=5)

            error_msg = str(exc_info.value)
            assert "x" * 100 in error_msg
            assert "..." in error_msg

    def test_invoke_timeout_exception_includes_partial_result(
        self, provider: AmpProvider
    ) -> None:
        """Test AC7: Timeout error includes partial_result with collected data."""
        with patch("bmad_assist.providers.amp.Popen") as mock_popen:
            mock_popen.return_value = create_amp_mock_process(
                wait_side_effect=TimeoutExpired(cmd=["amp"], timeout=5)
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert exc_info.value.partial_result is not None
            assert exc_info.value.partial_result.exit_code == -1

    def test_invoke_raises_exit_code_error_on_nonzero_exit(self, provider: AmpProvider) -> None:
        """Test AC8: invoke() raises ProviderExitCodeError on non-zero exit code."""
        with patch("bmad_assist.providers.amp.Popen") as mock_popen:
            mock_popen.return_value = create_amp_mock_process(
                stdout_content="",
                stderr_content="Error: No credits available",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert "exit code 1" in str(exc_info.value).lower()
            assert exc_info.value.exit_code == 1

    def test_invoke_nonzero_exit_includes_stderr(self, provider: AmpProvider) -> None:
        """Test AC8: Non-zero exit error includes stderr content."""
        with patch("bmad_assist.providers.amp.Popen") as mock_popen:
            mock_popen.return_value = create_amp_mock_process(
                stdout_content="",
                stderr_content="Error: No credits available",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert "No credits available" in str(exc_info.value)

    def test_invoke_raises_providererror_when_cli_not_found(self, provider: AmpProvider) -> None:
        """Test AC9: invoke() raises ProviderError on FileNotFoundError."""
        with patch("bmad_assist.providers.amp.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("amp")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            error_msg = str(exc_info.value).lower()
            assert "not found" in error_msg or "path" in error_msg

    def test_invoke_file_not_found_exception_is_chained(self, provider: AmpProvider) -> None:
        """Test AC9: FileNotFoundError is chained with 'from e'."""
        with patch("bmad_assist.providers.amp.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("amp")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, FileNotFoundError)

    def test_invoke_accepts_any_mode(self, provider: AmpProvider) -> None:
        """Test invoke() accepts any mode - CLI validates modes."""
        with patch("bmad_assist.providers.amp.Popen") as mock_popen:
            mock_popen.return_value = create_amp_mock_process(
                response_text="response",
                returncode=0,
            )
            # Any mode should be accepted - CLI validates
            result = provider.invoke("Hello", model="turbo")
            assert result.model == "turbo"

    def test_invoke_raises_valueerror_on_negative_timeout(self, provider: AmpProvider) -> None:
        """Test invoke() raises ValueError for negative timeout."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=-1)

        assert "timeout must be positive" in str(exc_info.value).lower()

    def test_invoke_raises_valueerror_on_zero_timeout(self, provider: AmpProvider) -> None:
        """Test invoke() raises ValueError for zero timeout."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=0)

        assert "timeout must be positive" in str(exc_info.value).lower()


class TestAmpProviderParseOutput:
    """Test AC10: parse_output() functionality."""

    @pytest.fixture
    def provider(self) -> AmpProvider:
        """Create AmpProvider instance."""
        return AmpProvider()

    def test_parse_output_extracts_stdout(self, provider: AmpProvider) -> None:
        """Test AC10: parse_output() returns result.stdout.strip()."""
        result = ProviderResult(
            stdout="Code review complete",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="smart",
            command=("amp", "-m", "smart", "-x"),
        )

        parsed = provider.parse_output(result)

        assert parsed == "Code review complete"

    def test_parse_output_strips_whitespace(self, provider: AmpProvider) -> None:
        """Test AC10: parse_output() strips leading/trailing whitespace."""
        result = ProviderResult(
            stdout="  Code review complete  \n",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="smart",
            command=("amp", "-m", "smart", "-x"),
        )

        parsed = provider.parse_output(result)

        assert parsed == "Code review complete"

    def test_parse_output_empty_stdout_returns_empty_string(self, provider: AmpProvider) -> None:
        """Test AC10: parse_output() returns empty string for empty stdout."""
        result = ProviderResult(
            stdout="",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="smart",
            command=("amp", "-m", "smart", "-x"),
        )

        parsed = provider.parse_output(result)

        assert parsed == ""


class TestAmpProviderExports:
    """Test AC11: Package exports AmpProvider."""

    def test_ampprovider_exported_from_providers(self) -> None:
        """Test AC11: AmpProvider can be imported from providers package."""
        from bmad_assist.providers import AmpProvider as ImportedProvider

        assert ImportedProvider is AmpProvider

    def test_ampprovider_in_all(self) -> None:
        """Test AC11: AmpProvider is in __all__."""
        from bmad_assist import providers

        assert "AmpProvider" in providers.__all__


class TestAmpProviderSettings:
    """Test settings file handling."""

    @pytest.fixture
    def provider(self) -> AmpProvider:
        """Create AmpProvider instance."""
        return AmpProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation."""
        with patch("bmad_assist.providers.amp.Popen") as mock:
            mock.return_value = create_amp_mock_process(
                response_text="response",
                returncode=0,
            )
            yield mock

    def test_invoke_with_existing_settings_file(
        self, provider: AmpProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test invoke() validates existing settings file."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"key": "value"}')

        provider.invoke("Hello", settings_file=settings_path)
        mock_popen_success.assert_called_once()

    def test_invoke_with_missing_settings_file(
        self, provider: AmpProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test invoke() gracefully handles missing settings file."""
        settings_path = tmp_path / "nonexistent.json"

        provider.invoke("Hello", settings_file=settings_path)
        mock_popen_success.assert_called_once()

    def test_invoke_settings_file_not_passed_to_cli(
        self, provider: AmpProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test settings file is NOT passed to Amp CLI."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"key": "value"}')

        provider.invoke("Hello", settings_file=settings_path)

        command = mock_popen_success.call_args[0][0]
        assert str(settings_path) not in command
        assert "--settings" not in command


class TestAmpProviderToolRestrictions:
    """Test AC12: Tool restriction enforcement for validators."""

    @pytest.fixture
    def provider(self) -> AmpProvider:
        """Create AmpProvider instance."""
        return AmpProvider()

    def test_allowed_tools_todowrite_only_adds_prompt_warning(
        self, provider: AmpProvider
    ) -> None:
        """Test AC12: allowed_tools=['TodoWrite'] injects prompt-level warning."""
        with patch("bmad_assist.providers.amp.Popen") as mock_popen:
            mock_process = create_amp_mock_process(
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

    def test_allowed_tools_none_does_not_add_warning(self, provider: AmpProvider) -> None:
        """Test AC12: allowed_tools=None does NOT inject warning."""
        with patch("bmad_assist.providers.amp.Popen") as mock_popen:
            mock_process = create_amp_mock_process(
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
        self, provider: AmpProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test AC12: Attempting Edit tool with restrictions logs warning."""
        import json

        # Build Amp format assistant event with tool_use
        edit_event = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": "test.md"},
                        }
                    ],
                },
            }
        )
        text_event = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Done"}],
                },
            }
        )
        custom_stdout = f"{edit_event}\n{text_event}\n"

        with patch("bmad_assist.providers.amp.Popen") as mock_popen:
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
                record for record in caplog.records if "restricted tool" in record.message.lower()
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
        from bmad_assist.providers import amp

        assert amp.__doc__ is not None
        assert "amp" in amp.__doc__.lower()

    def test_provider_has_docstring(self) -> None:
        """Test AmpProvider has docstring."""
        assert AmpProvider.__doc__ is not None

    def test_invoke_has_docstring(self) -> None:
        """Test invoke() has docstring."""
        assert AmpProvider.invoke.__doc__ is not None

    def test_invoke_has_google_style_docstring(self) -> None:
        """Test invoke() has Google-style docstring."""
        doc = AmpProvider.invoke.__doc__
        assert doc is not None
        assert "Args:" in doc
        assert "Returns:" in doc
        assert "Raises:" in doc

    def test_parse_output_has_docstring(self) -> None:
        """Test parse_output() has docstring."""
        assert AmpProvider.parse_output.__doc__ is not None

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        assert AmpProvider.supports_model.__doc__ is not None
