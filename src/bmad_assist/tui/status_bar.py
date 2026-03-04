"""Status bar component for the TUI.

Manages status bar data model and formatting for the fixed bottom lines
of the terminal. Delegates all terminal I/O to LayoutManager.

The status bar displays:
- Run elapsed time (with day-level support)
- Current phase info (using shortcut names)
- LLM session count
- Available keyboard commands
- Current log level

A daemon timer thread ticks every ~1 second to update the display.
"""

from __future__ import annotations

import logging
import shutil
import sys
import threading
import time

from bmad_assist.cli_utils import format_duration_cli
from bmad_assist.core.types import EpicId
from bmad_assist.ipc.types import RunnerState
from bmad_assist.tui.layout import LayoutManager

logger = logging.getLogger("bmad_assist.tui.status_bar")

# ---------------------------------------------------------------------------
# Phase shortcut mapping (AC #8)
# ---------------------------------------------------------------------------

PHASE_SHORTCUTS: dict[str, str] = {
    "create_story": "Create",
    "validate_story": "Validate",
    "validate_story_synthesis": "Val Synth",
    "dev_story": "Develop",
    "code_review": "Review",
    "code_review_synthesis": "Rev Synth",
    "retrospective": "Retro",
    "tea_framework": "Framework",
    "tea_ci": "CI",
    "tea_test_design": "Test Design",
    "atdd": "ATDD",
    "tea_automate": "Automate",
    "test_review": "Test Review",
    "trace": "Trace",
    "tea_nfr_assess": "NFR",
    "qa_plan_generate": "QA Plan",
    "qa_plan_execute": "QA Exec",
    "qa_remediate": "QA Fix",
}


# ---------------------------------------------------------------------------
# Duration formatter (AC #11)
# ---------------------------------------------------------------------------


def format_run_elapsed(seconds: float) -> str:
    """Format elapsed time with day-level support.

    Unlike ``format_duration_cli`` (which caps at hours), this adds
    day-level granularity for long-running sessions (24h+).

    Args:
        seconds: Duration in seconds (truncated to int).

    Returns:
        Human-readable string, e.g. ``1d 12h 45m 23s``.
    """
    total = max(0, int(seconds))
    days = total // 86400
    remainder = total % 86400
    hours = remainder // 3600
    remainder = remainder % 3600
    minutes = remainder // 60
    secs = remainder % 60

    if days > 0:
        return f"{days}d {hours}h {minutes}m {secs}s"
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


# ---------------------------------------------------------------------------
# StatusBar class (AC #1, #3)
# ---------------------------------------------------------------------------


