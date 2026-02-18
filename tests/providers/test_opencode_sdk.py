"""Tests for OpenCode SDK-based provider implementation.

Tests organized by Acceptance Criteria from the tech-spec.
"""

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bmad_assist.core.exceptions import ProviderError, ProviderTimeoutError
from bmad_assist.providers.base import BaseProvider, ProviderResult


# =============================================================================
# Module-level state reset fixture (autouse)
# =============================================================================


@pytest.fixture(autouse=True)
def opencode_sdk_state_reset():
    """Reset all module-level globals between tests."""
    import bmad_assist.providers.opencode_sdk as mod

    orig = {
        "_sdk_init_failed_at": mod._sdk_init_failed_at,
        "_server_process": mod._server_process,
        "_server_port": mod._server_port,
        "_server_token": mod._server_token,
        "_atexit_registered": mod._atexit_registered,
    }

    yield

    mod._sdk_init_failed_at = orig["_sdk_init_failed_at"]
    mod._server_process = orig["_server_process"]
    mod._server_port = orig["_server_port"]
    mod._server_token = orig["_server_token"]
    mod._atexit_registered = orig["_atexit_registered"]


# =============================================================================
# Mock helpers
# =============================================================================


def _make_mock_text_part(text: str) -> MagicMock:
    """Create a mock TextPart matching opencode_ai.types.TextPart."""
    part = MagicMock()
    part.text = text
    part.type = "text"
    # Make it pass isinstance check by setting __class__
    part.__class__.__name__ = "TextPart"
    return part


def _make_mock_assistant_message(
    session_id: str = "ses_test123",
    error: object = None,
) -> MagicMock:
    """Create a mock AssistantMessage response from session.chat()."""
    msg = MagicMock()
    msg.id = "msg_test"
    msg.session_id = session_id
    msg.role = "assistant"
    msg.error = error
    msg.cost = 0.001
    return msg


def _make_mock_messages_response(
    text: str = "Mock SDK response",
) -> list[MagicMock]:
    """Create a mock session.messages() response."""
    text_part = _make_mock_text_part(text)

    assistant_info = MagicMock()
    assistant_info.role = "assistant"

    item = MagicMock()
    item.info = assistant_info
    item.parts = [text_part]

    return [item]


def _make_mock_async_client(
    response_text: str = "Mock SDK response",
    session_id: str = "ses_test123",
    chat_side_effect: Exception | None = None,
    chat_error: object = None,
) -> MagicMock:
    """Create a fully mocked AsyncOpencode client."""
    client = MagicMock()

    # session.create()
    session = MagicMock()
    session.id = session_id
    client.session.create = AsyncMock(return_value=session)

    # session.chat()
    if chat_side_effect:
        client.session.chat = AsyncMock(side_effect=chat_side_effect)
    else:
        response = _make_mock_assistant_message(session_id, error=chat_error)
        client.session.chat = AsyncMock(return_value=response)

    # session.messages()
    messages = _make_mock_messages_response(response_text)
    client.session.messages = AsyncMock(return_value=messages)

    # session.delete()
    client.session.delete = AsyncMock(return_value=True)

    # session.abort()
    client.session.abort = AsyncMock(return_value=True)

    return client


def _patch_sdk_invoke(
    mock_client: MagicMock,
) -> tuple:
    """Create the standard set of patches for invoke tests.

    Returns patches for: _ensure_server, AsyncOpencode constructor, TextPart isinstance.
    """
    return (
        patch(
            "bmad_assist.providers.opencode_sdk._ensure_server",
            return_value=(14096, "token123"),
        ),
        patch("opencode_ai.AsyncOpencode", return_value=mock_client),
    )


