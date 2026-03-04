"""IPC instance discovery via socket enumeration and state probing.

Story 29.8: Finds running bmad-assist instances by scanning socket files,
reading lock files for PIDs, and probing live sockets for runner state.
Story 29.11: Adds DiscoveryService with background polling and change-detection
callbacks for Epic 31 multi-instance dashboard.

Provides:
- DiscoveredInstance frozen dataclass for discovered instance metadata
- discover_instances_async() for async consumers (Epic 31)
- discover_instances() sync wrapper for CLI context
- DiscoveryService for background polling with add/remove callbacks
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from bmad_assist.ipc.cleanup import is_socket_stale, read_socket_pid
from bmad_assist.ipc.protocol import (
    IPCError,
    SOCKET_DIR,
    deserialize,
    read_message,
    write_message,
)

__all__ = [
    "DiscoveredInstance",
    "DiscoveryService",
    "discover_instances",
    "discover_instances_async",
    "probe_instance",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredInstance:
    """Metadata for a discovered running bmad-assist instance.

    Attributes:
        socket_path: Absolute path to the .sock file.
        project_hash: The 32-char hex hash from the socket filename (stem).
        pid: PID from the .lock file (None if lock missing/invalid).
        state: The get_state response dict from the runner (empty dict if
            ping succeeded but get_state failed).
        discovered_at: UTC timestamp of when this scan completed.
        last_seen: UTC timestamp of the most recent scan confirming this
            instance is alive. For one-shot callers, equals discovered_at.
            The DiscoveryService updates this on each re-confirmation scan.

    """

    socket_path: Path
    project_hash: str
    pid: int | None
    state: dict[str, Any] = field(default_factory=dict)
    discovered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))


async def probe_instance(
    socket_path: Path, timeout: float
) -> dict[str, Any] | None:
    """Connect to a socket, ping, get_state, and disconnect.

    Public API for probing a single socket's runner state.

    Args:
        socket_path: Path to the Unix domain socket.
        timeout: Timeout in seconds for each network operation.

    Returns:
        The get_state result dict if both ping and get_state succeed,
        empty dict ``{}`` if ping succeeded but get_state failed (AC #2),
        or None if connection/ping failed entirely.

    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(socket_path)),
            timeout=timeout,
        )
    except asyncio.CancelledError:
        raise
    except (OSError, asyncio.TimeoutError, ConnectionError):
        return None

    try:
        # Send ping first to verify the server is alive
        ping_request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": "ping",
            "params": {},
            "id": 1,
        }
        await write_message(writer, ping_request)
        raw = await asyncio.wait_for(read_message(reader), timeout=timeout)
        ping_response = deserialize(raw)

        if ping_response.get("result", {}).get("pong") is not True:
            return None

        # Now send get_state — if this fails, return {} per AC #2
        # (ping succeeded so instance is alive, just state fetch failed)
        try:
            state_request: dict[str, Any] = {
                "jsonrpc": "2.0",
                "method": "get_state",
                "params": {},
                "id": 2,
            }
            await write_message(writer, state_request)
            raw = await asyncio.wait_for(read_message(reader), timeout=timeout)
            state_response = deserialize(raw)
            return state_response.get("result", {})
        except asyncio.CancelledError:
            raise
        except (OSError, asyncio.TimeoutError, ConnectionError, ValueError, IPCError):
            return {}  # Ping succeeded but get_state failed → AC #2

    except asyncio.CancelledError:
        raise
    except (OSError, asyncio.TimeoutError, ConnectionError, ValueError, IPCError):
        return None
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except (OSError, ConnectionError):
            pass


