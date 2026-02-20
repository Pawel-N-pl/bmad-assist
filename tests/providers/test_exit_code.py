"""Tests for exit code detection and classification (Story 4.4).

Tests the ExitStatus enum for semantic classification of Unix exit codes,
the ProviderExitCodeError exception with rich context, and ClaudeSubprocessProvider
integration with enhanced exit code handling.

Test Coverage:
- AC1: Exit code 0 treated as success
- AC2: Non-zero exit code raises ProviderExitCodeError
- AC3: Exit code is logged with context
- AC4: ExitStatus enum classifies exit codes semantically
- AC5: ProviderExitCodeError includes command context
- AC6: Signal termination is detected
- AC7: stderr is always captured and available
- AC8: ClaudeSubprocessProvider uses enhanced exit code handling
- AC9: Special exit codes are handled correctly
- AC10: Exception hierarchy is maintained
"""

import logging
from unittest.mock import patch

import pytest

from bmad_assist.core.exceptions import (
    BmadAssistError,
    ProviderError,
    ProviderExitCodeError,
)
from bmad_assist.providers.base import ExitStatus
from bmad_assist.providers.claude import ClaudeSubprocessProvider

from .conftest import create_mock_process


class TestExitStatus:
    """Tests for ExitStatus enum (AC4, AC6, AC9)."""

    def test_from_code_zero_is_success(self) -> None:
        """Test AC4: Exit code 0 classifies as SUCCESS."""
        assert ExitStatus.from_code(0) == ExitStatus.SUCCESS

    def test_from_code_one_is_error(self) -> None:
        """Test AC4: Exit code 1 classifies as ERROR (general error)."""
        assert ExitStatus.from_code(1) == ExitStatus.ERROR

    def test_from_code_two_is_misuse(self) -> None:
        """Test AC4: Exit code 2 classifies as MISUSE (incorrect usage)."""
        assert ExitStatus.from_code(2) == ExitStatus.MISUSE

    def test_from_code_generic_errors(self) -> None:
        """Test AC4: Exit codes 3-125 classify as ERROR."""
        # Test several values in the range
        for code in [3, 50, 100, 125]:
            assert ExitStatus.from_code(code) == ExitStatus.ERROR

    def test_from_code_126_cannot_execute(self) -> None:
        """Test AC9: Exit code 126 classifies as CANNOT_EXECUTE."""
        assert ExitStatus.from_code(126) == ExitStatus.CANNOT_EXECUTE

    def test_from_code_127_not_found(self) -> None:
        """Test AC9: Exit code 127 classifies as NOT_FOUND."""
        assert ExitStatus.from_code(127) == ExitStatus.NOT_FOUND

    def test_from_code_128_invalid_exit(self) -> None:
        """Test AC9: Exit code 128 classifies as INVALID_EXIT."""
        assert ExitStatus.from_code(128) == ExitStatus.INVALID_EXIT

    def test_from_code_signal_sigkill(self) -> None:
        """Test AC6: Exit code 137 (128+9) classifies as SIGNAL (SIGKILL)."""
        assert ExitStatus.from_code(137) == ExitStatus.SIGNAL

    def test_from_code_signal_sigterm(self) -> None:
        """Test AC6: Exit code 143 (128+15) classifies as SIGNAL (SIGTERM)."""
        assert ExitStatus.from_code(143) == ExitStatus.SIGNAL

    def test_from_code_signal_sigint(self) -> None:
        """Test AC6: Exit code 130 (128+2) classifies as SIGNAL (SIGINT)."""
        assert ExitStatus.from_code(130) == ExitStatus.SIGNAL

    def test_from_code_signal_sighup_129(self) -> None:
        """Test AC6: Exit code 129 (128+1) classifies as SIGNAL (SIGHUP).

        This is a critical boundary test between INVALID_EXIT (128) and SIGNAL (129+).
        """
        assert ExitStatus.from_code(129) == ExitStatus.SIGNAL
        assert ExitStatus.get_signal_number(129) == 1  # SIGHUP

    def test_get_signal_number_sigkill(self) -> None:
        """Test AC6: get_signal_number extracts 9 from exit code 137."""
        assert ExitStatus.get_signal_number(137) == 9

    def test_get_signal_number_sigterm(self) -> None:
        """Test AC6: get_signal_number extracts 15 from exit code 143."""
        assert ExitStatus.get_signal_number(143) == 15

    def test_get_signal_number_sigint(self) -> None:
        """Test AC6: get_signal_number extracts 2 from exit code 130."""
        assert ExitStatus.get_signal_number(130) == 2

    def test_get_signal_number_not_signal(self) -> None:
        """Test AC6: get_signal_number returns None for non-signal codes."""
        assert ExitStatus.get_signal_number(0) is None
        assert ExitStatus.get_signal_number(1) is None
        assert ExitStatus.get_signal_number(127) is None
        assert ExitStatus.get_signal_number(128) is None

    def test_all_enum_values_exist(self) -> None:
        """Test AC4: All expected ExitStatus values exist."""
        assert hasattr(ExitStatus, "SUCCESS")
        assert hasattr(ExitStatus, "ERROR")
        assert hasattr(ExitStatus, "MISUSE")
        assert hasattr(ExitStatus, "CANNOT_EXECUTE")
        assert hasattr(ExitStatus, "NOT_FOUND")
        assert hasattr(ExitStatus, "INVALID_EXIT")
        assert hasattr(ExitStatus, "SIGNAL")


