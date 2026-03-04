"""IPC command handler for bmad-assist runner control.

Story 29.5: Concrete implementation of the CommandHandler protocol.
Wires IPC commands to existing control mechanisms (pause flags,
CancellationContext, config reload, log level control).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from bmad_assist.core.exceptions import ConfigError
from bmad_assist.ipc.protocol import (
    ErrorCode,
    make_error_response,
    make_success_response,
)
from bmad_assist.ipc.types import (
    PauseParams,
    PauseResult,
    ReloadConfigParams,
    ReloadConfigResult,
    ResumeParams,
    ResumeResult,
    RunnerState,
    SetLogLevelParams,
    SetLogLevelResult,
    StopParams,
    StopResult,
)

if TYPE_CHECKING:
    from bmad_assist.core.loop.cancellation import CancellationContext
    from bmad_assist.ipc.server import SocketServer

__all__ = ["CommandHandlerImpl"]

logger = logging.getLogger(__name__)

# Top-level config keys that require process restart to take effect.
# "providers" covers all nested provider changes (e.g., providers.master.provider).
# "state_path" — state file location can't change mid-run.
_RESTART_REQUIRED_KEYS: frozenset[str] = frozenset({"providers", "state_path"})


class CommandHandlerImpl:
    """Concrete IPC command handler for bmad-assist runner control.

    Implements the CommandHandler protocol defined in server.py.
    Wires IPC commands to existing control mechanisms (pause flags,
    CancellationContext, config reload, log level control).
    """

    def __init__(
        self,
        project_root: Path,
        cancel_ctx: CancellationContext | None = None,
    ) -> None:
        self._project_root = project_root
        self._cancel_ctx = cancel_ctx
        self._server: SocketServer | None = None
        self._flag_dir = project_root / ".bmad-assist"

    def set_server(self, server: SocketServer) -> None:
        """Set SocketServer reference for runner state reads.

        Args:
            server: The SocketServer instance to read state from.

        """
        self._server = server

    async def __call__(
        self,
        method: str,
        params: dict[str, Any],
        request_id: str | int,
    ) -> dict[str, Any]:
        """Dispatch command to appropriate handler.

        Args:
            method: JSON-RPC method name.
            params: Method parameters dict.
            request_id: Request ID for response correlation.

        Returns:
            Complete JSON-RPC response dict.

        """
        dispatch = {
            "pause": self._handle_pause,
            "resume": self._handle_resume,
            "stop": self._handle_stop,
            "set_log_level": self._handle_set_log_level,
            "reload_config": self._handle_reload_config,
        }
        handler = dispatch.get(method)
        if handler is None:
            return make_error_response(
                request_id,
                ErrorCode.METHOD_NOT_FOUND,
                data={"method": method},
            )
        try:
            return await handler(params, request_id)
        except Exception as e:
            logger.error("Command %s failed: %s", method, e)
            return make_error_response(
                request_id,
                ErrorCode.INTERNAL_ERROR,
                data={"message": str(e)},
            )

    # -------------------------------------------------------------------------
    # State helpers
    # -------------------------------------------------------------------------

    def _get_runner_state(self) -> RunnerState:
        """Read cached runner state from SocketServer. Thread-safe."""
        if self._server is None:
            return RunnerState.IDLE
        with self._server._state_lock:
            return self._server._runner_state

    def _get_state_path(self) -> Path:
        """Derive state.yaml path from config."""
        from bmad_assist.core.config import get_config
        from bmad_assist.core.state import get_state_path

        config = get_config()
        return get_state_path(config, project_root=self._project_root)

    # -------------------------------------------------------------------------
    # pause
    # -------------------------------------------------------------------------

    async def _handle_pause(
        self, params: dict[str, Any], request_id: str | int
    ) -> dict[str, Any]:
        """Handle pause command.

        Creates pause.flag file to signal the main loop to pause
        at its next safe interrupt point.
        """
        try:
            PauseParams(**params)
        except ValidationError as e:
            return make_error_response(
                request_id,
                ErrorCode.INVALID_PARAMS,
                data={"message": str(e)},
            )

        state = self._get_runner_state()

        # Already paused
        if state == RunnerState.PAUSED:
            result = PauseResult(status="paused", was_already=True)
            return make_success_response(request_id, result.model_dump())

        # Invalid state transitions
        if state in (RunnerState.IDLE, RunnerState.STOPPING):
            return make_error_response(
                request_id,
                ErrorCode.INVALID_STATE,
                data={"message": f"Cannot pause: runner is {state.value}"},
            )

        # Validate state before pause
        from bmad_assist.core.loop.pause import validate_state_for_pause

        state_path = self._get_state_path()
        if not validate_state_for_pause(state_path):
            return make_error_response(
                request_id,
                ErrorCode.INVALID_STATE,
                data={"message": "State is not safe for pause"},
            )

        # Create pause.flag
        self._flag_dir.mkdir(parents=True, exist_ok=True)
        pause_flag = self._flag_dir / "pause.flag"
        pause_flag.touch()

        result = PauseResult(status="paused", was_already=False)
        return make_success_response(request_id, result.model_dump())

    # -------------------------------------------------------------------------
    # resume
    # -------------------------------------------------------------------------

    async def _handle_resume(
        self, params: dict[str, Any], request_id: str | int
    ) -> dict[str, Any]:
        """Handle resume command.

        Removes pause.flag file so wait_for_resume() detects the change.
        """
        try:
            ResumeParams(**params)
        except ValidationError as e:
            return make_error_response(
                request_id,
                ErrorCode.INVALID_PARAMS,
                data={"message": str(e)},
            )

        state = self._get_runner_state()

        # Invalid state transitions
        if state in (RunnerState.IDLE, RunnerState.STOPPING):
            return make_error_response(
                request_id,
                ErrorCode.INVALID_STATE,
                data={"message": f"Cannot resume: runner is {state.value}"},
            )

        # Not paused and no pause flag
        pause_flag = self._flag_dir / "pause.flag"
        if state != RunnerState.PAUSED and not pause_flag.exists():
            result = ResumeResult(status="running", was_already=True)
            return make_success_response(request_id, result.model_dump())

        # Remove pause.flag
        pause_flag.unlink(missing_ok=True)

        result = ResumeResult(status="running", was_already=False)
        return make_success_response(request_id, result.model_dump())

    # -------------------------------------------------------------------------
    # stop
    # -------------------------------------------------------------------------

    async def _handle_stop(
        self, params: dict[str, Any], request_id: str | int
    ) -> dict[str, Any]:
        """Handle stop command.

        Triggers graceful cancellation via CancellationContext and/or
        stop.flag for paused runners.
        """
        try:
            StopParams(**params)
        except ValidationError as e:
            return make_error_response(
                request_id,
                ErrorCode.INVALID_PARAMS,
                data={"message": str(e)},
            )

        state = self._get_runner_state()

        # Already idle
        if state == RunnerState.IDLE:
            result = StopResult(status="idle", was_already=True)
            return make_success_response(request_id, result.model_dump())

        # Already stopping
        if state == RunnerState.STOPPING:
            result = StopResult(status="stopping", was_already=True)
            return make_success_response(request_id, result.model_dump())

        # Paused: create stop.flag AND cancel
        if state == RunnerState.PAUSED:
            self._flag_dir.mkdir(parents=True, exist_ok=True)
            stop_flag = self._flag_dir / "stop.flag"
            stop_flag.touch()
            if self._cancel_ctx is not None:
                self._cancel_ctx.request_cancel()

        # Running: just cancel
        elif state == RunnerState.RUNNING:
            if self._cancel_ctx is not None:
                self._cancel_ctx.request_cancel()

        # Kill all running LLM subprocesses immediately
        from bmad_assist.providers.base import kill_all_child_pgids

        kill_all_child_pgids()

        result = StopResult(status="stopping", was_already=False)
        return {
            "jsonrpc": "2.0",
            "result": result.model_dump(),
            "id": request_id,
        }

    # -------------------------------------------------------------------------
    # set_log_level
    # -------------------------------------------------------------------------

    async def _handle_set_log_level(
        self, params: dict[str, Any], request_id: str | int
    ) -> dict[str, Any]:
        """Handle set_log_level command.

        Changes the Python logging level. Uses update_log_level() for
        DEBUG/INFO/WARNING, and direct setter for ERROR/CRITICAL.
        """
        try:
            params_model = SetLogLevelParams(**params)
        except ValidationError as e:
            return make_error_response(
                request_id,
                ErrorCode.INVALID_PARAMS,
                data={"message": str(e)},
            )

        level = params_model.level
        before_level = logging.getLogger().level

        if level in ("DEBUG", "INFO", "WARNING"):
            from bmad_assist.cli_utils import update_log_level

            update_log_level(level)
        else:
            # ERROR or CRITICAL: set directly (update_log_level doesn't support these)
            log_level = getattr(logging, level)
            root_logger = logging.getLogger()
            root_logger.setLevel(log_level)
            for h in root_logger.handlers:
                h.setLevel(log_level)
            # Keep cli_utils tracker in sync to prevent desync with file-based control
            import bmad_assist.cli_utils as _cli_utils

            _cli_utils._current_log_level = level

        changed = logging.getLogger().level != before_level

        result = SetLogLevelResult(level=level, changed=changed)
        return {
            "jsonrpc": "2.0",
            "result": result.model_dump(),
            "id": request_id,
        }

    # -------------------------------------------------------------------------
    # reload_config
    # -------------------------------------------------------------------------

    async def _handle_reload_config(
        self, params: dict[str, Any], request_id: str | int
    ) -> dict[str, Any]:
        """Handle reload_config command.

        Reloads configuration from disk via atomic singleton swap.
        Compares old and new config at top-level keys to report changes,
        and separates restart-required keys into the ``ignored`` list.
        """
        try:
            ReloadConfigParams(**params)
        except ValidationError as e:
            return make_error_response(
                request_id,
                ErrorCode.INVALID_PARAMS,
                data={"message": str(e)},
            )

        from bmad_assist.core.config import get_config
        from bmad_assist.core.config.loaders import reload_config

        # Snapshot old config before reload
        old_dict = get_config().model_dump(mode="json")

        try:
            reload_config(project_path=self._project_root)
        except ConfigError as e:
            return make_error_response(
                request_id,
                ErrorCode.CONFIG_INVALID,
                data={"message": str(e)},
            )

        # Snapshot new config after reload
        new_dict = get_config().model_dump(mode="json")

        # Compare top-level keys
        changes: list[dict[str, Any]] = []
        ignored: list[dict[str, Any]] = []
        old_keys = set(old_dict.keys())
        new_keys = set(new_dict.keys())

        for key in sorted(old_keys | new_keys):
            if key in old_keys and key not in new_keys:
                action = "removed"
            elif key not in old_keys and key in new_keys:
                action = "added"
            elif old_dict[key] != new_dict[key]:
                action = "changed"
            else:
                continue  # No change for this key

            if key in _RESTART_REQUIRED_KEYS:
                ignored.append({"key": key, "action": action, "reason": "requires_restart"})
            else:
                changes.append({"key": key, "action": action})

        result = ReloadConfigResult(
            reloaded=True,
            changes=changes,
            ignored=ignored,
            warnings=[],
        )
        return {
            "jsonrpc": "2.0",
            "result": result.model_dump(),
            "id": request_id,
        }