class StatusBar:
    """Status bar data model, formatter, and timer.

    Holds mutable state for what the status bar should display, formats it
    into plain-text strings, and delegates terminal I/O to
    :class:`LayoutManager`.

    Two lines are managed:
    - Penultimate line: phase elapsed time
    - Last line: full status bar (commands, run elapsed, phase, LLM, log)

    A daemon timer thread ticks every ~1 second to refresh the display.

    Args:
        layout: LayoutManager instance for terminal I/O.
    """

    def __init__(self, layout: LayoutManager) -> None:
        self._layout = layout

        # Data model fields (AC #3)
        self._run_start_time: float = 0.0
        self._phase: str | None = None
        self._epic_id: EpicId | None = None
        self._story_id: str | None = None
        self._phase_start_time: float = 0.0
        self._llm_sessions: int = 0
        self._log_level: str = "WARNING"
        self._paused: bool = False
        self._pause_countdown: str | None = None
        self._runner_state: RunnerState = RunnerState.IDLE
        self._frozen_run_elapsed: float | None = None  # Frozen on run end

        # Timer thread (AC #5)
        self._running: bool = False
        self._timer_thread: threading.Thread | None = None

        # Lock protects data model fields (AC #1)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Setters (AC #3) — each acquires lock, updates, renders
    # ------------------------------------------------------------------

    def set_run_start_time(self, t: float) -> None:
        """Set the monotonic time when the run started."""
        with self._lock:
            self._run_start_time = t
        self._render()

    def set_phase_info(
        self,
        phase: str,
        epic_id: EpicId,
        story_id: str,
        elapsed: float = 0.0,
    ) -> None:
        """Set current phase info and reset phase elapsed timer.

        Args:
            phase: Phase ID in snake_case (e.g. ``dev_story``).
            epic_id: Current epic identifier.
            story_id: Current story identifier (e.g. ``30.4``).
            elapsed: Seconds already elapsed for this phase (for reconnect
                hydration). When 0, timer starts from now.
        """
        with self._lock:
            self._phase = phase
            self._epic_id = epic_id
            self._story_id = story_id
            self._phase_start_time = time.monotonic() - elapsed
        self._render()

    def set_llm_sessions(self, count: int) -> None:
        """Set the total LLM invocation count."""
        with self._lock:
            self._llm_sessions = count
        self._render()

    def set_log_level(self, level: str) -> None:
        """Set the displayed log level string."""
        with self._lock:
            self._log_level = level
        self._render()

    def set_paused(self, paused: bool) -> None:
        """Set whether the runner is paused."""
        with self._lock:
            self._paused = paused
        self._render()

    def set_pause_countdown(self, countdown: str | None) -> None:
        """Set the pause countdown text for display.

        When not None and paused, the commands segment shows
        ``[r] resume in {countdown}`` instead of ``[r] resume``.

        Args:
            countdown: Formatted countdown string or None to clear.
        """
        with self._lock:
            self._pause_countdown = countdown
        self._render()

    def set_runner_state(self, state: RunnerState) -> None:
        """Set the runner lifecycle state."""
        with self._lock:
            if state == RunnerState.IDLE and self._runner_state != RunnerState.IDLE:
                # Freeze timers on run completion
                now = time.monotonic()
                if self._run_start_time:
                    self._frozen_run_elapsed = now - self._run_start_time
                self._phase = None  # Clear phase display
            elif state != RunnerState.IDLE and self._runner_state == RunnerState.IDLE:
                # New run starting — unfreeze
                self._frozen_run_elapsed = None
            self._runner_state = state
        self._render()

    # ------------------------------------------------------------------
    # Timer thread (AC #5, #6)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the 1-second timer thread.

        Idempotent — subsequent calls are no-ops.
        """
        if self._running:
            return
        self._running = True
        self._timer_thread = threading.Thread(
            target=self._timer_loop,
            name="tui-status-timer",
            daemon=True,
        )
        self._timer_thread.start()

    def stop(self) -> None:
        """Stop the timer thread.

        Joins with 500ms timeout. Idempotent and never raises.
        """
        self._running = False
        if self._timer_thread is not None:
            try:
                self._timer_thread.join(timeout=0.5)
            except Exception:
                pass
        self._timer_thread = None

    def _timer_loop(self) -> None:
        """Timer thread main loop.

        Sleeps in 0.1s increments (10 iterations ≈ 1s) for fast shutdown.
        Calls ``_render()`` once per ~1-second cycle.
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
                    self._render()
                except Exception:
                    logger.warning("Status bar render failed", exc_info=True)

    # ------------------------------------------------------------------
    # Rendering (AC #2, #4, #7, #10)
    # ------------------------------------------------------------------

    def _render(self) -> None:
        """Format and write both status lines.

        Acquires lock to snapshot data, formats outside lock, then
        calls LayoutManager methods (which have their own lock).
        """
        # Snapshot under lock
        with self._lock:
            run_start = self._run_start_time
            phase = self._phase
            story_id = self._story_id
            phase_start = self._phase_start_time
            llm_sessions = self._llm_sessions
            log_level = self._log_level
            paused = self._paused
            pause_countdown = self._pause_countdown
            frozen_run_elapsed = self._frozen_run_elapsed

        now = time.monotonic()

        # --- Phase elapsed line (penultimate) ---
        if paused:
            phase_text = "PAUSED"
        elif phase is not None:
            phase_elapsed = now - phase_start
            phase_text = f"current phase elapsed: {format_duration_cli(phase_elapsed)}"
        else:
            phase_text = ""

        # --- Status bar line (last) ---
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
        status_text = self._format_status_bar(
            cols=cols,
            run_start=run_start,
            now=now,
            phase=phase,
            story_id=story_id,
            llm_sessions=llm_sessions,
            log_level=log_level,
            paused=paused,
            pause_countdown=pause_countdown,
            frozen_run_elapsed=frozen_run_elapsed,
        )

        # Write to layout
        self._layout.update_phase_elapsed(phase_text)
        self._layout.update_status_bar(status_text)

    def _format_status_bar(
        self,
        cols: int = 200,
        *,
        run_start: float | None = None,
        now: float | None = None,
        phase: str | None = None,
        story_id: str | None = None,
        llm_sessions: int | None = None,
        log_level: str | None = None,
        paused: bool | None = None,
        pause_countdown: str | None = None,
        frozen_run_elapsed: float | None = None,
    ) -> str:
        """Build the status bar string with progressive truncation.

        When called without keyword args, reads from the data model
        under lock (used by tests). When called with args, uses the
        provided values (used by ``_render()`` after snapshotting).

        Args:
            cols: Terminal width for truncation.
            pause_countdown: Formatted countdown text or None.
            frozen_run_elapsed: Frozen seconds when run completed (None = live).

        Returns:
            Formatted status bar string.
        """
        # If kwargs not provided, snapshot from data model
        if run_start is None or now is None:
            _now = time.monotonic()
            with self._lock:
                run_start = self._run_start_time
                phase = self._phase
                story_id = self._story_id
                llm_sessions = self._llm_sessions
                log_level = self._log_level
                paused = self._paused
                pause_countdown = self._pause_countdown
                frozen_run_elapsed = self._frozen_run_elapsed
            now = _now

        # Build segments — use frozen elapsed if run completed
        if frozen_run_elapsed is not None:
            run_elapsed = format_run_elapsed(frozen_run_elapsed)
        elif run_start:
            run_elapsed = format_run_elapsed(now - run_start)
        else:
            run_elapsed = "0s"
        run_segment = f"run: {run_elapsed}"

        if paused:
            if pause_countdown is not None:
                resume_text = f"[r] resume in {pause_countdown}"
            else:
                resume_text = "[r] resume"
            commands_segment = f"{resume_text} / [s] stop / [c] config reload"
            phase_segment = "PAUSED"
        else:
            commands_segment = "[p] pause / [s] stop / [c] config reload"
            if phase and story_id:
                shortcut = PHASE_SHORTCUTS.get(
                    phase, phase.upper().replace("_", " ")
                )
                phase_segment = f"{story_id} {shortcut}"
            elif phase:
                shortcut = PHASE_SHORTCUTS.get(
                    phase, phase.upper().replace("_", " ")
                )
                phase_segment = shortcut
            else:
                phase_segment = ""

        llm_segment = f"LLM: {llm_sessions}"
        log_segment = f"[l] {log_level}"

        # Build segments list (with phase_segment possibly empty)
        core_segments = [run_segment]
        if phase_segment:
            core_segments.append(phase_segment)

        # Full version: core + llm + commands + log
        all_segments = core_segments + [llm_segment, commands_segment, log_segment]
        full = " / ".join(all_segments)
        if len(full) <= cols:
            return full

        # Drop commands first (lowest priority)
        segments = core_segments + [llm_segment, log_segment]
        text = " / ".join(segments)
        if len(text) <= cols:
            return text

        # Drop log level
        segments = core_segments + [llm_segment]
        text = " / ".join(segments)
        if len(text) <= cols:
            return text

        # Drop LLM count — minimum viable
        text = " / ".join(core_segments)
        return text