class TestProviderExitCodeError:
    """Tests for ProviderExitCodeError exception (AC2, AC5, AC10)."""

    def test_inherits_from_provider_error(self) -> None:
        """Test AC10: ProviderExitCodeError inherits from ProviderError."""
        error = ProviderExitCodeError(
            "test message",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
        )
        assert isinstance(error, ProviderError)

    def test_inherits_from_bmad_assist_error(self) -> None:
        """Test AC10: ProviderExitCodeError inherits from BmadAssistError."""
        error = ProviderExitCodeError(
            "test message",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
        )
        assert isinstance(error, BmadAssistError)

    def test_has_exit_code_attribute(self) -> None:
        """Test AC5: Error has exit_code attribute."""
        error = ProviderExitCodeError(
            "test",
            exit_code=42,
            exit_status=ExitStatus.ERROR,
        )
        assert error.exit_code == 42

    def test_has_exit_status_attribute(self) -> None:
        """Test AC5: Error has exit_status attribute."""
        error = ProviderExitCodeError(
            "test",
            exit_code=127,
            exit_status=ExitStatus.NOT_FOUND,
        )
        assert error.exit_status == ExitStatus.NOT_FOUND

    def test_has_stderr_attribute(self) -> None:
        """Test AC5: Error has stderr attribute."""
        error = ProviderExitCodeError(
            "test",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
            stderr="Error message from CLI",
        )
        assert error.stderr == "Error message from CLI"

    def test_stderr_defaults_to_empty_string(self) -> None:
        """Test AC7: stderr defaults to empty string, not None."""
        error = ProviderExitCodeError(
            "test",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
        )
        assert error.stderr == ""

    def test_has_command_attribute(self) -> None:
        """Test AC5: Error has command attribute as tuple."""
        cmd = ("claude", "-p", "hello", "--model", "sonnet")
        error = ProviderExitCodeError(
            "test",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
            command=cmd,
        )
        assert error.command == cmd

    def test_command_defaults_to_empty_tuple(self) -> None:
        """Test AC5: command defaults to empty tuple."""
        error = ProviderExitCodeError(
            "test",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
        )
        assert error.command == ()

    def test_message_is_accessible(self) -> None:
        """Test AC2: Error message is accessible via str()."""
        error = ProviderExitCodeError(
            "Claude CLI failed with exit code 1",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
        )
        assert str(error) == "Claude CLI failed with exit code 1"

    def test_backward_compatibility_caught_by_provider_error(self) -> None:
        """Test AC10: ProviderExitCodeError caught by except ProviderError."""
        error = ProviderExitCodeError(
            "test",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
        )

        caught = False
        try:
            raise error
        except ProviderError as e:
            caught = True
            assert isinstance(e, ProviderExitCodeError)

        assert caught, "ProviderExitCodeError should be caught by except ProviderError"


