"""Event bridge mapping IPC events to TUI Renderer Protocol.

Receives raw IPC event params dicts from SocketClient.subscribe() callback
and dispatches to InteractiveRenderer methods with correct field mapping.

Key responsibilities:
- Dispatch on params["type"] to appropriate handler
- Field name mapping (duration_seconds -> duration, etc.)
- Timestamp extraction from EventParams envelope (LogData has no timestamp)
- Seq gap detection with 5s debounce rehydration
- 30 FPS render throttling for log events
- Goodbye-aware reconnection logic
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from bmad_assist.ipc.client import SocketClient
from bmad_assist.ipc.types import RunnerState
from bmad_assist.tui.interactive import InteractiveRenderer
from bmad_assist.tui.status_bar import StatusBar

logger = logging.getLogger(__name__)


class EventBridge:
    """Bridge between IPC events and the TUI Renderer Protocol.

    Subscribes to SocketClient events and dispatches them to the
    InteractiveRenderer and StatusBar with correct field mapping.

    Args:
        renderer: InteractiveRenderer instance for rendering events.
        status_bar: StatusBar instance for metrics/phase updates (may be None).
        client: SocketClient instance for disconnect/get_state calls.
        clock: Injectable clock for deterministic testing (default: time.monotonic).

    """

    def __init__(  # noqa: D107
        self,
        renderer: InteractiveRenderer,
        status_bar: StatusBar | None,
        client: SocketClient,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._renderer = renderer
        self._status_bar = status_bar
        self._client = client
        self._clock = clock

        # Seq tracking (AC-E4)
        self._last_seq: int | None = None
        self._last_rehydration_time: float = 0.0
        self._REHYDRATION_DEBOUNCE: float = 5.0

        # 30 FPS throttle (AC-E5)
        self._last_flush_time: float = 0.0
        self._FLUSH_INTERVAL: float = 1.0 / 30  # ~33ms
        self._log_queue: list[dict[str, Any]] = []
        self._stopped: bool = False

        # Debug callback for session details
        self._on_session_details: Callable[[list[dict[str, Any]]], None] | None = None

        # Context tracking for state_changed events
        self._last_epic_id: int | str | None = None
        self._last_story_id: str | None = None

    def on_event(self, params: dict[str, Any]) -> None:
        """Dispatch IPC event to renderer. Called from SocketClient._dispatch_event().

        Args:
            params: Event params dict with type, seq, data, timestamp fields.

        """
        if self._stopped:
            return

        try:
            event_type = params.get("type", "")

            # Seq gap detection (AC-E4)
            seq = params.get("seq")
            if seq is not None:
                self._check_seq_gap(seq)

            # Dispatch based on event type
            if event_type == "log":
                self._handle_log(params)
            elif event_type == "phase_started":
                self._flush_log_queue()
                self._handle_phase_started(params)
            elif event_type == "phase_completed":
                self._flush_log_queue()
                self._handle_phase_completed(params)
            elif event_type == "state_changed":
                self._flush_log_queue()
                self._handle_state_changed(params)
            elif event_type == "metrics":
                self._handle_metrics(params)
            elif event_type == "goodbye":
                self._flush_log_queue()
                self._handle_goodbye(params)
            elif event_type == "error":
                self._flush_log_queue()
                self._handle_error(params)
            else:
                logger.debug("Unknown event type: %s", event_type)
        except Exception:
            logger.warning("EventBridge.on_event failed", exc_info=True)

    def set_session_details_callback(
        self, callback: Callable[[list[dict[str, Any]]], None]
    ) -> None:
        """Set callback for --debug session detail updates."""
        self._on_session_details = callback

    def flush(self) -> None:
        """Force flush any queued log events."""
        self._flush_log_queue()

    def stop(self) -> None:
        """Mark bridge as stopped, flush remaining events."""
        self._stopped = True
        self._flush_log_queue()

    def reset(self) -> None:
        """Reset state for reconnection."""
        self._last_seq = None
        self._last_epic_id = None
        self._last_story_id = None
        self._log_queue.clear()
        self._stopped = False

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def _handle_log(self, params: dict[str, Any]) -> None:
        """Queue log event for throttled rendering (AC-E5).

        Log events are batched and flushed at max 30 FPS. When >50 events
        are queued between flushes, coalesce to latest 5 + count summary.
        """
        self._log_queue.append(params)

        now = self._clock()
        if now - self._last_flush_time >= self._FLUSH_INTERVAL:
            self._flush_log_queue()

    def _handle_phase_started(self, params: dict[str, Any]) -> None:
        """Map phase_started event to renderer + status bar."""
        data = params.get("data", {})
        phase = data.get("phase", "")
        epic_id = data.get("epic_id")
        story_id = data.get("story_id", "")

        # Update context tracking
        self._last_epic_id = epic_id
        self._last_story_id = story_id

        self._renderer.render_phase_started(phase, epic_id, story_id)

        if self._status_bar is not None:
            self._status_bar.set_phase_info(
                phase, epic_id if epic_id is not None else "", story_id or ""
            )

    def _handle_phase_completed(self, params: dict[str, Any]) -> None:
        """Map phase_completed event to renderer.

        CRITICAL: Maps data["duration_seconds"] -> renderer's duration param.
        """
        data = params.get("data", {})
        phase = data.get("phase", "")
        epic_id = data.get("epic_id")
        story_id = data.get("story_id", "")
        duration = data.get("duration_seconds", 0.0)

        self._renderer.render_phase_completed(phase, epic_id, story_id, duration)

    def _handle_state_changed(self, params: dict[str, Any]) -> None:
        """Polymorphic dispatch on data["field"].

        - field="state" -> renderer.update_status(RunnerState)
        - field="current_phase" -> status_bar.set_phase_info with cached context
        - field="current_story" -> update cached story_id + status_bar
        - other fields -> ignored
        """
        data = params.get("data", {})
        field = data.get("field", "")
        new_value = data.get("new_value")

        if field == "state":
            try:
                state = RunnerState(new_value)
                self._renderer.update_status(state)
            except (ValueError, KeyError):
                logger.debug("Invalid RunnerState value: %s", new_value)
        elif field == "current_phase":
            if self._status_bar is not None and new_value is not None:
                self._status_bar.set_phase_info(
                    new_value,
                    self._last_epic_id if self._last_epic_id is not None else "",
                    self._last_story_id or "",
                )
        elif field == "current_story":
            self._last_story_id = new_value
            if self._status_bar is not None and new_value is not None:
                # Update status bar with current context, keep last known phase
                self._status_bar.set_phase_info(
                    "",
                    self._last_epic_id if self._last_epic_id is not None else "",
                    new_value,
                )
        # Other fields silently ignored

    def _handle_metrics(self, params: dict[str, Any]) -> None:
        """Update status bar with metrics snapshot."""
        if self._status_bar is None:
            return

        data = params.get("data", {})
        llm_sessions = data.get("llm_sessions")
        if llm_sessions is not None:
            self._status_bar.set_llm_sessions(llm_sessions)

        # Keep run elapsed in sync (recalibrate local clock from server data)
        elapsed = data.get("elapsed_seconds")
        if elapsed is not None and elapsed > 0:
            self._status_bar.set_run_start_time(time.monotonic() - elapsed)

        # Debug: forward session details
        session_details = data.get("session_details")
        if session_details is not None and self._on_session_details:
            self._on_session_details(session_details)

    def _handle_goodbye(self, params: dict[str, Any]) -> None:
        """Handle goodbye event with reason-aware reconnection (AC-E2).

        - reason="normal" -> client.disconnect() (terminal, no reconnect)
        - other reasons -> let auto-reconnect handle it
        """
        data = params.get("data", {})
        reason = data.get("reason", "")
        message = data.get("message")

        if reason == "normal":
            # Permanent shutdown — disconnect client (sets CLOSED state)
            logger.info("Runner completed normally, disconnecting")
            # Schedule disconnect on the event loop (we're in a sync callback)
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._client.disconnect())
            except RuntimeError:
                # No running loop — likely in sync test context
                logger.debug("No event loop for disconnect, skipping")
        else:
            # Non-normal shutdown — log and let auto-reconnect handle
            logger.info(
                "Runner goodbye: reason=%s message=%s",
                reason,
                message,
            )

    def _handle_error(self, params: dict[str, Any]) -> None:
        """Display error in scroll region via renderer."""
        data = params.get("data", {})
        code = data.get("code", -1)
        message = data.get("message", "Unknown error")

        # Render error as a log line at ERROR level
        error_text = f"[IPC ERROR {code}] {message}"
        ts = self._parse_timestamp(params)
        self._renderer.render_log("ERROR", error_text, "ipc.error", ts)

    # -----------------------------------------------------------------
    # Seq gap detection (AC-E4)
    # -----------------------------------------------------------------

    def _check_seq_gap(self, seq: int) -> None:
        """Track seq numbers and detect gaps.

        On gap detection, triggers get_state rehydration with 5s debounce.
        """
        if self._last_seq is not None:
            expected = self._last_seq + 1
            if seq != expected:
                logger.warning(
                    "Event sequence gap detected: expected %d, got %d",
                    expected,
                    seq,
                )
                self._trigger_rehydration()

        self._last_seq = seq

    def _trigger_rehydration(self) -> None:
        """Trigger get_state rehydration with 5s debounce."""
        now = self._clock()
        if now - self._last_rehydration_time < self._REHYDRATION_DEBOUNCE:
            logger.debug("Rehydration debounced (within %ss window)", self._REHYDRATION_DEBOUNCE)
            return

        self._last_rehydration_time = now
        logger.info("Triggering state rehydration via get_state")

        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._rehydrate())
        except RuntimeError:
            logger.debug("No event loop for rehydration, skipping")

    async def _rehydrate(self) -> None:
        """Fetch full state from runner and apply to status bar."""
        try:
            state = await self._client.get_state()
            if self._status_bar is not None:
                self._status_bar.set_llm_sessions(state.llm_sessions)
                if state.current_phase is not None:
                    phase_elapsed = getattr(state, "phase_elapsed_seconds", 0.0)
                    self._status_bar.set_phase_info(
                        state.current_phase,
                        state.current_epic if state.current_epic is not None else "",
                        state.current_story or "",
                        elapsed=phase_elapsed,
                    )
                self._status_bar.set_paused(state.paused)
                # Keep run elapsed in sync
                if state.elapsed_seconds > 0:
                    self._status_bar.set_run_start_time(
                        time.monotonic() - state.elapsed_seconds
                    )
            self._renderer.update_status(RunnerState(state.state))
            # Update context tracking
            self._last_epic_id = state.current_epic
            self._last_story_id = state.current_story
        except Exception:
            logger.warning("State rehydration failed", exc_info=True)

    # -----------------------------------------------------------------
    # Log queue flush with throttle (AC-E5)
    # -----------------------------------------------------------------

    def _flush_log_queue(self) -> None:
        """Process queued log events to renderer.

        When >50 events queued, coalesce to latest 5 + count summary.
        """
        if not self._log_queue:
            return

        queue = self._log_queue
        self._log_queue = []
        self._last_flush_time = self._clock()

        if len(queue) > 50:
            # Coalesce: show summary + latest 5
            dropped = len(queue) - 5
            ts = self._parse_timestamp(queue[-1])
            self._renderer.render_log(
                "INFO",
                f"... {dropped} more log lines ...",
                "tui.coalesce",
                ts,
            )
            queue = queue[-5:]

        for params in queue:
            data = params.get("data", {})
            level = data.get("level", "INFO")
            message = data.get("message", "")
            logger_name = data.get("logger", "")
            ts = self._parse_timestamp(params)

            self._renderer.render_log(level, message, logger_name, ts)

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _parse_timestamp(params: dict[str, Any]) -> datetime:
        """Parse ISO 8601 timestamp from event params envelope.

        LogData has NO timestamp field — extract from params["timestamp"].
        Falls back to datetime.now(UTC) if missing or unparseable.
        """
        ts_str = params.get("timestamp")
        if ts_str is None:
            return datetime.now(UTC)
        try:
            return datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            return datetime.now(UTC)
