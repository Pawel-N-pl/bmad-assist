"""Tests for timeout error prompt leak prevention (Fix #5)."""

import logging
from unittest.mock import patch

import pytest

from bmad_assist.core.exceptions import ProviderTimeoutError
from bmad_assist.providers import ClaudeSubprocessProvider

from .conftest import create_mock_process


class TestTimeoutErrorNoPromptLeak:
    """Verify timeout errors don't leak prompt content (Fix #5)."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create provider instance."""
        return ClaudeSubprocessProvider()

    def test_timeout_error_does_not_contain_prompt(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Error message must not contain the prompt text."""
        unique_prompt = "UNIQUE_SECRET_PROMPT_CONTENT_xyz123"

        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(never_finish=True)

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke(unique_prompt, timeout=5)

        error_msg = str(exc_info.value)
        assert unique_prompt not in error_msg

    def test_timeout_error_contains_timeout_value(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Error message should include the timeout duration."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(never_finish=True)

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("test prompt", timeout=5)

        error_msg = str(exc_info.value)
        assert "5s" in error_msg

    def test_timeout_error_contains_model_info(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Error message should include model info."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(never_finish=True)

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("test prompt", timeout=5, model="opus")

        error_msg = str(exc_info.value)
        assert "model=" in error_msg

    def test_timeout_error_contains_prompt_char_count(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Error message should include prompt length instead of content."""
        prompt = "x" * 5000

        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(never_finish=True)

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke(prompt, timeout=5)

        error_msg = str(exc_info.value)
        assert "prompt_chars=5000" in error_msg

    def test_prompt_logged_at_provider_level(
        self, provider: ClaudeSubprocessProvider, accelerated_time, caplog
    ) -> None:
        """Truncated prompt IS logged as WARNING at provider level."""
        prompt = "a" * 200

        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(never_finish=True)

            with (
                caplog.at_level(logging.WARNING, logger="bmad_assist.providers.claude"),
                pytest.raises(ProviderTimeoutError),
            ):
                provider.invoke(prompt, timeout=5)

        # Provider-level log should contain truncated prompt
        assert "prompt=" in caplog.text
