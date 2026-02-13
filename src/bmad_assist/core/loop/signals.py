"""Signal handling for immediate shutdown.

Story 6.6: Signal handling for shutdown (SIGINT, SIGTERM).
Updated: Hard kill on Ctrl+C - no graceful shutdown, immediate exit.

"""

import contextlib
import os
import signal
import threading
from collections.abc import Callable
from types import FrameType

from bmad_assist.core.exceptions import StateError
from bmad_assist.core.loop.types import LoopExitReason

__all__ = [
    "shutdown_requested",
    "request_shutdown",
    "reset_shutdown",
    "get_received_signal",
    "register_signal_handlers",
    "unregister_signal_handlers",
]


# =============================================================================
# Shutdown Management - Story 6.6
# =============================================================================

# Module-level shutdown state (thread-safe via threading.Event)
_shutdown_event = threading.Event()
_received_signal: int | None = None

# Previous signal handlers for proper restoration
# Type is the return type of signal.signal() - can be Handler or special int values
_previous_sigint_handler: Callable[[int, FrameType | None], None] | int | None = None
_previous_sigterm_handler: Callable[[int, FrameType | None], None] | int | None = None


def shutdown_requested() -> bool:
    """Check if shutdown has been requested via signal.

    Thread-safe check using threading.Event. This function should be called
    at safe points in the main loop (after save_state) to check if a
    graceful shutdown was requested.

    Returns:
        True if shutdown has been requested, False otherwise.

    Example:
        >>> reset_shutdown()
        >>> shutdown_requested()
        False
        >>> request_shutdown(signal.SIGINT)
        >>> shutdown_requested()
        True

    """
    return _shutdown_event.is_set()


def request_shutdown(signum: int) -> None:
    """Request graceful shutdown with the given signal number.

    Sets the shutdown flag and stores the signal number for exit code
    calculation. This is called by signal handlers.

    Args:
        signum: Signal number (e.g., signal.SIGINT=2, signal.SIGTERM=15).

    Note:
        Thread-safe via threading.Event.set(). Safe to call from
        signal handlers which run in the main thread.

    """
    global _received_signal
    _received_signal = signum
    _shutdown_event.set()


def reset_shutdown() -> None:
    """Clear shutdown state.

    Resets the shutdown flag and clears the stored signal number.
    Called at the start of run_loop() to ensure clean state for
    multiple invocations, and in test fixtures for isolation.

    Note:
        Must be called before register_signal_handlers() in run_loop().

    """
    global _received_signal
    _received_signal = None
    _shutdown_event.clear()


def get_received_signal() -> int | None:
    """Get the signal number that triggered shutdown.

    Returns:
        Signal number (2 for SIGINT, 15 for SIGTERM) if shutdown was
        requested, None otherwise.

    """
    return _received_signal


def _get_interrupt_exit_reason() -> LoopExitReason:
    """Determine the appropriate LoopExitReason for a signal interrupt.

    Maps the received signal number to the corresponding exit reason.
    Called when shutdown_requested() is True to determine which
    interrupt type caused the shutdown.

    Returns:
        LoopExitReason.INTERRUPTED_SIGINT for SIGINT (2)
        LoopExitReason.INTERRUPTED_SIGTERM for SIGTERM (15)
        LoopExitReason.INTERRUPTED_SIGINT as default if signal is unknown

    """
    sig = get_received_signal()
    if sig == signal.SIGTERM:
        return LoopExitReason.INTERRUPTED_SIGTERM
    # Default to SIGINT for SIGINT or any unknown signal
    return LoopExitReason.INTERRUPTED_SIGINT


# =============================================================================
# Signal Handlers - Story 6.6
# =============================================================================


def _handle_sigint(signum: int, frame: FrameType | None) -> None:
    """Handle SIGINT (Ctrl+C) signal with immediate hard kill.

    Kills all child processes (including those in separate sessions)
    and exits immediately. No graceful shutdown, no waiting for loops.

    Args:
        signum: Signal number (always signal.SIGINT=2).
        frame: Current stack frame (unused).

    """
    from bmad_assist.providers.base import kill_all_child_pgids

    # Kill child processes in separate sessions (start_new_session=True)
    kill_all_child_pgids()
    # Kill our own process group
    pid = os.getpid()
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    # Hard exit - no cleanup, no atexit handlers
    os._exit(130)  # 128 + SIGINT(2) = 130


def _handle_sigterm(signum: int, frame: FrameType | None) -> None:
    """Handle SIGTERM (kill) signal with immediate hard kill.

    Kills all child processes (including those in separate sessions)
    and exits immediately.

    Args:
        signum: Signal number (always signal.SIGTERM=15).
        frame: Current stack frame (unused).

    """
    from bmad_assist.providers.base import kill_all_child_pgids

    kill_all_child_pgids()
    pid = os.getpid()
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    os._exit(143)  # 128 + SIGTERM(15) = 143


def register_signal_handlers() -> None:
    """Register signal handlers for immediate hard kill on Ctrl+C.

    Installs handlers for SIGINT and SIGTERM that immediately kill
    all child processes and exit. No graceful shutdown.

    Must be called from the main thread (signal.signal() requirement).

    Raises:
        StateError: If not called from the main thread.

    """
    # Validate main thread - signal.signal() only works from main thread
    if threading.current_thread() is not threading.main_thread():
        raise StateError(
            "Signal handlers can only be registered from the main thread. "
            "Ensure run_loop() is called from the main thread."
        )

    global _previous_sigint_handler, _previous_sigterm_handler

    _previous_sigint_handler = signal.signal(signal.SIGINT, _handle_sigint)
    _previous_sigterm_handler = signal.signal(signal.SIGTERM, _handle_sigterm)


def unregister_signal_handlers() -> None:
    """Restore previous signal handlers.

    Restores handlers that were active before register_signal_handlers()
    was called. This preserves test runner handlers and CLI framework
    handlers that may have been installed.

    Falls back to SIG_DFL if no previous handler was saved.

    """
    # Restore SIGINT handler
    if _previous_sigint_handler is not None:
        signal.signal(signal.SIGINT, _previous_sigint_handler)
    else:
        signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Restore SIGTERM handler
    if _previous_sigterm_handler is not None:
        signal.signal(signal.SIGTERM, _previous_sigterm_handler)
    else:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
