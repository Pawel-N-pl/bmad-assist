"""IPC socket client library for bmad-assist JSON-RPC 2.0 protocol.

Story 29.3: Reusable async client for connecting to runner sockets,
sending commands, and receiving events. Provides both async (SocketClient)
and sync (SyncSocketClient) interfaces.

The client supports:
- Full JSON-RPC 2.0 request/response correlation
- Concurrent in-flight requests
- Event subscription with callback dispatch
- Auto-reconnect with exponential backoff
- Connection state tracking
- Type-safe convenience methods for all supported commands
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import logging
import threading
from collections.abc import Awaitable, Callable
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from bmad_assist.ipc.protocol import (
    PROTOCOL_VERSION,
    IPCError,
    MessageTooLargeError,
    deserialize,
    read_message,
    write_message,
)
from bmad_assist.ipc.types import (
    GetCapabilitiesResult,
    GetStateResult,
    PauseResult,
    PingResult,
    ReloadConfigResult,
    ResumeResult,
    SetLogLevelResult,
    StopResult,
)

__all__ = [
    "ConnectionState",
    "SocketClient",
    "SyncSocketClient",
    "IPCConnectionError",
    "IPCTimeoutError",
    "IPCCommandError",
    "IPCReconnectError",
]

logger = logging.getLogger(__name__)

# Keepalive interval — must be well below server's IDLE_TIMEOUT (60s)
# to prevent idle disconnections during paused/quiet runner states.
_KEEPALIVE_INTERVAL: float = 30.0


# =============================================================================
# Exception Hierarchy (Task 1 — AC #12)
# =============================================================================


class IPCConnectionError(IPCError):
    """Connection refused, timeout, or socket not found.

    Raised when:
    - Socket file does not exist (FileNotFoundError)
    - Server is not listening (ConnectionRefusedError)
    - Connection attempt times out
    - Attempting to send on a closed connection
    """

    pass


class IPCTimeoutError(IPCError):
    """Request timeout waiting for response.

    Raised when a send_command() call does not receive a matching
    response within the specified timeout.
    """

    pass


class IPCCommandError(IPCError):
    """Server returned a JSON-RPC error response.

    Attributes:
        code: Numeric JSON-RPC error code.
        message: Human-readable error description.
        data: Optional additional error context from the server.

    """

    def __init__(self, code: int, message: str, data: dict[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"[{code}] {message}")


class IPCReconnectError(IPCError):
    """Auto-reconnect failed after max retries.

    Raised when the client exhausts all reconnect attempts
    and cannot re-establish the connection.
    """

    pass


# =============================================================================
# ConnectionState Enum (Task 2 — AC #6)
# =============================================================================


class ConnectionState(str, Enum):
    """Client connection lifecycle states.

    Attributes:
        DISCONNECTED: Not connected (initial or after connection loss).
        CONNECTING: Connection attempt in progress.
        CONNECTED: Active connection established.
        RECONNECTING: Auto-reconnect in progress after connection loss.
        CLOSED: Explicitly disconnected — terminal state, no reconnect.

    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


# =============================================================================
# SocketClient (Tasks 3-9, 11 — AC #1-5, #7, #9-11)
# =============================================================================