# ---------------------------------------------------------------------------
# Manual test script (AC #12)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--test" not in sys.argv:
        print("Usage: python -m bmad_assist.tui.status_bar --test")
        sys.exit(1)

    print("Starting StatusBar demo (15 seconds or Ctrl+C)...")

    layout = LayoutManager(status_lines=2)
    sb = StatusBar(layout)

    layout.start()
    sb.start()

    phases = [
        ("create_story", 30, "30.1"),
        ("dev_story", 30, "30.4"),
        ("code_review", 26, "26.15"),
    ]
    phase_idx = 0

    try:
        sb.set_run_start_time(time.monotonic())
        sb.set_phase_info(*phases[0])
        sb.set_log_level("WARNING")
        sb.set_llm_sessions(0)

        start = time.monotonic()
        llm_count = 0
        paused = False

        while time.monotonic() - start < 15:
            elapsed = time.monotonic() - start

            # Change phase every 5 seconds
            new_idx = min(int(elapsed // 5), len(phases) - 1)
            if new_idx != phase_idx:
                phase_idx = new_idx
                sb.set_phase_info(*phases[phase_idx])
                layout.write_log(f"Phase changed to {phases[phase_idx][0]}")

            # Increment LLM count every 2 seconds
            if int(elapsed) // 2 > llm_count:
                llm_count = int(elapsed) // 2
                sb.set_llm_sessions(llm_count)

            # Toggle pause at 7s and 10s
            if 7 <= elapsed < 10 and not paused:
                paused = True
                sb.set_paused(True)
                layout.write_log("PAUSED")
            elif elapsed >= 10 and paused:
                paused = False
                sb.set_paused(False)
                layout.write_log("RESUMED")

            # Write log lines
            layout.write_log(
                f"[{int(elapsed):02d}s] Demo log line (phase={phases[phase_idx][0]})"
            )

            time.sleep(1)

    except KeyboardInterrupt:
        layout.write_log("Interrupted by user")
    finally:
        sb.stop()
        layout.stop()
        print("\nStatusBar demo stopped cleanly.")