async def discover_instances_async(
    probe_timeout: float = 2.0,
) -> list[DiscoveredInstance]:
    """Discover running bmad-assist instances by scanning sockets.

    Scans ~/.bmad-assist/sockets/ for .sock files, filters out stale
    sockets (dead PIDs), and probes live sockets concurrently for
    their runner state using asyncio.gather().

    Args:
        probe_timeout: Timeout in seconds for each socket probe.

    Returns:
        List of DiscoveredInstance sorted by socket_path.
        Empty list if socket directory doesn't exist or contains
        only stale sockets.

    """
    socket_dir = SOCKET_DIR.expanduser()
    try:
        if not socket_dir.exists():
            return []
    except PermissionError:
        return []

    sock_files = sorted(socket_dir.glob("*.sock"))
    if not sock_files:
        return []

    # Filter stale sockets and collect candidates for probing
    candidates: list[tuple[Path, str, int | None]] = []
    for sock_path in sock_files:
        if is_socket_stale(sock_path):
            continue
        project_hash = sock_path.stem
        lock_path = Path(f"{sock_path}.lock")
        pid = read_socket_pid(lock_path)
        candidates.append((sock_path, project_hash, pid))

    if not candidates:
        return []

    # Probe all candidates concurrently
    probe_coros = [
        probe_instance(sock_path, probe_timeout)
        for sock_path, _, _ in candidates
    ]
    results = await asyncio.gather(*probe_coros, return_exceptions=True)

    instances: list[DiscoveredInstance] = []
    scan_time = datetime.now(UTC)

    for (sock_path, project_hash, pid), result in zip(candidates, results):
        if isinstance(result, BaseException):
            # Probe raised an exception — skip this socket
            logger.debug(
                "Probe failed for socket %s: %s", sock_path.name, result
            )
            continue

        if result is None:
            # Probe returned None — socket didn't respond to ping
            continue

        # result is dict (may be {} if ping OK but get_state failed — AC #2)
        # Both discovered_at and last_seen set from same timestamp (AC #5)
        instances.append(
            DiscoveredInstance(
                socket_path=sock_path,
                project_hash=project_hash,
                pid=pid,
                state=result,
                discovered_at=scan_time,
                last_seen=scan_time,
            )
        )

    # Already iterated in sorted order from candidates, but re-sort
    # to guarantee deterministic output regardless of gather ordering
    instances.sort(key=lambda i: i.socket_path)
    return instances


def discover_instances(probe_timeout: float = 2.0) -> list[DiscoveredInstance]:
    """Discover running bmad-assist instances (sync wrapper).

    Calls discover_instances_async() via asyncio.run(). Safe for CLI
    context where no event loop is running. Do NOT call from within
    an already-running event loop (e.g., dashboard, run_loop).

    Args:
        probe_timeout: Timeout in seconds for each socket probe.

    Returns:
        List of DiscoveredInstance sorted by socket_path.

    """
    return asyncio.run(discover_instances_async(probe_timeout))


