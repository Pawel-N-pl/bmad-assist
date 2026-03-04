"""Unit and integration tests for IPC command handler.

Story 29.5: Tests cover CommandHandlerImpl for all 5 control commands
(pause, resume, stop, set_log_level, reload_config), state transition
validation, idempotency, error wrapping, and end-to-end client-server
round-trips.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import ConfigError
from bmad_assist.ipc.commands import CommandHandlerImpl
from bmad_assist.ipc.protocol import (
    ErrorCode,
    read_message,
    write_message,
    deserialize,
)
from bmad_assist.ipc.server import (
    IPCServerThread,
    SocketServer,
)
from bmad_assist.ipc.client import (
    IPCCommandError,
    SocketClient,
    SyncSocketClient,
)
from bmad_assist.ipc.types import (
    PauseResult,
    ResumeResult,
    RunnerState,
    SetLogLevelResult,
    StopResult,
    ReloadConfigResult,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_root_logger_level():
    """Restore root logger level and handler levels after each test.

    The set_log_level command modifies both root logger level AND all
    handler levels (including pytest's caplog handler). Without this
    fixture, later tests that rely on caplog capturing WARNING messages
    would fail because handlers are stuck at ERROR/CRITICAL.
    """
    root = logging.getLogger()
    original_level = root.level
    original_handler_levels = [(h, h.level) for h in root.handlers]
    yield
    root.setLevel(original_level)
    for handler, level in original_handler_levels:
        handler.setLevel(level)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a temporary project root with .bmad-assist directory."""
    bmad_dir = tmp_path / ".bmad-assist"
    bmad_dir.mkdir()
    return tmp_path


@pytest.fixture
def mock_cancel_ctx() -> MagicMock:
    """Create a mock CancellationContext."""
    ctx = MagicMock()
    ctx.is_cancelled = False
    return ctx


@pytest.fixture
def mock_server() -> MagicMock:
    """Create a mock SocketServer with state lock and state."""
    server = MagicMock(spec=SocketServer)
    server._state_lock = threading.Lock()
    server._runner_state = RunnerState.RUNNING
    server._runner_state_data = {}
    return server


@pytest.fixture
def handler(project_root: Path, mock_cancel_ctx: MagicMock, mock_server: MagicMock) -> CommandHandlerImpl:
    """Create a CommandHandlerImpl with mocked dependencies."""
    h = CommandHandlerImpl(
        project_root=project_root,
        cancel_ctx=mock_cancel_ctx,
    )
    h.set_server(mock_server)
    return h


@pytest.fixture
def state_yaml(project_root: Path) -> Path:
    """Create a valid state.yaml for pause validation."""
    state_dir = project_root / ".bmad-assist"
    state_dir.mkdir(exist_ok=True)
    state_path = state_dir / "state.yaml"
    state_path.write_text(
        "current_epic: 29\n"
        "current_story: '29.5'\n"
        "current_phase: dev_story\n"
    )
    return state_path


@pytest.fixture
def sock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create and monkeypatch socket directory for integration tests."""
    d = tmp_path / "sockets"
    d.mkdir(mode=0o700)
    monkeypatch.setattr("bmad_assist.ipc.server.get_socket_dir", lambda: d)
    return d


@pytest.fixture
def sock_path(sock_dir: Path) -> Path:
    """Socket path within the test socket directory."""
    return sock_dir / "test.sock"


# ============================================================================
# Unit Tests: CommandHandlerImpl dispatch (Task 10)
# ============================================================================


class TestCommandDispatch:
    """Test __call__ routing and error wrapping."""

    async def test_dispatches_to_correct_handler(
        self, handler: CommandHandlerImpl, state_yaml: Path
    ) -> None:
        """__call__ routes 'pause' to _handle_pause."""
        with patch.object(handler, "_get_state_path", return_value=state_yaml):
            response = await handler("pause", {}, "req-1")
        assert response["id"] == "req-1"
        assert "result" in response

    async def test_unknown_method_returns_method_not_found(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Unknown methods return METHOD_NOT_FOUND error."""
        response = await handler("nonexistent_method", {}, "req-2")
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.METHOD_NOT_FOUND.code

    async def test_internal_exception_wrapped_in_error(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Internal exceptions are wrapped in INTERNAL_ERROR response."""
        with patch.object(
            handler, "_handle_pause", side_effect=RuntimeError("boom")
        ):
            response = await handler("pause", {}, "req-3")
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.INTERNAL_ERROR.code
        assert "boom" in response["error"]["data"]["message"]


# ============================================================================
# Unit Tests: pause command (Task 10)
# ============================================================================


class TestPauseCommand:
    """Test _handle_pause behavior."""

    async def test_pause_success_creates_flag(
        self, handler: CommandHandlerImpl, project_root: Path, state_yaml: Path
    ) -> None:
        """Successful pause creates pause.flag and returns PauseResult."""
        with patch.object(handler, "_get_state_path", return_value=state_yaml):
            response = await handler("pause", {}, 1)
        assert response["result"]["status"] == "paused"
        assert response["result"]["was_already"] is False
        assert (project_root / ".bmad-assist" / "pause.flag").exists()

    async def test_pause_already_paused(
        self, handler: CommandHandlerImpl, mock_server: MagicMock
    ) -> None:
        """Pause when already PAUSED returns was_already=True."""
        mock_server._runner_state = RunnerState.PAUSED
        response = await handler("pause", {}, 2)
        assert response["result"]["status"] == "paused"
        assert response["result"]["was_already"] is True

    async def test_pause_from_idle_returns_invalid_state(
        self, handler: CommandHandlerImpl, mock_server: MagicMock
    ) -> None:
        """Pause from IDLE state returns INVALID_STATE error."""
        mock_server._runner_state = RunnerState.IDLE
        response = await handler("pause", {}, 3)
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.INVALID_STATE.code
        assert "idle" in response["error"]["data"]["message"]

    async def test_pause_from_stopping_returns_invalid_state(
        self, handler: CommandHandlerImpl, mock_server: MagicMock
    ) -> None:
        """Pause from STOPPING state returns INVALID_STATE error."""
        mock_server._runner_state = RunnerState.STOPPING
        response = await handler("pause", {}, 4)
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.INVALID_STATE.code

    async def test_pause_state_validation_failure(
        self, handler: CommandHandlerImpl, project_root: Path
    ) -> None:
        """Pause when state validation fails returns INVALID_STATE."""
        # No valid state.yaml, so validate_state_for_pause returns False
        bad_state = project_root / ".bmad-assist" / "state.yaml"
        bad_state.write_text("invalid: yaml\n")
        with patch.object(handler, "_get_state_path", return_value=bad_state):
            response = await handler("pause", {}, 5)
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.INVALID_STATE.code


# ============================================================================
# Unit Tests: resume command (Task 10)
# ============================================================================


class TestResumeCommand:
    """Test _handle_resume behavior."""

    async def test_resume_success_removes_flag(
        self, handler: CommandHandlerImpl, project_root: Path, mock_server: MagicMock
    ) -> None:
        """Successful resume removes pause.flag and returns ResumeResult."""
        mock_server._runner_state = RunnerState.PAUSED
        pause_flag = project_root / ".bmad-assist" / "pause.flag"
        pause_flag.touch()

        response = await handler("resume", {}, 1)
        assert response["result"]["status"] == "running"
        assert response["result"]["was_already"] is False
        assert not pause_flag.exists()

    async def test_resume_already_running(
        self, handler: CommandHandlerImpl, mock_server: MagicMock
    ) -> None:
        """Resume when already RUNNING and no pause.flag returns was_already=True."""
        mock_server._runner_state = RunnerState.RUNNING
        response = await handler("resume", {}, 2)
        assert response["result"]["status"] == "running"
        assert response["result"]["was_already"] is True

    async def test_resume_from_idle_returns_invalid_state(
        self, handler: CommandHandlerImpl, mock_server: MagicMock
    ) -> None:
        """Resume from IDLE returns INVALID_STATE error."""
        mock_server._runner_state = RunnerState.IDLE
        response = await handler("resume", {}, 3)
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.INVALID_STATE.code

    async def test_resume_from_stopping_returns_invalid_state(
        self, handler: CommandHandlerImpl, mock_server: MagicMock
    ) -> None:
        """Resume from STOPPING returns INVALID_STATE error."""
        mock_server._runner_state = RunnerState.STOPPING
        response = await handler("resume", {}, 4)
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.INVALID_STATE.code


# ============================================================================
# Unit Tests: stop command (Task 10)
# ============================================================================


class TestStopCommand:
    """Test _handle_stop behavior."""

    async def test_stop_from_running_calls_cancel(
        self, handler: CommandHandlerImpl, mock_cancel_ctx: MagicMock, mock_server: MagicMock
    ) -> None:
        """Stop from RUNNING calls request_cancel() on CancellationContext."""
        mock_server._runner_state = RunnerState.RUNNING
        response = await handler("stop", {}, 1)
        assert response["result"]["status"] == "stopping"
        assert response["result"]["was_already"] is False
        mock_cancel_ctx.request_cancel.assert_called_once()

    async def test_stop_from_paused_creates_flag_and_cancels(
        self, handler: CommandHandlerImpl, project_root: Path,
        mock_cancel_ctx: MagicMock, mock_server: MagicMock
    ) -> None:
        """Stop from PAUSED creates stop.flag AND calls request_cancel()."""
        mock_server._runner_state = RunnerState.PAUSED
        response = await handler("stop", {}, 2)
        assert response["result"]["status"] == "stopping"
        assert response["result"]["was_already"] is False
        assert (project_root / ".bmad-assist" / "stop.flag").exists()
        mock_cancel_ctx.request_cancel.assert_called_once()

    async def test_stop_from_idle_returns_was_already(
        self, handler: CommandHandlerImpl, mock_server: MagicMock
    ) -> None:
        """Stop from IDLE returns was_already=True."""
        mock_server._runner_state = RunnerState.IDLE
        response = await handler("stop", {}, 3)
        assert response["result"]["status"] == "idle"
        assert response["result"]["was_already"] is True

    async def test_stop_from_stopping_returns_was_already(
        self, handler: CommandHandlerImpl, mock_server: MagicMock
    ) -> None:
        """Stop from STOPPING returns was_already=True."""
        mock_server._runner_state = RunnerState.STOPPING
        response = await handler("stop", {}, 4)
        assert response["result"]["status"] == "stopping"
        assert response["result"]["was_already"] is True

    async def test_stop_without_cancel_ctx(
        self, project_root: Path, mock_server: MagicMock
    ) -> None:
        """Stop without cancel_ctx still creates stop.flag for paused runner."""
        h = CommandHandlerImpl(project_root=project_root, cancel_ctx=None)
        h.set_server(mock_server)
        mock_server._runner_state = RunnerState.PAUSED

        response = await h("stop", {}, 5)
        assert response["result"]["status"] == "stopping"
        assert (project_root / ".bmad-assist" / "stop.flag").exists()


# ============================================================================
# Unit Tests: set_log_level command (Task 10)
# ============================================================================


class TestSetLogLevelCommand:
    """Test _handle_set_log_level behavior."""

    async def test_set_debug_via_update_log_level(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Setting DEBUG uses update_log_level() and returns changed=True."""
        # Start from WARNING to ensure change is detected
        logging.getLogger().setLevel(logging.WARNING)
        response = await handler("set_log_level", {"level": "DEBUG"}, 1)
        assert response["result"]["level"] == "DEBUG"
        assert response["result"]["changed"] is True
        assert logging.getLogger().level == logging.DEBUG

    async def test_set_info_via_update_log_level(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Setting INFO via update_log_level() works."""
        logging.getLogger().setLevel(logging.WARNING)
        response = await handler("set_log_level", {"level": "INFO"}, 2)
        assert response["result"]["level"] == "INFO"
        assert response["result"]["changed"] is True

    async def test_set_warning_via_update_log_level(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Setting WARNING via update_log_level() works."""
        logging.getLogger().setLevel(logging.DEBUG)
        response = await handler("set_log_level", {"level": "WARNING"}, 3)
        assert response["result"]["level"] == "WARNING"
        assert response["result"]["changed"] is True

    async def test_set_error_direct(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Setting ERROR bypasses update_log_level and sets directly."""
        logging.getLogger().setLevel(logging.WARNING)
        response = await handler("set_log_level", {"level": "ERROR"}, 4)
        assert response["result"]["level"] == "ERROR"
        assert response["result"]["changed"] is True
        assert logging.getLogger().level == logging.ERROR

    async def test_set_critical_direct(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Setting CRITICAL bypasses update_log_level and sets directly."""
        logging.getLogger().setLevel(logging.WARNING)
        response = await handler("set_log_level", {"level": "CRITICAL"}, 5)
        assert response["result"]["level"] == "CRITICAL"
        assert response["result"]["changed"] is True
        assert logging.getLogger().level == logging.CRITICAL

    async def test_same_level_returns_changed_false(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Setting same level returns changed=False."""
        logging.getLogger().setLevel(logging.WARNING)
        # Need to also reset the module-level tracker in cli_utils
        with patch("bmad_assist.cli_utils._current_log_level", "WARNING"):
            response = await handler("set_log_level", {"level": "WARNING"}, 6)
        assert response["result"]["changed"] is False

    async def test_invalid_level_returns_invalid_params(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Invalid log level returns INVALID_PARAMS error."""
        response = await handler("set_log_level", {"level": "VERBOSE"}, 7)
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.INVALID_PARAMS.code

    async def test_missing_level_param_returns_invalid_params(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Missing 'level' parameter returns INVALID_PARAMS error."""
        response = await handler("set_log_level", {}, 8)
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.INVALID_PARAMS.code


# ============================================================================
# Unit Tests: reload_config command (Task 10)
# ============================================================================


class TestReloadConfigCommand:
    """Test _handle_reload_config behavior."""

    async def test_reload_success(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Successful reload returns ReloadConfigResult(reloaded=True)."""
        with patch(
            "bmad_assist.core.config.loaders.reload_config"
        ) as mock_reload:
            response = await handler("reload_config", {}, 1)
        assert response["result"]["reloaded"] is True
        assert response["result"]["changes"] == []
        mock_reload.assert_called_once()

    async def test_reload_config_error_returns_config_invalid(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Config validation failure returns CONFIG_INVALID error."""
        with patch(
            "bmad_assist.core.config.loaders.reload_config",
            side_effect=ConfigError("Invalid YAML: bad key"),
        ):
            response = await handler("reload_config", {}, 2)
        assert "error" in response
        assert response["error"]["code"] == ErrorCode.CONFIG_INVALID.code
        assert "Invalid YAML" in response["error"]["data"]["message"]

    async def test_reload_config_returns_changes_when_config_differs(
        self, handler: CommandHandlerImpl
    ) -> None:
        """AC #5: reload_config returns populated changes list when config differs."""
        old_mock = MagicMock()
        old_mock.model_dump.return_value = {"loop": {"story": ["a"]}, "providers": {}}

        new_mock = MagicMock()
        new_mock.model_dump.return_value = {"loop": {"story": ["a", "b"]}, "providers": {}}

        with patch(
            "bmad_assist.core.config.get_config", side_effect=[old_mock, new_mock]
        ):
            with patch("bmad_assist.core.config.loaders.reload_config"):
                response = await handler("reload_config", {}, 10)

        result = response["result"]
        assert result["reloaded"] is True
        assert any(
            c["key"] == "loop" and c["action"] == "changed"
            for c in result["changes"]
        )

    async def test_reload_config_empty_changes_when_config_same(
        self, handler: CommandHandlerImpl
    ) -> None:
        """AC #5: reload_config returns empty changes when config unchanged."""
        config_dict = {"loop": {"story": ["a"]}, "providers": {}}
        config_mock = MagicMock()
        config_mock.model_dump.return_value = config_dict

        with patch(
            "bmad_assist.core.config.get_config", return_value=config_mock
        ):
            with patch("bmad_assist.core.config.loaders.reload_config"):
                response = await handler("reload_config", {}, 11)

        result = response["result"]
        assert result["reloaded"] is True
        assert result["changes"] == []
        assert result["ignored"] == []
        assert result["warnings"] == []

    async def test_reload_config_ignored_for_restart_required_keys(
        self, handler: CommandHandlerImpl
    ) -> None:
        """AC #5: reload_config populates ignored list for restart-required keys."""
        old_mock = MagicMock()
        old_mock.model_dump.return_value = {
            "providers": {"master": {"provider": "claude"}},
            "state_path": "old_path",
            "loop": {},
        }

        new_mock = MagicMock()
        new_mock.model_dump.return_value = {
            "providers": {"master": {"provider": "gemini"}},
            "state_path": "new_path",
            "loop": {},
        }

        with patch(
            "bmad_assist.core.config.get_config", side_effect=[old_mock, new_mock]
        ):
            with patch("bmad_assist.core.config.loaders.reload_config"):
                response = await handler("reload_config", {}, 12)

        result = response["result"]
        assert result["reloaded"] is True
        # Both providers and state_path changed — should be in ignored
        assert len(result["ignored"]) == 2
        ignored_keys = {i["key"] for i in result["ignored"]}
        assert "providers" in ignored_keys
        assert "state_path" in ignored_keys
        for item in result["ignored"]:
            assert item["reason"] == "requires_restart"
        # No non-restart changes
        assert result["changes"] == []


# ============================================================================
# Unit Tests: Idempotency (Task 10.23)
# ============================================================================


class TestIdempotency:
    """Test all commands are idempotent."""

    async def test_pause_idempotent(
        self, handler: CommandHandlerImpl, mock_server: MagicMock
    ) -> None:
        """Repeated pause when already paused produces same result."""
        mock_server._runner_state = RunnerState.PAUSED
        r1 = await handler("pause", {}, 1)
        r2 = await handler("pause", {}, 2)
        assert r1["result"] == r2["result"]
        assert r1["result"]["was_already"] is True

    async def test_resume_idempotent(
        self, handler: CommandHandlerImpl, mock_server: MagicMock
    ) -> None:
        """Repeated resume when already running produces same result."""
        mock_server._runner_state = RunnerState.RUNNING
        r1 = await handler("resume", {}, 1)
        r2 = await handler("resume", {}, 2)
        assert r1["result"] == r2["result"]
        assert r1["result"]["was_already"] is True

    async def test_stop_idempotent(
        self, handler: CommandHandlerImpl, mock_server: MagicMock
    ) -> None:
        """Repeated stop when already stopping produces same result."""
        mock_server._runner_state = RunnerState.STOPPING
        r1 = await handler("stop", {}, 1)
        r2 = await handler("stop", {}, 2)
        assert r1["result"] == r2["result"]
        assert r1["result"]["was_already"] is True

    async def test_set_log_level_idempotent(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Repeated set_log_level with same level returns changed=False."""
        logging.getLogger().setLevel(logging.ERROR)
        r1 = await handler("set_log_level", {"level": "ERROR"}, 1)
        r2 = await handler("set_log_level", {"level": "ERROR"}, 2)
        # Both should report changed=False (already at ERROR)
        assert r2["result"]["changed"] is False

    async def test_reload_config_idempotent(
        self, handler: CommandHandlerImpl
    ) -> None:
        """Repeated reload_config is safe."""
        with patch("bmad_assist.core.config.loaders.reload_config"):
            r1 = await handler("reload_config", {}, 1)
            r2 = await handler("reload_config", {}, 2)
        assert r1["result"]["reloaded"] is True
        assert r2["result"]["reloaded"] is True


# ============================================================================
# Integration Tests: Real SocketServer + SocketClient (Task 11)
# ============================================================================


class TestCommandsIntegration:
    """Integration tests with real server, handler, and client."""

    async def test_client_pause_creates_flag(
        self, project_root: Path, sock_path: Path, mock_cancel_ctx: MagicMock
    ) -> None:
        """Client sends pause -> pause.flag created, receives PauseResult."""
        # Create valid state.yaml
        state_path = project_root / ".bmad-assist" / "state.yaml"
        state_path.write_text(
            "current_epic: 29\ncurrent_story: '29.5'\ncurrent_phase: dev_story\n"
        )

        handler = CommandHandlerImpl(
            project_root=project_root, cancel_ctx=mock_cancel_ctx
        )
        server = SocketServer(
            socket_path=sock_path, project_root=project_root, handler=handler
        )
        handler.set_server(server)
        server.update_runner_state(RunnerState.RUNNING, {})

        await server.start()
        try:
            # Patch get_state_path to use our test state.yaml
            with patch.object(handler, "_get_state_path", return_value=state_path):
                client = SocketClient(sock_path, auto_reconnect=False)
                await client.connect()
                try:
                    result = await client.pause()
                    assert result.status == "paused"
                    assert result.was_already is False
                    assert (project_root / ".bmad-assist" / "pause.flag").exists()
                finally:
                    await client.disconnect()
        finally:
            await server.stop()

    async def test_client_resume_removes_flag(
        self, project_root: Path, sock_path: Path, mock_cancel_ctx: MagicMock
    ) -> None:
        """Client sends resume -> pause.flag removed, receives ResumeResult."""
        pause_flag = project_root / ".bmad-assist" / "pause.flag"
        pause_flag.touch()

        handler = CommandHandlerImpl(
            project_root=project_root, cancel_ctx=mock_cancel_ctx
        )
        server = SocketServer(
            socket_path=sock_path, project_root=project_root, handler=handler
        )
        handler.set_server(server)
        server.update_runner_state(RunnerState.PAUSED, {})

        await server.start()
        try:
            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect()
            try:
                result = await client.resume()
                assert result.status == "running"
                assert result.was_already is False
                assert not pause_flag.exists()
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    async def test_client_stop_triggers_cancellation(
        self, project_root: Path, sock_path: Path, mock_cancel_ctx: MagicMock
    ) -> None:
        """Client sends stop -> cancel_ctx.request_cancel() called."""
        handler = CommandHandlerImpl(
            project_root=project_root, cancel_ctx=mock_cancel_ctx
        )
        server = SocketServer(
            socket_path=sock_path, project_root=project_root, handler=handler
        )
        handler.set_server(server)
        server.update_runner_state(RunnerState.RUNNING, {})

        await server.start()
        try:
            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect()
            try:
                result = await client.stop()
                assert result.status == "stopping"
                mock_cancel_ctx.request_cancel.assert_called_once()
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    async def test_client_set_log_level_debug(
        self, project_root: Path, sock_path: Path, mock_cancel_ctx: MagicMock
    ) -> None:
        """Client sends set_log_level(DEBUG) -> root logger level changes."""
        logging.getLogger().setLevel(logging.WARNING)

        handler = CommandHandlerImpl(
            project_root=project_root, cancel_ctx=mock_cancel_ctx
        )
        server = SocketServer(
            socket_path=sock_path, project_root=project_root, handler=handler
        )
        handler.set_server(server)
        server.update_runner_state(RunnerState.RUNNING, {})

        await server.start()
        try:
            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect()
            try:
                result = await client.set_log_level("DEBUG")
                assert result.level == "DEBUG"
                assert result.changed is True
                assert logging.getLogger().level == logging.DEBUG
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    async def test_client_set_log_level_error(
        self, project_root: Path, sock_path: Path, mock_cancel_ctx: MagicMock
    ) -> None:
        """Client sends set_log_level(ERROR) -> root logger level changes."""
        logging.getLogger().setLevel(logging.WARNING)

        handler = CommandHandlerImpl(
            project_root=project_root, cancel_ctx=mock_cancel_ctx
        )
        server = SocketServer(
            socket_path=sock_path, project_root=project_root, handler=handler
        )
        handler.set_server(server)
        server.update_runner_state(RunnerState.RUNNING, {})

        await server.start()
        try:
            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect()
            try:
                result = await client.set_log_level("ERROR")
                assert result.level == "ERROR"
                assert result.changed is True
                assert logging.getLogger().level == logging.ERROR
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    async def test_client_unknown_method(
        self, project_root: Path, sock_path: Path, mock_cancel_ctx: MagicMock
    ) -> None:
        """Client sends unknown method -> receives METHOD_NOT_FOUND error."""
        handler = CommandHandlerImpl(
            project_root=project_root, cancel_ctx=mock_cancel_ctx
        )
        server = SocketServer(
            socket_path=sock_path, project_root=project_root, handler=handler
        )
        handler.set_server(server)

        await server.start()
        try:
            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect()
            try:
                with pytest.raises(IPCCommandError) as exc_info:
                    await client.send_command("nonexistent")
                assert exc_info.value.code == ErrorCode.METHOD_NOT_FOUND.code
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    async def test_client_pause_when_idle(
        self, project_root: Path, sock_path: Path, mock_cancel_ctx: MagicMock
    ) -> None:
        """Client sends pause when IDLE -> receives INVALID_STATE error."""
        handler = CommandHandlerImpl(
            project_root=project_root, cancel_ctx=mock_cancel_ctx
        )
        server = SocketServer(
            socket_path=sock_path, project_root=project_root, handler=handler
        )
        handler.set_server(server)
        server.update_runner_state(RunnerState.IDLE, {})

        await server.start()
        try:
            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect()
            try:
                with pytest.raises(IPCCommandError) as exc_info:
                    await client.pause()
                assert exc_info.value.code == ErrorCode.INVALID_STATE.code
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    async def test_client_invalid_log_level(
        self, project_root: Path, sock_path: Path, mock_cancel_ctx: MagicMock
    ) -> None:
        """Client sends set_log_level with invalid level -> INVALID_PARAMS."""
        handler = CommandHandlerImpl(
            project_root=project_root, cancel_ctx=mock_cancel_ctx
        )
        server = SocketServer(
            socket_path=sock_path, project_root=project_root, handler=handler
        )
        handler.set_server(server)

        await server.start()
        try:
            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect()
            try:
                with pytest.raises(IPCCommandError) as exc_info:
                    await client.send_command("set_log_level", {"level": "VERBOSE"})
                assert exc_info.value.code == ErrorCode.INVALID_PARAMS.code
            finally:
                await client.disconnect()
        finally:
            await server.stop()

    async def test_full_pause_resume_roundtrip(
        self, project_root: Path, sock_path: Path, mock_cancel_ctx: MagicMock
    ) -> None:
        """Full round-trip: pause -> verify paused -> resume -> verify running."""
        state_path = project_root / ".bmad-assist" / "state.yaml"
        state_path.write_text(
            "current_epic: 29\ncurrent_story: '29.5'\ncurrent_phase: dev_story\n"
        )

        handler = CommandHandlerImpl(
            project_root=project_root, cancel_ctx=mock_cancel_ctx
        )
        server = SocketServer(
            socket_path=sock_path, project_root=project_root, handler=handler
        )
        handler.set_server(server)
        server.update_runner_state(RunnerState.RUNNING, {})

        await server.start()
        try:
            with patch.object(handler, "_get_state_path", return_value=state_path):
                client = SocketClient(sock_path, auto_reconnect=False)
                await client.connect()
                try:
                    # Step 1: Pause
                    pause_result = await client.pause()
                    assert pause_result.status == "paused"
                    assert (project_root / ".bmad-assist" / "pause.flag").exists()

                    # Update server state to simulate main loop detecting pause
                    server.update_runner_state(RunnerState.PAUSED, {})

                    # Step 2: Resume
                    resume_result = await client.resume()
                    assert resume_result.status == "running"
                    assert not (project_root / ".bmad-assist" / "pause.flag").exists()
                finally:
                    await client.disconnect()
        finally:
            await server.stop()

    async def test_server_without_handler_returns_internal_error(
        self, sock_path: Path
    ) -> None:
        """Server without handler returns INTERNAL_ERROR for supported methods."""
        server = SocketServer(
            socket_path=sock_path,
            project_root=sock_path.parent.parent,
            handler=None,
        )
        await server.start()
        try:
            client = SocketClient(sock_path, auto_reconnect=False)
            await client.connect()
            try:
                with pytest.raises(IPCCommandError) as exc_info:
                    await client.pause()
                assert exc_info.value.code == ErrorCode.INTERNAL_ERROR.code
            finally:
                await client.disconnect()
        finally:
            await server.stop()
