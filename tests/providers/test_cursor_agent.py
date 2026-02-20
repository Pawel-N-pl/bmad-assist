"""Tests for CursorAgentProvider.

Tests the Cursor Agent CLI subprocess-based provider implementation.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers import CursorAgentProvider
from bmad_assist.providers.base import BaseProvider, ExitStatus, ProviderResult

from .conftest import create_cursor_mock_process


class TestCursorAgentProviderStructure:
    """Tests for CursorAgentProvider class structure and inheritance."""

    def test_inherits_from_base_provider(self):
        """CursorAgentProvider should inherit from BaseProvider."""
        provider = CursorAgentProvider()
        assert isinstance(provider, BaseProvider)

    def test_provider_name_is_cursor_agent(self):
        """Provider name should be 'cursor-agent'."""
        provider = CursorAgentProvider()
        assert provider.provider_name == "cursor-agent"

    def test_default_model_is_claude_sonnet_4(self):
        """Default model should be 'claude-sonnet-4'."""
        provider = CursorAgentProvider()
        assert provider.default_model == "claude-sonnet-4"


class TestCursorAgentProviderModels:
    """Tests for model support."""

    def test_supports_any_model(self):
        """supports_model should always return True."""
        provider = CursorAgentProvider()
        assert provider.supports_model("claude-sonnet-4") is True
        assert provider.supports_model("gpt-4o") is True
        assert provider.supports_model("any-model-name") is True
        assert provider.supports_model("") is True


class TestCursorAgentProviderInvoke:
    """Tests for invoke method."""

    def test_invoke_success(self, mock_cursor_popen_success):
        """Successful invocation should return ProviderResult."""
        provider = CursorAgentProvider()
        result = provider.invoke("Test prompt", timeout=30)

        assert isinstance(result, ProviderResult)
        assert result.exit_code == 0
        assert "Mock Cursor Agent response" in result.stdout
        assert result.model == "claude-sonnet-4"

    def test_invoke_with_model(self, mock_cursor_popen_success):
        """Should use specified model."""
        provider = CursorAgentProvider()
        result = provider.invoke("Test prompt", model="gpt-4o", timeout=30)

        assert result.model == "gpt-4o"
        # Check command includes model
        assert "--model" in result.command
        assert "gpt-4o" in result.command

    def test_invoke_command_structure(self, mock_cursor_popen_success):
        """Command should have correct structure."""
        provider = CursorAgentProvider()
        result = provider.invoke("Test prompt", timeout=30)

        assert result.command[0] == "cursor-agent"
        assert "--print" in result.command
        assert "--model" in result.command
        assert "--force" in result.command
        assert "Test prompt" in result.command

    def test_invoke_with_cwd(self):
        """Should pass cwd to Popen."""
        with patch("bmad_assist.providers.cursor_agent.Popen") as mock_popen:
            mock_popen.return_value = create_cursor_mock_process()
            provider = CursorAgentProvider()
            test_cwd = Path("/tmp/test-project")

            provider.invoke("Test prompt", cwd=test_cwd, timeout=30)

            # Check Popen was called with cwd
            call_kwargs = mock_popen.call_args.kwargs
            assert call_kwargs["cwd"] == test_cwd

    def test_invoke_uses_default_timeout(self, mock_cursor_popen_success):
        """Should use DEFAULT_TIMEOUT when timeout is None."""
        provider = CursorAgentProvider()
        result = provider.invoke("Test prompt")  # No timeout specified

        # Should complete without error
        assert result.exit_code == 0

    def test_invoke_negative_timeout_raises(self):
        """Negative timeout should raise ValueError."""
        provider = CursorAgentProvider()
        with pytest.raises(ValueError, match="timeout must be positive"):
            provider.invoke("Test prompt", timeout=-1)

    def test_invoke_zero_timeout_raises(self):
        """Zero timeout should raise ValueError."""
        provider = CursorAgentProvider()
        with pytest.raises(ValueError, match="timeout must be positive"):
            provider.invoke("Test prompt", timeout=0)


class TestCursorAgentProviderErrors:
    """Tests for error handling."""

    def test_cli_not_found_raises_provider_error(self, mock_cursor_popen_not_found):
        """FileNotFoundError should raise ProviderError."""
        provider = CursorAgentProvider()
        with pytest.raises(ProviderError, match="Cursor Agent CLI not found"):
            provider.invoke("Test prompt", timeout=30)

    def test_timeout_raises_provider_timeout_error(self, mock_cursor_popen_timeout):
        """Timeout should raise ProviderTimeoutError."""
        provider = CursorAgentProvider()
        with pytest.raises(ProviderTimeoutError, match="Cursor Agent CLI timeout"):
            provider.invoke("Test prompt", timeout=5)

    def test_timeout_error_has_partial_result(self, mock_cursor_popen_timeout):
        """ProviderTimeoutError should include partial_result."""
        provider = CursorAgentProvider()
        with pytest.raises(ProviderTimeoutError) as exc_info:
            provider.invoke("Test prompt", timeout=5)

        assert exc_info.value.partial_result is not None
        assert exc_info.value.partial_result.exit_code == -1

    def test_nonzero_exit_raises_exit_code_error(self, mock_cursor_popen_error):
        """Non-zero exit should raise ProviderExitCodeError."""
        provider = CursorAgentProvider()
        with pytest.raises(ProviderExitCodeError, match="exit code 1"):
            provider.invoke("Test prompt", timeout=30)

    def test_exit_code_error_has_details(self, mock_cursor_popen_error):
        """ProviderExitCodeError should include exit details."""
        provider = CursorAgentProvider()
        with pytest.raises(ProviderExitCodeError) as exc_info:
            provider.invoke("Test prompt", timeout=30)

        assert exc_info.value.exit_code == 1
        assert exc_info.value.exit_status == ExitStatus.ERROR
        assert "Cursor Agent error message" in exc_info.value.stderr


class TestCursorAgentProviderParseOutput:
    """Tests for parse_output method."""

    def test_parse_output_strips_whitespace(self):
        """parse_output should strip leading/trailing whitespace."""
        provider = CursorAgentProvider()
        result = ProviderResult(
            stdout="  Response text  \n",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="claude-sonnet-4",
            command=("cursor-agent", "--print", "test"),
        )

        parsed = provider.parse_output(result)
        assert parsed == "Response text"

    def test_parse_output_empty_string(self):
        """parse_output should handle empty stdout."""
        provider = CursorAgentProvider()
        result = ProviderResult(
            stdout="",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="claude-sonnet-4",
            command=("cursor-agent", "--print", "test"),
        )

        parsed = provider.parse_output(result)
        assert parsed == ""


class TestCursorAgentProviderSettings:
    """Tests for settings file handling."""

    def test_settings_file_validated_but_not_passed(self):
        """Settings file should be validated but not passed to CLI."""
        with patch("bmad_assist.providers.cursor_agent.Popen") as mock_popen:
            mock_popen.return_value = create_cursor_mock_process()

            # Create a temp file that "exists"
            with patch("bmad_assist.providers.base.Path.exists", return_value=True):
                with patch("bmad_assist.providers.base.Path.is_file", return_value=True):
                    provider = CursorAgentProvider()
                    settings = Path("/tmp/settings.json")

                    result = provider.invoke("Test", settings_file=settings, timeout=30)

                    # Settings should NOT be in command
                    assert str(settings) not in result.command

    def test_missing_settings_file_logs_warning(self, caplog):
        """Missing settings file should log warning but not fail."""
        with patch("bmad_assist.providers.cursor_agent.Popen") as mock_popen:
            mock_popen.return_value = create_cursor_mock_process()
            provider = CursorAgentProvider()
            settings = Path("/nonexistent/settings.json")

            # Should complete without raising
            result = provider.invoke("Test", settings_file=settings, timeout=30)

            assert result.exit_code == 0


class TestCursorAgentProviderRetry:
    """Tests for retry behavior on transient errors."""

    def test_retries_on_transient_error(self):
        """Should retry on transient errors (empty stderr + exit code 1)."""
        call_count = 0

        def create_process_with_fail_then_success(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                # First two calls fail with empty stderr (transient)
                return create_cursor_mock_process(
                    stdout_content="",
                    stderr_content="",
                    returncode=1,
                )
            # Third call succeeds
            return create_cursor_mock_process(response_text="Success")

        with patch("bmad_assist.providers.cursor_agent.Popen") as mock_popen:
            with patch("bmad_assist.providers.cursor_agent.time.sleep"):
                mock_popen.side_effect = create_process_with_fail_then_success
                provider = CursorAgentProvider()

                result = provider.invoke("Test prompt", timeout=30)

                assert result.exit_code == 0
                assert call_count == 3  # Failed twice, succeeded third time

    def test_no_retry_on_permanent_error(self):
        """Should not retry on permanent errors (non-empty stderr)."""
        with patch("bmad_assist.providers.cursor_agent.Popen") as mock_popen:
            mock_popen.return_value = create_cursor_mock_process(
                stdout_content="",
                stderr_content="Invalid API key",
                returncode=1,
            )
            provider = CursorAgentProvider()

            with pytest.raises(ProviderExitCodeError, match="Invalid API key"):
                provider.invoke("Test prompt", timeout=30)

            # Should only have tried once
            assert mock_popen.call_count == 1

    def test_max_retries_reached(self):
        """Should raise after MAX_RETRIES attempts."""
        with patch("bmad_assist.providers.cursor_agent.Popen") as mock_popen:
            with patch("bmad_assist.providers.cursor_agent.time.sleep"):
                # Always fail with transient error
                mock_popen.return_value = create_cursor_mock_process(
                    stdout_content="",
                    stderr_content="",
                    returncode=1,
                )
                provider = CursorAgentProvider()

                with pytest.raises(ProviderExitCodeError):
                    provider.invoke("Test prompt", timeout=30)

                # Should have tried MAX_RETRIES (5) times
                assert mock_popen.call_count == 5


class TestCursorAgentProviderIgnoredFlags:
    """Tests for flags that are ignored by Cursor Agent."""

    def test_disable_tools_ignored(self, mock_cursor_popen_success):
        """disable_tools should be ignored."""
        provider = CursorAgentProvider()
        result = provider.invoke("Test", disable_tools=True, timeout=30)

        # Should still complete successfully
        assert result.exit_code == 0

    def test_allowed_tools_ignored(self, mock_cursor_popen_success):
        """allowed_tools should be ignored."""
        provider = CursorAgentProvider()
        result = provider.invoke("Test", allowed_tools=["Read", "Bash"], timeout=30)

        assert result.exit_code == 0

    def test_no_cache_ignored(self, mock_cursor_popen_success):
        """no_cache should be ignored."""
        provider = CursorAgentProvider()
        result = provider.invoke("Test", no_cache=True, timeout=30)

        assert result.exit_code == 0
