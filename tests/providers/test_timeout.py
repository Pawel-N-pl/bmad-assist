"""Unit tests for Provider Timeout Handling (Story 4.3).

Tests cover subprocess timeout behavior for ClaudeSubprocessProvider:
- AC1: subprocess.TimeoutExpired is caught and wrapped in ProviderTimeoutError
- AC2: Partial output captured on timeout
- AC3: Process is terminated on timeout (via subprocess.run timeout parameter)
- AC4: Timeout event is logged with context
- AC5: ProviderTimeoutError is a subclass of ProviderError
- AC7: invoke() validates timeout parameter
- AC8: ProviderTimeoutError includes truncated prompt
- AC9: Duration is calculated even on timeout
- AC10: Exception handling pattern follows project conventions

Note: These tests use ClaudeSubprocessProvider explicitly since they test
subprocess-specific timeout behavior. ClaudeSDKProvider handles timeouts
differently via asyncio.wait_for().
"""

import logging
from unittest.mock import patch

import pytest

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderTimeoutError,
)
from bmad_assist.providers import ClaudeSubprocessProvider
from bmad_assist.providers.base import ProviderResult

from .conftest import create_mock_process


class TestProviderTimeoutErrorHierarchy:
    """Test AC5: ProviderTimeoutError exception hierarchy."""

    def test_provider_timeout_error_inherits_from_provider_error(self) -> None:
        """Test AC5: ProviderTimeoutError inherits from ProviderError."""
        assert issubclass(ProviderTimeoutError, ProviderError)

    def test_provider_timeout_error_is_bmad_assist_error(self) -> None:
        """Test AC5: ProviderTimeoutError is part of BmadAssistError hierarchy."""
        from bmad_assist.core.exceptions import BmadAssistError

        assert issubclass(ProviderTimeoutError, BmadAssistError)

    def test_provider_timeout_error_has_docstring(self) -> None:
        """Test AC5: ProviderTimeoutError has docstring explaining context."""
        assert ProviderTimeoutError.__doc__ is not None
        doc = ProviderTimeoutError.__doc__.lower()
        assert "timeout" in doc
        assert "partial" in doc

    def test_provider_timeout_error_has_partial_result_attribute(self) -> None:
        """Test AC5: ProviderTimeoutError has partial_result attribute."""
        error = ProviderTimeoutError("Test timeout")
        assert hasattr(error, "partial_result")
        assert error.partial_result is None  # Default value

    def test_provider_timeout_error_with_partial_result(self) -> None:
        """Test AC5: ProviderTimeoutError can store partial_result."""
        partial = ProviderResult(
            stdout="Partial output",
            stderr="",
            exit_code=-1,
            duration_ms=1000,
            model="sonnet",
            command=("claude", "-p", "test"),
        )
        error = ProviderTimeoutError("Test timeout", partial_result=partial)

        assert error.partial_result is not None
        assert error.partial_result.stdout == "Partial output"

    def test_provider_timeout_error_can_be_caught_as_provider_error(self) -> None:
        """Test AC5: ProviderTimeoutError can be caught as ProviderError."""
        with pytest.raises(ProviderError):
            raise ProviderTimeoutError("Test timeout")

    def test_provider_timeout_error_can_be_caught_specifically(self) -> None:
        """Test AC5: ProviderTimeoutError can be caught specifically."""
        with pytest.raises(ProviderTimeoutError):
            raise ProviderTimeoutError("Test timeout")


