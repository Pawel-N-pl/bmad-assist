"""Unit tests for KimiProvider implementation.

Tests cover the Popen-based Kimi provider for Multi-LLM validation with JSON streaming.

Tests cover:
- AC1-3: Provider structure (inheritance, provider_name, supports_model)
- AC4-7: Thinking mode auto-detection and config override
- AC8-10: Settings file handling and --config-file flag
- AC11: Prompt input via stdin
- AC12-15: JSONL parsing (OpenAI-style, reasoning_content, tool_calls, malformed)
- AC16-18: Retry logic for transient failures
- AC19-21: Error handling (exit codes, timeout)
- AC22-23: Registry integration
- AC24-33: Adversarial review fixes
"""

import json
from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers import BaseProvider, KimiProvider, ProviderResult, get_provider, list_providers
from bmad_assist.providers.kimi import (
    DEFAULT_TIMEOUT,
    KIMI_PERMANENT_PATTERNS,
    KIMI_TRANSIENT_PATTERNS,
    MAX_RETRIES,
    PROMPT_TRUNCATE_LENGTH,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    _calculate_retry_delay,
    _is_kimi_transient_error,
    _truncate_prompt,
)
from .conftest import (
    create_kimi_mock_process,
    make_kimi_json_output,
    make_kimi_multi_message_output,
)


class TestKimiProviderStructure:
    """Test AC1-3: KimiProvider class definition."""

    def test_provider_inherits_from_baseprovider(self) -> None:
        """Test AC1: KimiProvider inherits from BaseProvider."""
        assert issubclass(KimiProvider, BaseProvider)

    def test_provider_has_class_docstring(self) -> None:
        """Test AC1: KimiProvider has docstring explaining its purpose."""
        assert KimiProvider.__doc__ is not None
        assert "kimi" in KimiProvider.__doc__.lower()
        assert "subprocess" in KimiProvider.__doc__.lower()

    def test_provider_name_returns_kimi(self) -> None:
        """Test AC3: provider_name returns 'kimi'."""
        provider = KimiProvider()
        assert provider.provider_name == "kimi"

    def test_default_model_returns_kimi_for_coding(self) -> None:
        """Test: default_model returns 'kimi-code/kimi-for-coding'."""
        provider = KimiProvider()
        assert provider.default_model == "kimi-code/kimi-for-coding"

    def test_default_model_is_non_empty_string(self) -> None:
        """Test: default_model returns a non-empty string."""
        provider = KimiProvider()
        assert provider.default_model is not None
        assert isinstance(provider.default_model, str)
        assert len(provider.default_model) > 0

    def test_provider_name_has_docstring(self) -> None:
        """Test: provider_name property has docstring."""
        assert KimiProvider.provider_name.fget.__doc__ is not None


