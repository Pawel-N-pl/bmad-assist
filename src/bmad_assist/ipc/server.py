"""IPC socket server for bmad-assist JSON-RPC 2.0 protocol.

Story 29.2: Async Unix domain socket server embedded within LoopRunner
that starts automatically when a run begins and accepts client connections
for real-time monitoring and control.

The server runs in a dedicated daemon thread with its own asyncio event loop,
since run_loop() is synchronous and blocking. Communication between the main
thread and server thread uses thread-safe primitives.
"""

from __future__ import annotations

import asyncio
import atexit
import itertools
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from bmad_assist import __version__
from bmad_assist.core.exceptions import StateError
from bmad_assist.core.loop.locking import _is_pid_alive
from bmad_assist.ipc.protocol import (
    IDLE_TIMEOUT,
    MAX_CONNECTIONS,
    MAX_MESSAGE_SIZE,
    MAX_PARSE_ERRORS,
    PROTOCOL_VERSION,
    SUPPORTED_METHODS,
    ErrorCode,
    IPCError,
    MessageTooLargeError,
    deserialize,
    get_socket_dir,
    make_error_response,
    validate_socket_path_length,
    make_event,
    read_message,
    write_message,
)
from bmad_assist.ipc.types import (
    EventPriority,
    GetCapabilitiesResult,
    GetStateResult,
    PingResult,
    RunnerState,
    get_event_priority,
)

__all__ = [
    "SocketServer",
    "IPCServerThread",
    "CommandHandler",
]

logger = logging.getLogger(__name__)

# Broadcast write timeout per client (seconds)
_BROADCAST_WRITE_TIMEOUT = 1.0

# Backpressure threshold (bytes) — matches MAX_MESSAGE_SIZE
_BACKPRESSURE_THRESHOLD = MAX_MESSAGE_SIZE


# =============================================================================
# CommandHandler Protocol (stub for Story 29.5)
# =============================================================================


class CommandHandler(Protocol):
    """Protocol for IPC command handling (fully implemented in Story 29.5)."""

    async def __call__(
        self, method: str, params: dict[str, Any], request_id: str | int
    ) -> dict[str, Any]:
        """Handle a JSON-RPC method call and return result dict.

        Args:
            method: The JSON-RPC method name (e.g., "ping", "get_state").
            params: The params dict from the request.
            request_id: The request ID for response correlation.

        Returns:
            Result dict suitable for wrapping in RPCResponse.

        Raises:
            IPCError: If method execution fails.

        """
        ...


# =============================================================================
# SocketServer
# =============================================================================