class TestClaudeSubprocessProviderExitCode:
    """Tests for ClaudeSubprocessProvider exit code handling (AC1, AC3, AC7, AC8)."""

    def test_exit_code_zero_returns_success(self) -> None:
        """Test AC1: Exit code 0 treated as success, no exception raised."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="Hello response",
                returncode=0,
            )

            provider = ClaudeSubprocessProvider()
            result = provider.invoke("Hello", timeout=5)

            assert result.exit_code == 0
            assert result.stdout == "Hello response"

    def test_exit_code_zero_output_available_for_parse(self) -> None:
        """Test AC1: Output is available for parse_output()."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="Response text",
                returncode=0,
            )

            provider = ClaudeSubprocessProvider()
            result = provider.invoke("Hello", timeout=5)
            parsed = provider.parse_output(result)

            assert parsed == "Response text"

    def test_non_zero_exit_raises_exit_code_error(self) -> None:
        """Test AC2, AC8: Non-zero exit raises ProviderExitCodeError."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="Error: invalid argument\n",
                returncode=1,
            )

            provider = ClaudeSubprocessProvider()

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello", timeout=5)

            error = exc_info.value
            assert error.exit_code == 1
            assert error.exit_status == ExitStatus.ERROR

    def test_error_includes_stderr_content(self) -> None:
        """Test AC2, AC7: Error includes stderr content."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="Error: something went wrong\n",
                returncode=1,
            )

            provider = ClaudeSubprocessProvider()

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello", timeout=5)

            error = exc_info.value
            assert "something went wrong" in error.stderr
            assert "something went wrong" in str(error)

    def test_error_includes_command(self) -> None:
        """Test AC2, AC5: Error includes command as tuple."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="Error\n",
                returncode=1,
            )

            provider = ClaudeSubprocessProvider()

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello", model="opus", timeout=5)

            error = exc_info.value
            assert isinstance(error.command, tuple)
            assert "claude" in error.command
            assert "opus" in error.command

    def test_stderr_empty_becomes_empty_string(self) -> None:
        """Test AC7: Empty/None stderr becomes empty string."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="",
                returncode=1,
            )

            provider = ClaudeSubprocessProvider()

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert exc_info.value.stderr == ""

    def test_signal_exit_code_detected(self) -> None:
        """Test AC6: Signal termination (137=SIGKILL) is detected."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="Partial",
                stderr_content="",
                returncode=137,  # 128 + 9 (SIGKILL)
            )

            provider = ClaudeSubprocessProvider()

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello", timeout=5)

            error = exc_info.value
            assert error.exit_code == 137
            assert error.exit_status == ExitStatus.SIGNAL
            # AC2: Message includes exit code and signal info
            assert "exit code 137" in str(error)
            assert "signal 9" in str(error)

    def test_exit_code_127_not_found(self) -> None:
        """Test AC9: Exit code 127 (command not found) handled correctly."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="command not found\n",
                returncode=127,
            )

            provider = ClaudeSubprocessProvider()

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello", timeout=5)

            error = exc_info.value
            assert error.exit_code == 127
            assert error.exit_status == ExitStatus.NOT_FOUND
            # AC2: Message includes exit code and suggests checking PATH
            assert "exit code 127" in str(error)
            assert "path" in str(error).lower()

    def test_exit_code_126_cannot_execute(self) -> None:
        """Test AC9: Exit code 126 (cannot execute) handled correctly."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="permission denied\n",
                returncode=126,
            )

            provider = ClaudeSubprocessProvider()

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello", timeout=5)

            error = exc_info.value
            assert error.exit_code == 126
            assert error.exit_status == ExitStatus.CANNOT_EXECUTE
            # AC2: Message includes exit code and mentions permission
            assert "exit code 126" in str(error)
            assert "permission" in str(error).lower()

    def test_logging_includes_exit_code(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test AC3: Logger.error() called with exit code."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="Error occurred\n",
                returncode=1,
            )

            provider = ClaudeSubprocessProvider()

            with caplog.at_level(logging.ERROR), pytest.raises(ProviderExitCodeError):
                provider.invoke("Hello", timeout=5)

            # Check log contains exit code
            assert "exit_code=1" in caplog.text

    def test_logging_includes_provider_name(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test AC3: Logging includes provider name context."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="Error occurred\n",
                returncode=1,
            )

            provider = ClaudeSubprocessProvider()

            with caplog.at_level(logging.ERROR), pytest.raises(ProviderExitCodeError):
                provider.invoke("Hello", timeout=5)

            # Log comes from claude provider module
            assert "bmad_assist.providers.claude" in caplog.text

    def test_logging_includes_model(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test AC3: Logging includes model used."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="Error\n",
                returncode=1,
            )

            provider = ClaudeSubprocessProvider()

            with caplog.at_level(logging.ERROR), pytest.raises(ProviderExitCodeError):
                provider.invoke("Hello", model="opus", timeout=5)

            assert "model=opus" in caplog.text

    def test_logging_includes_exit_status_name(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test AC3: Logging includes semantic exit status."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="Error\n",
                returncode=127,
            )

            provider = ClaudeSubprocessProvider()

            with caplog.at_level(logging.ERROR), pytest.raises(ProviderExitCodeError):
                provider.invoke("Hello", timeout=5)

            assert "status=NOT_FOUND" in caplog.text

    def test_logging_includes_stderr_truncated(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test AC3: Logging includes stderr truncated to 200 chars."""
        long_stderr = "E" * 300  # 300 char stderr
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content=long_stderr + "\n",
                returncode=1,
            )

            provider = ClaudeSubprocessProvider()

            with caplog.at_level(logging.ERROR), pytest.raises(ProviderExitCodeError):
                provider.invoke("Hello", timeout=5)

            # Should be truncated
            assert "E" * 200 in caplog.text
            assert "E" * 201 not in caplog.text

    def test_full_stderr_available_in_error_attribute(self) -> None:
        """Test AC7: Full stderr available in error.stderr attribute."""
        long_stderr = "E" * 300  # 300 char stderr
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content=long_stderr + "\n",
                returncode=1,
            )

            provider = ClaudeSubprocessProvider()

            with pytest.raises(ProviderExitCodeError) as exc_info:
                provider.invoke("Hello", timeout=5)

            # Full stderr in attribute (includes newline from mock)
            assert long_stderr in exc_info.value.stderr

    def test_logging_uses_structured_parameters(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test AC3: Logging uses structured parameters (not f-string)."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                stdout_content="",
                stderr_content="Error\n",
                returncode=1,
            )

            provider = ClaudeSubprocessProvider()

            with caplog.at_level(logging.ERROR), pytest.raises(ProviderExitCodeError):
                provider.invoke("Hello", timeout=5)

            # Structured format should have "exit_code=X" not interpolated
            # The message format uses %s parameters
            assert any("exit_code=" in record.message for record in caplog.records), (
                "Logging should use structured parameters"
            )