class TestKimiProviderModels:
    """Test AC2: supports_model() always returns True."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    def test_supports_model_always_returns_true(self, provider: KimiProvider) -> None:
        """Test AC2: supports_model() always returns True - CLI validates models."""
        assert provider.supports_model("kimi-for-coding") is True
        assert provider.supports_model("kimi-k2") is True
        assert provider.supports_model("kimi-k2-thinking-turbo") is True
        assert provider.supports_model("any-future-model") is True
        assert provider.supports_model("gpt-4") is True  # Even non-Kimi models
        assert provider.supports_model("unknown") is True

    def test_supports_model_empty_string_returns_true(self, provider: KimiProvider) -> None:
        """Test AC2: supports_model('') returns True - CLI will reject if invalid."""
        assert provider.supports_model("") is True

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        assert KimiProvider.supports_model.__doc__ is not None


class TestKimiProviderInvokeBasic:
    """Test invoke() happy path with Popen-based streaming."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation with JSON streaming."""
        with patch("bmad_assist.providers.kimi.Popen") as mock:
            mock.return_value = create_kimi_mock_process(
                response_text="Code review complete",
                returncode=0,
            )
            yield mock

    def test_invoke_builds_correct_command_with_stream_json(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: invoke() builds command with --output-format stream-json."""
        provider.invoke("Review code", model="kimi-for-coding")

        mock_popen_success.assert_called_once()
        call_args = mock_popen_success.call_args
        command = call_args[0][0]

        assert command[:6] == [
            "kimi",
            "--print",
            "--output-format",
            "stream-json",
            "-m",
            "kimi-for-coding",
        ]

    def test_invoke_prompt_via_stdin(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC11: invoke() sends prompt via stdin, not -p flag."""
        provider.invoke("Review code", model="kimi-for-coding")

        # Verify prompt was written to stdin
        mock_process = mock_popen_success.return_value
        mock_process.stdin.write.assert_called_once()
        written_prompt = mock_process.stdin.write.call_args[0][0]
        assert "Review code" in written_prompt
        mock_process.stdin.close.assert_called_once()

    def test_invoke_uses_default_model_when_none(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: invoke(model=None) uses default_model."""
        provider.invoke("Hello", model=None)

        command = mock_popen_success.call_args[0][0]
        assert "-m" in command
        model_index = command.index("-m")
        assert command[model_index + 1] == "kimi-code/kimi-for-coding"

    def test_invoke_returns_providerresult_on_success(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC19: invoke() returns ProviderResult on exit code 0."""
        result = provider.invoke("Hello", model="kimi-for-coding", timeout=30)

        assert isinstance(result, ProviderResult)

    def test_invoke_providerresult_has_stdout(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: ProviderResult.stdout contains extracted text from JSON stream."""
        result = provider.invoke("Hello")

        assert result.stdout == "Code review complete"

    def test_invoke_providerresult_has_stderr(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: ProviderResult.stderr contains captured stderr."""
        result = provider.invoke("Hello")

        assert result.stderr == ""

    def test_invoke_providerresult_has_exit_code(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC19: ProviderResult.exit_code is 0 on success."""
        result = provider.invoke("Hello")

        assert result.exit_code == 0

    def test_invoke_providerresult_has_duration_ms(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: ProviderResult.duration_ms is positive integer."""
        result = provider.invoke("Hello")

        assert isinstance(result.duration_ms, int)
        assert result.duration_ms >= 0

    def test_invoke_providerresult_has_model(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: ProviderResult.model contains the model used."""
        result = provider.invoke("Hello", model="kimi-k2")

        assert result.model == "kimi-k2"

    def test_invoke_providerresult_model_uses_default_when_none(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: ProviderResult.model uses default when model=None."""
        result = provider.invoke("Hello", model=None)

        assert result.model == "kimi-code/kimi-for-coding"

    def test_invoke_providerresult_has_command_tuple(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: ProviderResult.command is tuple of command executed."""
        result = provider.invoke("Hello", model="kimi-k2")

        assert isinstance(result.command, tuple)
        assert result.command[:6] == (
            "kimi",
            "--print",
            "--output-format",
            "stream-json",
            "-m",
            "kimi-k2",
        )

    def test_invoke_includes_work_dir_when_cwd_provided(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: invoke() includes --work-dir when cwd is provided."""
        provider.invoke("Hello", cwd=Path("/test/project"))

        command = mock_popen_success.call_args[0][0]
        assert "--work-dir" in command
        wd_index = command.index("--work-dir")
        assert command[wd_index + 1] == "/test/project"

    def test_invoke_validates_timeout_positive(self, provider: KimiProvider) -> None:
        """Test: invoke() raises ValueError for non-positive timeout."""
        with pytest.raises(ValueError, match="timeout must be positive"):
            provider.invoke("Hello", timeout=0)

        with pytest.raises(ValueError, match="timeout must be positive"):
            provider.invoke("Hello", timeout=-1)


class TestKimiProviderThinkingMode:
    """Test AC4-7: Thinking mode auto-detection and config override."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation."""
        with patch("bmad_assist.providers.kimi.Popen") as mock:
            mock.return_value = create_kimi_mock_process(returncode=0)
            yield mock

    def test_thinking_auto_detect_from_model_name(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC4: Model name containing 'thinking' enables --thinking flag."""
        provider.invoke("Hello", model="kimi-k2-thinking-turbo")

        command = mock_popen_success.call_args[0][0]
        assert "--thinking" in command

    def test_thinking_not_enabled_for_regular_model(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC5: Model name without 'thinking' does NOT include --thinking."""
        provider.invoke("Hello", model="kimi-for-coding")

        command = mock_popen_success.call_args[0][0]
        assert "--thinking" not in command

    def test_thinking_auto_detect_case_insensitive(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: Auto-detection is case-insensitive."""
        provider.invoke("Hello", model="kimi-THINKING-test")

        command = mock_popen_success.call_args[0][0]
        assert "--thinking" in command

    def test_should_enable_thinking_with_none_model(self, provider: KimiProvider) -> None:
        """Test AC31: _should_enable_thinking() with model=None uses default_model."""
        result = provider._should_enable_thinking(None, None)
        # default_model is "kimi-for-coding" which doesn't contain "thinking"
        assert result is False

    def test_should_enable_thinking_with_empty_model(self, provider: KimiProvider) -> None:
        """Test AC31: _should_enable_thinking() with empty model uses default_model."""
        result = provider._should_enable_thinking("", None)
        assert result is False

    def test_should_enable_thinking_config_override_true(self, provider: KimiProvider) -> None:
        """Test AC6: Config param thinking=True enables thinking regardless of model."""
        # Model without "thinking" but config_thinking=True
        result = provider._should_enable_thinking("kimi-for-coding", True)
        assert result is True

    def test_should_enable_thinking_config_override_false(self, provider: KimiProvider) -> None:
        """Test AC7: Config param thinking=False disables thinking even if model has it."""
        # Model with "thinking" but config_thinking=False
        result = provider._should_enable_thinking("kimi-k2-thinking-turbo", False)
        assert result is False

    def test_should_enable_thinking_config_none_uses_autodetect(
        self, provider: KimiProvider
    ) -> None:
        """Test: Config param None falls back to auto-detection."""
        result = provider._should_enable_thinking("kimi-thinking", None)
        assert result is True

        result = provider._should_enable_thinking("kimi-regular", None)
        assert result is False


class TestKimiProviderSettingsFile:
    """Test AC8-10: Settings file handling."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation."""
        with patch("bmad_assist.providers.kimi.Popen") as mock:
            mock.return_value = create_kimi_mock_process(returncode=0)
            yield mock

    def test_invoke_with_existing_settings_file(
        self, provider: KimiProvider, mock_popen_success: MagicMock, tmp_path: Path
    ) -> None:
        """Test AC8: Valid settings_file path includes --config-file flag."""
        settings = tmp_path / "config.toml"
        settings.write_text("[kimi]\napi_key = 'test'")

        provider.invoke("Hello", settings_file=settings)

        command = mock_popen_success.call_args[0][0]
        assert "--config-file" in command
        cf_index = command.index("--config-file")
        assert command[cf_index + 1] == str(settings)

    def test_invoke_with_missing_settings_file_logs_warning(
        self, provider: KimiProvider, mock_popen_success: MagicMock, caplog
    ) -> None:
        """Test AC9: Non-existent settings_file logs warning and executes without flag."""
        missing_path = Path("/nonexistent/config.toml")

        with caplog.at_level("WARNING"):
            provider.invoke("Hello", settings_file=missing_path)

        assert "Settings file not found" in caplog.text

        command = mock_popen_success.call_args[0][0]
        assert "--config-file" not in command

    def test_invoke_without_settings_file_no_config_flag(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC10: No settings_file means no --config-file flag."""
        provider.invoke("Hello", settings_file=None)

        command = mock_popen_success.call_args[0][0]
        assert "--config-file" not in command

    # Note: Settings file resolution tests removed - now uses shared
    # resolve_settings_file() and validate_settings_file() from base.py
    # which are tested in tests/providers/test_settings_loading.py


class TestKimiProviderJSONLParsing:
    """Test AC12-15: JSONL parsing."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    def test_parse_kimi_jsonl_extracts_assistant_content(
        self, provider: KimiProvider
    ) -> None:
        """Test AC12: Parse JSONL and extract assistant content."""
        stdout = make_kimi_json_output("Response text here")

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "Response text here"

    def test_parse_kimi_jsonl_with_reasoning_content_fallback(
        self, provider: KimiProvider
    ) -> None:
        """Test AC13: reasoning_content used when content is empty."""
        msg = {"role": "assistant", "content": "", "reasoning_content": "Thinking steps..."}
        stdout = json.dumps(msg) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "Thinking steps..."

    def test_parse_kimi_jsonl_content_takes_priority_over_reasoning(
        self, provider: KimiProvider
    ) -> None:
        """Test AC13: content field has priority over reasoning_content."""
        msg = {
            "role": "assistant",
            "content": "Final answer",
            "reasoning_content": "Thinking steps...",
        }
        stdout = json.dumps(msg) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "Final answer"

    def test_parse_kimi_jsonl_skips_tool_messages(self, provider: KimiProvider) -> None:
        """Test: tool role messages are skipped."""
        lines = [
            json.dumps({"role": "assistant", "content": "Let me check"}),
            json.dumps({"role": "tool", "tool_call_id": "tc_1", "content": "file contents"}),
            json.dumps({"role": "assistant", "content": "Based on the file..."}),
        ]
        stdout = "\n".join(lines) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "Let me check\nBased on the file..."

    def test_parse_kimi_jsonl_handles_empty_content(self, provider: KimiProvider) -> None:
        """Test: Empty content field is handled gracefully."""
        msg = {"role": "assistant", "content": ""}
        stdout = json.dumps(msg) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == ""

    def test_parse_kimi_jsonl_with_tool_calls_only(self, provider: KimiProvider) -> None:
        """Test AC14: tool_calls without content extracts empty content."""
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "id": "tc_1",
                    "function": {"name": "Shell", "arguments": '{"command": "ls"}'},
                }
            ],
        }
        stdout = json.dumps(msg) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == ""

    def test_parse_kimi_jsonl_handles_malformed_json(
        self, provider: KimiProvider, caplog
    ) -> None:
        """Test AC15: Malformed JSON line is logged and skipped."""
        lines = [
            json.dumps({"role": "assistant", "content": "First"}),
            "{invalid json...",
            json.dumps({"role": "assistant", "content": "Second"}),
        ]
        stdout = "\n".join(lines) + "\n"

        with caplog.at_level("WARNING"):
            result = provider._parse_kimi_jsonl(stdout)

        assert "Malformed JSON line" in caplog.text
        assert result == "First\nSecond"


class TestKimiProviderToolCalls:
    """Test tool_calls array handling."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation."""
        with patch("bmad_assist.providers.kimi.Popen") as mock:
            mock.return_value = create_kimi_mock_process(returncode=0)
            yield mock

    def test_tool_calls_logged_but_not_in_output(
        self, provider: KimiProvider
    ) -> None:
        """Test AC14: tool_calls are logged but not included in output text."""
        msg = {
            "role": "assistant",
            "content": "Let me check the file",
            "tool_calls": [
                {
                    "type": "function",
                    "id": "tc_1",
                    "function": {"name": "ReadFile", "arguments": '{"path": "/test.py"}'},
                }
            ],
        }
        stdout = json.dumps(msg) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "Let me check the file"
        assert "ReadFile" not in result
        assert "tc_1" not in result

    def test_mixed_tool_calls_and_content(self, provider: KimiProvider) -> None:
        """Test: Messages with both tool_calls and content extract content only."""
        lines = [
            json.dumps({
                "role": "assistant",
                "content": "Step 1",
                "tool_calls": [{"type": "function", "id": "tc_1", "function": {"name": "Shell", "arguments": "{}"}}],
            }),
            json.dumps({"role": "tool", "tool_call_id": "tc_1", "content": "output"}),
            json.dumps({"role": "assistant", "content": "Step 2"}),
        ]
        stdout = "\n".join(lines) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "Step 1\nStep 2"

    def test_multiple_tool_calls_in_single_message(self, provider: KimiProvider) -> None:
        """Test: Multiple tool_calls in one message are handled."""
        msg = {
            "role": "assistant",
            "content": "Running checks",
            "tool_calls": [
                {"type": "function", "id": "tc_1", "function": {"name": "ReadFile", "arguments": "{}"}},
                {"type": "function", "id": "tc_2", "function": {"name": "Grep", "arguments": "{}"}},
            ],
        }
        stdout = json.dumps(msg) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "Running checks"


class TestKimiProviderThinkingContent:
    """Test reasoning_content edge cases."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    def test_thinking_only_response_uses_reasoning(self, provider: KimiProvider) -> None:
        """Test: Response with only reasoning_content (no content) uses reasoning."""
        msg = {"role": "assistant", "reasoning_content": "Step by step thinking..."}
        stdout = json.dumps(msg) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "Step by step thinking..."

    def test_empty_content_with_reasoning_uses_reasoning(
        self, provider: KimiProvider
    ) -> None:
        """Test: Empty content string with reasoning_content uses reasoning."""
        msg = {"role": "assistant", "content": "", "reasoning_content": "Thinking..."}
        stdout = json.dumps(msg) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "Thinking..."

    def test_both_empty_returns_empty_string(self, provider: KimiProvider) -> None:
        """Test: Both content and reasoning_content empty returns empty string."""
        msg = {"role": "assistant", "content": "", "reasoning_content": ""}
        stdout = json.dumps(msg) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == ""

    def test_neither_field_returns_empty_string(self, provider: KimiProvider) -> None:
        """Test: Neither content nor reasoning_content returns empty string."""
        msg = {"role": "assistant"}
        stdout = json.dumps(msg) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == ""


class TestKimiProviderMalformedJSON:
    """Test AC15: Graceful degradation for malformed JSON."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    def test_partial_json_line_skipped(self, provider: KimiProvider, caplog) -> None:
        """Test: Partial/truncated JSON is skipped with warning."""
        lines = [
            json.dumps({"role": "assistant", "content": "Start"}),
            '{"role": "assistant", "content": "Trun',  # Truncated
        ]
        stdout = "\n".join(lines) + "\n"

        with caplog.at_level("WARNING"):
            result = provider._parse_kimi_jsonl(stdout)

        assert "Malformed JSON line" in caplog.text
        assert result == "Start"

    def test_completely_invalid_json_skipped(self, provider: KimiProvider, caplog) -> None:
        """Test: Completely invalid JSON is skipped."""
        lines = [
            json.dumps({"role": "assistant", "content": "Valid"}),
            "not json at all",
            json.dumps({"role": "assistant", "content": "Also valid"}),
        ]
        stdout = "\n".join(lines) + "\n"

        with caplog.at_level("WARNING"):
            result = provider._parse_kimi_jsonl(stdout)

        assert result == "Valid\nAlso valid"

    def test_empty_lines_ignored(self, provider: KimiProvider) -> None:
        """Test: Empty lines are silently ignored."""
        lines = [
            json.dumps({"role": "assistant", "content": "First"}),
            "",
            "   ",
            json.dumps({"role": "assistant", "content": "Second"}),
        ]
        stdout = "\n".join(lines) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "First\nSecond"

    def test_long_malformed_line_truncated_in_log(
        self, provider: KimiProvider, caplog
    ) -> None:
        """Test: Long malformed lines are truncated in log messages."""
        long_invalid = "x" * 200  # > 100 chars
        lines = [
            json.dumps({"role": "assistant", "content": "Valid"}),
            long_invalid,
        ]
        stdout = "\n".join(lines) + "\n"

        with caplog.at_level("WARNING"):
            provider._parse_kimi_jsonl(stdout)

        # Log should contain truncated version with ...
        assert "..." in caplog.text


class TestKimiProviderRetryLogic:
    """Test AC16-18: Retry logic for transient failures."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    def test_is_transient_error_rate_limit(self) -> None:
        """Test AC24: Exit 1 with '429' is transient (retry)."""
        assert _is_kimi_transient_error("Error: 429 Too Many Requests", 1) is True
        assert _is_kimi_transient_error("rate limit exceeded", 1) is True

    def test_is_transient_error_unauthorized(self) -> None:
        """Test AC25: Exit 1 with '401 unauthorized' is NOT transient (no retry)."""
        assert _is_kimi_transient_error("Error: 401 unauthorized", 1) is False
        assert _is_kimi_transient_error("authentication failed", 1) is False

    def test_is_transient_error_server_errors(self) -> None:
        """Test: 5xx errors are transient."""
        assert _is_kimi_transient_error("500 Internal Server Error", 1) is True
        assert _is_kimi_transient_error("503 service unavailable", 1) is True

    def test_is_transient_error_exit_0_not_transient(self) -> None:
        """Test: Exit code 0 is never transient."""
        assert _is_kimi_transient_error("some error", 0) is False

    def test_is_transient_error_exit_2_not_transient(self) -> None:
        """Test: Exit code 2 (BadParameter) is never transient."""
        assert _is_kimi_transient_error("some error", 2) is False

    def test_is_transient_error_exit_127_not_transient(self) -> None:
        """Test: Exit code 127 (not found) is never transient."""
        assert _is_kimi_transient_error("some error", 127) is False

    def test_is_transient_error_empty_stderr_exit_1(self) -> None:
        """Test: Empty stderr with exit 1 is transient (network issue)."""
        assert _is_kimi_transient_error("", 1) is True
        assert _is_kimi_transient_error("   ", 1) is True

    def test_calculate_retry_delay_exponential_backoff(self) -> None:
        """Test: Delay increases exponentially."""
        delay_0 = _calculate_retry_delay(0)
        delay_1 = _calculate_retry_delay(1)
        delay_2 = _calculate_retry_delay(2)

        # Base is 2.0s with ±25% jitter
        assert 1.5 <= delay_0 <= 2.5
        assert 3.0 <= delay_1 <= 5.0
        assert 6.0 <= delay_2 <= 10.0

    def test_calculate_retry_delay_capped_at_max(self) -> None:
        """Test AC32: Delay is capped at RETRY_MAX_DELAY."""
        delay_high = _calculate_retry_delay(10)  # Would be 2^10 * 2 = 2048s without cap

        # Max is 30s with ±25% jitter
        assert delay_high <= RETRY_MAX_DELAY * 1.25
        assert delay_high >= RETRY_MAX_DELAY * 0.75 * 0.5  # Allow for jitter

    def test_invoke_retries_on_transient_error(self, provider: KimiProvider) -> None:
        """Test AC16: invoke() retries on transient error."""
        call_count = 0

        def mock_wait(timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return 1  # Fail first 2 times
            return 0  # Succeed on 3rd

        with patch("bmad_assist.providers.kimi.Popen") as mock_popen:
            mock_process = create_kimi_mock_process(returncode=0)
            mock_process.wait = mock_wait
            mock_popen.return_value = mock_process

            with patch("bmad_assist.providers.kimi.time.sleep"):  # Skip delays
                result = provider.invoke("Hello")

        assert call_count == 3
        assert result.exit_code == 0

    def test_invoke_no_retry_on_permanent_error(self, provider: KimiProvider) -> None:
        """Test AC17: invoke() raises immediately on permanent error (exit 2)."""
        with patch("bmad_assist.providers.kimi.Popen") as mock_popen:
            mock_popen.return_value = create_kimi_mock_process(
                stderr_content="BadParameter: invalid flag",
                returncode=2,
            )

            with pytest.raises(ProviderExitCodeError):
                provider.invoke("Hello")

        # Should only be called once (no retry)
        assert mock_popen.call_count == 1


class TestKimiProviderErrors:
    """Test AC19-21: Error handling."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    def test_invoke_raises_provider_timeout_error(self, provider: KimiProvider) -> None:
        """Test AC21: invoke() raises ProviderTimeoutError on timeout."""
        with patch("bmad_assist.providers.kimi.Popen") as mock_popen:
            mock_process = create_kimi_mock_process(returncode=0)
            # Make first wait() raise TimeoutExpired, subsequent calls return 0
            wait_call_count = [0]

            def mock_wait(timeout=None):
                wait_call_count[0] += 1
                if wait_call_count[0] == 1:
                    raise TimeoutExpired(cmd=["kimi"], timeout=timeout or 5)
                return 0  # cleanup calls succeed

            mock_process.wait = MagicMock(side_effect=mock_wait)
            mock_process.terminate = MagicMock()
            mock_process.kill = MagicMock()
            mock_popen.return_value = mock_process

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert "timeout" in str(exc_info.value).lower()

    def test_invoke_timeout_includes_partial_result(self, provider: KimiProvider) -> None:
        """Test AC21: Timeout error includes partial result."""
        with patch("bmad_assist.providers.kimi.Popen") as mock_popen:
            mock_process = create_kimi_mock_process(returncode=0)
            # Make first wait() raise TimeoutExpired, subsequent calls return 0
            wait_call_count = [0]

            def mock_wait(timeout=None):
                wait_call_count[0] += 1
                if wait_call_count[0] == 1:
                    raise TimeoutExpired(cmd=["kimi"], timeout=timeout or 5)
                return 0  # cleanup calls succeed

            mock_process.wait = MagicMock(side_effect=mock_wait)
            mock_process.terminate = MagicMock()
            mock_process.kill = MagicMock()
            mock_popen.return_value = mock_process

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert exc_info.value.partial_result is not None
            assert isinstance(exc_info.value.partial_result, ProviderResult)

    def test_invoke_raises_exit_code_error_on_failure(
        self, provider: KimiProvider
    ) -> None:
        """Test: invoke() raises ProviderExitCodeError on non-zero exit."""
        with patch("bmad_assist.providers.kimi.Popen") as mock_popen:
            mock_popen.return_value = create_kimi_mock_process(
                stderr_content="API error: 404 model not found",
                returncode=1,
            )

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            assert exc_info.value.exit_code == 1

    def test_invoke_raises_provider_error_when_cli_not_found(
        self, provider: KimiProvider
    ) -> None:
        """Test AC20: invoke() raises ProviderError when CLI not found."""
        with patch("bmad_assist.providers.kimi.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("kimi")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert "not found" in str(exc_info.value).lower()


class TestKimiProviderExitStatus:
    """Test exit status classification."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    def test_exit_status_127_not_found(self, provider: KimiProvider) -> None:
        """Test AC20: Exit code 127 maps to NOT_FOUND status."""
        with patch("bmad_assist.providers.kimi.Popen") as mock_popen:
            mock_popen.return_value = create_kimi_mock_process(returncode=127)

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            from bmad_assist.providers.base import ExitStatus
            assert exc_info.value.exit_status == ExitStatus.NOT_FOUND

    def test_exit_status_126_cannot_execute(self, provider: KimiProvider) -> None:
        """Test: Exit code 126 maps to CANNOT_EXECUTE status."""
        with patch("bmad_assist.providers.kimi.Popen") as mock_popen:
            mock_popen.return_value = create_kimi_mock_process(returncode=126)

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            from bmad_assist.providers.base import ExitStatus
            assert exc_info.value.exit_status == ExitStatus.CANNOT_EXECUTE

    def test_exit_status_2_misuse(self, provider: KimiProvider) -> None:
        """Test: Exit code 2 maps to MISUSE status."""
        with patch("bmad_assist.providers.kimi.Popen") as mock_popen:
            mock_popen.return_value = create_kimi_mock_process(returncode=2)

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            from bmad_assist.providers.base import ExitStatus
            assert exc_info.value.exit_status == ExitStatus.MISUSE

    def test_exit_status_signal(self, provider: KimiProvider) -> None:
        """Test: Exit code > 128 maps to SIGNAL status."""
        with patch("bmad_assist.providers.kimi.Popen") as mock_popen:
            mock_popen.return_value = create_kimi_mock_process(returncode=137)  # SIGKILL

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello")

            from bmad_assist.providers.base import ExitStatus
            assert exc_info.value.exit_status == ExitStatus.SIGNAL


class TestKimiProviderEmptyResponse:
    """Test empty/missing content handling."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    def test_empty_response_no_assistant_messages(self, provider: KimiProvider) -> None:
        """Test: No assistant messages returns empty string."""
        stdout = json.dumps({"role": "user", "content": "Hello"}) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == ""

    def test_empty_stdout_returns_empty_string(self, provider: KimiProvider) -> None:
        """Test: Empty stdout returns empty string."""
        result = provider._parse_kimi_jsonl("")

        assert result == ""

    def test_whitespace_only_content_preserved(self, provider: KimiProvider) -> None:
        """Test: Whitespace-only content is preserved (not stripped in parsing)."""
        msg = {"role": "assistant", "content": "   "}
        stdout = json.dumps(msg) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "   "

    def test_parse_output_strips_whitespace(self, provider: KimiProvider) -> None:
        """Test: parse_output() strips leading/trailing whitespace."""
        result = ProviderResult(
            stdout="  response text  \n",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="kimi",
            command=("kimi",),
        )

        assert provider.parse_output(result) == "response text"


class TestKimiProviderExports:
    """Test AC22-23: Registry integration and exports."""

    def test_kimi_in_list_providers(self) -> None:
        """Test AC22: 'kimi' is in list_providers()."""
        providers = list_providers()
        assert "kimi" in providers

    def test_get_provider_returns_kimi_instance(self) -> None:
        """Test AC22: get_provider('kimi') returns KimiProvider instance."""
        provider = get_provider("kimi")
        assert isinstance(provider, KimiProvider)
        assert provider.provider_name == "kimi"

    def test_kimi_provider_exported_from_package(self) -> None:
        """Test: KimiProvider is exported from providers package."""
        from bmad_assist.providers import KimiProvider as ImportedProvider
        assert ImportedProvider is KimiProvider


class TestKimiProviderMultipleMessages:
    """Test AC30: Multiple assistant messages concatenation."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    def test_multiple_messages_joined_with_newline(self, provider: KimiProvider) -> None:
        """Test AC30: Multiple assistant messages joined with newlines."""
        stdout = make_kimi_multi_message_output(["First", "Second", "Third"])

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "First\nSecond\nThird"

    def test_multiple_messages_preserve_order(self, provider: KimiProvider) -> None:
        """Test: Message order is preserved."""
        lines = [
            json.dumps({"role": "assistant", "content": "One"}),
            json.dumps({"role": "assistant", "content": "Two"}),
            json.dumps({"role": "assistant", "content": "Three"}),
        ]
        stdout = "\n".join(lines) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        parts = result.split("\n")
        assert parts == ["One", "Two", "Three"]


class TestKimiProviderToolRestrictions:
    """Test AC26: Tool restriction prompt injection."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    @pytest.fixture
    def mock_popen_success(self):
        """Mock Popen for successful invocation."""
        with patch("bmad_assist.providers.kimi.Popen") as mock:
            mock.return_value = create_kimi_mock_process(returncode=0)
            yield mock

    def test_allowed_tools_injects_restriction_prefix(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test AC26: allowed_tools set injects tool restriction prefix."""
        provider.invoke("Review code", allowed_tools=["Read", "Glob"])

        mock_process = mock_popen_success.return_value
        written_prompt = mock_process.stdin.write.call_args[0][0]

        assert "VALIDATOR" in written_prompt
        assert "ALLOWED TOOLS: Read, Glob" in written_prompt
        assert "Review code" in written_prompt

    def test_no_allowed_tools_no_restriction(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: allowed_tools=None means no restriction prefix."""
        provider.invoke("Review code", allowed_tools=None)

        mock_process = mock_popen_success.return_value
        written_prompt = mock_process.stdin.write.call_args[0][0]

        assert "VALIDATOR" not in written_prompt
        assert written_prompt == "Review code"

    def test_empty_allowed_tools_shows_none(
        self, provider: KimiProvider, mock_popen_success: MagicMock
    ) -> None:
        """Test: allowed_tools=[] shows 'NONE' in restriction."""
        provider.invoke("Review code", allowed_tools=[])

        mock_process = mock_popen_success.return_value
        written_prompt = mock_process.stdin.write.call_args[0][0]

        assert "ALLOWED TOOLS: NONE" in written_prompt


class TestKimiProviderUnicode:
    """Test Unicode handling (emoji, CJK, special chars)."""

    @pytest.fixture
    def provider(self) -> KimiProvider:
        """Create KimiProvider instance."""
        return KimiProvider()

    def test_unicode_in_content(self, provider: KimiProvider) -> None:
        """Test: Unicode content is preserved."""
        msg = {"role": "assistant", "content": "Hello 你好 🎉 émoji"}
        stdout = json.dumps(msg, ensure_ascii=False) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "Hello 你好 🎉 émoji"

    def test_unicode_in_reasoning_content(self, provider: KimiProvider) -> None:
        """Test: Unicode in reasoning_content is preserved."""
        msg = {"role": "assistant", "content": "", "reasoning_content": "思考中... 🤔"}
        stdout = json.dumps(msg, ensure_ascii=False) + "\n"

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "思考中... 🤔"

    def test_escaped_unicode_decoded(self, provider: KimiProvider) -> None:
        """Test: Escaped Unicode is properly decoded."""
        # JSON with escaped unicode
        stdout = '{"role": "assistant", "content": "Hello \\u4e16\\u754c"}\n'

        result = provider._parse_kimi_jsonl(stdout)

        assert result == "Hello 世界"


class TestDocstringsExist:
    """Test Google-style docstrings exist."""

    def test_kimiprovider_class_docstring(self) -> None:
        """Test: KimiProvider has class docstring."""
        assert KimiProvider.__doc__ is not None
        assert len(KimiProvider.__doc__) > 100

    def test_invoke_method_docstring(self) -> None:
        """Test: invoke() has detailed docstring."""
        assert KimiProvider.invoke.__doc__ is not None
        assert "Args:" in KimiProvider.invoke.__doc__
        assert "Returns:" in KimiProvider.invoke.__doc__
        assert "Raises:" in KimiProvider.invoke.__doc__

    def test_parse_output_method_docstring(self) -> None:
        """Test: parse_output() has docstring."""
        assert KimiProvider.parse_output.__doc__ is not None

    def test_supports_model_method_docstring(self) -> None:
        """Test: supports_model() has docstring."""
        assert KimiProvider.supports_model.__doc__ is not None

    def test_truncate_prompt_docstring(self) -> None:
        """Test: _truncate_prompt() has docstring."""
        assert _truncate_prompt.__doc__ is not None

    def test_is_kimi_transient_error_docstring(self) -> None:
        """Test: _is_kimi_transient_error() has docstring."""
        assert _is_kimi_transient_error.__doc__ is not None

    def test_calculate_retry_delay_docstring(self) -> None:
        """Test: _calculate_retry_delay() has docstring."""
        assert _calculate_retry_delay.__doc__ is not None


class TestTruncatePrompt:
    """Test _truncate_prompt() helper."""

    def test_short_prompt_not_truncated(self) -> None:
        """Test: Prompt <= limit is returned unchanged."""
        prompt = "short prompt"
        result = _truncate_prompt(prompt)
        assert result == prompt

    def test_exact_limit_not_truncated(self) -> None:
        """Test: Prompt exactly at limit is not truncated."""
        prompt = "x" * PROMPT_TRUNCATE_LENGTH
        result = _truncate_prompt(prompt)
        assert result == prompt

    def test_long_prompt_truncated(self) -> None:
        """Test: Long prompt is truncated with ellipsis."""
        prompt = "x" * (PROMPT_TRUNCATE_LENGTH + 50)
        result = _truncate_prompt(prompt)
        assert len(result) == PROMPT_TRUNCATE_LENGTH + 3
        assert result.endswith("...")


class TestConstants:
    """Test module constants are properly defined."""

    def test_default_timeout_positive(self) -> None:
        """Test: DEFAULT_TIMEOUT is positive."""
        assert DEFAULT_TIMEOUT > 0

    def test_max_retries_positive(self) -> None:
        """Test: MAX_RETRIES is positive."""
        assert MAX_RETRIES > 0

    def test_retry_delays_positive(self) -> None:
        """Test: Retry delay constants are positive."""
        assert RETRY_BASE_DELAY > 0
        assert RETRY_MAX_DELAY > RETRY_BASE_DELAY

    def test_transient_patterns_non_empty(self) -> None:
        """Test: KIMI_TRANSIENT_PATTERNS is non-empty."""
        assert len(KIMI_TRANSIENT_PATTERNS) > 0

    def test_permanent_patterns_non_empty(self) -> None:
        """Test: KIMI_PERMANENT_PATTERNS is non-empty."""
        assert len(KIMI_PERMANENT_PATTERNS) > 0