class SocketServer:
    """Async Unix domain socket server for JSON-RPC 2.0 IPC.

    Handles multiple concurrent client connections with per-connection
    message loops, method routing, and event broadcast capability.

    Args:
        socket_path: Path where the Unix domain socket will be created.
        project_root: Path to the project root directory.
        handler: Optional command handler callback for routing methods.

    """

    def __init__(
        self,
        socket_path: Path,
        project_root: Path,
        handler: CommandHandler | None = None,
    ) -> None:
        self._socket_path = socket_path
        self._project_root = project_root
        self._handler = handler
        self._server: asyncio.AbstractServer | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._client_ids: dict[asyncio.StreamWriter, str] = {}
        self._is_running = False
        self._lock_path = Path(f"{socket_path}.lock")
        self._event_seq = itertools.count(1)
        self._state_lock = threading.Lock()
        self._runner_state: RunnerState = RunnerState.IDLE
        self._runner_state_data: dict[str, Any] = {}
        logger.debug("SocketServer created for %s", socket_path)

    @property
    def is_running(self) -> bool:
        """Whether the server is currently listening for connections."""
        return self._is_running

    @property
    def client_count(self) -> int:
        """Number of currently connected clients."""
        return len(self._clients)

    def update_runner_state(
        self,
        state: RunnerState | None = None,
        state_data: dict[str, Any] | None = None,
    ) -> None:
        """Update the cached runner state for get_state queries.

        Thread-safe: uses a lock to ensure atomic reads/writes between
        the main thread (writer) and server thread (reader).

        Args:
            state: New runner state, or None to keep current.
            state_data: New state data dict, or None to keep current.

        """
        with self._state_lock:
            if state is not None:
                self._runner_state = state
            if state_data is not None:
                self._runner_state_data = state_data.copy()

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the socket server and begin accepting connections.

        Creates the socket directory (via get_socket_dir()), checks for stale
        sockets, creates the Unix domain socket with 0600 permissions, and
        writes a PID lock file.

        Raises:
            StateError: If a live process already owns the socket.
            IPCError: If socket directory creation fails or socket path
                exceeds the 107-byte sun_path limit.

        """
        if self._is_running:
            logger.warning("Server already running, ignoring start()")
            return

        # Ensure socket directory exists (0700 permissions)
        get_socket_dir()

        # Check for stale socket
        self._check_stale_socket()

        # Story 29.7: Validate socket path length (107-byte sun_path limit)
        validate_socket_path_length(self._socket_path)

        # Start the async Unix server
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self._socket_path),
        )

        try:
            # Set socket file permissions to 0600 (owner read/write only)
            os.chmod(self._socket_path, 0o600)

            # Write PID lock file (atomic)
            self._write_lock_file()
        except OSError:
            # Cleanup partially started server to prevent resource leak
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            raise

        self._is_running = True
        logger.info(
            "IPC server started on %s (PID %d)",
            self._socket_path,
            os.getpid(),
        )

    async def stop(self) -> None:
        """Stop the server, close all connections, and clean up files.

        Closes all client connections first, then the server, then removes
        the socket file and lock file.
        """
        if not self._is_running:
            return

        self._is_running = False
        logger.info("IPC server stopping...")

        # Close all client connections (with timeout to avoid hanging on bad clients)
        for writer in list(self._clients):
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except (asyncio.TimeoutError, OSError, ConnectionError):
                pass
        self._clients.clear()
        self._client_ids.clear()

        # Close the server
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Remove socket file
        try:
            if self._socket_path.exists():
                self._socket_path.unlink()
                logger.debug("Removed socket file: %s", self._socket_path)
        except OSError as e:
            logger.warning("Failed to remove socket file: %s", e)

        # Remove lock file
        try:
            if self._lock_path.exists():
                self._lock_path.unlink()
                logger.debug("Removed lock file: %s", self._lock_path)
        except OSError as e:
            logger.warning("Failed to remove lock file: %s", e)

        logger.info("IPC server stopped")

    # -------------------------------------------------------------------------
    # Stale socket detection
    # -------------------------------------------------------------------------

    def _check_stale_socket(self) -> None:
        """Check for existing socket file and remove if stale.

        Reads the .lock PID file and checks if the owning process is alive.
        If dead, removes both .sock and .lock files. If alive, raises StateError.

        Raises:
            StateError: If a live process already owns the socket.

        """
        if not self._socket_path.exists():
            return

        # Try to read the lock file
        pid = self._read_socket_lock_pid()

        if pid is not None and _is_pid_alive(pid):
            raise StateError(
                f"Another IPC server is already running (PID {pid}) "
                f"on socket {self._socket_path}. "
                "If this is incorrect, remove the stale socket files."
            )

        # Stale socket — remove
        logger.warning(
            "Removing stale socket (PID %s is dead): %s",
            pid,
            self._socket_path,
        )
        try:
            self._socket_path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("Failed to remove stale socket: %s", e)
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("Failed to remove stale lock: %s", e)

    def _read_socket_lock_pid(self) -> int | None:
        """Read PID from the socket lock file.

        Returns:
            PID as integer, or None if lock file doesn't exist or is invalid.

        """
        try:
            content = self._lock_path.read_text().strip()
            return int(content.split("\n")[0].strip())
        except (OSError, ValueError, IndexError):
            return None

    def _write_lock_file(self) -> None:
        """Write PID lock file using atomic pattern."""
        temp_path = self._lock_path.with_suffix(".tmp")
        try:
            content = f"{os.getpid()}\n{datetime.now(UTC).isoformat()}\n"
            temp_path.write_text(content)
            os.replace(temp_path, self._lock_path)
        except OSError as e:
            logger.warning("Failed to write lock file: %s", e)
            # Clean up temp file
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    # -------------------------------------------------------------------------
    # Connection handling
    # -------------------------------------------------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection.

        Tracks connection, runs per-connection message loop, and cleans up
        on disconnect.

        Args:
            reader: Client stream reader.
            writer: Client stream writer.

        """
        # Check connection limit
        if len(self._clients) >= MAX_CONNECTIONS:
            logger.warning(
                "Connection limit reached (%d), rejecting new client",
                MAX_CONNECTIONS,
            )
            try:
                error_resp = make_error_response(
                    None,
                    ErrorCode.RUNNER_BUSY,
                    data={"reason": "max_connections_reached", "limit": MAX_CONNECTIONS},
                )
                await write_message(writer, error_resp)
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            return

        # Track the connection
        self._clients.add(writer)
        peer = writer.get_extra_info("peername", "unknown")
        client_id = f"client-{id(writer)}"
        self._client_ids[writer] = client_id
        logger.info("Client connected: %s (total: %d)", peer, len(self._clients))

        parse_error_count = 0
        loop = asyncio.get_running_loop()
        last_activity = loop.time()

        try:
            while self._is_running:
                try:
                    # Wait for message with idle timeout
                    raw = await asyncio.wait_for(
                        read_message(reader),
                        timeout=IDLE_TIMEOUT,
                    )
                    last_activity = loop.time()

                except asyncio.TimeoutError:
                    # Idle timeout — close connection
                    elapsed = loop.time() - last_activity
                    logger.info(
                        "Client idle timeout (%.0fs), closing: %s",
                        elapsed,
                        peer,
                    )
                    break

                except asyncio.IncompleteReadError:
                    # Client disconnected mid-message — normal
                    logger.debug("Client disconnected: %s", peer)
                    break

                except MessageTooLargeError as e:
                    # Message too large — send error but keep connection
                    logger.warning("Message too large from %s: %s", peer, e)
                    error_resp = make_error_response(
                        None,
                        ErrorCode.PARSE_ERROR,
                        data={"reason": "message_too_large", "size": e.size},
                    )
                    try:
                        await write_message(writer, error_resp)
                    except Exception:
                        break
                    continue

                except (ConnectionResetError, BrokenPipeError):
                    logger.debug("Client connection reset: %s", peer)
                    break

                # Parse the message
                try:
                    message = deserialize(raw)
                    parse_error_count = 0  # Reset on successful parse
                except IPCError as e:
                    parse_error_count += 1
                    logger.warning(
                        "Parse error #%d from %s: %s",
                        parse_error_count,
                        peer,
                        e,
                    )
                    error_resp = make_error_response(
                        None, ErrorCode.PARSE_ERROR
                    )
                    try:
                        await write_message(writer, error_resp)
                    except Exception:
                        break

                    if parse_error_count >= MAX_PARSE_ERRORS:
                        logger.warning(
                            "Too many parse errors (%d), closing: %s",
                            parse_error_count,
                            peer,
                        )
                        break
                    continue

                # Route the message
                response = await self._route_message(message)
                if response is not None:
                    try:
                        await write_message(writer, response)
                    except (ConnectionResetError, BrokenPipeError):
                        logger.debug("Client disconnected during write: %s", peer)
                        break

        except Exception as e:
            logger.warning("Unexpected error handling client %s: %s", peer, e)
        finally:
            # Clean up
            self._clients.discard(writer)
            self._client_ids.pop(writer, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info("Client disconnected: %s (total: %d)", peer, len(self._clients))

    # -------------------------------------------------------------------------
    # Method routing
    # -------------------------------------------------------------------------

    async def _route_message(
        self, message: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Route an incoming JSON-RPC request to the appropriate handler.

        Args:
            message: Deserialized JSON-RPC message dict.

        Returns:
            JSON-RPC response dict, or None for notifications.

        """
        # Validate basic JSON-RPC structure
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params", {})

        if not isinstance(method, str):
            return make_error_response(
                request_id, ErrorCode.INVALID_REQUEST,
                data={"reason": "missing or invalid 'method' field"},
            )

        # Notifications (no id) don't get responses
        if request_id is None and method != "event":
            return None

        # Route to handler
        if method == "ping":
            return self._handle_ping(request_id)
        elif method == "get_capabilities":
            return self._handle_get_capabilities(request_id)
        elif method == "get_state":
            return self._handle_get_state(request_id)
        elif method in SUPPORTED_METHODS:
            # Story 29.5: Dispatch to command handler
            if self._handler is None:
                return make_error_response(
                    request_id,
                    ErrorCode.INTERNAL_ERROR,
                    data={"reason": "No command handler configured"},
                )
            try:
                return await self._handler(method, params, request_id)
            except Exception as e:
                return make_error_response(
                    request_id,
                    ErrorCode.INTERNAL_ERROR,
                    data={"message": str(e)},
                )
        else:
            # Unknown method
            return make_error_response(
                request_id,
                ErrorCode.METHOD_NOT_FOUND,
                data={"method": method},
            )

    def _handle_ping(self, request_id: str | int | None) -> dict[str, Any]:
        """Handle ping request.

        Returns:
            JSON-RPC success response with PingResult.

        """
        result = PingResult(
            pong=True,
            server_time=datetime.now(UTC).isoformat(),
        )
        return {
            "jsonrpc": "2.0",
            "result": result.model_dump(),
            "id": request_id,
        }

    def _handle_get_capabilities(
        self, request_id: str | int | None
    ) -> dict[str, Any]:
        """Handle get_capabilities request.

        Feature flags are code-derived (not config-derived) and reflect
        actually-available protocol features. Downstream clients (e.g.,
        Epic 31's DiscoveryService) use these to detect capabilities
        without version string parsing.

        Returns:
            JSON-RPC success response with GetCapabilitiesResult.

        """
        result = GetCapabilitiesResult(
            protocol_version=PROTOCOL_VERSION,
            server_version=__version__,
            supported_methods=sorted(SUPPORTED_METHODS),
            connected_clients=list(self._client_ids.values()),
            features={
                "goodbye_event": True,
                "project_identity": True,
                "reload_config": True,
            },
        )
        return {
            "jsonrpc": "2.0",
            "result": result.model_dump(),
            "id": request_id,
        }

    def _handle_get_state(
        self, request_id: str | int | None
    ) -> dict[str, Any]:
        """Handle get_state request with current runner state.

        Returns:
            JSON-RPC success response with GetStateResult.

        """
        with self._state_lock:
            runner_state = self._runner_state
            state_data = self._runner_state_data.copy()

        is_running = runner_state == RunnerState.RUNNING
        is_paused = runner_state == RunnerState.PAUSED

        # Compute phase elapsed at request time from phase_started_at ISO timestamp
        phase_elapsed = 0.0
        phase_started_str = state_data.get("phase_started_at")
        if phase_started_str:
            try:
                from datetime import UTC, datetime

                phase_started = datetime.fromisoformat(phase_started_str)
                if phase_started.tzinfo is None:
                    phase_started = phase_started.replace(tzinfo=UTC)
                phase_elapsed = max(0.0, (datetime.now(UTC) - phase_started).total_seconds())
            except (ValueError, TypeError):
                pass

        # Read current log level from root logger (always fresh)
        import logging as _logging

        current_log_level = _logging.getLevelName(_logging.getLogger().level)

        result = GetStateResult(
            state=runner_state.value,
            running=is_running,
            paused=is_paused,
            current_epic=state_data.get("current_epic"),
            current_story=state_data.get("current_story"),
            current_phase=state_data.get("current_phase"),
            elapsed_seconds=state_data.get("elapsed_seconds", 0.0),
            phase_elapsed_seconds=phase_elapsed,
            llm_sessions=state_data.get("llm_sessions", 0),
            log_level=current_log_level,
            session_details=state_data.get("session_details", []),
            error=state_data.get("error"),
            # Story 29.9: Project identity (static, from server init)
            # Use resolve() to guarantee absolute path (AC says "absolute project root path")
            project_name=self._project_root.resolve().name,
            project_path=str(self._project_root.resolve()),
        )
        return {
            "jsonrpc": "2.0",
            "result": result.model_dump(),
            "id": request_id,
        }

    # -------------------------------------------------------------------------
    # Event broadcast
    # -------------------------------------------------------------------------

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Broadcast a JSON-RPC notification to all connected clients.

        Priority-aware backpressure: if a client's write buffer exceeds
        the threshold, drop lower-priority events. Never drop essential
        events; close slow connections instead.

        Args:
            event: JSON-RPC event notification dict (from make_event()).

        """
        if not self._clients:
            return

        # Determine event priority
        event_type = ""
        params = event.get("params", {})
        if isinstance(params, dict):
            event_type = params.get("type", "")
        priority = get_event_priority(event_type)

        disconnected: list[asyncio.StreamWriter] = []

        for writer in list(self._clients):
            try:
                # Check backpressure
                transport = writer.transport
                if transport is not None:
                    buffer_size = transport.get_write_buffer_size()
                    if buffer_size > _BACKPRESSURE_THRESHOLD:
                        if priority == EventPriority.LOGS:
                            # Drop low-priority events for slow clients
                            logger.debug(
                                "Dropping logs event for slow client (buffer=%d)",
                                buffer_size,
                            )
                            continue
                        elif priority == EventPriority.METRICS:
                            # Drop metrics for very slow clients
                            logger.debug(
                                "Dropping metrics event for slow client (buffer=%d)",
                                buffer_size,
                            )
                            continue
                        else:
                            # Essential event but buffer full — close slow connection
                            logger.warning(
                                "Closing slow client (buffer=%d, can't drop essential event)",
                                buffer_size,
                            )
                            disconnected.append(writer)
                            continue

                # Write with timeout to prevent blocking
                await asyncio.wait_for(
                    write_message(writer, event),
                    timeout=_BROADCAST_WRITE_TIMEOUT,
                )

            except asyncio.TimeoutError:
                logger.warning("Broadcast write timeout, marking client for removal")
                disconnected.append(writer)
            except (ConnectionResetError, BrokenPipeError, OSError):
                logger.debug("Client disconnected during broadcast")
                disconnected.append(writer)
            except Exception as e:
                logger.warning("Broadcast error: %s", e)
                disconnected.append(writer)

        # Clean up disconnected clients
        for writer in disconnected:
            self._clients.discard(writer)
            self._client_ids.pop(writer, None)
            try:
                writer.close()
            except Exception:
                pass

    def next_event_seq(self) -> int:
        """Get the next monotonically increasing event sequence number.

        Returns:
            Next sequence number (starts at 1).

        """
        return next(self._event_seq)


# =============================================================================
# IPCServerThread — Thread bridge for sync run_loop()
# =============================================================================


class IPCServerThread:
    """Thread bridge that runs SocketServer in a dedicated daemon thread.

    Manages a daemon thread with its own asyncio event loop, allowing
    the synchronous run_loop() to interact with the async SocketServer
    via thread-safe methods.

    Args:
        socket_path: Path for the Unix domain socket.
        project_root: Path to the project root directory.
        handler: Optional command handler for routing.

    """

    def __init__(
        self,
        socket_path: Path,
        project_root: Path,
        handler: CommandHandler | None = None,
    ) -> None:
        self._socket_path = socket_path
        self._project_root = project_root
        self._handler = handler
        self._server: SocketServer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._start_error: Exception | None = None
        self._atexit_registered = False

    @property
    def is_running(self) -> bool:
        """Whether the server is currently running. Thread-safe."""
        server = self._server
        return server is not None and server.is_running

    @property
    def client_count(self) -> int:
        """Number of currently connected clients. Thread-safe."""
        server = self._server
        return server.client_count if server is not None else 0

    def start(self, timeout: float = 5.0) -> None:
        """Start the IPC server in a daemon thread.

        Creates a new asyncio event loop in a daemon thread, starts the
        SocketServer on that loop, and waits for it to be ready.

        Args:
            timeout: Maximum seconds to wait for server to start.

        Raises:
            StateError: If server fails to start within timeout.
            StateError: If a stale socket from a live process is detected.

        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("IPCServerThread already running")
            return

        self._started.clear()
        self._start_error = None

        self._thread = threading.Thread(
            target=self._run_server_loop,
            name="ipc-server",
            daemon=True,
        )
        self._thread.start()

        # Wait for server to be ready
        if not self._started.wait(timeout):
            raise StateError(
                f"IPC server failed to start within {timeout}s"
            )

        if self._start_error is not None:
            raise self._start_error

        # Register atexit handler as backup cleanup
        if not self._atexit_registered:
            atexit.register(self._atexit_cleanup)
            self._atexit_registered = True

        logger.info("IPC server thread started")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the IPC server and join the daemon thread.

        Schedules SocketServer.stop() on the server loop, then stops
        the loop and joins the thread.

        Args:
            timeout: Maximum seconds to wait for server to stop.

        """
        if self._loop is None or self._server is None:
            return

        loop = self._loop

        if loop.is_closed():
            return

        # Schedule stop on the server loop
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._server.stop(), loop
            )
            future.result(timeout=timeout)
        except Exception as e:
            logger.warning("Error during IPC server stop: %s", e)

        # Stop the event loop
        loop.call_soon_threadsafe(loop.stop)

        # Join the thread
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("IPC server thread did not stop in time")

        self._loop = None
        self._server = None
        self._thread = None

        # Unregister atexit handler to prevent accumulation on repeated start/stop
        if self._atexit_registered:
            atexit.unregister(self._atexit_cleanup)
            self._atexit_registered = False

        logger.info("IPC server thread stopped")

    def broadcast_threadsafe(self, event: dict[str, Any]) -> None:
        """Schedule an async broadcast from the sync run_loop() thread.

        Uses asyncio.run_coroutine_threadsafe() to schedule the broadcast
        on the server's event loop. Fire-and-forget — does not wait for
        completion or raise exceptions.

        Args:
            event: JSON-RPC event notification dict (from make_event()).

        """
        if self._loop is None or self._server is None:
            return

        loop = self._loop
        if loop.is_closed():
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self._server.broadcast(event), loop
            )
        except RuntimeError:
            # Loop closed between check and call
            pass

    def update_state(
        self,
        state: RunnerState | None = None,
        state_data: dict[str, Any] | None = None,
    ) -> None:
        """Update the cached runner state. Thread-safe.

        Args:
            state: New runner state.
            state_data: New state data dict.

        """
        if self._server is not None:
            self._server.update_runner_state(state, state_data)

    def make_event(
        self, event_type: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create an event dict with auto-incrementing sequence number.

        Args:
            event_type: Event type string.
            data: Event payload data.

        Returns:
            JSON-RPC event notification dict.

        """
        if self._server is not None:
            seq = self._server.next_event_seq()
        else:
            seq = 0
        return make_event(event_type, data, seq=seq)

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _run_server_loop(self) -> None:
        """Thread target: create event loop, start server, run forever."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            self._server = SocketServer(
                socket_path=self._socket_path,
                project_root=self._project_root,
                handler=self._handler,
            )

            # Start the server
            self._loop.run_until_complete(self._server.start())
            self._started.set()

            # Run the event loop until stopped
            self._loop.run_forever()

        except Exception as e:
            self._start_error = e
            self._started.set()  # Unblock the waiting start() call
            logger.error("IPC server thread failed: %s", e)
        finally:
            # Clean up the event loop
            if self._loop is not None and not self._loop.is_closed():
                try:
                    # Run pending cleanup tasks
                    pending = asyncio.all_tasks(self._loop)
                    if pending:
                        self._loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except Exception:
                    pass
                finally:
                    self._loop.close()

    def _atexit_cleanup(self) -> None:
        """Best-effort cleanup on process exit."""
        try:
            if self._socket_path.exists():
                self._socket_path.unlink()
            lock_path = Path(f"{self._socket_path}.lock")
            if lock_path.exists():
                lock_path.unlink()
        except OSError:
            pass