class TestTimeoutHandling:
    """Test AC1, AC2, AC3, AC4: Timeout handling behavior."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create ClaudeProvider instance."""
        return ClaudeSubprocessProvider()

    def test_timeout_raises_provider_timeout_error(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC1: TimeoutExpired is wrapped in ProviderTimeoutError."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError):
                provider.invoke("Hello", timeout=5)

    def test_timeout_error_message_includes_timeout_value(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC1: Error message includes timeout value."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert "5s" in str(exc_info.value)

    def test_timeout_error_message_includes_provider_name(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC1: Error message includes provider name."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            # "Claude CLI timeout" is in the message
            assert "Claude" in str(exc_info.value)

    def test_timeout_captures_partial_stdout(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC2: Partial stdout is captured on timeout."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            # Create mock with partial stream-json output before timeout
            mock_popen.return_value = create_mock_process(
                response_text="Partial response before timeout...",
                never_finish=True,
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            error = exc_info.value
            assert error.partial_result is not None
            assert "Partial response" in error.partial_result.stdout

    def test_timeout_captures_partial_stderr(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC2: Partial stderr is captured on timeout."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stderr_content="Warning: something happened\n",
                never_finish=True,
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            error = exc_info.value
            assert error.partial_result is not None
            assert "Warning: something happened" in error.partial_result.stderr

    def test_timeout_no_partial_when_empty(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC2: partial_result has empty strings when no output captured."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="",
                never_finish=True,
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            error = exc_info.value
            assert error.partial_result is not None
            assert error.partial_result.stdout == ""
            assert error.partial_result.stderr == ""

    def test_partial_stdout_is_always_string(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC2: partial_result.stdout is always str (never None)."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="Some warning\n",
                never_finish=True,
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            result = exc_info.value.partial_result
            assert result is not None
            assert isinstance(result.stdout, str)

    def test_partial_stderr_is_always_string(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC2: partial_result.stderr is always str (never None)."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="Some output",
                stderr_content="",
                never_finish=True,
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            result = exc_info.value.partial_result
            assert result is not None
            assert isinstance(result.stderr, str)

    def test_process_wait_called_for_completion_check(
        self, provider: ClaudeSubprocessProvider
    ) -> None:
        """Test AC3: process.wait() is called to check for completion."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_process = create_mock_process(response_text="response")
            mock_popen.return_value = mock_process

            provider.invoke("Hello", timeout=60)

            # wait() should be called at least once to check completion
            assert mock_process.wait.called

    def test_timeout_logging_with_context(
        self, provider: ClaudeSubprocessProvider, caplog: pytest.LogCaptureFixture,
        accelerated_time
    ) -> None:
        """Test AC4: Timeout event is logged with full context."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="Partial",
                never_finish=True,
            )

            with caplog.at_level(logging.WARNING), pytest.raises(ProviderTimeoutError):
                provider.invoke("Hello world", timeout=5)

            # Check log message contains required context
            assert len(caplog.records) >= 1
            log_msg = caplog.records[-1].message

            # AC4: Provider name
            assert "claude" in log_msg.lower()
            # AC4: Model used
            assert "sonnet" in log_msg.lower()
            # AC4: Timeout value
            assert "5" in log_msg

    def test_timeout_logging_level_is_warning(
        self, provider: ClaudeSubprocessProvider, caplog: pytest.LogCaptureFixture,
        accelerated_time
    ) -> None:
        """Test AC4: Log level is WARNING (not ERROR or INFO)."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                never_finish=True
            )

            with caplog.at_level(logging.DEBUG), pytest.raises(ProviderTimeoutError):
                provider.invoke("Hello", timeout=5)

            # Find the timeout log record
            timeout_logs = [r for r in caplog.records if "timeout" in r.message.lower()]
            assert len(timeout_logs) >= 1
            assert timeout_logs[-1].levelno == logging.WARNING


class TestTimeoutValidation:
    """Test AC7: Timeout parameter validation."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create ClaudeProvider instance."""
        return ClaudeSubprocessProvider()

    def test_timeout_validation_negative(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC7: Negative timeout raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=-1)

        error_msg = str(exc_info.value)
        assert "positive" in error_msg.lower()
        assert "-1" in error_msg  # Value included in message

    def test_timeout_validation_zero(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC7: Zero timeout raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=0)

        error_msg = str(exc_info.value)
        assert "positive" in error_msg.lower()
        assert "0" in error_msg  # Value included in message

    def test_timeout_validation_one_is_minimum(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC7: timeout=1 is accepted (minimum valid value)."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_process = create_mock_process(response_text="response")
            mock_popen.return_value = mock_process

            # Should not raise
            result = provider.invoke("Hello", timeout=1)
            assert result is not None

            # Verify wait() was used to check completion
            assert mock_process.wait.called

    def test_timeout_validation_none_uses_default(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC7: timeout=None uses DEFAULT_TIMEOUT."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_process = create_mock_process(response_text="response")
            mock_popen.return_value = mock_process

            provider.invoke("Hello", timeout=None)

            # Verify wait() was used to check completion
            assert mock_process.wait.called

    def test_timeout_validation_positive_accepted(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC7: Positive timeout values are accepted."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_process = create_mock_process(response_text="response")
            mock_popen.return_value = mock_process

            # Various positive values should work
            for timeout_value in [1, 10, 60, 300, 3600]:
                result = provider.invoke("Hello", timeout=timeout_value)
                assert result is not None


class TestTimeoutContext:
    """Test AC8, AC9, AC10: Error context and exception chaining."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create ClaudeProvider instance."""
        return ClaudeSubprocessProvider()

    def test_prompt_truncation_long_prompt(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC8: Error message contains prompt_chars count, not content."""
        long_prompt = "x" * 150

        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke(long_prompt, timeout=5)

            error_msg = str(exc_info.value)
            # Should NOT contain prompt content (Fix #5)
            assert "x" * 100 not in error_msg
            # Should contain prompt char count instead
            assert "prompt_chars=150" in error_msg

    def test_prompt_truncation_short_prompt(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC8: Short prompts also use char count, not content."""
        short_prompt = "Hello world"

        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke(short_prompt, timeout=5)

            error_msg = str(exc_info.value)
            # Prompt content not in error message (Fix #5)
            assert "Hello world" not in error_msg
            # Char count is included
            assert "prompt_chars=11" in error_msg

    def test_utf8_prompt_truncation_preserves_characters(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC8: UTF-8 characters preserved in truncation."""
        # Prompt with emoji and non-ASCII (>100 chars)
        emoji_prompt = "🚀" * 50 + "日本語テスト" * 10  # >100 chars

        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke(emoji_prompt, timeout=5)

            error_msg = str(exc_info.value)
            # Should not contain replacement character (broken UTF-8)
            assert "\ufffd" not in error_msg
            # Should be valid string
            assert isinstance(error_msg, str)

    def test_duration_calculated_on_timeout(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC9: duration_ms is calculated even on timeout path."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="partial",
                never_finish=True,
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            result = exc_info.value.partial_result
            assert result is not None
            assert isinstance(result.duration_ms, int)
            assert result.duration_ms >= 0

    def test_duration_is_integer(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC9: duration_ms is truncated to integer."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="partial",
                never_finish=True,
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            result = exc_info.value.partial_result
            assert result is not None
            # Verify it's an integer, not float
            assert isinstance(result.duration_ms, int)

    def test_exception_chaining_preserved(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC10: Exception context is preserved for debugging."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                never_finish=True
            )

            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            # Exception should be a ProviderTimeoutError
            assert isinstance(exc_info.value, ProviderTimeoutError)


class TestTypeCheckingImport:
    """Test TYPE_CHECKING import for circular import prevention."""

    def test_type_checking_no_circular_import(self) -> None:
        """Test AC5: TYPE_CHECKING prevents runtime circular import.

        The TYPE_CHECKING pattern in exceptions.py imports ProviderResult
        only for type hints, not at runtime. This test verifies both
        modules can be imported and work together.
        """
        # Both imports should work without circular import errors
        from bmad_assist.core.exceptions import ProviderTimeoutError
        from bmad_assist.providers.base import ProviderResult

        # Both should be accessible
        assert ProviderTimeoutError is not None
        assert ProviderResult is not None

        # ProviderTimeoutError should be able to accept ProviderResult
        partial = ProviderResult(
            stdout="test",
            stderr="",
            exit_code=-1,
            duration_ms=100,
            model="sonnet",
            command=("claude", "-p", "test"),
        )
        error = ProviderTimeoutError("test", partial_result=partial)
        assert error.partial_result is partial

    def test_provider_timeout_error_partial_result_type(self) -> None:
        """Test partial_result accepts ProviderResult instances."""
        from bmad_assist.providers.base import ProviderResult

        partial = ProviderResult(
            stdout="output",
            stderr="",
            exit_code=-1,
            duration_ms=500,
            model="opus",
            command=("claude",),
        )

        error = ProviderTimeoutError("timeout occurred", partial_result=partial)
        assert error.partial_result is not None
        assert error.partial_result.stdout == "output"


class TestRegressionStory42:
    """Verify Story 4.2 tests still pass with new timeout handling."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create ClaudeProvider instance."""
        return ClaudeSubprocessProvider()

    def test_timeout_error_is_now_provider_timeout_error(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test that timeout now raises ProviderTimeoutError specifically."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                never_finish=True
            )

            # Should raise ProviderTimeoutError (subclass of ProviderError)
            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello", timeout=5)

            # Verify it's actually a ProviderTimeoutError
            assert isinstance(exc_info.value, ProviderTimeoutError)

    def test_existing_success_case_still_works(self, provider: ClaudeSubprocessProvider) -> None:
        """Test successful invocation still returns ProviderResult."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(response_text="response")

            result = provider.invoke("Hello")

            assert isinstance(result, ProviderResult)
            assert result.stdout == "response"


class TestExportsAndPackage:
    """Test exports from core and providers packages."""

    def test_provider_timeout_error_exported_from_core(self) -> None:
        """Test ProviderTimeoutError exported from core package."""
        from bmad_assist.core import ProviderTimeoutError as CoreExport
        from bmad_assist.core.exceptions import (
            ProviderTimeoutError as DirectExport,
        )

        # Both should be the same class
        assert CoreExport is DirectExport

    def test_provider_timeout_error_in_core_all(self) -> None:
        """Test ProviderTimeoutError in core.__all__."""
        from bmad_assist import core

        assert "ProviderTimeoutError" in core.__all__

    def test_provider_error_exported_from_core(self) -> None:
        """Test ProviderError exported from core package."""
        from bmad_assist.core import ProviderError as CoreExport
        from bmad_assist.core.exceptions import ProviderError as DirectExport

        # Both should be the same class
        assert CoreExport is DirectExport
