"""Unit tests for ClaudeSubprocessProvider implementation.

Tests cover the subprocess-based Claude provider which is retained for
benchmarking and fair comparison with Codex/Gemini providers.

For the primary SDK-based provider tests, see test_claude_sdk.py.

Tests cover:
- AC1: ClaudeSubprocessProvider extends BaseProvider
- AC2: provider_name returns "claude-subprocess"
- AC3: default_model returns "sonnet"
- AC4: supports_model() validates Claude models
- AC5: invoke() builds correct command
- AC6: invoke() uses --settings flag when settings_file provided
- AC7: invoke() returns ProviderResult on success
- AC8: invoke() raises ProviderError on timeout
- AC9: invoke() raises ProviderError on non-zero exit
- AC10: invoke() raises ProviderError when CLI not found
- AC11: parse_output() extracts response from stdout
- AC12: Package exports ClaudeSubprocessProvider
"""

from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import ProviderError
from bmad_assist.providers import BaseProvider, ClaudeSubprocessProvider, ProviderResult
from bmad_assist.providers.base import extract_tool_details
from bmad_assist.providers.claude import (
    PROMPT_TRUNCATE_LENGTH,
    SUPPORTED_MODELS,
    _truncate_prompt,
)


def make_stream_json_output(text: str = "Mock response", session_id: str = "test-session") -> str:
    """Create stream-json format output for testing.

    Args:
        text: Response text to include.
        session_id: Session ID for init message.

    Returns:
        Multi-line string with JSON stream messages.

    """
    import json

    lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": session_id}),
        json.dumps(
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "total_cost_usd": 0.001,
                "duration_ms": 100,
                "num_turns": 1,
                "result": text,
                "session_id": session_id,
            }
        ),
    ]
    return "\n".join(lines) + "\n"


def create_mock_process(
    stdout_content: str | None = None,
    stderr_content: str = "",
    returncode: int = 0,
    wait_side_effect: Exception | None = None,
    response_text: str = "Mock response",
    poll_returns_none_count: int = 1,
    never_finish: bool = False,
) -> MagicMock:
    """Create a mock Popen process for testing.

    Args:
        stdout_content: Raw content for stdout. If None, generates stream-json.
        stderr_content: Content to return from stderr.readline()
        returncode: Exit code to return from poll() when done
        wait_side_effect: Exception to raise from wait() (e.g., TimeoutExpired)
        response_text: Text to include in stream-json output (if stdout_content is None)
        poll_returns_none_count: Number of poll() calls that return None before
            returning returncode. Set to 1 for instant completion.
        never_finish: If True, poll() always returns None (for timeout tests).

    Returns:
        MagicMock configured to behave like a Popen process

    """
    mock_process = MagicMock()

    # Generate stream-json if no raw content provided
    if stdout_content is None:
        stdout_content = make_stream_json_output(response_text)

    # Create file-like objects for stdout/stderr
    stdout_lines = stdout_content.split("\n") if stdout_content else []
    stderr_lines = stderr_content.split("\n") if stderr_content else []

    # Add newlines back except for empty strings
    stdout_iter = iter([line + "\n" if line else "" for line in stdout_lines])
    stderr_iter = iter([line + "\n" if line else "" for line in stderr_lines])

    mock_process.stdout.readline.side_effect = lambda: next(stdout_iter, "")
    mock_process.stderr.readline.side_effect = lambda: next(stderr_iter, "")
    mock_process.stdout.close = MagicMock()
    mock_process.stderr.close = MagicMock()

    # Mock stdin for prompt input
    mock_process.stdin = MagicMock()
    mock_process.stdin.write = MagicMock()
    mock_process.stdin.close = MagicMock()

    # Mock poll() and wait() for the process loop
    if never_finish:
        # Always return None (process never finishes - for timeout tests)
        mock_process.poll.return_value = None
        # wait() raises TimeoutExpired for providers using wait()
        mock_process.wait.side_effect = TimeoutExpired(cmd=["mock"], timeout=5)
    else:
        # Return None poll_returns_none_count times, then returncode
        poll_call_count = [0]

        def poll_side_effect():
            poll_call_count[0] += 1
            if poll_call_count[0] <= poll_returns_none_count:
                return None
            return returncode

        mock_process.poll.side_effect = poll_side_effect

    # Legacy wait mock for backward compatibility
    if wait_side_effect:
        mock_process.wait.side_effect = wait_side_effect
    else:
        mock_process.wait.return_value = returncode

    mock_process.kill = MagicMock()
    mock_process.pid = 12345  # For process group operations

    return mock_process


