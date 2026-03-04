"""Non-blocking keyboard input handler for the TUI.

Captures single keystrokes without requiring Enter, running in a background
daemon thread with robust terminal restoration. Uses cbreak mode (NOT raw mode)
to preserve SIGINT generation from Ctrl+C.

All terminal-specific imports (termios, tty, select) are guarded inside methods
for platform compatibility (these modules don't exist on Windows).
"""

from __future__ import annotations

import atexit
import logging
import sys
import threading
import time
from typing import IO, Callable

logger = logging.getLogger("bmad_assist.tui.input")

# Long-press detection constants
_REPEAT_WINDOW: float = 0.15  # 150ms between repeats
_LONG_PRESS_THRESHOLD: int = 5  # Fire long-press after 5 rapid repeats


class InputHandler:
    """Manages non-blocking keyboard input with callback dispatch.

    Enters cbreak mode for character-at-a-time input without echo,
    while preserving SIGINT (Ctrl+C) generation. Runs an input poll
    loop in a daemon thread using select() with 50ms timeout.

    Supports both normal key callbacks and long-press detection via
    keyboard repeat rate analysis.
    """

    def __init__(self) -> None:
        self._callbacks: dict[str, Callable[[], None]] = {}
        self._long_press_callbacks: dict[str, Callable[[], None]] = {}
        self._running: bool = False
        self._old_settings: list[object] | None = None
        self._restored: bool = False
        self._thread: threading.Thread | None = None
        self._stdin: IO[str] | None = sys.stdin  # Captured at init for testability
        self._atexit_registered: bool = False

        # Long-press tracking (AC #5)
        self._last_key: str | None = None
        self._last_key_time: float = 0.0
        self._repeat_count: int = 0
        self._long_press_fired: bool = False
        self._last_key_was_repeat: bool = False

    def register(self, key: str, callback: Callable[[], None]) -> None:
        """Register a key→callback mapping.

        Args:
            key: Single ASCII character (case-sensitive).
            callback: Function to call when key is pressed.
        """
        self._callbacks[key] = callback

    def register_long_press(self, key: str, callback: Callable[[], None]) -> None:
        """Register a long-press callback for a key.

        Args:
            key: Single ASCII character (case-sensitive).
            callback: Function to call on long-press detection.
        """
        self._long_press_callbacks[key] = callback

    def start(self) -> None:
        """Enter cbreak mode and launch input polling thread.

        Saves terminal attributes, enters cbreak mode (character-at-a-time,
        no echo, SIGINT preserved), registers atexit handler, and starts
        a daemon thread running _input_loop().

        No-op if already running or stdin is not a TTY. Safe to call
        multiple times (idempotent).
        """
        if self._running:
            return

        # Non-TTY guard: pipes, CI, redirected input, GUI (stdin=None)
        if self._stdin is None or not self._stdin.isatty():
            logger.debug("stdin is not a TTY — input handler disabled")
            return

        # Guard imports for platform compatibility (Windows has no termios/tty)
        try:
            import termios
            import tty
        except ImportError:
            logger.debug("termios/tty not available — input handler disabled")
            return

        # Save current terminal attributes
        try:
            fd = self._stdin.fileno()
            self._old_settings = termios.tcgetattr(fd)
        except (termios.error, OSError, ValueError) as exc:
            logger.warning("Failed to get terminal attributes: %s", exc)
            return

        # Enter cbreak mode (preserves SIGINT, disables echo + canonical mode)
        try:
            tty.setcbreak(fd)
        except (termios.error, OSError) as exc:
            logger.warning("Failed to enter cbreak mode: %s", exc)
            self._old_settings = None
            return

        # Register atexit handler as backup cleanup layer
        if not self._atexit_registered:
            atexit.register(self._restore_terminal)
            self._atexit_registered = True

        self._running = True
        self._restored = False

        # Start daemon thread for input polling
        self._thread = threading.Thread(
            target=self._input_loop,
            name="tui-input",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the input thread and restore terminal attributes.

        Sets _running to False, joins the thread with 200ms timeout,
        restores terminal via TCSAFLUSH, and unregisters atexit handler.

        Idempotent — safe to call multiple times. Never raises.
        """
        if not self._running and self._old_settings is None:
            return

        self._running = False

        # Join thread with timeout (don't block forever — daemon will die anyway)
        if self._thread is not None:
            try:
                self._thread.join(timeout=0.2)
            except (RuntimeError, OSError):
                pass  # Thread may not have started or already dead

        self._restore_terminal()

        # Unregister atexit to prevent accumulation on repeated start/stop
        if self._atexit_registered:
            atexit.unregister(self._restore_terminal)
            self._atexit_registered = False

    def _restore_terminal(self) -> None:
        """Restore terminal attributes. Idempotent via _restored flag.

        Uses TCSAFLUSH to discard unread input bytes accumulated during
        cbreak mode. Never raises — terminal may already be restored or
        fd may be closed.

        Sets _restored=True only on successful restoration. On failure,
        _old_settings is still cleared (stale settings shouldn't be retried
        since the fd may be invalid).
        """
        if self._restored or self._old_settings is None:
            return

        try:
            import termios

            fd = self._stdin.fileno()
            termios.tcsetattr(fd, termios.TCSAFLUSH, self._old_settings)
            self._restored = True
        except Exception:  # noqa: BLE001
            # termios.error, OSError, ValueError — all acceptable
            # Don't set _restored=True on failure; terminal may still
            # need restoration via other means (e.g., `reset` command).
            pass
        finally:
            self._old_settings = None

    def _input_loop(self) -> None:
        """Poll stdin for input with 50ms timeout.

        Reads single characters and dispatches via _process_key().
        Handles EOF (empty read) by exiting cleanly. All exceptions
        are caught to prevent thread crash.
        """
        import select

        while self._running:
            try:
                readable, _, _ = select.select([self._stdin], [], [], 0.05)
                if readable:
                    ch = self._stdin.read(1)
                    if not ch:
                        # EOF: stdin closed (PTY disconnect, pipe end, etc.)
                        logger.debug("stdin EOF — input thread exiting")
                        self._running = False
                        break
                    self._process_key(ch)
            except Exception:  # noqa: BLE001
                if not self._running:
                    break  # Expected during shutdown
                logger.warning("Input loop error", exc_info=True)

    def _process_key(self, ch: str) -> None:
        """Process a single keypress with long-press detection.

        Dispatch rules:
        - repeat_count == 1 AND not _last_key_was_repeat: trigger NORMAL callback
        - repeat_count 2-4 (within repeat window): no dispatch (accumulating)
        - repeat_count >= 5 AND not _long_press_fired: trigger LONG-PRESS
        - repeat_count > threshold OR _long_press_fired: no dispatch (suppress)

        Args:
            ch: Single character read from stdin.
        """
        now = time.monotonic()

        if ch == self._last_key and (now - self._last_key_time) < _REPEAT_WINDOW:
            # Same key within repeat window — accumulating
            self._repeat_count += 1
            self._last_key_was_repeat = True
        else:
            # Different key OR same key with window expired — genuine new press
            # NOTE: We intentionally do NOT distinguish "same key after window"
            # from "different key". The original design suppressed same-key
            # presses after window expiry to avoid OS keyboard repeat initial
            # delay (~500ms) double-firing. However, this made it impossible
            # to press the same key twice (e.g., toggle pause/resume with 'p').
            # Accepting an occasional extra callback fire from OS repeat start
            # is far less harmful than breaking toggle controls entirely.
            self._repeat_count = 1
            self._last_key_was_repeat = False
            self._long_press_fired = False

        self._last_key = ch
        self._last_key_time = now

        # Dispatch logic
        if self._repeat_count == 1 and not self._last_key_was_repeat:
            # Genuine new key press → normal callback
            cb = self._callbacks.get(ch)
            if cb is not None:
                try:
                    cb()
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Callback exception for key %r", ch, exc_info=True
                    )
        elif self._repeat_count >= _LONG_PRESS_THRESHOLD and not self._long_press_fired:
            # Long-press threshold reached → long-press callback
            lp_cb = self._long_press_callbacks.get(ch)
            if lp_cb is not None:
                try:
                    lp_cb()
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Long-press callback exception for key %r",
                        ch,
                        exc_info=True,
                    )
            self._long_press_fired = True
        # else: counts 2-4 (accumulating) or > threshold (already fired) — no dispatch


# --- Manual test script ---

if __name__ == "__main__":
    import time as _time

    if "--test" not in sys.argv:
        print("Usage: python -m bmad_assist.tui.input --test")
        sys.exit(1)

    handler = InputHandler()
    quit_flag = threading.Event()

    def _on_pause() -> None:
        print("  → PAUSE pressed")

    def _on_stop() -> None:
        print("  → STOP pressed")

    def _on_config() -> None:
        print("  → CONFIG RELOAD pressed")

    def _on_log_level() -> None:
        print("  → LOG LEVEL pressed")

    def _on_resume() -> None:
        print("  → RESUME pressed")

    def _on_quit() -> None:
        print("  → QUIT pressed — exiting...")
        quit_flag.set()

    def _on_long_press_p() -> None:
        print("  → LONG PRESS detected on 'p'")

    handler.register("p", _on_pause)
    handler.register("s", _on_stop)
    handler.register("c", _on_config)
    handler.register("l", _on_log_level)
    handler.register("r", _on_resume)
    handler.register("q", _on_quit)
    handler.register_long_press("p", _on_long_press_p)

    print("Input handler demo (10s or press 'q' to quit)")
    print("Keys: [p]ause [s]top [c]onfig [l]og-level [r]esume [q]uit")
    print("Hold 'p' for long-press detection")
    print()

    handler.start()
    try:
        start_time = _time.monotonic()
        while not quit_flag.is_set() and (_time.monotonic() - start_time) < 10:
            _time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n  → Ctrl+C caught")
    finally:
        handler.stop()
        print("\nInput handler stopped. Terminal restored.")
