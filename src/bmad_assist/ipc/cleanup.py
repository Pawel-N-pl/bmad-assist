"""IPC socket cleanup utilities for stale socket detection and removal.

Story 29.6: Socket cleanup on crash — defense-in-depth cleanup strategy.

Provides:
- Stale socket detection via PID liveness and optional connect+ping probe
- Orphaned socket scanning and batch cleanup
- Signal-safe cleanup for use from signal handlers
- Module-level active socket tracking for signal handler access
- Startup cleanup for project-specific stale sockets
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from bmad_assist.core.loop.locking import _is_pid_alive
from bmad_assist.ipc.protocol import (
    SOCKET_DIR,
    compute_project_hash,
    deserialize,
    read_message,
    write_message,
)

__all__ = [
    "is_socket_stale",
    "read_socket_pid",
    "find_orphaned_sockets",
    "cleanup_socket",
    "cleanup_orphaned_sockets",
    "cleanup_stale_sockets_on_startup",
    "set_active_socket",
    "get_active_socket",
    "clear_active_socket",
    "signal_safe_cleanup",
]

logger = logging.getLogger(__name__)

# =============================================================================
# Module-level active socket tracking (AC #10)
# =============================================================================

# Thread-safe via GIL — simple assignment is atomic in CPython.
# Signal handlers read this variable for best-effort cleanup.
_active_socket_path: Path | None = None

# Pre-allocated string versions for signal-safe cleanup.
# Avoids str() conversion and string concatenation inside signal handlers.
_active_socket_path_str: str | None = None
_active_lock_path_str: str | None = None


def set_active_socket(path: Path) -> None:
    """Set the active socket path for signal handler cleanup.

    Called from _start_ipc_server() BEFORE server start to eliminate
    the window where a signal fires during start() with path still None.

    Pre-allocates string representations for signal-safe cleanup
    (avoids str() and string concatenation in signal handler context).

    Args:
        path: The socket file path to track.

    """
    global _active_socket_path, _active_socket_path_str, _active_lock_path_str
    _active_socket_path = path
    _active_socket_path_str = str(path)
    _active_lock_path_str = str(path) + ".lock"


def get_active_socket() -> Path | None:
    """Get the currently active socket path.

    Returns:
        The active socket path, or None if no server is running.

    """
    return _active_socket_path


def clear_active_socket() -> None:
    """Clear the active socket path.

    Called from run_loop()'s IPC finally block unconditionally.
    """
    global _active_socket_path, _active_socket_path_str, _active_lock_path_str
    _active_socket_path = None
    _active_socket_path_str = None
    _active_lock_path_str = None


# =============================================================================
# Signal-safe cleanup (AC #3)
# =============================================================================


def signal_safe_cleanup() -> None:
    """Best-effort socket cleanup from signal handler context.

    ASYNC-SIGNAL-SAFE: Only uses os.unlink() with pre-allocated strings —
    no pathlib, no logging, no memory allocation, no locks, no function
    calls into Python's import machinery.

    Called from SIGINT/SIGTERM/SIGHUP handlers via pre-stored reference.
    """
    # Read pre-allocated strings (atomic in CPython via GIL)
    sock_str = _active_socket_path_str
    lock_str = _active_lock_path_str
    if sock_str is None:
        return
    try:
        os.unlink(sock_str)
    except OSError:
        pass
    if lock_str is not None:
        try:
            os.unlink(lock_str)
        except OSError:
            pass


# =============================================================================
# Socket lock file reading
# =============================================================================


def read_socket_pid(lock_path: Path) -> int | None:
    """Read PID from a socket lock file.

    Socket lock files contain PID on the first line and ISO timestamp
    on the second line.

    Args:
        lock_path: Path to the .sock.lock file.

    Returns:
        PID as integer, or None if lock file doesn't exist or is invalid.

    """
    try:
        content = lock_path.read_text().strip()
        return int(content.split("\n")[0].strip())
    except (OSError, ValueError, IndexError):
        return None


# Backward-compatible alias for internal callers
_read_socket_lock_pid = read_socket_pid


# =============================================================================
# Connect+ping probe (AC #1)
# =============================================================================


async def _probe_socket(socket_path: Path) -> bool:
    """Try to connect and ping a socket. Returns True if alive.

    Sends a JSON-RPC ping request and checks for a pong response.
    Times out after 2 seconds.

    Args:
        socket_path: Path to the Unix domain socket.

    Returns:
        True if socket responds to ping, False otherwise.

    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(socket_path)),
            timeout=2.0,
        )
        try:
            request: dict[str, Any] = {"jsonrpc": "2.0", "method": "ping", "id": 1}
            await write_message(writer, request)
            raw = await asyncio.wait_for(read_message(reader), timeout=2.0)
            msg = deserialize(raw)
            return msg.get("result", {}).get("pong") is True
        finally:
            writer.close()
            await writer.wait_closed()
    except (OSError, asyncio.TimeoutError, ConnectionError, ValueError):
        return False


def _run_probe_sync(socket_path: Path) -> bool:
    """Bridge async probe to sync context via dedicated thread event loop.

    Uses ThreadPoolExecutor to avoid RuntimeError when called from
    an already-running event loop (e.g., inside pytest-asyncio).

    Args:
        socket_path: Path to the Unix domain socket.

    Returns:
        True if socket responds to ping, False otherwise.

    """
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        try:
            return ex.submit(asyncio.run, _probe_socket(socket_path)).result(timeout=3.0)
        except (OSError, asyncio.TimeoutError, concurrent.futures.TimeoutError, RuntimeError):
            return False