class TestClaudeSubprocessProviderStructure:
    """Test AC1, AC2, AC3: ClaudeSubprocessProvider class definition."""

    def test_subprocess_provider_inherits_from_baseprovider(self) -> None:
        """Test AC1: ClaudeSubprocessProvider inherits from BaseProvider."""
        assert issubclass(ClaudeSubprocessProvider, BaseProvider)

    def test_subprocess_provider_has_class_docstring(self) -> None:
        """Test AC1: ClaudeSubprocessProvider has docstring explaining its purpose."""
        assert ClaudeSubprocessProvider.__doc__ is not None
        assert "subprocess" in ClaudeSubprocessProvider.__doc__.lower()
        assert "benchmarking" in ClaudeSubprocessProvider.__doc__.lower()

    def test_provider_name_returns_claude_subprocess(self) -> None:
        """Test AC2: provider_name returns 'claude-subprocess'."""
        provider = ClaudeSubprocessProvider()
        assert provider.provider_name == "claude-subprocess"

    def test_default_model_returns_sonnet(self) -> None:
        """Test AC3: default_model returns 'sonnet'."""
        provider = ClaudeSubprocessProvider()
        assert provider.default_model == "sonnet"

    def test_default_model_can_be_overridden_in_subclass(self) -> None:
        """Test AC3: default_model can be overridden via subclass."""

        class CustomProvider(ClaudeSubprocessProvider):
            @property
            def default_model(self) -> str | None:
                return "opus"

        provider = CustomProvider()
        assert provider.default_model == "opus"