class SocketClient:
    """Async IPC client for JSON-RPC 2.0 over Unix domain sockets.

    Connects to a bmad-assist runner socket, sends commands with
    request correlation, receives events via callbacks, and optionally
    auto-reconnects on connection loss.

    Args:
        socket_path: Path to the Unix domain socket.
        client_id: Optional identifier included in every request.
        auto_reconnect: Whether to auto-reconnect on connection loss.
        max_retries: Maximum reconnect attempts (default: 5).
        on_reconnect: Callback invoked after successful reconnection.
        on_disconnect: Callback invoked immediately on connection loss.

    """

    def __init__(
        self,
        socket_path: Path,
        client_id: str | None = None,
        auto_reconnect: bool = True,
        max_retries: int = 5,
        on_reconnect: Callable[[], Any] | None = None,
        on_disconnect: Callable[[], Any] | None = None,
        on_reconnect_failed: Callable[[IPCReconnectError], None] | None = None,
        initial_delay: float = 0.1,
        max_delay: float = 10.0,
    ) -> None:
        self._socket_path = socket_path
        self._client_id = client_id
        self._auto_reconnect = auto_reconnect
        self._max_retries = max_retries
        self._on_reconnect = on_reconnect
        self._on_disconnect = on_disconnect
        self._on_reconnect_failed = on_reconnect_failed
        self._initial_delay = initial_delay
        self._max_delay = max_delay

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._state: ConnectionState = ConnectionState.DISCONNECTED
        self._request_id_counter = itertools.count(1)
        self._pending: dict[int | str, asyncio.Future[dict[str, Any]]] = {}
        self._event_callbacks: list[Callable[[dict[str, Any]], Awaitable[None] | None]] = []
        self._reader_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        """Whether the client has an active connection."""
        return self._state == ConnectionState.CONNECTED

    @property
    def state(self) -> ConnectionState:
        """Current connection lifecycle state."""
        return self._state

    def _next_request_id(self) -> int:
        """Get the next auto-incrementing integer request ID."""
        return next(self._request_id_counter)

    # -------------------------------------------------------------------------
    # Connection Lifecycle (Task 4 — AC #2, #10)
    # -------------------------------------------------------------------------

    async def connect(self, timeout: float = 5.0) -> None:
        """Establish connection to the stored socket path.

        Connects to the Unix domain socket, starts the background reader
        task, and sends a ping to verify the server is alive.

        Args:
            timeout: Maximum seconds to wait for connection.

        Raises:
            IPCConnectionError: If connection fails or ping verification fails.

        """
        if self._state == ConnectionState.CONNECTED:
            return

        if self._state == ConnectionState.CLOSED:
            raise IPCConnectionError("Client is closed — create a new instance to reconnect")

        self._state = ConnectionState.CONNECTING
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self._socket_path)),
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            self._state = ConnectionState.DISCONNECTED
            raise IPCConnectionError(f"Socket not found: {self._socket_path}") from exc
        except ConnectionRefusedError as exc:
            self._state = ConnectionState.DISCONNECTED
            raise IPCConnectionError(f"Connection refused: {self._socket_path}") from exc
        except TimeoutError as exc:
            self._state = ConnectionState.DISCONNECTED
            raise IPCConnectionError(
                f"Connection timed out after {timeout}s: {self._socket_path}"
            ) from exc
        except OSError as exc:
            self._state = ConnectionState.DISCONNECTED
            raise IPCConnectionError(f"Connection failed: {self._socket_path}: {exc}") from exc

        self._reader = reader
        self._writer = writer
        self._state = ConnectionState.CONNECTED

        # Start background reader task
        self._reader_task = asyncio.create_task(self._reader_loop())

        # Verify server is alive with ping (AC #10)
        try:
            await self.ping()
        except Exception as exc:
            # Ping failed — close and raise
            await self._close_connection()
            if self._state != ConnectionState.CLOSED:
                self._state = ConnectionState.DISCONNECTED
            raise IPCConnectionError(f"Server ping verification failed: {exc}") from exc

        # Start keepalive to prevent server idle timeout
        self._start_keepalive()

        logger.info(
            "Connected to IPC server at %s (client_id=%s)",
            self._socket_path,
            self._client_id,
        )

    async def disconnect(self) -> None:
        """Gracefully close the connection.

        Sets state to CLOSED (terminal — prevents auto-reconnect).
        Cancels the reader task, fails all pending requests, and clears
        all event callbacks to prevent memory leaks from orphaned subscriptions.
        """
        self._state = ConnectionState.CLOSED
        await self._close_connection()
        self._event_callbacks.clear()
        logger.info("Disconnected from IPC server")

    async def _close_connection(self) -> None:
        """Internal connection cleanup — close writer, cancel reader, fail pending."""
        # Stop keepalive before tearing down the connection
        self._stop_keepalive()

        # Cancel reader task
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        # Close writer
        if self._writer is not None and not self._writer.is_closing():
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (OSError, ConnectionError):
                pass
        self._writer = None
        self._reader = None

        # Fail all pending requests
        self._fail_pending(IPCConnectionError("Connection closed"))

    def _fail_pending(self, error: Exception) -> None:
        """Set exception on all pending request futures."""
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    # -------------------------------------------------------------------------
    # Keepalive (prevents server idle timeout during quiet periods)
    # -------------------------------------------------------------------------

    def _start_keepalive(self) -> None:
        """Start the background keepalive task."""
        self._stop_keepalive()
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    def _stop_keepalive(self) -> None:
        """Cancel the background keepalive task."""
        if self._keepalive_task is not None and not self._keepalive_task.done():
            self._keepalive_task.cancel()
        self._keepalive_task = None

    async def _keepalive_loop(self) -> None:
        """Send periodic pings to prevent server idle timeout.

        Runs as a background task, sending a ping every _KEEPALIVE_INTERVAL
        seconds. If the ping fails, exits silently — the reader loop will
        detect the connection loss and trigger reconnection.
        """
        try:
            while self._state == ConnectionState.CONNECTED:
                await asyncio.sleep(_KEEPALIVE_INTERVAL)
                if self._state != ConnectionState.CONNECTED:
                    break
                try:
                    await self.send_command("ping", timeout=10.0)
                except (IPCConnectionError, IPCTimeoutError):
                    # Connection issue — reader loop will handle reconnect
                    logger.debug("Keepalive ping failed, connection may be lost")
                    break
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    # -------------------------------------------------------------------------
    # Background Reader Task (Task 5 — AC #4, #5)
    # -------------------------------------------------------------------------

    async def _reader_loop(self) -> None:
        """Continuously read messages, route responses and events."""
        if self._reader is None:
            logger.error("_reader_loop called with no reader — internal state error")
            return
        try:
            while self._state == ConnectionState.CONNECTED:
                try:
                    raw = await read_message(self._reader)
                except asyncio.CancelledError:
                    return
                except asyncio.IncompleteReadError:
                    logger.debug("Server closed connection (IncompleteReadError)")
                    break
                except ConnectionResetError:
                    logger.debug("Connection reset by server")
                    break
                except MessageTooLargeError as exc:
                    logger.warning("Received oversized message, skipping: %s", exc)
                    continue
                except (OSError, ConnectionError) as exc:
                    logger.debug("Connection error in reader: %s", exc)
                    break

                try:
                    msg = deserialize(raw)
                except IPCError as exc:
                    logger.warning("Failed to deserialize message: %s", exc)
                    continue

                # Route: response, error response, or event
                request_id = msg.get("id")
                if request_id is not None and request_id in self._pending:
                    future = self._pending.pop(request_id)
                    if not future.done():
                        if "error" in msg:
                            err = msg["error"]
                            future.set_exception(
                                IPCCommandError(
                                    code=err.get("code", -1),
                                    message=err.get("message", "Unknown error"),
                                    data=err.get("data"),
                                )
                            )
                        else:
                            future.set_result(msg.get("result", {}))
                elif msg.get("method") == "event":
                    await self._dispatch_event(msg.get("params", {}))
                else:
                    logger.debug("Unexpected message (no matching pending request): %s", msg)

        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("Unexpected error in reader loop: %s", exc)

        # Connection lost — handle reconnect or mark disconnected
        if self._state == ConnectionState.CONNECTED:
            await self._handle_connection_lost()

    async def _dispatch_event(self, params: dict[str, Any]) -> None:
        """Dispatch event to all subscribed callbacks.

        Args:
            params: Event params dict (type, data, seq, timestamp).

        """
        for callback in list(self._event_callbacks):
            try:
                result = callback(params)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.warning(
                    "Event callback %s raised exception: %s",
                    getattr(callback, "__name__", callback),
                    exc,
                )

    async def _handle_connection_lost(self) -> None:
        """Handle unexpected connection loss — reconnect or mark disconnected."""
        # Invoke on_disconnect callback
        if self._on_disconnect is not None:
            try:
                result = self._on_disconnect()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.warning("on_disconnect callback error: %s", exc)

        # Fail all pending requests
        self._fail_pending(IPCConnectionError("Connection lost"))

        # Close writer
        if self._writer is not None and not self._writer.is_closing():
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (OSError, ConnectionError):
                pass
        self._writer = None
        self._reader = None

        if self._auto_reconnect and self._state != ConnectionState.CLOSED:
            await self._reconnect()
        else:
            self._state = ConnectionState.DISCONNECTED
            self._event_callbacks.clear()

    # -------------------------------------------------------------------------
    # Auto-Reconnect (Task 8 — AC #7)
    # -------------------------------------------------------------------------

    async def _reconnect(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        self._state = ConnectionState.RECONNECTING

        for attempt in range(self._max_retries):
            delay = min(self._initial_delay * (2**attempt), self._max_delay)
            logger.info(
                "Reconnect attempt %d/%d in %.1fs...",
                attempt + 1,
                self._max_retries,
                delay,
            )
            await asyncio.sleep(delay)

            if self._state == ConnectionState.CLOSED:
                return

            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(str(self._socket_path)),
                    timeout=5.0,
                )
            except (TimeoutError, FileNotFoundError, ConnectionRefusedError, OSError):
                continue

            # Verify with ping
            self._reader = reader
            self._writer = writer
            self._state = ConnectionState.CONNECTED

            try:
                # Send ping directly (not via send_command to avoid
                # reader task race — reader task not started yet)
                ping_id = self._next_request_id()
                request: dict[str, Any] = {
                    "jsonrpc": "2.0",
                    "method": "ping",
                    "params": {},
                    "id": ping_id,
                }
                if self._client_id is not None:
                    request["client_id"] = self._client_id

                await write_message(writer, request)
                raw = await asyncio.wait_for(read_message(reader), timeout=5.0)
                msg = deserialize(raw)

                if "error" in msg:
                    raise IPCConnectionError("Ping returned error during reconnect")

            except (TimeoutError, OSError, ConnectionError, IPCConnectionError, IPCError):
                # Ping failed — close and try again
                try:
                    writer.close()
                    await writer.wait_closed()
                except (OSError, ConnectionError):
                    pass
                self._reader = None
                self._writer = None
                self._state = ConnectionState.RECONNECTING
                continue

            # Success — restart reader task and keepalive
            self._reader_task = asyncio.create_task(self._reader_loop())
            self._start_keepalive()

            logger.info("Reconnected to IPC server at %s", self._socket_path)

            # Invoke on_reconnect callback
            if self._on_reconnect is not None:
                try:
                    result = self._on_reconnect()
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:
                    logger.warning("on_reconnect callback error: %s", exc)

            return

        # Max retries exhausted
        self._state = ConnectionState.DISCONNECTED
        self._event_callbacks.clear()
        logger.error(
            "Reconnect failed after %d attempts to %s",
            self._max_retries,
            self._socket_path,
        )

        if self._on_reconnect_failed is not None:
            try:
                err = IPCReconnectError(
                    f"Reconnect failed after {self._max_retries} attempts to {self._socket_path}"
                )
                self._on_reconnect_failed(err)
            except Exception as cb_exc:
                logger.warning("on_reconnect_failed callback error: %s", cb_exc)

    # -------------------------------------------------------------------------
    # Command Sending (Task 6 — AC #3, #4, #9)
    # -------------------------------------------------------------------------

    async def send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the matching response.

        Args:
            method: RPC method name (e.g., "ping", "get_state").
            params: Optional method parameters dict.
            timeout: Maximum seconds to wait for response.

        Returns:
            Result dict from the JSON-RPC response.

        Raises:
            IPCConnectionError: If not connected.
            IPCTimeoutError: If response not received within timeout.
            IPCCommandError: If server returns a JSON-RPC error response.

        """
        if self._state != ConnectionState.CONNECTED:
            raise IPCConnectionError("Not connected")

        if self._writer is None or self._writer.is_closing():
            raise IPCConnectionError("Connection is closing")

        request_id = self._next_request_id()

        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id,
        }
        if self._client_id is not None:
            request["client_id"] = self._client_id

        # Create future for response correlation
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future

        try:
            await write_message(self._writer, request)
        except (OSError, ConnectionError) as exc:
            self._pending.pop(request_id, None)
            raise IPCConnectionError(f"Failed to send command: {exc}") from exc

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            self._pending.pop(request_id, None)
            raise IPCTimeoutError(
                f"Timeout waiting for response to '{method}' (id={request_id}, timeout={timeout}s)"
            )

        return result

    # -------------------------------------------------------------------------
    # Event Subscription (Task 7 — AC #5)
    # -------------------------------------------------------------------------

    def subscribe(self, callback: Callable[[dict[str, Any]], Awaitable[None] | None]) -> None:
        """Register an event callback.

        Args:
            callback: Function called with event params dict.
                Can be sync or async. Exceptions are caught and logged.

        """
        self._event_callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[dict[str, Any]], Awaitable[None] | None]) -> None:
        """Remove an event callback. Silent no-op if not found.

        Args:
            callback: Previously registered callback to remove.

        """
        try:
            self._event_callbacks.remove(callback)
        except ValueError:
            pass

    def clear_subscriptions(self) -> None:
        """Clear all registered event callbacks.

        Use when a subscriber is done but the client connection should remain
        active for other consumers (e.g., when a TUI component is destroyed
        but the client remains connected for other components).
        """
        self._event_callbacks.clear()

    # -------------------------------------------------------------------------
    # Convenience Methods (Task 9 — AC #11)
    # -------------------------------------------------------------------------

    async def ping(self) -> PingResult:
        """Send a ping and return typed result."""
        result = await self.send_command("ping")
        return PingResult(**result)

    async def get_state(self) -> GetStateResult:
        """Query runner state and return typed result."""
        result = await self.send_command("get_state")
        return GetStateResult(**result)

    async def get_capabilities(self) -> GetCapabilitiesResult:
        """Query server capabilities and return typed result.

        Logs a warning if protocol version differs from client's
        PROTOCOL_VERSION (forward-compatible by design).
        """
        result = await self.send_command("get_capabilities")
        caps = GetCapabilitiesResult(**result)

        if caps.protocol_version != PROTOCOL_VERSION:
            logger.warning(
                "Protocol version mismatch: client=%s, server=%s",
                PROTOCOL_VERSION,
                caps.protocol_version,
            )

        return caps

    async def pause(self) -> PauseResult:
        """Pause the runner and return typed result."""
        result = await self.send_command("pause")
        return PauseResult(**result)

    async def resume(self) -> ResumeResult:
        """Resume the runner and return typed result."""
        result = await self.send_command("resume")
        return ResumeResult(**result)

    async def stop(self) -> StopResult:
        """Stop the runner and return typed result."""
        result = await self.send_command("stop")
        return StopResult(**result)

    async def set_log_level(
        self, level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    ) -> SetLogLevelResult:
        """Set the server log level and return typed result."""
        result = await self.send_command("set_log_level", {"level": level})
        return SetLogLevelResult(**result)

    async def reload_config(self) -> ReloadConfigResult:
        """Trigger config reload and return typed result."""
        result = await self.send_command("reload_config")
        return ReloadConfigResult(**result)

    # -------------------------------------------------------------------------
    # Context Manager (Task 11 — AC #2)
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> SocketClient:
        """Connect on entering async context."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Disconnect on exiting async context."""
        await self.disconnect()