# =============================================================================
# Stale socket detection (AC #1)
# =============================================================================


def is_socket_stale(socket_path: Path, probe: bool = False) -> bool:
    """Check if a socket file is stale (orphaned from a dead process).

    Reads the corresponding .lock file PID and verifies process liveness.
    If no lock file exists, the socket is treated as stale.
    If PID is alive and probe=True, attempts a connect+ping probe.

    Args:
        socket_path: Path to the .sock file.
        probe: If True and PID is alive, attempt connect+ping verification.

    Returns:
        True if the socket is stale (should be cleaned up), False if active.

    """
    lock_path = Path(f"{socket_path}.lock")

    if not lock_path.exists():
        return True

    pid = read_socket_pid(lock_path)

    if pid is None:
        # Invalid lock file content
        return True

    if not _is_pid_alive(pid):
        return True

    # PID is alive — socket is likely active
    if probe:
        # Attempt connect+ping to verify (handles PID reuse edge case)
        if not _run_probe_sync(socket_path):
            return True

    return False


# =============================================================================
# Orphaned socket scanning (AC #1)
# =============================================================================


def find_orphaned_sockets() -> list[tuple[Path, int | None, str]]:
    """Scan socket directory for orphaned (stale) socket files.

    Checks each .sock file in ~/.bmad-assist/sockets/ for staleness
    by reading the lock file PID and verifying process liveness.

    Returns:
        List of (socket_path, pid, reason) tuples for stale sockets.
        Reasons: "no_lock_file", "process_dead", "connect_failed".

    """
    socket_dir = SOCKET_DIR.expanduser()
    if not socket_dir.exists():
        return []

    orphans: list[tuple[Path, int | None, str]] = []
    for sock_file in sorted(socket_dir.glob("*.sock")):
        lock_path = Path(f"{sock_file}.lock")

        if not lock_path.exists():
            orphans.append((sock_file, None, "no_lock_file"))
            continue

        pid = read_socket_pid(lock_path)

        if pid is None or not _is_pid_alive(pid):
            orphans.append((sock_file, pid, "process_dead"))
            continue

        # PID alive — not orphaned for basic scan
        # (connect_failed reason only used with force/probe mode)

    return orphans


# =============================================================================
# Socket cleanup (AC #1)
# =============================================================================


def cleanup_socket(socket_path: Path) -> bool:
    """Remove a socket file and its corresponding lock file.

    Uses unlink(missing_ok=True) so it's safe to call even if
    files were already removed.

    Args:
        socket_path: Path to the .sock file.

    Returns:
        True if any file was removed, False if neither existed.

    """
    removed = False
    lock_path = Path(f"{socket_path}.lock")

    try:
        socket_path.unlink()
        removed = True
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Failed to remove socket file %s: %s", socket_path, e)

    try:
        lock_path.unlink()
        removed = True
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Failed to remove lock file %s: %s", lock_path, e)

    return removed


def cleanup_orphaned_sockets(force: bool = False) -> list[Path]:
    """Find and remove orphaned socket files.

    Decision matrix:
    - no_lock_file → always remove (regardless of force)
    - process_dead → always remove
    - connect_failed → only remove when force=True

    When force=True, also probes sockets with live PIDs and removes
    those that fail the connect+ping check.

    Args:
        force: If True, also remove sockets that fail connect probe
               even if PID appears alive.

    Returns:
        List of socket paths that were cleaned up.

    """
    cleaned: list[Path] = []

    # Get standard orphans (no_lock_file, process_dead)
    orphans = find_orphaned_sockets()

    for sock_path, pid, reason in orphans:
        if reason == "connect_failed" and not force:
            continue
        if cleanup_socket(sock_path):
            logger.warning(
                "Removed orphaned socket %s (PID=%s, reason=%s)",
                sock_path.name,
                pid,
                reason,
            )
            cleaned.append(sock_path)

    # If force=True, also probe live-PID sockets
    if force:
        socket_dir = SOCKET_DIR.expanduser()
        if socket_dir.exists():
            for sock_file in sorted(socket_dir.glob("*.sock")):
                # Skip already cleaned
                if sock_file in cleaned:
                    continue
                # Skip sockets that passed basic check
                lock_path = Path(f"{sock_file}.lock")
                if not lock_path.exists():
                    continue
                pid = read_socket_pid(lock_path)
                if pid is None or not _is_pid_alive(pid):
                    continue
                # PID alive — probe to verify
                if not _run_probe_sync(sock_file):
                    if cleanup_socket(sock_file):
                        logger.warning(
                            "Removed orphaned socket %s (PID=%s, reason=connect_failed)",
                            sock_file.name,
                            pid,
                        )
                        cleaned.append(sock_file)

    return cleaned


# =============================================================================
# Startup cleanup (AC #9)
# =============================================================================


def cleanup_stale_sockets_on_startup(project_root: Path) -> None:
    """Remove stale socket for the current project on startup.

    Called from _start_ipc_server() before server creation. Only removes
    the socket matching the current project hash (not all sockets).

    This covers the case where a previous signal handler cleanup failed
    (e.g., SIGKILL which bypasses all handlers).

    Args:
        project_root: Path to the project root directory.

    """
    project_hash = compute_project_hash(project_root)
    socket_dir = SOCKET_DIR.expanduser()

    if not socket_dir.exists():
        return

    sock_path = socket_dir / f"{project_hash}.sock"
    if not sock_path.exists():
        return

    if is_socket_stale(sock_path):
        logger.warning(
            "Removing stale socket for project %s on startup: %s",
            project_root.name,
            sock_path.name,
        )
        cleanup_socket(sock_path)