class TestExceptionHierarchyIntegration:
    """Integration tests for exception hierarchy (AC10)."""

    def test_catch_chain_provider_error(self) -> None:
        """Test AC10: Can catch as ProviderError in try/except."""
        error = ProviderExitCodeError(
            "test",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
            stderr="test error",
            command=("claude", "-p", "test"),
        )

        # Test catching as ProviderError
        try:
            raise error
        except ProviderError as caught:
            assert caught.exit_code == 1
            assert caught.stderr == "test error"

    def test_catch_chain_bmad_assist_error(self) -> None:
        """Test AC10: Can catch as BmadAssistError in try/except."""
        error = ProviderExitCodeError(
            "test",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
        )

        # Test catching as BmadAssistError
        try:
            raise error
        except BmadAssistError as caught:
            assert isinstance(caught, ProviderExitCodeError)

    def test_selective_catch_exit_code_error(self) -> None:
        """Test AC10: Can selectively catch ProviderExitCodeError."""
        error = ProviderExitCodeError(
            "test",
            exit_code=1,
            exit_status=ExitStatus.ERROR,
        )

        # Test selective catching
        try:
            raise error
        except ProviderExitCodeError as caught:
            # Access specific attributes
            assert caught.exit_status == ExitStatus.ERROR
            assert caught.exit_code == 1


class TestExitCodeEdgeCases:
    """Edge case tests for exit code handling."""

    def test_exit_status_negative_code(self) -> None:
        """Test ExitStatus handles negative exit codes (shouldn't happen but handle)."""
        # Negative codes shouldn't occur but should classify as ERROR
        status = ExitStatus.from_code(-1)
        assert status == ExitStatus.ERROR

    def test_exit_status_large_code(self) -> None:
        """Test ExitStatus handles very large exit codes (signal range)."""
        # Very large code (>255) would wrap on most systems, but handle anyway
        status = ExitStatus.from_code(255)
        assert status == ExitStatus.SIGNAL  # 255 > 128

    def test_get_signal_number_edge_129(self) -> None:
        """Test get_signal_number for edge case 129 (signal 1 = SIGHUP)."""
        assert ExitStatus.get_signal_number(129) == 1

    def test_exit_code_error_with_all_attributes(self) -> None:
        """Test ProviderExitCodeError with all attributes set."""
        cmd = ("claude", "-p", "prompt text", "--model", "opus", "--print")
        error = ProviderExitCodeError(
            "Full error message with context",
            exit_code=143,
            exit_status=ExitStatus.SIGNAL,
            stderr="Process terminated\n",
            command=cmd,
        )

        assert str(error) == "Full error message with context"
        assert error.exit_code == 143
        assert error.exit_status == ExitStatus.SIGNAL
        assert error.stderr == "Process terminated\n"
        assert error.command == cmd
        assert isinstance(error, ProviderError)
        assert isinstance(error, BmadAssistError)
