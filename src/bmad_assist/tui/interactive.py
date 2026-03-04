"""InteractiveRenderer - TUI renderer with log filtering (Stories 30.1-30.6).

Stub methods log at DEBUG level and do nothing visible. render_log() and
set_log_level() have real implementations when components are wired via
set_components(). Other methods remain stubs until full components are wired.
"""

from __future__ import annotations

import logging
from datetime import datetime

from bmad_assist.core.types import EpicId
from bmad_assist.ipc.types import RunnerState
from bmad_assist.tui.input import InputHandler
from bmad_assist.tui.layout import LayoutManager
from bmad_assist.tui.log_level import LogLevelToggle
from bmad_assist.tui.status_bar import StatusBar
from bmad_assist.tui.timer import PauseTimer

logger = logging.getLogger("bmad_assist.tui.interactive")


class InteractiveRenderer:
    """TUI renderer with local log level filtering.

    Initially a stub — all methods log a DEBUG message and return.
    When ``set_components()`` wires in a ``LayoutManager`` and
    ``LogLevelToggle``, ``render_log()`` and ``set_log_level()`` gain
    real implementations with local filtering and delegation.

    When full components are wired (status_bar, input_handler, pause_timer),
    ``start()``, ``stop()``, ``render_phase_started()``,
    ``render_phase_completed()``, and ``update_status()`` also gain real
    implementations.
    """

    def __init__(self) -> None:
        self._layout: LayoutManager | None = None
        self._log_level_toggle: LogLevelToggle | None = None
        self._status_bar: StatusBar | None = None
        self._input_handler: InputHandler | None = None
        self._pause_timer: PauseTimer | None = None
        self._started: bool = False

    def set_components(
        self,
        layout: LayoutManager,
        log_toggle: LogLevelToggle,
        status_bar: StatusBar | None = None,
        input_handler: InputHandler | None = None,
        pause_timer: PauseTimer | None = None,
    ) -> None:
        """Wire layout and log toggle for render_log/set_log_level.

        Args:
            layout: LayoutManager for writing to scroll region.
            log_toggle: LogLevelToggle for current filter level.
            status_bar: Optional StatusBar for phase/status display.
            input_handler: Optional InputHandler for keyboard input.
            pause_timer: Optional PauseTimer for pause countdown.
        """
        self._layout = layout
        self._log_level_toggle = log_toggle
        self._status_bar = status_bar
        self._input_handler = input_handler
        self._pause_timer = pause_timer

    def start(self) -> None:
        """Start all wired components. Idempotent."""
        if self._started:
            return
        if self._layout is None and self._status_bar is None:
            logger.debug("InteractiveRenderer.start: not implemented")
            return
        if self._layout is not None:
            self._layout.start()
        if self._status_bar is not None:
            self._status_bar.start()
        if self._input_handler is not None:
            self._input_handler.start()
        if self._pause_timer is not None:
            self._pause_timer.start()
        self._started = True

    def stop(self) -> None:
        """Stop all wired components in reverse order. Idempotent."""
        if not self._started:
            if self._layout is None and self._status_bar is None:
                logger.debug("InteractiveRenderer.stop: not implemented")
            return
        self._started = False
        # Stop in reverse order of start
        if self._pause_timer is not None:
            try:
                self._pause_timer.stop()
            except Exception:
                logger.warning("PauseTimer.stop() failed", exc_info=True)
        if self._input_handler is not None:
            try:
                self._input_handler.stop()
            except Exception:
                logger.warning("InputHandler.stop() failed", exc_info=True)
        if self._status_bar is not None:
            try:
                self._status_bar.stop()
            except Exception:
                logger.warning("StatusBar.stop() failed", exc_info=True)
        if self._layout is not None:
            try:
                self._layout.stop()
            except Exception:
                logger.warning("LayoutManager.stop() failed", exc_info=True)

    def render_log(self, level: str, message: str, logger_name: str, timestamp: datetime) -> None:
        """Render a log message with local level filtering.

        When components are wired, filters by current log level from
        ``LogLevelToggle.get_level()`` and formats as::

            [HH:MM:SS] LEVEL    message

        Falls back to stub debug log when components are not wired.

        Args:
            level: Log level name (DEBUG, INFO, WARNING, ERROR).
            message: Log message text.
            logger_name: Logger name (accepted but not displayed).
            timestamp: When the log event occurred.
        """
        if self._log_level_toggle is None or self._layout is None:
            logger.debug("InteractiveRenderer.render_log: not implemented")
            return

        # Local TUI-side filtering (AC #7)
        incoming_numeric = getattr(logging, level.upper(), logging.INFO)
        filter_level = self._log_level_toggle.get_level()
        filter_numeric = getattr(logging, filter_level.upper(), logging.INFO)

        if incoming_numeric < filter_numeric:
            return

        # Format: [HH:MM:SS] LEVEL    message (AC #9)
        time_str = timestamp.strftime("%H:%M:%S")
        level_padded = level.upper().ljust(8)
        formatted = f"[{time_str}] {level_padded} {message}"
        self._layout.write_log(formatted)

    def render_phase_started(self, phase: str, epic_id: EpicId, story_id: str) -> None:
        """Update TUI phase indicator, or log stub if not wired."""
        if self._status_bar is None and self._layout is None:
            logger.debug("InteractiveRenderer.render_phase_started: not implemented")
            return
        if self._status_bar is not None:
            self._status_bar.set_phase_info(phase, epic_id, story_id)
        if self._layout is not None:
            banner = f"{'─' * 40}\n  Phase: {phase} [{epic_id}.{story_id}]\n{'─' * 40}"
            self._layout.write_log(banner)

    def render_phase_completed(
        self, phase: str, epic_id: EpicId, story_id: str, duration: float
    ) -> None:
        """Update TUI phase completion, or log stub if not wired."""
        if self._layout is None:
            logger.debug("InteractiveRenderer.render_phase_completed: not implemented")
            return
        mins = int(duration) // 60
        secs = int(duration) % 60
        self._layout.write_log(f"  Phase {phase} completed in {mins}m {secs}s")

    def update_status(self, state: RunnerState) -> None:
        """Update TUI status bar, or log stub if not wired."""
        if self._status_bar is None:
            logger.debug("InteractiveRenderer.update_status: not implemented")
            return
        self._status_bar.set_runner_state(state)

    def reset(self) -> None:
        """Clear all displayed state for reconnect hydration (CS-6)."""
        if self._status_bar is not None:
            self._status_bar.set_phase_info("", 0, "")
            self._status_bar.set_llm_sessions(0)
            self._status_bar.set_paused(False)
            self._status_bar.set_pause_countdown(None)

    def set_log_level(self, level: str) -> None:
        """Set log level, delegating to LogLevelToggle when wired.

        Falls back to stub debug log when toggle is not wired.

        Args:
            level: Log level name (DEBUG, INFO, WARNING).
        """
        if self._log_level_toggle is None:
            logger.debug("InteractiveRenderer.set_log_level: not implemented")
            return

        self._log_level_toggle.set_level(level)