class TestClaudeSubprocessProviderModels:
    """Test AC4: supports_model() validation."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create ClaudeSubprocessProvider instance."""
        return ClaudeSubprocessProvider()

    def test_supported_models_constant_is_frozenset(self) -> None:
        """Test SUPPORTED_MODELS is a frozenset."""
        assert isinstance(SUPPORTED_MODELS, frozenset)

    def test_supported_models_contains_opus(self) -> None:
        """Test SUPPORTED_MODELS includes opus."""
        assert "opus" in SUPPORTED_MODELS

    def test_supported_models_contains_sonnet(self) -> None:
        """Test SUPPORTED_MODELS includes sonnet."""
        assert "sonnet" in SUPPORTED_MODELS

    def test_supported_models_contains_haiku(self) -> None:
        """Test SUPPORTED_MODELS includes haiku."""
        assert "haiku" in SUPPORTED_MODELS

    def test_supports_model_opus(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC4: supports_model('opus') returns True."""
        assert provider.supports_model("opus") is True

    def test_supports_model_sonnet(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC4: supports_model('sonnet') returns True."""
        assert provider.supports_model("sonnet") is True

    def test_supports_model_haiku(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC4: supports_model('haiku') returns True."""
        assert provider.supports_model("haiku") is True

    def test_supports_model_claude_prefix(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC4: supports_model('claude-*') returns True."""
        assert provider.supports_model("claude-3-5-sonnet-20241022") is True

    def test_supports_model_gpt_returns_false(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC4: supports_model('gpt-4') returns False."""
        assert provider.supports_model("gpt-4") is False

    def test_supports_model_unknown_returns_false(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC4: supports_model('unknown') returns False."""
        assert provider.supports_model("unknown") is False

    def test_supports_model_empty_string_returns_false(
        self, provider: ClaudeSubprocessProvider
    ) -> None:
        """Test AC4: supports_model('') returns False."""
        assert provider.supports_model("") is False

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        assert ClaudeSubprocessProvider.supports_model.__doc__ is not None
        assert "model" in ClaudeSubprocessProvider.supports_model.__doc__.lower()


class TestClaudeSubprocessProviderInvoke:
    """Test AC5, AC6, AC7: invoke() success cases."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create ClaudeSubprocessProvider instance."""
        return ClaudeSubprocessProvider()

    @pytest.fixture
    def mock_successful_popen(self):
        """Mock Popen for successful invocation with stream-json output."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process(
                response_text="Mock response",
                stderr_content="",
                returncode=0,
            )
            yield mock

    def test_invoke_builds_correct_command(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC5: invoke() builds command as expected (prompt via stdin)."""
        provider.invoke("Hello", model="opus")

        mock_successful_popen.assert_called_once()
        call_args = mock_successful_popen.call_args
        command = call_args[0][0]

        # Prompt passed via stdin, not command line (to avoid "Argument list too long")
        # --dangerously-skip-permissions for automated workflows
        # --verbose is required for stream-json with --print
        assert command == [
            "claude",
            "-p",
            "-",
            "--model",
            "opus",
            "--output-format",
            "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]

    def test_invoke_uses_pipe_for_stdout(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC5: invoke() uses PIPE for stdout."""
        from subprocess import PIPE

        provider.invoke("Hello")

        call_kwargs = mock_successful_popen.call_args[1]
        assert call_kwargs["stdout"] == PIPE

    def test_invoke_uses_pipe_for_stderr(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC5: invoke() uses PIPE for stderr."""
        from subprocess import PIPE

        provider.invoke("Hello")

        call_kwargs = mock_successful_popen.call_args[1]
        assert call_kwargs["stderr"] == PIPE

    def test_invoke_uses_stdin_for_prompt(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test: invoke() passes prompt via stdin to avoid 'Argument list too long'."""
        from subprocess import PIPE

        provider.invoke("Hello world prompt")

        # stdin should be PIPE
        call_kwargs = mock_successful_popen.call_args[1]
        assert call_kwargs["stdin"] == PIPE

        # Prompt should be written to stdin
        mock_process = mock_successful_popen.return_value
        mock_process.stdin.write.assert_called_once_with("Hello world prompt")
        mock_process.stdin.close.assert_called_once()

    def test_invoke_uses_text_true(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC5: invoke() calls Popen with text=True."""
        provider.invoke("Hello")

        call_kwargs = mock_successful_popen.call_args[1]
        assert call_kwargs["text"] is True

    def test_invoke_waits_for_process(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC5: invoke() uses wait() to wait for process completion."""
        provider.invoke("Hello", timeout=60)

        mock_process = mock_successful_popen.return_value
        # wait() is called to check if process finished
        assert mock_process.wait.called

    def test_invoke_uses_default_timeout_implicitly(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC5: invoke() defaults to DEFAULT_TIMEOUT when timeout=None.

        Since we use poll() loop with time.perf_counter() for timeout,
        we verify that the process completes without timeout error when
        process finishes quickly.
        """
        # This should complete without ProviderTimeoutError
        result = provider.invoke("Hello")
        assert result.exit_code == 0

    def test_invoke_uses_default_model_when_none(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC5: invoke(model=None) uses default_model ('sonnet')."""
        provider.invoke("Hello", model=None)

        command = mock_successful_popen.call_args[0][0]
        # Prompt via stdin (-), not command line
        # --verbose is required for stream-json with --print
        assert command == [
            "claude",
            "-p",
            "-",
            "--model",
            "sonnet",
            "--output-format",
            "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]

    def test_invoke_uses_default_model_when_not_specified(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC5: invoke() without model arg uses default_model."""
        provider.invoke("Hello")

        command = mock_successful_popen.call_args[0][0]
        assert "--model" in command
        assert "sonnet" in command

    def test_invoke_with_settings_file(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Test AC6: invoke() adds --settings when settings_file provided."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{}")

        provider.invoke("Hello", settings_file=settings_path)

        command = mock_successful_popen.call_args[0][0]
        assert "--settings" in command
        assert str(settings_path) in command

    def test_invoke_without_settings_file(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC6: invoke() omits --settings when settings_file is None."""
        provider.invoke("Hello")

        command = mock_successful_popen.call_args[0][0]
        assert "--settings" not in command

    def test_invoke_returns_providerresult_on_success(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC7: invoke() returns ProviderResult on success."""
        result = provider.invoke("Hello")

        assert isinstance(result, ProviderResult)

    def test_invoke_providerresult_has_stdout(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC7: ProviderResult contains stdout."""
        result = provider.invoke("Hello")

        assert "Mock response" in result.stdout

    def test_invoke_providerresult_has_stderr(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC7: ProviderResult contains stderr."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process(
                stdout_content="output",
                stderr_content="some warning",
                returncode=0,
            )
            result = provider.invoke("Hello")

        assert "some warning" in result.stderr

    def test_invoke_providerresult_has_exit_code(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC7: ProviderResult contains exit_code."""
        result = provider.invoke("Hello")

        assert result.exit_code == 0

    def test_invoke_providerresult_has_duration_ms(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC7: ProviderResult contains duration_ms."""
        result = provider.invoke("Hello")

        assert result.duration_ms >= 0

    def test_invoke_providerresult_has_model(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC7: ProviderResult contains model."""
        result = provider.invoke("Hello", model="opus")

        assert result.model == "opus"

    def test_invoke_providerresult_model_uses_default_when_none(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC7: ProviderResult.model uses default when not specified."""
        result = provider.invoke("Hello")

        assert result.model == "sonnet"

    def test_invoke_providerresult_has_command_tuple(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC7: ProviderResult contains command as tuple (prompt via stdin)."""
        result = provider.invoke("Hello", model="opus")

        # Prompt via stdin (-), not in command tuple
        # --verbose is required for stream-json with --print
        assert result.command == (
            "claude",
            "-p",
            "-",
            "--model",
            "opus",
            "--output-format",
            "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        )

    def test_invoke_does_not_use_shell_true(
        self, provider: ClaudeSubprocessProvider, mock_successful_popen: MagicMock
    ) -> None:
        """Test AC5: invoke() never uses shell=True (security)."""
        provider.invoke("Hello")

        call_kwargs = mock_successful_popen.call_args[1]
        # shell should either not be present or be False
        assert call_kwargs.get("shell", False) is False


class TestClaudeSubprocessProviderErrors:
    """Test AC8, AC9, AC10: Error handling."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create ClaudeSubprocessProvider instance."""
        return ClaudeSubprocessProvider()

    def test_invoke_raises_providererror_on_timeout(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC8: invoke() raises ProviderError when timeout exceeded."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process(never_finish=True)

            with pytest.raises(ProviderError) as exc_info:
                # Use very short timeout to make test fast
                provider.invoke("Hello", timeout=1)

            assert "timeout" in str(exc_info.value).lower()
            assert "1s" in str(exc_info.value)

    def test_invoke_timeout_error_includes_truncated_prompt(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC8: Timeout error includes prompt_chars count, not content."""
        long_prompt = "x" * 150

        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process(never_finish=True)

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke(long_prompt, timeout=1)

            error_msg = str(exc_info.value)
            # Should NOT contain prompt content (Fix #5)
            assert "x" * 100 not in error_msg
            # Should contain prompt char count
            assert "prompt_chars=150" in error_msg

    def test_invoke_timeout_error_short_prompt_not_truncated(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC8: Short prompts also show char count, not content."""
        short_prompt = "Hello world"

        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process(never_finish=True)

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke(short_prompt, timeout=1)

            error_msg = str(exc_info.value)
            assert "Hello world" not in error_msg
            assert "prompt_chars=11" in error_msg

    def test_invoke_timeout_kills_process(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test AC8: Timeout triggers process.kill()."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock_process = create_mock_process(never_finish=True)
            mock.return_value = mock_process

            with pytest.raises(ProviderError):
                provider.invoke("Hello", timeout=1)

            mock_process.kill.assert_called_once()

    def test_invoke_raises_providererror_on_nonzero_exit(
        self, provider: ClaudeSubprocessProvider
    ) -> None:
        """Test AC9: invoke() raises ProviderError on non-zero exit code."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process(
                stdout_content="",
                stderr_content="Error: Invalid model",
                returncode=1,
            )

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert "exit code 1" in str(exc_info.value).lower()

    def test_invoke_nonzero_exit_includes_stderr(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC9: Non-zero exit error includes stderr content."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process(
                stdout_content="",
                stderr_content="Error: Invalid model specified",
                returncode=1,
            )

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert "Invalid model" in str(exc_info.value)

    def test_invoke_raises_providererror_when_cli_not_found(
        self, provider: ClaudeSubprocessProvider
    ) -> None:
        """Test AC10: invoke() raises ProviderError when CLI not found."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.side_effect = FileNotFoundError("claude")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert "not found" in str(exc_info.value).lower()

    def test_invoke_file_not_found_exception_is_chained(
        self, provider: ClaudeSubprocessProvider
    ) -> None:
        """Test AC10: FileNotFoundError is chained with 'from e'."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.side_effect = FileNotFoundError("claude")

            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, FileNotFoundError)

    def test_invoke_accepts_valid_short_model(self, provider: ClaudeSubprocessProvider) -> None:
        """Test invoke() doesn't raise for valid short models."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process()

            # Should not raise
            for model in ["opus", "sonnet", "haiku"]:
                provider.invoke("Hello", model=model)

    def test_invoke_accepts_claude_prefix_model(self, provider: ClaudeSubprocessProvider) -> None:
        """Test invoke() doesn't raise for claude-* models."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process()

            # Should not raise
            provider.invoke("Hello", model="claude-3-5-sonnet-20241022")


class TestClaudeSubprocessProviderParseOutput:
    """Test AC11: parse_output() extracts response."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create ClaudeSubprocessProvider instance."""
        return ClaudeSubprocessProvider()

    def test_parse_output_returns_stdout_stripped(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC11: parse_output() returns stdout with whitespace stripped."""
        result = ProviderResult(
            stdout="  Hello World  \n",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="sonnet",
            command=("claude", "-p", "test"),
        )

        output = provider.parse_output(result)

        assert output == "Hello World"

    def test_parse_output_handles_empty_stdout(self, provider: ClaudeSubprocessProvider) -> None:
        """Test AC11: parse_output() handles empty stdout."""
        result = ProviderResult(
            stdout="",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="sonnet",
            command=("claude", "-p", "test"),
        )

        output = provider.parse_output(result)

        assert output == ""

    def test_parse_output_preserves_internal_whitespace(
        self, provider: ClaudeSubprocessProvider
    ) -> None:
        """Test AC11: parse_output() preserves whitespace inside response."""
        result = ProviderResult(
            stdout="  Line 1\n  Line 2  \n",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="sonnet",
            command=("claude", "-p", "test"),
        )

        output = provider.parse_output(result)

        assert "Line 1\n  Line 2" in output

    def test_parse_output_has_docstring(self) -> None:
        """Test parse_output() has docstring."""
        assert ClaudeSubprocessProvider.parse_output.__doc__ is not None


class TestClaudeSubprocessProviderExports:
    """Test AC12: Package exports."""

    def test_package_exports_claudesubprocessprovider(self) -> None:
        """Test AC12: bmad_assist.providers exports ClaudeSubprocessProvider."""
        from bmad_assist.providers import ClaudeSubprocessProvider as ExportedProvider

        assert ExportedProvider is ClaudeSubprocessProvider

    def test_package_exports_providerresult(self) -> None:
        """Test AC12: bmad_assist.providers exports ProviderResult."""
        from bmad_assist.providers import ProviderResult as ExportedResult

        assert ExportedResult is ProviderResult


class TestTruncatePrompt:
    """Test _truncate_prompt helper function."""

    def test_truncate_prompt_short_unchanged(self) -> None:
        """Test short prompts are not truncated."""
        prompt = "Hello world"
        result = _truncate_prompt(prompt)
        assert result == prompt

    def test_truncate_prompt_exact_length_unchanged(self) -> None:
        """Test prompts at exactly PROMPT_TRUNCATE_LENGTH are not truncated."""
        prompt = "x" * PROMPT_TRUNCATE_LENGTH
        result = _truncate_prompt(prompt)
        assert result == prompt
        assert "..." not in result

    def test_truncate_prompt_long_truncated(self) -> None:
        """Test long prompts are truncated with ellipsis."""
        prompt = "x" * (PROMPT_TRUNCATE_LENGTH + 50)
        result = _truncate_prompt(prompt)
        assert len(result) == PROMPT_TRUNCATE_LENGTH + 3  # +3 for "..."
        assert result.endswith("...")

    def test_truncate_prompt_preserves_start(self) -> None:
        """Test truncation preserves the start of the prompt."""
        prompt = "START" + "x" * 200 + "END"
        result = _truncate_prompt(prompt)
        assert result.startswith("START")


class TestClaudeSubprocessProviderTimeout:
    """Test timeout validation."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create ClaudeSubprocessProvider instance."""
        return ClaudeSubprocessProvider()

    def test_invoke_rejects_zero_timeout(self, provider: ClaudeSubprocessProvider) -> None:
        """Test invoke() raises ValueError for timeout=0."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=0)

        assert "timeout" in str(exc_info.value).lower()
        assert "positive" in str(exc_info.value).lower()

    def test_invoke_rejects_negative_timeout(self, provider: ClaudeSubprocessProvider) -> None:
        """Test invoke() raises ValueError for negative timeout."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=-5)

        assert "timeout" in str(exc_info.value).lower()

    def test_invoke_accepts_positive_timeout(self, provider: ClaudeSubprocessProvider) -> None:
        """Test invoke() accepts positive timeout values."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process()

            # Should not raise
            provider.invoke("Hello", timeout=1)
            provider.invoke("Hello", timeout=60)
            provider.invoke("Hello", timeout=3600)


class TestExtractToolDetails:
    """Test extract_tool_details function for tool display formatting."""

    def test_read_with_file_path(self) -> None:
        """Test Read tool with Claude-style file_path parameter."""
        result = extract_tool_details("Read", {"file_path": "/home/user/project/src/file.py"})
        assert "file.py" in result
        assert result != "?"

    def test_read_with_path(self) -> None:
        """Test Read tool with Gemini/GLM-style path parameter."""
        result = extract_tool_details("Read", {"path": "/home/user/project/src/file.py"})
        assert "file.py" in result
        assert result != "?"

    def test_read_with_empty_input(self) -> None:
        """Test Read tool with empty input returns ?."""
        result = extract_tool_details("Read", {})
        assert result == "?"

    def test_edit_with_file_path(self) -> None:
        """Test Edit tool with file_path parameter."""
        result = extract_tool_details(
            "Edit", {"file_path": "/src/utils.py", "old_string": "def foo():\n    pass"}
        )
        assert "utils.py" in result
        assert "def foo()" in result

    def test_edit_with_path(self) -> None:
        """Test Edit tool with Gemini-style path parameter."""
        result = extract_tool_details("Edit", {"path": "/src/utils.py", "old_string": "def bar()"})
        assert "utils.py" in result
        assert "def bar()" in result

    def test_bash_extracts_command(self) -> None:
        """Test Bash tool extracts command preview."""
        result = extract_tool_details("Bash", {"command": "git status"})
        assert "git status" in result

    def test_grep_extracts_pattern(self) -> None:
        """Test Grep tool extracts pattern and path."""
        result = extract_tool_details("Grep", {"pattern": "TODO", "path": "src/"})
        assert "TODO" in result
        assert "src/" in result

    def test_unknown_tool_returns_empty(self) -> None:
        """Test unknown tool returns empty string."""
        result = extract_tool_details("UnknownTool", {"some": "data"})
        assert result == ""

    def test_gemini_run_shell_command(self) -> None:
        """Test Gemini's run_shell_command maps to Bash."""
        result = extract_tool_details("run_shell_command", {"command": "ls -la"})
        assert "ls -la" in result

    def test_gemini_read_file(self) -> None:
        """Test Gemini's read_file maps to Read."""
        result = extract_tool_details("read_file", {"path": "/home/user/file.py"})
        assert "file.py" in result


class TestClaudeSubprocessProviderCancelSupport:
    """Tests for cancel_token support in ClaudeSubprocessProvider."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create ClaudeSubprocessProvider instance."""
        return ClaudeSubprocessProvider()

    def test_invoke_accepts_cancel_token(self, provider: ClaudeSubprocessProvider) -> None:
        """Test invoke() accepts cancel_token parameter."""
        import threading

        cancel_token = threading.Event()

        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process()

            # Should not raise
            result = provider.invoke("Hello", cancel_token=cancel_token)
            assert result.exit_code == 0

    def test_invoke_returns_cancelled_result_when_token_set(
        self, provider: ClaudeSubprocessProvider, accelerated_time
    ) -> None:
        """Test invoke() returns cancelled result when cancel_token is set."""
        import threading

        cancel_token = threading.Event()
        cancel_token.set()  # Pre-set the token

        with (
            patch("bmad_assist.providers.claude.Popen") as mock,
            patch("bmad_assist.providers.claude.os.getpgid", return_value=12345),
            patch("bmad_assist.providers.claude.os.killpg"),
        ):
            mock.return_value = create_mock_process(never_finish=True)

            result = provider.invoke("Hello", cancel_token=cancel_token)

            assert result.exit_code == -15
            assert "Cancelled" in result.stderr

    def test_cancel_method_terminates_process(self, provider: ClaudeSubprocessProvider) -> None:
        """Test cancel() terminates current process."""
        import signal

        with (
            patch("bmad_assist.providers.claude.os.getpgid", return_value=12345),
            patch("bmad_assist.providers.claude.os.killpg") as mock_killpg,
        ):
                mock_process = MagicMock()
                # Process finishes after SIGTERM
                poll_calls = [0]

                def poll_effect():
                    poll_calls[0] += 1
                    if poll_calls[0] >= 2:  # Finish after 2nd poll
                        return 0
                    return None

                mock_process.poll.side_effect = poll_effect

                provider._current_process = mock_process

                provider.cancel()

                # Should have sent SIGTERM (first call)
                mock_killpg.assert_any_call(12345, signal.SIGTERM)

    def test_cancel_method_does_nothing_when_no_process(
        self, provider: ClaudeSubprocessProvider
    ) -> None:
        """Test cancel() is safe when no process is running."""
        # Should not raise
        provider.cancel()

    def test_invoke_clears_current_process_on_completion(
        self, provider: ClaudeSubprocessProvider
    ) -> None:
        """Test _current_process is cleared after invoke() completes."""
        with patch("bmad_assist.providers.claude.Popen") as mock:
            mock.return_value = create_mock_process()

            provider.invoke("Hello")

            assert provider._current_process is None
