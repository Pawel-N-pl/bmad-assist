"""Unit tests for ClaudeSDKProvider implementation.

Tests cover:
- AC1: ClaudeSDKProvider extends BaseProvider
- AC2: provider_name returns "claude"
- AC3: default_model returns "sonnet"
- AC4: supports_model() validates Claude models
- AC5: invoke() uses Claude Agent SDK
- AC6: invoke() returns ProviderResult on success
- AC7: invoke() raises ProviderError on SDK errors
- AC8: invoke() handles timeout via asyncio
- AC9: ClaudeSubprocessProvider tests (in test_claude.py)
- AC10: Package exports updated correctly
- AC11: No fallback logic exists
- AC12: invoke() handles SDK edge cases
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force SDK path in tests (bypass nested Claude Code detection)
os.environ["BMAD_SDK_FORCE"] = "1"

from bmad_assist.core.exceptions import ProviderError, ProviderTimeoutError
from bmad_assist.providers import (
    BaseProvider,
    ClaudeProvider,
    ClaudeSDKProvider,
    ClaudeSubprocessProvider,
    ProviderResult,
)
from bmad_assist.providers.claude_sdk import (
    DEFAULT_TIMEOUT,
    SUPPORTED_MODELS,
)


class TestClaudeSDKProviderStructure:
    """Test AC1, AC2, AC3: ClaudeSDKProvider class definition."""

    def test_sdk_provider_inherits_from_baseprovider(self) -> None:
        """Test AC1: ClaudeSDKProvider inherits from BaseProvider."""
        assert issubclass(ClaudeSDKProvider, BaseProvider)

    def test_sdk_provider_has_class_docstring(self) -> None:
        """Test AC1: ClaudeSDKProvider has docstring explaining SDK integration."""
        assert ClaudeSDKProvider.__doc__ is not None
        assert "sdk" in ClaudeSDKProvider.__doc__.lower()
        assert "primary" in ClaudeSDKProvider.__doc__.lower()

    def test_sdk_provider_docstring_mentions_no_fallback(self) -> None:
        """Test AC1: ClaudeSDKProvider docstring mentions no fallback design."""
        assert ClaudeSDKProvider.__doc__ is not None
        assert "fallback" in ClaudeSDKProvider.__doc__.lower()

    def test_provider_name_returns_claude(self) -> None:
        """Test AC2: provider_name returns 'claude'."""
        provider = ClaudeSDKProvider()
        assert provider.provider_name == "claude"

    def test_default_model_returns_sonnet(self) -> None:
        """Test AC3: default_model returns 'sonnet'."""
        provider = ClaudeSDKProvider()
        assert provider.default_model == "sonnet"


class TestClaudeSDKProviderModels:
    """Test AC4: supports_model() validation."""

    @pytest.fixture
    def provider(self) -> ClaudeSDKProvider:
        """Create ClaudeSDKProvider instance."""
        return ClaudeSDKProvider()

    def test_supported_models_constant_is_frozenset(self) -> None:
        """Test SUPPORTED_MODELS is a frozenset."""
        assert isinstance(SUPPORTED_MODELS, frozenset)

    def test_supported_models_matches_subprocess_provider(self) -> None:
        """Test SUPPORTED_MODELS matches subprocess provider."""
        from bmad_assist.providers.claude import (
            SUPPORTED_MODELS as SUBPROCESS_MODELS,
        )

        assert SUPPORTED_MODELS == SUBPROCESS_MODELS

    def test_supports_model_opus(self, provider: ClaudeSDKProvider) -> None:
        """Test AC4: supports_model('opus') returns True."""
        assert provider.supports_model("opus") is True

    def test_supports_model_sonnet(self, provider: ClaudeSDKProvider) -> None:
        """Test AC4: supports_model('sonnet') returns True."""
        assert provider.supports_model("sonnet") is True

    def test_supports_model_haiku(self, provider: ClaudeSDKProvider) -> None:
        """Test AC4: supports_model('haiku') returns True."""
        assert provider.supports_model("haiku") is True

    def test_supports_model_full_identifier(self, provider: ClaudeSDKProvider) -> None:
        """Test AC4: supports_model('claude-sonnet-4-20250514') returns True."""
        assert provider.supports_model("claude-sonnet-4-20250514") is True

    def test_supports_model_gpt4_returns_false(self, provider: ClaudeSDKProvider) -> None:
        """Test AC4: supports_model('gpt-4') returns False."""
        assert provider.supports_model("gpt-4") is False


async def _mock_async_generator(
    messages: list[MagicMock],
) -> AsyncIterator[MagicMock]:
    """Create async generator from list of messages for testing."""
    for msg in messages:
        yield msg


def _patch_sdk_client(messages: list[MagicMock] | None = None, connect_error: Exception | None = None):
    """Create a patch context for ClaudeSDKClient that returns mock messages.

    Args:
        messages: Messages to yield from receive_messages(). If None, yields nothing.
        connect_error: If set, client.connect() raises this error.

    Returns:
        A context manager that patches ClaudeSDKClient and returns the mock class.

    """
    mock_client_class = MagicMock()
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    if connect_error:
        mock_client.connect = AsyncMock(side_effect=connect_error)
    else:
        mock_client.connect = AsyncMock()

    if messages is not None:
        mock_client.receive_messages.return_value = _mock_async_generator(messages)
    else:
        mock_client.receive_messages.return_value = _mock_async_generator([])

    mock_client.disconnect = AsyncMock()

    return patch("bmad_assist.providers.claude_sdk.ClaudeSDKClient", mock_client_class)


class TestClaudeSDKProviderInvoke:
    """Test AC5, AC6: invoke() with SDK."""

    @pytest.fixture
    def provider(self) -> ClaudeSDKProvider:
        """Create ClaudeSDKProvider instance."""
        return ClaudeSDKProvider()

    @pytest.fixture
    def mock_text_block(self) -> MagicMock:
        """Create mock TextBlock."""
        from claude_agent_sdk import TextBlock

        return TextBlock(text="Hello response")

    @pytest.fixture
    def mock_assistant_message(self, mock_text_block: MagicMock) -> MagicMock:
        """Create mock AssistantMessage with TextBlock."""
        from claude_agent_sdk import AssistantMessage

        return AssistantMessage(
            content=[mock_text_block],
            model="sonnet",
        )

    @pytest.fixture
    def mock_result_message(self) -> MagicMock:
        """Create mock ResultMessage."""
        from claude_agent_sdk import ResultMessage

        return ResultMessage(
            subtype="success",
            duration_ms=1000,
            duration_api_ms=900,
            is_error=False,
            num_turns=1,
            session_id="test-session",
            total_cost_usd=0.001,
            usage={"input_tokens": 10, "output_tokens": 20},
            result=None,
        )

    def test_invoke_success_returns_providerresult(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """Test AC5, AC6: invoke() uses SDK and returns ProviderResult."""
        messages = [mock_assistant_message, mock_result_message]

        with _patch_sdk_client(messages) as mock_cls:
            result = provider.invoke("Hello", model="opus")

            assert isinstance(result, ProviderResult)
            mock_cls.assert_called_once()

    def test_invoke_stdout_contains_response(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """Test AC6: ProviderResult.stdout contains response text from TextBlock."""
        messages = [mock_assistant_message, mock_result_message]

        with _patch_sdk_client(messages):
            result = provider.invoke("Hello")

            assert result.stdout == "Hello response"

    def test_invoke_stderr_is_empty(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """Test AC6: ProviderResult.stderr is empty string."""
        messages = [mock_assistant_message, mock_result_message]

        with _patch_sdk_client(messages):
            result = provider.invoke("Hello")

            assert result.stderr == ""

    def test_invoke_exit_code_is_zero(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """Test AC6: ProviderResult.exit_code is 0."""
        messages = [mock_assistant_message, mock_result_message]

        with _patch_sdk_client(messages):
            result = provider.invoke("Hello")

            assert result.exit_code == 0

    def test_invoke_duration_ms_is_positive(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """Test AC6: ProviderResult.duration_ms is positive integer."""
        messages = [mock_assistant_message, mock_result_message]

        with _patch_sdk_client(messages):

            result = provider.invoke("Hello")

            assert isinstance(result.duration_ms, int)
            assert result.duration_ms >= 0

    def test_invoke_model_recorded(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """Test AC6: ProviderResult.model contains the model used."""
        messages = [mock_assistant_message, mock_result_message]

        with _patch_sdk_client(messages):
            result = provider.invoke("Hello", model="opus")

            assert result.model == "opus"

    def test_invoke_command_describes_sdk(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """Test AC6: ProviderResult.command is tuple describing SDK invocation."""
        messages = [mock_assistant_message, mock_result_message]

        with _patch_sdk_client(messages):
            result = provider.invoke("Hello", model="opus")

            assert isinstance(result.command, tuple)
            assert result.command == ("sdk", "query", "opus")

    def test_invoke_uses_default_model(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """Test AC6: invoke() uses default_model when none specified."""
        messages = [mock_assistant_message, mock_result_message]

        with _patch_sdk_client(messages):
            result = provider.invoke("Hello")

            assert result.model == "sonnet"

    def test_invoke_uses_default_timeout(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """Test invoke() uses DEFAULT_TIMEOUT when timeout=None."""
        messages = [mock_assistant_message, mock_result_message]

        with _patch_sdk_client(messages):
            result = provider.invoke("Hello")

            # If timeout was used correctly, invoke succeeds
            # The timeout is enforced internally via asyncio.wait_for
            assert result.exit_code == 0

    def test_invoke_passes_settings_to_sdk(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test AC5: invoke() passes validated settings file to SDK options."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"timeout": 600}')

        messages = [mock_assistant_message, mock_result_message]

        with _patch_sdk_client(messages) as mock_cls:
            provider.invoke("Hello", settings_file=settings_path)

            # Verify options passed to ClaudeSDKClient constructor
            call_args = mock_cls.call_args[1]
            options = call_args["options"]
            # settings is converted to str for SDK
            assert options.settings == str(settings_path)


class TestClaudeSDKProviderErrors:
    """Test AC7, AC8, AC11, AC12: Error handling."""

    @pytest.fixture
    def provider(self) -> ClaudeSDKProvider:
        """Create ClaudeSDKProvider instance."""
        return ClaudeSDKProvider()

    def test_invoke_raises_providererror_on_cli_not_found(
        self, provider: ClaudeSDKProvider
    ) -> None:
        """Test AC7: invoke() raises ProviderError on CLINotFoundError."""
        from claude_agent_sdk import CLINotFoundError

        with _patch_sdk_client(connect_error=CLINotFoundError("Claude not found")):
            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert "Claude Code not found" in str(exc_info.value)

    def test_invoke_cli_not_found_exception_chained(self, provider: ClaudeSDKProvider) -> None:
        """Test AC7: CLINotFoundError is chained with 'from e'."""
        from claude_agent_sdk import CLINotFoundError

        with _patch_sdk_client(connect_error=CLINotFoundError("Claude not found")):
            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, CLINotFoundError)

    def test_invoke_raises_providererror_on_process_error(
        self, provider: ClaudeSDKProvider
    ) -> None:
        """Test AC7: invoke() raises ProviderError on ProcessError with exit code."""
        from claude_agent_sdk import ProcessError

        with _patch_sdk_client(
            connect_error=ProcessError("Process failed", exit_code=1, stderr="Error details")
        ):
            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            error_msg = str(exc_info.value)
            assert "exit code 1" in error_msg.lower()
            assert "Error details" in error_msg

    def test_invoke_process_error_exception_chained(self, provider: ClaudeSDKProvider) -> None:
        """Test AC7: ProcessError is chained with 'from e'."""
        from claude_agent_sdk import ProcessError

        with _patch_sdk_client(
            connect_error=ProcessError("Process failed", exit_code=1, stderr="Error")
        ):
            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, ProcessError)

    def test_invoke_raises_timeout_error(self, provider: ClaudeSDKProvider) -> None:
        """Test AC8: invoke() raises ProviderTimeoutError on TimeoutError."""
        # Mock _invoke_async to raise TimeoutError when awaited
        # This simulates asyncio.wait_for timeout without creating un-awaited coroutines
        async_mock = AsyncMock(side_effect=TimeoutError())
        with patch.object(provider, "_invoke_async", async_mock):
            with pytest.raises(ProviderTimeoutError) as exc_info:
                provider.invoke("Hello", timeout=5)

            assert "SDK timeout after 5s" in str(exc_info.value)

    def test_invoke_timeout_error_not_provider_error(self, provider: ClaudeSDKProvider) -> None:
        """Test AC8: ProviderTimeoutError is distinct subclass of ProviderError."""
        assert issubclass(ProviderTimeoutError, ProviderError)
        assert ProviderTimeoutError is not ProviderError

    def test_invoke_raises_providererror_on_unsupported_model(
        self, provider: ClaudeSDKProvider
    ) -> None:
        """Test invoke() raises ProviderError for unsupported models."""
        with pytest.raises(ProviderError) as exc_info:
            provider.invoke("Hello", model="gpt-4")

        error_msg = str(exc_info.value).lower()
        assert "unsupported model" in error_msg
        assert "gpt-4" in error_msg

    def test_invoke_raises_valueerror_on_invalid_timeout(self, provider: ClaudeSDKProvider) -> None:
        """Test invoke() raises ValueError for non-positive timeout."""
        with pytest.raises(ValueError) as exc_info:
            provider.invoke("Hello", timeout=0)

        assert "timeout must be positive" in str(exc_info.value)

        with pytest.raises(ValueError):
            provider.invoke("Hello", timeout=-5)


class TestClaudeSDKProviderEmptyResponse:
    """Test AC12: Empty response handling."""

    @pytest.fixture
    def provider(self) -> ClaudeSDKProvider:
        """Create ClaudeSDKProvider instance."""
        return ClaudeSDKProvider()

    def test_invoke_raises_providererror_on_empty_response(
        self, provider: ClaudeSDKProvider
    ) -> None:
        """Test AC12: invoke() raises ProviderError if no AssistantMessage received."""
        with _patch_sdk_client(messages=[]):
            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert "No response received" in str(exc_info.value)

    def test_invoke_raises_providererror_on_only_result_message(
        self, provider: ClaudeSDKProvider
    ) -> None:
        """Test AC12: ProviderError raised if only ResultMessage (no AssistantMessage)."""
        from claude_agent_sdk import ResultMessage

        result_msg = ResultMessage(
            subtype="success",
            duration_ms=1000,
            duration_api_ms=900,
            is_error=False,
            num_turns=1,
            session_id="test-session",
            total_cost_usd=0.001,
            usage={},
            result=None,
        )

        with _patch_sdk_client(messages=[result_msg]):
            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert "No response received" in str(exc_info.value)


class TestClaudeSDKProviderGenericException:
    """Test AC12: Generic exception handling."""

    @pytest.fixture
    def provider(self) -> ClaudeSDKProvider:
        """Create ClaudeSDKProvider instance."""
        return ClaudeSDKProvider()

    def test_invoke_wraps_generic_exception(self, provider: ClaudeSDKProvider) -> None:
        """Test AC12: Generic exceptions are wrapped in ProviderError."""
        # Mock _invoke_async to raise RuntimeError when awaited
        async_mock = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        with patch.object(provider, "_invoke_async", async_mock):
            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert "Unexpected SDK error" in str(exc_info.value)

    def test_invoke_generic_exception_chained(self, provider: ClaudeSDKProvider) -> None:
        """Test AC12: Generic exception is chained with 'from e'."""
        # Mock _invoke_async to raise RuntimeError when awaited
        async_mock = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        with patch.object(provider, "_invoke_async", async_mock):
            with pytest.raises(ProviderError) as exc_info:
                provider.invoke("Hello")

            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, RuntimeError)


class TestClaudeSDKProviderNoFallback:
    """Test AC11: No fallback logic exists."""

    @pytest.fixture
    def provider(self) -> ClaudeSDKProvider:
        """Create ClaudeSDKProvider instance."""
        return ClaudeSDKProvider()

    def test_sdk_module_does_not_import_subprocess(self) -> None:
        """Test AC11: claude_sdk module does not import subprocess."""
        import subprocess

        from bmad_assist.providers import claude_sdk

        # Check that subprocess is not in the module's namespace
        assert "subprocess" not in dir(claude_sdk)
        assert "run" not in dir(claude_sdk) or claude_sdk.run is not subprocess.run

    def test_invoke_error_does_not_fallback(self, provider: ClaudeSDKProvider) -> None:
        """Test AC11: SDK failure propagates immediately, no fallback."""
        from claude_agent_sdk import ProcessError

        with _patch_sdk_client(
            connect_error=ProcessError("Failed", exit_code=1, stderr="Error")
        ) as mock_cls:
            with pytest.raises(ProviderError):
                provider.invoke("Hello")

            # Should only create one client (no retry/fallback)
            assert mock_cls.call_count == 1


class TestClaudeSDKProviderParseOutput:
    """Test parse_output() functionality."""

    @pytest.fixture
    def provider(self) -> ClaudeSDKProvider:
        """Create ClaudeSDKProvider instance."""
        return ClaudeSDKProvider()

    def test_parse_output_extracts_stdout(self, provider: ClaudeSDKProvider) -> None:
        """Test parse_output() returns result.stdout.strip()."""
        result = ProviderResult(
            stdout="Hello response",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="sonnet",
            command=("sdk", "query", "sonnet"),
        )

        parsed = provider.parse_output(result)

        assert parsed == "Hello response"

    def test_parse_output_strips_whitespace(self, provider: ClaudeSDKProvider) -> None:
        """Test parse_output() strips leading/trailing whitespace."""
        result = ProviderResult(
            stdout="  Hello response  \n",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="sonnet",
            command=("sdk", "query", "sonnet"),
        )

        parsed = provider.parse_output(result)

        assert parsed == "Hello response"

    def test_parse_output_empty_returns_empty(self, provider: ClaudeSDKProvider) -> None:
        """Test parse_output() returns empty string for empty stdout."""
        result = ProviderResult(
            stdout="",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="sonnet",
            command=("sdk", "query", "sonnet"),
        )

        parsed = provider.parse_output(result)

        assert parsed == ""


class TestPackageExports:
    """Test AC10: Package exports."""

    def test_claudesdkprovider_exported(self) -> None:
        """Test AC10: ClaudeSDKProvider is exported from providers."""
        from bmad_assist.providers import ClaudeSDKProvider as Imported

        assert Imported is ClaudeSDKProvider

    def test_claudesubprocessprovider_exported(self) -> None:
        """Test AC10: ClaudeSubprocessProvider is exported from providers."""
        from bmad_assist.providers import ClaudeSubprocessProvider as Imported

        assert Imported is ClaudeSubprocessProvider

    def test_claudeprovider_is_alias_for_sdk(self) -> None:
        """Test AC10: ClaudeProvider is alias for ClaudeSDKProvider."""
        assert ClaudeProvider is ClaudeSDKProvider

    def test_all_includes_three_providers(self) -> None:
        """Test AC10: __all__ includes all three provider names."""
        from bmad_assist import providers

        assert "ClaudeProvider" in providers.__all__
        assert "ClaudeSDKProvider" in providers.__all__
        assert "ClaudeSubprocessProvider" in providers.__all__

    def test_providers_have_same_interface(self) -> None:
        """Test both providers implement same BaseProvider interface."""
        sdk_provider = ClaudeSDKProvider()
        subprocess_provider = ClaudeSubprocessProvider()

        # Both have same interface methods
        assert hasattr(sdk_provider, "provider_name")
        assert hasattr(sdk_provider, "default_model")
        assert hasattr(sdk_provider, "invoke")
        assert hasattr(sdk_provider, "parse_output")
        assert hasattr(sdk_provider, "supports_model")

        assert hasattr(subprocess_provider, "provider_name")
        assert hasattr(subprocess_provider, "default_model")
        assert hasattr(subprocess_provider, "invoke")
        assert hasattr(subprocess_provider, "parse_output")
        assert hasattr(subprocess_provider, "supports_model")


class TestDocstringsExist:
    """Verify all public methods have docstrings."""

    def test_module_has_docstring(self) -> None:
        """Test module has docstring."""
        from bmad_assist.providers import claude_sdk

        assert claude_sdk.__doc__ is not None
        assert "sdk" in claude_sdk.__doc__.lower()

    def test_claudesdkprovider_has_docstring(self) -> None:
        """Test ClaudeSDKProvider has docstring."""
        assert ClaudeSDKProvider.__doc__ is not None

    def test_provider_name_has_docstring(self) -> None:
        """Test provider_name property has docstring."""
        fget = ClaudeSDKProvider.provider_name.fget
        assert fget is not None
        assert fget.__doc__ is not None

    def test_default_model_has_docstring(self) -> None:
        """Test default_model property has docstring."""
        fget = ClaudeSDKProvider.default_model.fget
        assert fget is not None
        assert fget.__doc__ is not None

    def test_invoke_has_docstring(self) -> None:
        """Test invoke() has docstring."""
        assert ClaudeSDKProvider.invoke.__doc__ is not None

    def test_invoke_has_google_style_docstring(self) -> None:
        """Test invoke() has Google-style docstring."""
        doc = ClaudeSDKProvider.invoke.__doc__
        assert doc is not None
        assert "Args:" in doc
        assert "Returns:" in doc
        assert "Raises:" in doc

    def test_parse_output_has_docstring(self) -> None:
        """Test parse_output() has docstring."""
        assert ClaudeSDKProvider.parse_output.__doc__ is not None

    def test_supports_model_has_docstring(self) -> None:
        """Test supports_model() has docstring."""
        assert ClaudeSDKProvider.supports_model.__doc__ is not None


class TestDisableTools:
    """Test disable_tools=True sets allowed_tools=[] for SDK."""

    @pytest.fixture
    def provider(self) -> ClaudeSDKProvider:
        """Create ClaudeSDKProvider instance."""
        return ClaudeSDKProvider()

    @pytest.fixture
    def mock_text_block(self) -> MagicMock:
        """Create mock TextBlock."""
        from claude_agent_sdk import TextBlock

        return TextBlock(text="response")

    @pytest.fixture
    def mock_assistant_message(self, mock_text_block: MagicMock) -> MagicMock:
        """Create mock AssistantMessage."""
        from claude_agent_sdk import AssistantMessage

        return AssistantMessage(content=[mock_text_block], model="sonnet")

    @pytest.fixture
    def mock_result_message(self) -> MagicMock:
        """Create mock ResultMessage."""
        from claude_agent_sdk import ResultMessage

        return ResultMessage(
            subtype="success",
            duration_ms=1000,
            duration_api_ms=900,
            is_error=False,
            num_turns=1,
            session_id="test-session",
            total_cost_usd=0.001,
            usage={"input_tokens": 10, "output_tokens": 20},
            result=None,
        )

    def test_disable_tools_passes_empty_allowed_tools(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """When disable_tools=True, allowed_tools=[] is passed to _invoke_async."""
        messages = [mock_assistant_message, mock_result_message]

        with (
            _patch_sdk_client(messages),
            patch.object(provider, "_invoke_async", wraps=provider._invoke_async) as mock_invoke_async,
        ):
            provider.invoke("test prompt", model="sonnet", disable_tools=True)
            # _invoke_async should be called with allowed_tools=[]
            mock_invoke_async.assert_called_once()
            call_args = mock_invoke_async.call_args
            assert call_args[0][4] == []  # 5th positional arg = allowed_tools

    def test_disable_tools_false_does_not_set_allowed_tools(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """When disable_tools=False, allowed_tools remains None (all tools)."""
        messages = [mock_assistant_message, mock_result_message]

        with (
            _patch_sdk_client(messages),
            patch.object(provider, "_invoke_async", wraps=provider._invoke_async) as mock_invoke_async,
        ):
            provider.invoke("test prompt", model="sonnet", disable_tools=False)
            mock_invoke_async.assert_called_once()
            call_args = mock_invoke_async.call_args
            assert call_args[0][4] is None  # allowed_tools stays None

    def test_disable_tools_with_explicit_allowed_tools_keeps_them(
        self,
        provider: ClaudeSDKProvider,
        mock_assistant_message: MagicMock,
        mock_result_message: MagicMock,
    ) -> None:
        """When disable_tools=True but allowed_tools is already set, keep explicit list."""
        messages = [mock_assistant_message, mock_result_message]

        with (
            _patch_sdk_client(messages),
            patch.object(provider, "_invoke_async", wraps=provider._invoke_async) as mock_invoke_async,
        ):
            provider.invoke(
                "test prompt", model="sonnet", disable_tools=True,
                allowed_tools=["Read", "Glob"],
            )
            mock_invoke_async.assert_called_once()
            call_args = mock_invoke_async.call_args
            assert call_args[0][4] == ["Read", "Glob"]


class TestConstants:
    """Test module constants."""

    def test_default_timeout_is_300(self) -> None:
        """Test DEFAULT_TIMEOUT is 300 seconds (5 minutes)."""
        assert DEFAULT_TIMEOUT == 300

    def test_supported_models_contains_expected(self) -> None:
        """Test SUPPORTED_MODELS contains opus, sonnet, haiku."""
        assert "opus" in SUPPORTED_MODELS
        assert "sonnet" in SUPPORTED_MODELS
        assert "haiku" in SUPPORTED_MODELS


@pytest.mark.integration
class TestClaudeSDKIntegration:
    """Integration tests - skip if SDK not available."""

    @pytest.fixture
    def provider(self) -> ClaudeSDKProvider:
        """Create ClaudeSDKProvider instance."""
        return ClaudeSDKProvider()

    def test_sdk_import_succeeds(self) -> None:
        """Test claude-agent-sdk can be imported."""
        from claude_agent_sdk import ClaudeAgentOptions, query

        assert query is not None
        assert ClaudeAgentOptions is not None
