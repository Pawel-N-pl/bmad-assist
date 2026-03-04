"""Pause timer component for the TUI.

Manages countdown-based pause with auto-resume, pause extension via
repeated ``p`` key presses, and long-press ``p`` to reset hours.

Updates the StatusBar's command segment every second with remaining time.

The PauseTimer is a standalone component that delegates display updates
to StatusBar and log messages to LayoutManager. IPC integration is done
via fire-and-forget callbacks set externally.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable

from bmad_assist.tui.layout import LayoutManager
from bmad_assist.tui.status_bar import StatusBar

logger = logging.getLogger("bmad_assist.tui.timer")

_ONE_HOUR_SECONDS: int = 3600


# ---------------------------------------------------------------------------
# Countdown formatter (AC #12)
# ---------------------------------------------------------------------------


def format_countdown(seconds: int) -> str:
    """Format countdown remaining time for status bar display.

    Unlike ``format_run_elapsed()`` which always shows all units, this
    uses a compact format appropriate for a countdown display:

    - >= 1 hour: ``{h}h {m}m`` (seconds omitted for cleaner display)
    - >= 1 minute: ``{m}m {s}s``
    - < 1 minute: ``{s}s``

    Args:
        seconds: Remaining seconds (non-negative).

    Returns:
        Formatted countdown string.
    """
    total = max(0, seconds)
    hours = total // 3600
    remainder = total % 3600
    minutes = remainder // 60
    secs = remainder % 60

    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


# ---------------------------------------------------------------------------
# PauseTimer class (AC #1)
# ---------------------------------------------------------------------------


class PauseTimer:
    """Manages pause countdown state and IPC integration.

    Holds the countdown timer, dispatches between activate/extend on ``p``
    key presses, and auto-resumes when the countdown reaches zero.

    A daemon timer thread decrements ``_remaining_seconds`` every ~1 second
    and updates the StatusBar display.

    Args:
        status_bar: StatusBar instance for display updates.
        layout: LayoutManager instance for log messages.
    """

    def __init__(self, status_bar: StatusBar, layout: LayoutManager) -> None:
        self._status_bar = status_bar
        self._layout = layout

        # Timer state (AC #1)
        self._remaining_seconds: int = 0
        self._active: bool = False

        # Thread lifecycle
        self._running: bool = False
        self._timer_thread: threading.Thread | None = None

        # Lock protects _remaining_seconds and _active
        self._lock = threading.Lock()

        # External callbacks (fire-and-forget)
        self._pause_callback: Callable[[], None] | None = None
        self._resume_callback: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # Callback setters
    # ------------------------------------------------------------------

    def set_pause_callback(self, cb: Callable[[], None]) -> None:
        """Set callback to execute when pause is activated."""
        self._pause_callback = cb

    def set_resume_callback(self, cb: Callable[[], None]) -> None:
        """Set callback to execute when resume triggers."""
        self._resume_callback = cb

    # ------------------------------------------------------------------
    # Core methods (AC #2, #3, #4, #5)
    # ------------------------------------------------------------------

    def activate(self) -> None:
        """Start a pause countdown.

        Sets ``_remaining_seconds=3600``, ``_active=True``, fires the
        pause callback, switches StatusBar to paused mode, and writes
        a log message.
        """
        with self._lock:
            self._remaining_seconds = _ONE_HOUR_SECONDS
            self._active = True

        # Fire-and-forget pause callback
        if self._pause_callback is not None:
            try:
                self._pause_callback()
            except Exception:
                logger.warning("Pause callback failed", exc_info=True)

        self._status_bar.set_paused(True)

        countdown_text = format_countdown(_ONE_HOUR_SECONDS)
        self._layout.write_log(
            f"PAUSED — auto-resume in {countdown_text}"
        )
        self._update_countdown_display()

    def deactivate(self) -> None:
        """Clear the pause and resume.

        Idempotent: if not active, returns immediately without any
        side effects (no callbacks, no logs).
        """
        with self._lock:
            if not self._active:
                return
            self._active = False
            self._remaining_seconds = 0

        # Fire-and-forget resume callback
        if self._resume_callback is not None:
            try:
                self._resume_callback()
            except Exception:
                logger.warning("Resume callback failed", exc_info=True)

        self._status_bar.set_paused(False)
        self._status_bar.set_pause_countdown(None)
        self._layout.write_log("RESUMED (manual)")

    def extend(self) -> None:
        """Add 1 hour to remaining countdown time."""
        with self._lock:
            self._remaining_seconds += _ONE_HOUR_SECONDS
            remaining = self._remaining_seconds

        countdown_text = format_countdown(remaining)
        self._layout.write_log(
            f"Pause extended — auto-resume in {countdown_text}"
        )
        self._update_countdown_display()

    def reset_to_minutes(self) -> None:
        """Drop hours from remaining time, keeping only minutes/seconds.

        If remaining > 3600, sets to ``remaining % 3600``. Edge case:
        if modulo result is 0, sets to 60 (1 minute minimum).

        No-op if remaining <= 3600.
        """
        with self._lock:
            if self._remaining_seconds <= _ONE_HOUR_SECONDS:
                return
            result = self._remaining_seconds % _ONE_HOUR_SECONDS
            if result == 0:
                result = 60  # Prevent immediate auto-resume surprise
            self._remaining_seconds = result
            remaining = self._remaining_seconds

        countdown_text = format_countdown(remaining)
        self._layout.write_log(
            f"Pause hours reset — auto-resume in {countdown_text}"
        )
        self._update_countdown_display()

    # ------------------------------------------------------------------
    # Key dispatch (AC #7, #8)
    # ------------------------------------------------------------------

    def on_pause_key(self) -> None:
        """Dispatch ``p`` key: activate if not paused, extend if paused.

        Reads ``_active`` under lock and dispatches atomically to avoid
        TOCTOU races between the check and the method call.
        """
        with self._lock:
            was_active = self._active
            if was_active:
                # Inline extend logic under lock to prevent race with
                # auto-resume setting _active=False between check and call
                self._remaining_seconds += _ONE_HOUR_SECONDS
                remaining = self._remaining_seconds
        if was_active:
            countdown_text = format_countdown(remaining)
            self._layout.write_log(
                f"Pause extended — auto-resume in {countdown_text}"
            )
            self._update_countdown_display()
        else:
            self.activate()

    def on_long_press_p(self) -> None:
        """Dispatch long-press ``p``: reset hours if active, no-op otherwise."""
        with self._lock:
            active = self._active
        if active:
            self.reset_to_minutes()

    # ------------------------------------------------------------------
    # Display update (AC #11)
    # ------------------------------------------------------------------

    def _update_countdown_display(self) -> None:
        """Update StatusBar's countdown segment."""
        with self._lock:
            active = self._active
            remaining = self._remaining_seconds

        if active:
            self._status_bar.set_pause_countdown(format_countdown(remaining))
        else:
            self._status_bar.set_pause_countdown(None)

    # ------------------------------------------------------------------
    # Timer thread (AC #9, #10, #13)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the countdown timer thread.

        Idempotent — subsequent calls are no-ops. Thread-safe: the
        ``_lock`` prevents concurrent callers from spawning multiple
        threads.
        """
        with self._lock:
            if self._running:
                return
            self._running = True
        self._timer_thread = threading.Thread(
            target=self._timer_loop,
            name="tui-pause-timer",
            daemon=True,
        )
        self._timer_thread.start()

    def stop(self) -> None:
        """Stop the timer thread and clean up pause state.

        Calls ``deactivate()`` unconditionally (which is a no-op when
        not active) to ensure the runner is resumed if the TUI exits
        while paused. Idempotent and never raises.
        """
        self._running = False
        if self._timer_thread is not None:
            try:
                self._timer_thread.join(timeout=0.5)
            except Exception:
                pass
        self._timer_thread = None

        # Clean up pause state if still active
        try:
            self.deactivate()
        except Exception:
            logger.warning("Deactivate during stop failed", exc_info=True)

    def _timer_loop(self) -> None:
        """Timer thread main loop.

        Sleeps in 0.1s increments (10 iterations ≈ 1s) for <200ms
        shutdown response. Decrements ``_remaining_seconds`` once
        per ~1-second cycle and triggers auto-resume when it reaches 0.
        """
        tick = 0
        while self._running:
            time.sleep(0.1)
            if not self._running:
                break
            tick += 1
            if tick >= 10:
                tick = 0
                try:
                    self._tick()
                except Exception:
                    logger.warning("Pause timer tick failed", exc_info=True)

    def _tick(self) -> None:
        """One-second tick: decrement counter and check for auto-resume."""
        with self._lock:
            if not self._active:
                return
            self._remaining_seconds -= 1
            if self._remaining_seconds <= 0:
                self._remaining_seconds = 0
                self._active = False
                should_auto_resume = True
            else:
                should_auto_resume = False

        if should_auto_resume:
            # Fire-and-forget resume callback
            if self._resume_callback is not None:
                try:
                    self._resume_callback()
                except Exception:
                    logger.warning("Resume callback failed during auto-resume", exc_info=True)

            self._status_bar.set_paused(False)
            self._status_bar.set_pause_countdown(None)
            self._layout.write_log("Auto-resumed — pause timer expired")
        else:
            self._update_countdown_display()


# ---------------------------------------------------------------------------
# Manual test script (AC #15)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--test" not in sys.argv:
        print("Usage: python -m bmad_assist.tui.timer --test")
        sys.exit(1)

    print("Starting PauseTimer demo (~20 seconds or Ctrl+C)...")

    layout = LayoutManager(status_lines=2)
    sb = StatusBar(layout)
    pt = PauseTimer(sb, layout)

    # Wire mock callbacks
    def on_pause() -> None:
        layout.write_log("[callback] pause.flag created")

    def on_resume() -> None:
        layout.write_log("[callback] pause.flag removed")

    pt.set_pause_callback(on_pause)
    pt.set_resume_callback(on_resume)

    layout.start()
    sb.start()
    pt.start()

    try:
        sb.set_run_start_time(time.monotonic())
        sb.set_phase_info("dev_story", 30, "30.5")
        sb.set_llm_sessions(0)
        sb.set_log_level("WARNING")

        start = time.monotonic()

        # Step 1: Activate pause (countdown = 1h)
        layout.write_log("--- Step 1: Activate pause ---")
        pt.on_pause_key()
        time.sleep(5)

        # Step 2: Extend (add 1h)
        layout.write_log("--- Step 2: Extend pause (+1h) ---")
        pt.on_pause_key()
        time.sleep(3)

        # Step 3: Deactivate (manual resume)
        layout.write_log("--- Step 3: Manual resume ---")
        pt.deactivate()
        time.sleep(3)

        # Step 4: Activate with short timer for auto-resume demo
        layout.write_log("--- Step 4: Activate with 5s timer ---")
        pt.activate()
        with pt._lock:
            pt._remaining_seconds = 5
        pt._update_countdown_display()
        layout.write_log("Waiting for auto-resume in ~5s...")
        time.sleep(8)

        layout.write_log("--- Demo complete ---")

    except KeyboardInterrupt:
        layout.write_log("Interrupted by user")
    finally:
        pt.stop()
        sb.stop()
        layout.stop()
        print("\nPauseTimer demo stopped cleanly.")
