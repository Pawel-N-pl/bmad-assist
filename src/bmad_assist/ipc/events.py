"""IPC event emission for real-time loop monitoring.

Story 29.4: EventEmitter bridges the synchronous run_loop() with the async
IPC broadcast infrastructure. IPCLogHandler forwards Python log records
as IPC log events.

Three event distribution systems coexist independently:
- _dispatch_event()    → External notifications (Slack, webhooks)
- dashboard emit_*()   → Dashboard stdout markers (DASHBOARD_EVENT:)
- EventEmitter.emit()  → IPC socket clients (TUI, debug scripts)
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from bmad_assist.ipc.protocol import EVENT_RATE_LIMIT
from bmad_assist.ipc.types import RunnerState

if TYPE_CHECKING:
    from bmad_assist.core.types import EpicId
    from bmad_assist.ipc.server import IPCServerThread

__all__ = [
    "EventEmitter",
    "IPCLogHandler",
]

logger = logging.getLogger(__name__)

# Logger name for this module — used to prevent infinite recursion
# when rate-limit warnings are captured by IPCLogHandler.
_INTERNAL_LOGGER_NAME = "bmad_assist.ipc.events"


class EventEmitter:
    """Lightweight, thread-safe event emitter for IPC broadcast.

    Wraps IPCServerThread.make_event() + broadcast_threadsafe() to provide
    typed emit methods for each event type. All methods are fire-and-forget
    and never raise exceptions.

    If the server reference is None, all methods are silent no-ops
    (graceful degradation when IPC is disabled).

    Args:
        server: IPCServerThread instance or None for no-op mode.

    """

    def __init__(self, server: IPCServerThread | None) -> None:
        self._server = server
        self._prev_runner_state: RunnerState | None = None
        self._goodbye_sent: bool = False  # Suppress events after goodbye

        # Rate limiting state for log events (AC #4)
        self._rate_limit_lock = threading.Lock()
        self._log_count: int = 0
        self._log_window_start: float = time.monotonic()
        self._log_dropped: int = 0

        # Metrics thread state (AC #9)
        self._metrics_thread: threading.Thread | None = None
        self._metrics_stop: threading.Event = threading.Event()
        self._metrics_interval: float = 10.0
        self._state_getter: Callable[[], dict[str, Any]] | None = None

    # -----------------------------------------------------------------
    # Core emit — fire-and-forget
    # -----------------------------------------------------------------

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Create and broadcast an IPC event. Never raises.

        After a goodbye event has been sent, all subsequent emissions are
        suppressed to ensure goodbye is the last event clients see.

        Args:
            event_type: Event type string (e.g., "phase_started").
            data: Event payload dict matching the corresponding Pydantic model.

        """
        if self._server is None:
            return
        if self._goodbye_sent and event_type != "goodbye":
            return  # Suppress post-goodbye events
        try:
            event = self._server.make_event(event_type, data)
            self._server.broadcast_threadsafe(event)
        except Exception:
            pass  # Fire-and-forget: never block the main loop

    # -----------------------------------------------------------------
    # Typed emit methods
    # -----------------------------------------------------------------

    def emit_phase_started(
        self,
        phase: str,
        epic_id: EpicId | None,
        story_id: str | None,
    ) -> None:
        """Emit a phase_started event.

        Args:
            phase: Phase identifier (e.g., "create_story").
            epic_id: Current epic identifier (int or str).
            story_id: Current story identifier.

        """
        self.emit("phase_started", {
            "phase": phase,
            "epic_id": epic_id,
            "story_id": story_id,
        })

    def emit_phase_completed(
        self,
        phase: str,
        epic_id: EpicId | None,
        story_id: str | None,
        duration_seconds: float,
    ) -> None:
        """Emit a phase_completed event.

        Args:
            phase: Phase identifier that completed.
            epic_id: Epic identifier.
            story_id: Story identifier.
            duration_seconds: Wall-clock phase duration in seconds.

        """
        self.emit("phase_completed", {
            "phase": phase,
            "epic_id": epic_id,
            "story_id": story_id,
            "duration_seconds": duration_seconds,
        })

    def emit_log(
        self,
        level: str,
        message: str,
        logger_name: str | None,
    ) -> None:
        """Emit a log event with rate limiting.

        Only log events are rate-limited (max EVENT_RATE_LIMIT per second).
        Uses a re-entrancy guard to prevent infinite recursion when the
        rate-limit warning itself is captured by IPCLogHandler.

        Args:
            level: Log level string (e.g., "WARNING").
            message: Log message text.
            logger_name: Name of the logger that emitted the record.

        """
        if self._server is None:
            return

        # Re-entrancy guard: never process our own internal log records
        # to prevent IPCLogHandler → emit_log → logger.warning → IPCLogHandler loop
        if logger_name == _INTERNAL_LOGGER_NAME:
            return

        with self._rate_limit_lock:
            now = time.monotonic()
            if now - self._log_window_start >= 1.0:
                # New 1-second window
                self._log_window_start = now
                self._log_count = 0

            if self._log_count >= EVENT_RATE_LIMIT:
                self._log_dropped += 1
                if self._log_dropped % 100 == 0:
                    logger.warning(
                        "IPC log rate limit: dropped %d events", self._log_dropped
                    )
                return

            self._log_count += 1

        self.emit("log", {
            "level": level,
            "message": message,
            "logger": logger_name,
        })

    def emit_state_changed(
        self,
        field: str,
        old_value: Any,
        new_value: Any,
    ) -> None:
        """Emit a state_changed event.

        Args:
            field: Name of the state field that changed.
            old_value: Previous value (must be JSON-serializable).
            new_value: New value (must be JSON-serializable).

        """
        self.emit("state_changed", {
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
        })

    def emit_metrics(
        self,
        llm_sessions: int,
        elapsed_seconds: float,
        phase: str | None,
        pause_state: bool,
    ) -> None:
        """Emit a metrics snapshot event.

        Args:
            llm_sessions: Total LLM sessions invoked so far.
            elapsed_seconds: Total elapsed run time in seconds.
            phase: Currently executing phase, if any.
            pause_state: True if runner is currently paused.

        """
        self.emit("metrics", {
            "llm_sessions": llm_sessions,
            "elapsed_seconds": elapsed_seconds,
            "phase": phase,
            "pause_state": pause_state,
        })

    def emit_goodbye(
        self,
        reason: Literal["normal", "stop_command", "error"],
        message: str | None = None,
    ) -> None:
        """Emit a goodbye (shutdown) event.

        Broadcast before IPC server shutdown to notify connected clients
        of graceful disconnection. Fire-and-forget: never raises.

        Args:
            reason: Shutdown reason ("normal", "stop_command", or "error").
            message: Optional human-readable message (e.g., error description).

        """
        self._goodbye_sent = True  # Suppress all subsequent events
        self.emit("goodbye", {
            "reason": reason,
            "message": message,
        })

    def emit_error(
        self,
        code: int,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit an error event.

        Args:
            code: Numeric error code (from ErrorCode enum).
            message: Human-readable error description.
            data: Additional error context.

        """
        self.emit("error", {
            "code": code,
            "message": message,
            "data": data,
        })

    # -----------------------------------------------------------------
    # State tracking with change detection
    # -----------------------------------------------------------------

    def update_state(
        self,
        state: RunnerState,
        state_data: dict[str, Any],
    ) -> None:
        """Update runner state and auto-emit state_changed on transitions.

        Forwards to IPCServerThread.update_state() for get_state queries,
        and emits a state_changed event when RunnerState changes.

        Args:
            state: New RunnerState value.
            state_data: State data dict matching GetStateResult schema.

        """
        if self._server is None:
            return

        old_state = self._prev_runner_state
        self._server.update_state(state, state_data)

        if old_state is not None and old_state != state:
            self.emit_state_changed("state", old_state.value, state.value)

        self._prev_runner_state = state

    # -----------------------------------------------------------------
    # Metrics background thread
    # -----------------------------------------------------------------

    def start_metrics(
        self,
        interval: float = 10.0,
        state_getter: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        """Start the periodic metrics emission thread.

        Args:
            interval: Seconds between metric snapshots (default 10s).
            state_getter: Callback returning current metrics dict with keys
                ``llm_sessions``, ``elapsed_seconds``, ``phase``, ``pause_state``.

        """
        if self._server is None:
            return

        self._metrics_interval = interval
        self._state_getter = state_getter
        self._metrics_stop.clear()

        self._metrics_thread = threading.Thread(
            target=self._metrics_loop,
            name="ipc-metrics",
            daemon=True,
        )
        self._metrics_thread.start()

    def stop_metrics(self) -> None:
        """Stop the metrics emission thread."""
        self._metrics_stop.set()
        if self._metrics_thread is not None:
            self._metrics_thread.join(timeout=5.0)
            self._metrics_thread = None

    def _metrics_loop(self) -> None:
        """Background thread: emit metrics at configured interval.

        Also refreshes the server's cached state_data so that get_state
        returns current elapsed_seconds, llm_sessions, and phase info.
        """
        while not self._metrics_stop.wait(timeout=self._metrics_interval):
            try:
                if self._state_getter is not None:
                    data = self._state_getter()
                    self.emit_metrics(**{
                        k: data[k] for k in ("llm_sessions", "elapsed_seconds", "phase", "pause_state")
                    })
                    # Refresh server cache so get_state returns fresh data
                    if self._server is not None:
                        self._server.update_state(None, data)
            except Exception as exc:
                logger.debug("Metrics emission error: %s", exc)


class IPCLogHandler(logging.Handler):
    """Logging handler that forwards log records as IPC log events.

    Converts Python LogRecord objects into IPC log events via EventEmitter.
    Default level is WARNING to avoid flooding the IPC channel.

    The handler MUST NOT raise exceptions — logging infrastructure requires
    silent failure on handler errors.

    Args:
        emitter: EventEmitter instance for event dispatch.
        level: Minimum log level to forward (default WARNING).

    """

    def __init__(self, emitter: EventEmitter, level: int = logging.WARNING) -> None:
        super().__init__(level=level)
        self._emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        """Forward a log record as an IPC log event.

        Args:
            record: Python logging LogRecord.

        """
        try:
            self._emitter.emit_log(
                level=record.levelname,
                message=record.getMessage(),
                logger_name=record.name,
            )
        except Exception:
            pass  # Handler MUST NOT raise
