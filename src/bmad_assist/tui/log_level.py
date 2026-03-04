"""Log level toggle component for the TUI.

Manages runtime log level cycling via the ``l`` key:
WARNING → INFO → DEBUG → WARNING (wrapping).

Updates the StatusBar display immediately, sends the level change to the
runner via IPC callback (fire-and-forget), and provides the current filter
level for local TUI-side log filtering in ``InteractiveRenderer.render_log()``.

The LogLevelToggle is a standalone component that delegates display updates
to StatusBar and log messages to LayoutManager. IPC integration is done
via a fire-and-forget callback set externally.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable

from bmad_assist.cli_utils import update_log_level
from bmad_assist.tui.layout import LayoutManager
from bmad_assist.tui.status_bar import StatusBar

logger = logging.getLogger("bmad_assist.tui.log_level")

LOG_LEVEL_CYCLE: tuple[str, ...] = ("WARNING", "INFO", "DEBUG")
"""Defines the cycle order for the ``l`` key toggle."""


class LogLevelToggle:
    """Manages log level cycling state and IPC integration.

    Cycles through WARNING → INFO → DEBUG → WARNING on each ``l`` key press.
    Delegates display updates to StatusBar, log messages to LayoutManager,
    and Python logging level changes to ``update_log_level()`` from cli_utils.

    Args:
        status_bar: StatusBar instance for display updates.
        layout: LayoutManager instance for log messages.
    """

    def __init__(self, status_bar: StatusBar, layout: LayoutManager) -> None:
        self._status_bar = status_bar
        self._layout = layout
        self._current_level: str = "WARNING"
        self._ipc_callback: Callable[[str], None] | None = None

    # ------------------------------------------------------------------
    # Callback setter (AC #4)
    # ------------------------------------------------------------------

    def set_ipc_callback(self, cb: Callable[[str], None]) -> None:
        """Set the IPC callback for sending level changes to the runner.

        Args:
            cb: Callback that receives the new level string (e.g., ``"DEBUG"``).
        """
        self._ipc_callback = cb

    # ------------------------------------------------------------------
    # Level accessors (AC #5, #6)
    # ------------------------------------------------------------------

    def get_level(self) -> str:
        """Return current log level string.

        Thread-safe read — ``_current_level`` is a simple string
        assignment, atomic in CPython.
        """
        return self._current_level

    def set_level(self, level: str) -> None:
        """Programmatic setter for external callers (e.g., IPC sync).

        Validates level is in ``LOG_LEVEL_CYCLE`` (case-insensitive).
        If invalid, returns silently (no-op).

        Does NOT call ``_ipc_callback`` (avoids echo loop).
        Does NOT write a log message (avoids feedback loop).

        Args:
            level: Log level name (e.g., ``"DEBUG"``, ``"info"``).
        """
        normalized = level.upper()
        if normalized not in LOG_LEVEL_CYCLE:
            return

        self._current_level = normalized
        self._status_bar.set_log_level(normalized)
        update_log_level(normalized)

    # ------------------------------------------------------------------
    # Key handler (AC #2)
    # ------------------------------------------------------------------

    def on_log_level_key(self) -> None:
        """Cycle the log level on ``l`` key press.

        Cycles: WARNING → INFO → DEBUG → WARNING (wrapping).

        Updates internal state, StatusBar display, Python logging level,
        calls IPC callback (fire-and-forget), and writes a log message.
        This is the method registered with ``InputHandler.register("l", ...)``.
        """
        # Find current index and advance
        try:
            idx = LOG_LEVEL_CYCLE.index(self._current_level)
        except ValueError:
            # Current level not in cycle (shouldn't happen, but be safe)
            idx = -1
        new_idx = (idx + 1) % len(LOG_LEVEL_CYCLE)
        new_level = LOG_LEVEL_CYCLE[new_idx]

        # Update state, display, and Python logging via set_level()
        self.set_level(new_level)

        # Fire-and-forget IPC callback
        if self._ipc_callback is not None:
            try:
                self._ipc_callback(new_level)
            except Exception:  # noqa: BLE001
                logger.warning("IPC log-level callback failed", exc_info=True)

        # Write log message to scroll region
        self._layout.write_log(f"Log level: {new_level}")


# ---------------------------------------------------------------------------
# Manual test script (AC #11)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--test" not in sys.argv:
        print("Usage: python -m bmad_assist.tui.log_level --test")
        sys.exit(1)

    import time

    print("Starting LogLevelToggle demo (~5 seconds or Ctrl+C)...")

    layout = LayoutManager(status_lines=2)
    sb = StatusBar(layout)
    toggle = LogLevelToggle(sb, layout)

    # Wire mock IPC callback
    def mock_ipc_callback(level: str) -> None:
        layout.write_log(f"[IPC callback] set_log_level({level})")

    toggle.set_ipc_callback(mock_ipc_callback)

    layout.start()
    sb.start()

    try:
        sb.set_run_start_time(time.monotonic())
        sb.set_phase_info("dev_story", 30, "30.6")
        sb.set_llm_sessions(0)
        sb.set_log_level("WARNING")

        # Step 1: Cycle WARNING → INFO
        layout.write_log("--- Step 1: Cycle WARNING → INFO ---")
        toggle.on_log_level_key()
        time.sleep(1)

        # Step 2: Cycle INFO → DEBUG
        layout.write_log("--- Step 2: Cycle INFO → DEBUG ---")
        toggle.on_log_level_key()
        time.sleep(1)

        # Step 3: Cycle DEBUG → WARNING
        layout.write_log("--- Step 3: Cycle DEBUG → WARNING ---")
        toggle.on_log_level_key()
        time.sleep(1)

        # Step 4: Programmatic set_level("DEBUG")
        layout.write_log("--- Step 4: Programmatic set_level('DEBUG') ---")
        toggle.set_level("DEBUG")
        layout.write_log(f"Current level: {toggle.get_level()}")
        time.sleep(1)

        # Step 5: Show final state
        layout.write_log(f"--- Final state: {toggle.get_level()} ---")
        layout.write_log("--- Demo complete ---")
        time.sleep(1)

    except KeyboardInterrupt:
        layout.write_log("Interrupted by user")
    finally:
        sb.stop()
        layout.stop()
        print("\nLogLevelToggle demo stopped cleanly.")