def _run_invoke_with_mock(
    provider: object,
    mock_client: MagicMock,
    prompt: str = "Hello",
    **invoke_kwargs: object,
) -> ProviderResult:
    """Run invoke with standard mocking. Handles isinstance for TextPart."""
    import bmad_assist.providers.opencode_sdk as mod

    invoke_kwargs.setdefault("model", "opencode/claude-sonnet-4")
    invoke_kwargs.setdefault("timeout", 30)

    with (
        patch.object(mod, "_ensure_server", return_value=(14096, "token123")),
        patch("opencode_ai.AsyncOpencode", return_value=mock_client),
    ):
        # Monkey-patch isinstance check for TextPart inside _invoke_async
        # The lazy import `from opencode_ai.types import TextPart as SDKTextPart`
        # gets the REAL class. We need to make our mock parts pass isinstance.
        # Simplest: patch the types module to return our mock class.
        mock_text_part_class = type(mock_client.session.messages.return_value[0].parts[0])

        with patch("opencode_ai.types.TextPart", mock_text_part_class):
            return provider.invoke(prompt, **invoke_kwargs)  # type: ignore[union-attr]


# =============================================================================
# AC1-AC3: Structure Tests
# =============================================================================


class TestOpenCodeSDKProviderStructure:
    """AC1-AC3: Provider class structure."""

    def test_ac1_inherits_from_base_provider(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        assert issubclass(OpenCodeSDKProvider, BaseProvider)

    def test_ac1_has_docstring(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        assert OpenCodeSDKProvider.__doc__ is not None
        doc = OpenCodeSDKProvider.__doc__.lower()
        assert "opencode" in doc
        assert "sdk" in doc

    def test_ac2_provider_name(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        assert OpenCodeSDKProvider().provider_name == "opencode-sdk"

    def test_ac3_default_model(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        assert OpenCodeSDKProvider().default_model == "opencode/claude-sonnet-4"


# =============================================================================
# AC4: Model Support
# =============================================================================


class TestOpenCodeSDKProviderModels:
    """AC4: supports_model format validation."""

    def test_supports_standard_model(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        p = OpenCodeSDKProvider()
        assert p.supports_model("opencode/claude-sonnet-4")

    def test_supports_any_slash_model(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        p = OpenCodeSDKProvider()
        assert p.supports_model("xai/grok-4")
        assert p.supports_model("foo/bar")

    def test_rejects_no_slash(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        assert not OpenCodeSDKProvider().supports_model("gpt-4")

    def test_rejects_empty_string(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        assert not OpenCodeSDKProvider().supports_model("")

    def test_supports_multiple_slashes(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        assert OpenCodeSDKProvider().supports_model("a/b/c")


# =============================================================================
# AC5-AC6: Invoke Happy Path
# =============================================================================


class TestOpenCodeSDKProviderInvoke:
    """AC5-AC6: SDK call sequence and ProviderResult."""

    def test_ac5_invoke_calls_sdk_sequence(self):
        """AC5: create -> chat -> messages -> delete."""
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        mock_client = _make_mock_async_client("Test response", "ses_abc")

        result = _run_invoke_with_mock(provider, mock_client)

        mock_client.session.create.assert_awaited_once()
        mock_client.session.chat.assert_awaited_once()
        mock_client.session.messages.assert_awaited_once()
        mock_client.session.delete.assert_awaited_once()

    def test_ac6_provider_result_structure(self):
        """AC6: ProviderResult has correct fields."""
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        mock_client = _make_mock_async_client("Test response", "ses_abc")

        result = _run_invoke_with_mock(provider, mock_client)

        assert result.stdout == "Test response"
        assert result.stderr == ""
        assert result.exit_code == 0
        assert result.duration_ms >= 0
        assert result.model is not None
        assert "opencode-sdk" in result.command
        assert result.provider_session_id == "ses_abc"


# =============================================================================
# AC7-AC9: Error Handling
# =============================================================================


class TestOpenCodeSDKProviderErrors:
    """AC7-AC9: Timeout, connection error, import error."""

    def test_ac7_timeout(self):
        """AC7: TimeoutError -> ProviderTimeoutError."""
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()

        with (
            patch(
                "bmad_assist.providers.opencode_sdk._ensure_server",
                return_value=(14096, "tok"),
            ),
            patch(
                "bmad_assist.core.async_utils.run_async_in_thread",
                side_effect=TimeoutError,
            ),
        ):
            with pytest.raises(ProviderTimeoutError):
                provider.invoke("Hello", model="opencode/claude-sonnet-4", timeout=1)

    def test_ac8_server_failure_sets_cooldown(self):
        """AC8: Server startup failure sets cooldown."""
        import bmad_assist.providers.opencode_sdk as mod
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()

        with patch(
            "bmad_assist.providers.opencode_sdk._ensure_server",
            side_effect=ProviderError("Server failed to start"),
        ):
            with pytest.raises(ProviderError):
                provider.invoke("Hello", model="opencode/claude-sonnet-4")
            assert mod._sdk_init_failed_at > 0

    def test_ac8_connection_error_no_cooldown(self):
        """AC8: Runtime ConnectionError does NOT set cooldown."""
        import bmad_assist.providers.opencode_sdk as mod
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()

        with (
            patch(
                "bmad_assist.providers.opencode_sdk._ensure_server",
                return_value=(14096, "tok"),
            ),
            patch(
                "bmad_assist.core.async_utils.run_async_in_thread",
                side_effect=ConnectionError("refused"),
            ),
        ):
            with pytest.raises(ProviderError, match="connection error"):
                provider.invoke("Hello", model="opencode/claude-sonnet-4")
            assert mod._sdk_init_failed_at == 0.0

    def test_ac9_import_error(self):
        """AC9: Missing package -> ProviderError with install instructions."""
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()

        with (
            patch(
                "bmad_assist.providers.opencode_sdk._ensure_server",
                return_value=(14096, "tok"),
            ),
            patch(
                "bmad_assist.core.async_utils.run_async_in_thread",
                side_effect=ImportError("No module named 'opencode_ai'"),
            ),
        ):
            with pytest.raises(ProviderError, match="opencode-ai package not installed"):
                provider.invoke("Hello", model="opencode/claude-sonnet-4")


# =============================================================================
# AC10: Parse Output
# =============================================================================


class TestOpenCodeSDKProviderParseOutput:
    """AC10: Text extraction."""

    def test_strips_whitespace(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        p = OpenCodeSDKProvider()
        result = ProviderResult(
            stdout="  Response text  \n",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="test",
            command=("opencode-sdk",),
        )
        assert p.parse_output(result) == "Response text"

    def test_empty_stdout(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        p = OpenCodeSDKProvider()
        result = ProviderResult(
            stdout="", stderr="", exit_code=0, duration_ms=0, model="t", command=()
        )
        assert p.parse_output(result) == ""


# =============================================================================
# AC11: Package Exports
# =============================================================================


class TestOpenCodeSDKProviderExports:
    """AC11: Import safety."""

    def test_import_succeeds(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        assert OpenCodeSDKProvider is not None

    def test_no_top_level_sdk_import(self):
        """No top-level opencode_ai import in module."""
        import ast

        import importlib.util

        spec = importlib.util.find_spec("bmad_assist.providers.opencode_sdk")
        assert spec is not None and spec.origin is not None
        source = Path(spec.origin).read_text()
        tree = ast.parse(source)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(
                        "opencode_ai"
                    ), f"Top-level import: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("opencode_ai"):
                    pytest.fail(f"Top-level from-import: {node.module}")


# =============================================================================
# AC12: Tool Restriction
# =============================================================================


class TestOpenCodeSDKProviderToolRestriction:
    """AC12: Prompt-level tool injection."""

    def test_tool_restriction_in_prompt(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        mock_client = _make_mock_async_client("Response", "ses_t")

        result = _run_invoke_with_mock(
            provider,
            mock_client,
            prompt="Review code",
            allowed_tools=["Read", "Grep"],
        )

        call_kwargs = mock_client.session.chat.call_args.kwargs
        parts = call_kwargs.get("parts", [])
        prompt_text = parts[0]["text"]
        assert "FORBIDDEN" in prompt_text
        assert "Read" in prompt_text


# =============================================================================
# AC13: Cooldown Fallback
# =============================================================================


class TestOpenCodeSDKProviderCooldown:
    """AC13: Cooldown -> subprocess fallback."""

    def test_cooldown_delegates_to_subprocess(self):
        import bmad_assist.providers.opencode_sdk as mod
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        mod._sdk_init_failed_at = time.monotonic()

        mock_subprocess = MagicMock()
        mock_subprocess.invoke.return_value = ProviderResult(
            stdout="subprocess result",
            stderr="",
            exit_code=0,
            duration_ms=100,
            model="opencode/claude-sonnet-4",
            command=("opencode", "run"),
        )

        with patch(
            "bmad_assist.providers.opencode.OpenCodeProvider",
            return_value=mock_subprocess,
        ):
            result = provider.invoke(
                "Hello",
                model="opencode/claude-sonnet-4",
                timeout=30,
                cwd=Path("/tmp"),
                allowed_tools=["Read"],
                color_index=1,
                display_model="test-model",
            )

            assert result.stdout == "subprocess result"
            kw = mock_subprocess.invoke.call_args.kwargs
            assert kw["model"] == "opencode/claude-sonnet-4"
            assert kw["timeout"] == 30
            assert kw["cwd"] == Path("/tmp")
            assert kw["allowed_tools"] == ["Read"]
            assert kw["color_index"] == 1
            assert kw["display_model"] == "test-model"

    def test_cooldown_expired_retries_sdk(self):
        import bmad_assist.providers.opencode_sdk as mod
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        mod._sdk_init_failed_at = time.monotonic() - 200

        mock_client = _make_mock_async_client("SDK response")

        result = _run_invoke_with_mock(provider, mock_client)
        assert result.stdout == "SDK response"


# =============================================================================
# AC14: Server Lifecycle
# =============================================================================


class TestOpenCodeSDKProviderServerLifecycle:
    """AC14: _ensure_server behavior."""

    def test_starts_server_when_none_running(self):
        import bmad_assist.providers.opencode_sdk as mod

        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None

        with (
            patch.object(mod, "_resolve_opencode_binary", return_value="/usr/bin/opencode"),
            patch.object(mod, "Popen", return_value=mock_process),
            patch.object(mod, "_health_check", side_effect=[False, False, True]),
            patch.object(mod, "_read_pid_file", return_value=None),
            patch.object(mod, "_write_pid_file"),
            patch.object(mod, "_cleanup_pid_files"),
            patch.object(mod, "register_child_pgid"),
            patch.object(mod, "time") as mock_time,
            patch.object(mod, "atexit"),
        ):
            mock_time.sleep = MagicMock()
            mock_time.monotonic.return_value = 1000.0

            port, token = mod._ensure_server()

            assert port == mod.DEFAULT_SERVER_PORT
            assert token is not None
            assert len(token) > 0

    def test_reuses_healthy_server(self):
        import bmad_assist.providers.opencode_sdk as mod

        mod._server_port = 14096
        mod._server_token = "existing-token"

        with patch.object(mod, "_health_check", return_value=True):
            port, token = mod._ensure_server()
            assert port == 14096
            assert token == "existing-token"

    def test_double_checked_locking_skips_lock(self):
        import bmad_assist.providers.opencode_sdk as mod

        mod._server_port = 14096
        mod._server_token = "tok"

        health_calls = []

        def mock_health(port: int, timeout: float = 2.0) -> bool:
            health_calls.append(port)
            return True

        with patch.object(mod, "_health_check", side_effect=mock_health):
            mod._ensure_server()
            # Quick check succeeds, lock never acquired
            assert len(health_calls) == 1


# =============================================================================
# AC15: Cancel
# =============================================================================


class TestOpenCodeSDKProviderCancel:
    """AC15: Cancel via session.abort()."""

    def test_cancel_no_sessions_is_noop(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        provider.cancel()  # Should not raise

    def test_cancel_calls_abort(self):
        import bmad_assist.providers.opencode_sdk as mod
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        provider._active_sessions[threading.get_ident()] = "ses_cancel"
        mod._server_port = 14096
        mod._server_token = "tok"

        with patch("httpx.post") as mock_post:
            provider.cancel()
            mock_post.assert_called_once()
            url = mock_post.call_args[0][0]
            assert "ses_cancel" in url
            assert "abort" in url


# =============================================================================
# AC16: Session Cleanup
# =============================================================================


class TestOpenCodeSDKProviderSessionCleanup:
    """AC16: Session delete in finally block."""

    def test_delete_called_in_finally(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        mock_client = _make_mock_async_client("Response", "ses_cleanup")

        _run_invoke_with_mock(provider, mock_client)
        mock_client.session.delete.assert_awaited_once_with(id="ses_cleanup")

    def test_delete_failure_doesnt_crash(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        mock_client = _make_mock_async_client("Response", "ses_err")
        mock_client.session.delete = AsyncMock(side_effect=Exception("delete failed"))

        result = _run_invoke_with_mock(provider, mock_client)
        assert result.stdout == "Response"

    def test_session_cleared_from_active(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        mock_client = _make_mock_async_client("Response", "ses_track")

        _run_invoke_with_mock(provider, mock_client)
        assert len(provider._active_sessions) == 0


# =============================================================================
# AC17: Registry
# =============================================================================


class TestOpenCodeSDKProviderRegistry:
    """AC17: Registry integration."""

    def test_get_opencode_sdk(self):
        from bmad_assist.providers.registry import get_provider

        p = get_provider("opencode-sdk")
        assert p.provider_name == "opencode-sdk"

    def test_opencode_still_works(self):
        from bmad_assist.providers.registry import get_provider

        p = get_provider("opencode")
        assert p.provider_name == "opencode"


# =============================================================================
# AC18: Response Parsing Robustness
# =============================================================================


class TestOpenCodeSDKProviderResponseParsing:
    """AC18: Malformed response handling."""

    def test_empty_messages_uses_fallback(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        mock_client = _make_mock_async_client("Test", "ses_e")
        mock_client.session.messages = AsyncMock(return_value=[])

        # Make chat response stringifiable
        chat_resp = _make_mock_assistant_message("ses_e")
        chat_resp.__str__ = lambda self: "fallback text"
        mock_client.session.chat = AsyncMock(return_value=chat_resp)

        import bmad_assist.providers.opencode_sdk as mod

        with (
            patch.object(mod, "_ensure_server", return_value=(14096, "tok")),
            patch("opencode_ai.AsyncOpencode", return_value=mock_client),
            patch("opencode_ai.types.TextPart", type(None)),  # Nothing matches
        ):
            result = provider.invoke(
                "Hello", model="opencode/claude-sonnet-4", timeout=30
            )
            assert result.stdout != ""


# =============================================================================
# AC19: PID File Handling
# =============================================================================


class TestOpenCodeSDKProviderPIDFile:
    """AC19: PID file lifecycle."""

    def test_stale_pid_file_cleaned(self):
        from bmad_assist.providers.opencode_sdk import _read_pid_file

        import tempfile

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("bmad_assist.providers.opencode_sdk._PID_DIR", Path(tmpdir)),
        ):
            pid_file = Path(tmpdir) / "opencode-server-14096.pid"
            pid_file.write_text(json.dumps({"port": 14096, "pid": 999999, "token": "t"}))

            result = _read_pid_file(14096)
            assert result is None
            assert not pid_file.exists()

    def test_corrupt_pid_file(self):
        from bmad_assist.providers.opencode_sdk import _read_pid_file

        import tempfile

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("bmad_assist.providers.opencode_sdk._PID_DIR", Path(tmpdir)),
        ):
            Path(tmpdir, "opencode-server-14096.pid").write_text("not json")
            assert _read_pid_file(14096) is None

    def test_missing_pid_file(self):
        from bmad_assist.providers.opencode_sdk import _read_pid_file

        import tempfile

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("bmad_assist.providers.opencode_sdk._PID_DIR", Path(tmpdir)),
        ):
            assert _read_pid_file(14096) is None


# =============================================================================
# AC20: Server Crash Recovery
# =============================================================================


class TestOpenCodeSDKProviderServerCrashRecovery:
    """AC20: ConnectionError -> no cooldown -> retry SDK."""

    def test_connection_error_no_cooldown(self):
        import bmad_assist.providers.opencode_sdk as mod
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()

        with (
            patch.object(mod, "_ensure_server", return_value=(14096, "tok")),
            patch(
                "bmad_assist.core.async_utils.run_async_in_thread",
                side_effect=ConnectionError("Connection refused"),
            ),
        ):
            with pytest.raises(ProviderError):
                provider.invoke("Hello", model="opencode/claude-sonnet-4")
            assert mod._sdk_init_failed_at == 0.0


# =============================================================================
# AC21: Registry Import Safety
# =============================================================================


class TestOpenCodeSDKProviderRegistryImportSafety:
    """AC21: Registry init without opencode-ai."""

    def test_module_loads_without_sdk(self):
        """Module loads without opencode-ai being available at import time."""
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        assert OpenCodeSDKProvider is not None


# =============================================================================
# Additional Edge Cases
# =============================================================================


class TestOpenCodeSDKProviderEdgeCases:
    """Additional edge case tests."""

    def test_invalid_timeout(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        with pytest.raises(ValueError, match="timeout must be positive"):
            OpenCodeSDKProvider().invoke("Hello", model="opencode/x", timeout=0)

    def test_invalid_model_format(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        with pytest.raises(ProviderError, match="Invalid model format"):
            OpenCodeSDKProvider().invoke("Hello", model="gpt-4")

    def test_default_model_used_when_none(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        mock_client = _make_mock_async_client("Response")

        result = _run_invoke_with_mock(provider, mock_client, model=None)

        kw = mock_client.session.chat.call_args.kwargs
        assert kw["provider_id"] == "opencode"
        assert kw["model_id"] == "claude-sonnet-4"

    def test_health_check_false_on_error(self):
        from bmad_assist.providers.opencode_sdk import _health_check

        with patch("httpx.get", side_effect=ConnectionError("refused")):
            assert _health_check(14096) is False

    def test_find_free_port(self):
        from bmad_assist.providers.opencode_sdk import _find_free_port

        port = _find_free_port()
        assert isinstance(port, int)
        assert port > 0

    def test_generate_auth_token_unique(self):
        from bmad_assist.providers.opencode_sdk import _generate_auth_token

        tokens = {_generate_auth_token() for _ in range(10)}
        assert len(tokens) == 10

    def test_resolve_binary_env_var(self):
        from bmad_assist.providers.opencode_sdk import _resolve_opencode_binary

        with (
            patch.dict(os.environ, {"BMAD_OPENCODE_CLI_PATH": "/usr/local/bin/opencode"}),
            patch("os.path.isfile", return_value=True),
            patch("os.access", return_value=True),
        ):
            assert _resolve_opencode_binary() == "/usr/local/bin/opencode"

    def test_resolve_binary_not_found(self):
        from bmad_assist.providers.opencode_sdk import _resolve_opencode_binary

        with (
            patch.dict(os.environ, {}, clear=False),
            patch("shutil.which", return_value=None),
        ):
            # Clear env var if set
            os.environ.pop("BMAD_OPENCODE_CLI_PATH", None)
            with pytest.raises(ProviderError, match="not found"):
                _resolve_opencode_binary()

    def test_chat_error_response_raises(self):
        from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

        provider = OpenCodeSDKProvider()
        mock_client = _make_mock_async_client(
            "Resp", "ses_e2", chat_error="API error occurred"
        )

        import bmad_assist.providers.opencode_sdk as mod

        with (
            patch.object(mod, "_ensure_server", return_value=(14096, "tok")),
            patch("opencode_ai.AsyncOpencode", return_value=mock_client),
        ):
            with pytest.raises(ProviderError, match="SDK error"):
                provider.invoke("Hello", model="opencode/claude-sonnet-4", timeout=30)