class DiscoveryService:
    """Background service that polls for running bmad-assist instances.

    Runs a daemon thread with periodic discovery scans, maintains a
    thread-safe instance list, and fires callbacks on instance add/remove.

    Args:
        poll_interval: Seconds between automatic scans (default: 5.0).
        probe_timeout: Timeout per socket probe in seconds (default: 2.0).

    """

    def __init__(
        self,
        poll_interval: float = 5.0,
        probe_timeout: float = 2.0,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if probe_timeout <= 0:
            raise ValueError("probe_timeout must be positive")
        self._poll_interval = poll_interval
        self._probe_timeout = probe_timeout
        self._instances: list[DiscoveredInstance] = []
        self._lock = threading.Lock()
        self._prev_paths: set[Path] = set()
        # Map socket_path -> DiscoveredInstance for last_seen tracking
        self._instance_map: dict[Path, DiscoveredInstance] = {}
        self._added_callbacks: list[Callable[[DiscoveredInstance], None]] = []
        self._removed_callbacks: list[Callable[[Path], None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_event: asyncio.Event | None = None
        self._refresh_event: asyncio.Event | None = None
        self._started = threading.Event()
        self._start_error: BaseException | None = None

    def start(self) -> None:
        """Start the background polling thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._started.clear()
        self._start_error = None
        self._thread = threading.Thread(
            target=self._run_poll_loop,
            name="ipc-discovery",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(timeout=5.0):
            self.stop()
            raise RuntimeError("DiscoveryService failed to start within timeout")
        if self._start_error is not None:
            self.stop()
            raise self._start_error

    def stop(self, timeout: float = 5.0) -> None:
        """Stop polling and join the thread."""
        loop = self._loop
        if loop is not None and self._stop_event is not None:
            loop.call_soon_threadsafe(self._stop_event.set)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None
        self._loop = None

    def get_instances(self) -> list[DiscoveredInstance]:
        """Return a thread-safe snapshot of discovered instances."""
        with self._lock:
            return list(self._instances)

    def refresh(self) -> list[DiscoveredInstance]:
        """Trigger immediate scan and return updated instances.

        Dispatches a scan on the polling thread's event loop and blocks
        until it completes. Resets the poll timer so the next automatic
        scan starts from a fresh interval.

        Returns:
            Updated list of discovered instances.

        Raises:
            RuntimeError: If the service is not running.

        """
        loop = self._loop
        if loop is None or self._refresh_event is None:
            raise RuntimeError("DiscoveryService is not running")

        # Schedule scan directly and wait for completion.
        # Also signal refresh_event to reset the poll timer so the
        # next automatic scan starts from a fresh interval.
        future = asyncio.run_coroutine_threadsafe(
            self._do_scan(), loop
        )
        loop.call_soon_threadsafe(self._refresh_event.set)

        max_timeout = self._probe_timeout + self._poll_interval + 2.0
        try:
            future.result(timeout=max_timeout)
        except concurrent.futures.TimeoutError:
            logger.warning("DiscoveryService refresh timed out")
        except concurrent.futures.CancelledError:
            logger.debug("DiscoveryService refresh cancelled")

        return self.get_instances()

    def on_added(self, callback: Callable[[DiscoveredInstance], None]) -> None:
        """Register a callback for newly discovered instances."""
        self._added_callbacks.append(callback)

    def on_removed(self, callback: Callable[[Path], None]) -> None:
        """Register a callback for removed instances."""
        self._removed_callbacks.append(callback)

    def __enter__(self) -> DiscoveryService:
        """Start the service as a context manager."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Stop the service on context exit."""
        self.stop()

    def _run_poll_loop(self) -> None:
        """Thread target: run asyncio event loop with periodic scanning."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._stop_event = asyncio.Event()
            self._refresh_event = asyncio.Event()
            self._started.set()
            self._loop.run_until_complete(self._poll_loop())
        except Exception as exc:
            self._start_error = exc
            self._started.set()
        finally:
            loop = self._loop
            if loop is not None:
                try:
                    # Drain pending tasks
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except RuntimeError:
                    pass
                loop.close()
            self._loop = None

    async def _poll_loop(self) -> None:
        """Async polling loop: scan, detect changes, sleep."""
        if self._stop_event is None or self._refresh_event is None:
            raise RuntimeError("_poll_loop called before events initialized")

        while not self._stop_event.is_set():
            await self._do_scan()
            # Wait for poll_interval OR early wakeup from refresh/stop
            try:
                await asyncio.wait_for(
                    self._wait_for_wakeup(),
                    timeout=self._poll_interval,
                )
            except asyncio.TimeoutError:
                pass  # Normal timeout — next scan cycle

    async def _wait_for_wakeup(self) -> None:
        """Wait until either stop or refresh event is set."""
        if self._stop_event is None or self._refresh_event is None:
            raise RuntimeError("_wait_for_wakeup called before events initialized")

        stop_task = asyncio.create_task(self._stop_event.wait())
        refresh_task = asyncio.create_task(self._refresh_event.wait())
        try:
            done, pending = await asyncio.wait(
                {stop_task, refresh_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        finally:
            # Clear refresh event for next cycle (don't clear stop)
            self._refresh_event.clear()

    async def _do_scan(self) -> None:
        """Execute a single discovery scan with change detection."""
        try:
            current_instances = await discover_instances_async(
                probe_timeout=self._probe_timeout
            )
        except (OSError, RuntimeError) as exc:
            logger.debug("Discovery scan failed: %s", exc)
            return

        scan_time = datetime.now(UTC)
        current_paths = {inst.socket_path for inst in current_instances}

        # Snapshot previous state under lock for safe comparison
        with self._lock:
            prev_paths = self._prev_paths
            prev_map = self._instance_map

        # Detect additions and removals
        added_paths = current_paths - prev_paths
        removed_paths = prev_paths - current_paths

        # Build updated instance list with last_seen tracking
        updated_instances: list[DiscoveredInstance] = []
        updated_map: dict[Path, DiscoveredInstance] = {}

        for inst in current_instances:
            if inst.socket_path in added_paths:
                # New instance — use as-is (discovered_at and last_seen from scan)
                updated_instances.append(inst)
                updated_map[inst.socket_path] = inst
            else:
                # Re-confirmed instance — preserve original discovered_at,
                # update last_seen
                prev = prev_map.get(inst.socket_path)
                if prev is not None:
                    updated_inst = dataclasses.replace(
                        inst,
                        discovered_at=prev.discovered_at,
                        last_seen=scan_time,
                    )
                else:
                    updated_inst = dataclasses.replace(
                        inst, last_seen=scan_time
                    )
                updated_instances.append(updated_inst)
                updated_map[inst.socket_path] = updated_inst

        # Update thread-safe state (all mutable bookkeeping under one lock)
        with self._lock:
            self._instances = updated_instances
            self._prev_paths = current_paths
            self._instance_map = updated_map

        # Fire callbacks (fire-and-forget, never crash polling thread)
        for path in added_paths:
            inst = updated_map.get(path)
            if inst is not None:
                for callback in self._added_callbacks:
                    try:
                        callback(inst)
                    except Exception:
                        logger.warning(
                            "on_added callback error for %s",
                            path.name,
                            exc_info=True,
                        )

        for path in removed_paths:
            for callback in self._removed_callbacks:
                try:
                    callback(path)
                except Exception:
                    logger.warning(
                        "on_removed callback error for %s",
                        path.name,
                        exc_info=True,
                    )