# =============================================================================
# SyncSocketClient (Task 10 — AC #8)
# =============================================================================


class SyncSocketClient:
    """Synchronous wrapper for SocketClient using a dedicated daemon thread.

    Provides a blocking interface for use from sync code (TUI, CLI tools).
    Runs an asyncio event loop in a daemon thread, same pattern as
    IPCServerThread.

    Args:
        socket_path: Path to the Unix domain socket.
        client_id: Optional identifier included in every request.
        auto_reconnect: Whether to auto-reconnect on connection loss.
        max_retries: Maximum reconnect attempts.
        on_reconnect: Callback invoked after successful reconnection.
        on_disconnect: Callback invoked on connection loss.
        on_reconnect_failed: Optional callback invoked when reconnect
            retries are exhausted. Receives an IPCReconnectError.

    """

    def __init__(
        self,
        socket_path: Path,
        client_id: str | None = None,
        auto_reconnect: bool = True,
        max_retries: int = 5,
        on_reconnect: Callable[[], Any] | None = None,
        on_disconnect: Callable[[], Any] | None = None,
        on_reconnect_failed: Callable[[IPCReconnectError], None] | None = None,
        initial_delay: float = 0.1,
        max_delay: float = 10.0,
    ) -> None:
        self._socket_path = socket_path
        self._client_id = client_id
        self._auto_reconnect = auto_reconnect
        self._max_retries = max_retries
        self._on_reconnect = on_reconnect
        self._on_disconnect = on_disconnect
        self._on_reconnect_failed = on_reconnect_failed
        self._initial_delay = initial_delay
        self._max_delay = max_delay
        self._inner: SocketClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_error: Exception | None = None
        self._last_state: ConnectionState = ConnectionState.DISCONNECTED

    @property
    def is_connected(self) -> bool:
        """Whether the inner client has an active connection."""
        inner = self._inner
        return inner is not None and inner.is_connected

    @property
    def state(self) -> ConnectionState:
        """Current connection lifecycle state.

        Caches the last known state so that CLOSED survives _inner
        being set to None during _stop_loop().
        """
        inner = self._inner
        if inner is not None:
            self._last_state = inner.state
        return self._last_state

    def connect(self, timeout: float = 5.0) -> None:
        """Start daemon thread, create client, and connect.

        Args:
            timeout: Maximum seconds to wait for connection.

        Raises:
            IPCConnectionError: If connection fails.

        """
        if self._thread is not None and self._thread.is_alive():
            return

        self._ready.clear()
        self._start_error = None

        self._thread = threading.Thread(
            target=self._run_loop,
            name="ipc-client",
            daemon=True,
        )
        self._thread.start()

        # Wait for the event loop to be ready
        if not self._ready.wait(timeout=timeout + 2.0):
            raise IPCConnectionError("Client thread failed to start")

        if self._start_error is not None:
            raise self._start_error  # type: ignore[misc]

        # Now connect the async client
        assert self._loop is not None
        assert self._inner is not None

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._inner.connect(timeout=timeout), self._loop
            )
            future.result(timeout=timeout + 2.0)
        except Exception as exc:
            self._stop_loop()
            if isinstance(exc, (IPCConnectionError, IPCTimeoutError)):
                raise
            raise IPCConnectionError(f"Connect failed: {exc}") from exc

    def disconnect(self) -> None:
        """Disconnect and stop the daemon thread."""
        if self._loop is None or self._inner is None:
            return

        loop = self._loop
        if loop.is_closed():
            return

        try:
            future = asyncio.run_coroutine_threadsafe(self._inner.disconnect(), loop)
            future.result(timeout=5.0)
        except Exception as exc:
            logger.warning("Error during disconnect: %s", exc)

        # Capture state before _stop_loop nullifies _inner
        if self._inner is not None:
            self._last_state = self._inner.state

        self._stop_loop()

    def _stop_loop(self) -> None:
        """Stop the event loop and join the thread."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread is not None:
            self._thread.join(timeout=5.0)

        self._loop = None
        self._inner = None
        self._thread = None

    def send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a JSON-RPC command and block until response.

        Args:
            method: RPC method name.
            params: Optional method parameters.
            timeout: Maximum seconds to wait.

        Returns:
            Result dict from the JSON-RPC response.

        Raises:
            IPCConnectionError: If not connected.
            IPCTimeoutError: If response not received within timeout.
            IPCCommandError: If server returns an error response.

        """
        if self._loop is None or self._inner is None:
            raise IPCConnectionError("Not connected")

        future = asyncio.run_coroutine_threadsafe(
            self._inner.send_command(method, params, timeout=timeout),
            self._loop,
        )
        return future.result(timeout=timeout + 2.0)

    def subscribe(self, callback: Callable[[dict[str, Any]], Awaitable[None] | None]) -> None:
        """Register an event callback. Thread-safe.

        Args:
            callback: Function called with event params dict.

        """
        if self._loop is None or self._inner is None:
            return
        self._loop.call_soon_threadsafe(self._inner.subscribe, callback)

    def unsubscribe(self, callback: Callable[[dict[str, Any]], Awaitable[None] | None]) -> None:
        """Remove an event callback. Thread-safe.

        Args:
            callback: Previously registered callback to remove.

        """
        if self._loop is None or self._inner is None:
            return
        self._loop.call_soon_threadsafe(self._inner.unsubscribe, callback)

    def clear_subscriptions(self) -> None:
        """Clear all registered event callbacks. Thread-safe.

        Use when a subscriber is done but the client connection should remain
        active for other consumers (e.g., when a TUI component is destroyed
        but the client remains connected for other components).
        """
        if self._loop is None or self._inner is None:
            return
        self._loop.call_soon_threadsafe(self._inner.clear_subscriptions)

    # Convenience methods (sync wrappers)

    def ping(self, timeout: float = 30.0) -> PingResult:
        """Send a ping and return typed result."""
        if self._loop is None or self._inner is None:
            raise IPCConnectionError("Not connected")
        future = asyncio.run_coroutine_threadsafe(self._inner.ping(), self._loop)
        return future.result(timeout=timeout)

    def get_state(self, timeout: float = 30.0) -> GetStateResult:
        """Query runner state and return typed result."""
        if self._loop is None or self._inner is None:
            raise IPCConnectionError("Not connected")
        future = asyncio.run_coroutine_threadsafe(self._inner.get_state(), self._loop)
        return future.result(timeout=timeout)

    def get_capabilities(self, timeout: float = 30.0) -> GetCapabilitiesResult:
        """Query server capabilities and return typed result."""
        if self._loop is None or self._inner is None:
            raise IPCConnectionError("Not connected")
        future = asyncio.run_coroutine_threadsafe(self._inner.get_capabilities(), self._loop)
        return future.result(timeout=timeout)

    def pause(self, timeout: float = 30.0) -> PauseResult:
        """Pause the runner and return typed result."""
        if self._loop is None or self._inner is None:
            raise IPCConnectionError("Not connected")
        future = asyncio.run_coroutine_threadsafe(self._inner.pause(), self._loop)
        return future.result(timeout=timeout)

    def resume(self, timeout: float = 30.0) -> ResumeResult:
        """Resume the runner and return typed result."""
        if self._loop is None or self._inner is None:
            raise IPCConnectionError("Not connected")
        future = asyncio.run_coroutine_threadsafe(self._inner.resume(), self._loop)
        return future.result(timeout=timeout)

    def stop(self, timeout: float = 30.0) -> StopResult:
        """Stop the runner and return typed result."""
        if self._loop is None or self._inner is None:
            raise IPCConnectionError("Not connected")
        future = asyncio.run_coroutine_threadsafe(self._inner.stop(), self._loop)
        return future.result(timeout=timeout)

    def set_log_level(
        self,
        level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        timeout: float = 30.0,
    ) -> SetLogLevelResult:
        """Set the server log level and return typed result."""
        if self._loop is None or self._inner is None:
            raise IPCConnectionError("Not connected")
        future = asyncio.run_coroutine_threadsafe(self._inner.set_log_level(level), self._loop)
        return future.result(timeout=timeout)

    def reload_config(self, timeout: float = 30.0) -> ReloadConfigResult:
        """Trigger config reload and return typed result."""
        if self._loop is None or self._inner is None:
            raise IPCConnectionError("Not connected")
        future = asyncio.run_coroutine_threadsafe(self._inner.reload_config(), self._loop)
        return future.result(timeout=timeout)

    # Context manager

    def __enter__(self) -> SyncSocketClient:
        """Connect on entering context."""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Disconnect on exiting context."""
        self.disconnect()

    # Internal

    def _run_loop(self) -> None:
        """Thread target: create event loop, create client, run forever."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            self._inner = SocketClient(
                socket_path=self._socket_path,
                client_id=self._client_id,
                auto_reconnect=self._auto_reconnect,
                max_retries=self._max_retries,
                on_reconnect=self._on_reconnect,
                on_disconnect=self._on_disconnect,
                on_reconnect_failed=self._on_reconnect_failed,
                initial_delay=self._initial_delay,
                max_delay=self._max_delay,
            )

            self._ready.set()
            self._loop.run_forever()

        except Exception as exc:
            self._start_error = exc  # type: ignore[assignment]
            self._ready.set()
            logger.error("IPC client thread failed: %s", exc)
        finally:
            if self._loop is not None and not self._loop.is_closed():
                try:
                    pending = asyncio.all_tasks(self._loop)
                    if pending:
                        self._loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except Exception:
                    pass
                finally:
                    self._loop.close()
