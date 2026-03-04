"""IPC protocol definitions, serialization, and socket path utilities.

Task 2: Error codes enum (JSON-RPC standard + custom).
Task 3: Protocol constants and supported methods.
Task 7: Length-prefixed framing serialization helpers.
Task 8: Socket path utilities (directory, project hash, socket path).
"""

import asyncio
import hashlib
import json
import logging
import struct
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from bmad_assist.core.exceptions import BmadAssistError
from bmad_assist.core.platform import is_wsl

__all__ = [
    # Error codes
    "ErrorCode",
    # Constants
    "PROTOCOL_VERSION",
    "MAX_MESSAGE_SIZE",
    "MAX_CONNECTIONS",
    "IDLE_TIMEOUT",
    "CONNECT_TIMEOUT",
    "MAX_PARSE_ERRORS",
    "EVENT_RATE_LIMIT",
    "SOCKET_DIR",
    "WRITE_COMMANDS",
    "READ_COMMANDS",
    "SUPPORTED_METHODS",
    # Exceptions
    "IPCError",
    "MessageTooLargeError",
    # Serialization
    "serialize",
    "deserialize",
    "read_message",
    "write_message",
    # Response/event builders
    "make_error_response",
    "make_success_response",
    "make_event",
    # Socket path utilities
    "get_socket_dir",
    "compute_project_hash",
    "get_socket_path",
    "validate_socket_path_length",
]

logger = logging.getLogger(__name__)

# =============================================================================
# Error Codes - Task 2
# =============================================================================

# Length-prefix header size: 4 bytes, big-endian uint32
_HEADER_SIZE = 4


class ErrorCode(str, Enum):
    """JSON-RPC 2.0 error codes (standard + custom).

    Standard codes (-32700 to -32603) follow the JSON-RPC 2.0 specification.
    Custom codes (-32000 to -32003) are bmad-assist IPC extensions.

    Attributes:
        PARSE_ERROR: Invalid JSON received by the server.
        INVALID_REQUEST: JSON is not a valid Request object.
        METHOD_NOT_FOUND: Requested method does not exist.
        INVALID_PARAMS: Invalid method parameters.
        INTERNAL_ERROR: Internal JSON-RPC error.
        RUNNER_BUSY: Command rejected temporarily (retry with backoff).
        INVALID_STATE: Invalid state transition (e.g., resume when not paused).
        CONFIG_INVALID: Config reload validation failed.
        VERSION_MISMATCH: Client protocol version incompatible.

    """

    PARSE_ERROR = "-32700"
    INVALID_REQUEST = "-32600"
    METHOD_NOT_FOUND = "-32601"
    INVALID_PARAMS = "-32602"
    INTERNAL_ERROR = "-32603"
    RUNNER_BUSY = "-32000"
    INVALID_STATE = "-32001"
    CONFIG_INVALID = "-32002"
    VERSION_MISMATCH = "-32003"

    @property
    def message(self) -> str:
        """Human-readable description of this error code."""
        return _ERROR_MESSAGES[self]

    @property
    def code(self) -> int:
        """Numeric error code for JSON-RPC responses."""
        return int(self.value)


_ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.PARSE_ERROR: "Parse error: invalid JSON",
    ErrorCode.INVALID_REQUEST: "Invalid request: not a valid JSON-RPC 2.0 object",
    ErrorCode.METHOD_NOT_FOUND: "Method not found",
    ErrorCode.INVALID_PARAMS: "Invalid method parameters",
    ErrorCode.INTERNAL_ERROR: "Internal error",
    ErrorCode.RUNNER_BUSY: "Runner busy: command rejected temporarily",
    ErrorCode.INVALID_STATE: "Invalid state transition",
    ErrorCode.CONFIG_INVALID: "Configuration validation failed",
    ErrorCode.VERSION_MISMATCH: "Protocol version mismatch",
}


# =============================================================================
# Protocol Constants - Task 3
# =============================================================================

PROTOCOL_VERSION: str = "1.0"
MAX_MESSAGE_SIZE: int = 65536  # 64KB
MAX_CONNECTIONS: int = 10
IDLE_TIMEOUT: int = 60  # seconds
CONNECT_TIMEOUT: int = 5  # seconds
MAX_PARSE_ERRORS: int = 3
EVENT_RATE_LIMIT: int = 100  # per second

SOCKET_DIR: Path = Path("~/.bmad-assist/sockets/")

# DrvFS warning deduplication flag (Story 29.7, AC #3)
_drvfs_warned: bool = False

WRITE_COMMANDS: frozenset[str] = frozenset(
    {"pause", "resume", "stop", "reload_config", "set_log_level"}
)
READ_COMMANDS: frozenset[str] = frozenset(
    {"get_state", "get_capabilities", "ping"}
)
SUPPORTED_METHODS: frozenset[str] = READ_COMMANDS | WRITE_COMMANDS


# =============================================================================
# Exceptions - Task 7
# =============================================================================


class IPCError(BmadAssistError):
    """IPC protocol violation error.

    Raised when:
    - Message framing is invalid
    - Deserialization fails
    - Protocol-level errors occur
    """

    pass


class MessageTooLargeError(IPCError):
    """Message exceeds MAX_MESSAGE_SIZE.

    Raised when:
    - Serialized message payload exceeds 64KB
    - Received length prefix indicates oversized message

    Attributes:
        size: Actual message size in bytes.
        max_size: Maximum allowed size in bytes.

    """

    def __init__(self, size: int, max_size: int = MAX_MESSAGE_SIZE) -> None:
        """Initialize MessageTooLargeError.

        Args:
            size: Actual message size in bytes.
            max_size: Maximum allowed size in bytes.

        """
        super().__init__(
            f"Message size {size} bytes exceeds maximum {max_size} bytes"
        )
        self.size = size
        self.max_size = max_size


# =============================================================================
# Serialization Helpers - Task 7
# =============================================================================


def serialize(message: dict[str, Any]) -> bytes:
    """Serialize a message dict to length-prefixed JSON bytes.

    Encodes the message as UTF-8 JSON, then prepends a 4-byte big-endian
    uint32 length prefix indicating the payload size.

    Args:
        message: Dict to serialize (typically a JSON-RPC request/response).

    Returns:
        Bytes with 4-byte length prefix followed by JSON payload.

    Raises:
        MessageTooLargeError: If JSON payload exceeds MAX_MESSAGE_SIZE.
        IPCError: If message cannot be serialized to JSON.

    """
    try:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IPCError(f"Cannot serialize message: {exc}") from exc

    if len(payload) > MAX_MESSAGE_SIZE:
        raise MessageTooLargeError(len(payload))

    header = struct.pack(">I", len(payload))
    return header + payload


def deserialize(data: bytes) -> dict[str, Any]:
    """Deserialize a JSON payload (without length prefix) to a dict.

    Args:
        data: Raw JSON bytes (no length prefix).

    Returns:
        Parsed message as a dict.

    Raises:
        IPCError: If data is not valid JSON or not a JSON object.

    """
    try:
        message = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IPCError(f"Invalid JSON: {exc}") from exc

    if not isinstance(message, dict):
        raise IPCError(f"Expected JSON object, got {type(message).__name__}")

    return message


async def read_message(reader: asyncio.StreamReader) -> bytes:
    """Read a length-prefixed message from an async stream.

    Reads a 4-byte big-endian uint32 length prefix, validates the size,
    then reads exactly that many bytes of payload.

    Args:
        reader: Async stream reader (e.g., from asyncio.open_unix_connection).

    Returns:
        Raw JSON payload bytes (without the length prefix).

    Raises:
        MessageTooLargeError: If declared size exceeds MAX_MESSAGE_SIZE.
        IPCError: If the stream ends before the full message is received.
        ConnectionError: If the connection is closed during read.

    """
    header = await reader.readexactly(_HEADER_SIZE)
    (length,) = struct.unpack(">I", header)

    if length > MAX_MESSAGE_SIZE:
        raise MessageTooLargeError(length)

    if length == 0:
        raise IPCError("Received zero-length message")

    return await reader.readexactly(length)


async def write_message(
    writer: asyncio.StreamWriter, message: dict[str, Any]
) -> None:
    """Serialize and write a message to an async stream.

    Args:
        writer: Async stream writer (e.g., from asyncio.open_unix_connection).
        message: Dict to serialize and send.

    Raises:
        MessageTooLargeError: If serialized message exceeds MAX_MESSAGE_SIZE.
        IPCError: If message cannot be serialized.
        ConnectionError: If the connection is closed during write.

    """
    data = serialize(message)
    writer.write(data)
    await writer.drain()


# =============================================================================
# Response / Event Builders - Task 7
# =============================================================================


def make_error_response(
    id: str | int | None,
    code: ErrorCode,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response dict.

    Args:
        id: Request ID to echo back (None for notifications/parse errors).
        code: Error code enum value.
        data: Optional additional error data.

    Returns:
        JSON-RPC 2.0 error response dict.

    """
    error: dict[str, Any] = {
        "code": code.code,
        "message": code.message,
    }
    if data is not None:
        error["data"] = data

    return {
        "jsonrpc": "2.0",
        "error": error,
        "id": id,
    }


def make_success_response(
    id: str | int | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 success response dict.

    Args:
        id: Request ID to echo back.
        result: The result dict to include.

    Returns:
        JSON-RPC 2.0 success response dict.

    """
    return {
        "jsonrpc": "2.0",
        "result": result,
        "id": id,
    }


def make_event(
    type: str,
    data: dict[str, Any],
    seq: int,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 notification for a server-sent event.

    Events are JSON-RPC notifications (no id field) with method "event"
    and params containing the event type, data, sequence number, and timestamp.

    Args:
        type: Event type string (e.g., "state_changed", "phase_started").
        data: Event payload data.
        seq: Monotonically increasing sequence number.
        timestamp: ISO 8601 timestamp. If None, uses current UTC time.

    Returns:
        JSON-RPC 2.0 notification dict.

    """
    if timestamp is None:
        timestamp = datetime.now(UTC).isoformat()

    return {
        "jsonrpc": "2.0",
        "method": "event",
        "params": {
            "type": type,
            "data": data,
            "seq": seq,
            "timestamp": timestamp,
        },
    }


# =============================================================================
# Socket Path Utilities - Task 8
# =============================================================================


def validate_socket_path_length(socket_path: Path) -> None:
    """Validate that a socket path does not exceed the sun_path limit.

    Unix domain sockets have a 108-byte sun_path field (107 usable bytes).
    This function checks the UTF-8 byte length of the resolved path and
    raises IPCError if it exceeds 107 bytes. Prevents a cryptic OSError
    on WSL2 (and native Linux) when home directory paths are long.

    Args:
        socket_path: Path to validate.

    Raises:
        IPCError: If the resolved path exceeds 107 bytes (UTF-8 encoded).

    """
    resolved = str(socket_path.resolve())
    byte_len = len(resolved.encode("utf-8"))
    if byte_len > 107:
        raise IPCError(
            f"Socket path exceeds 107-byte sun_path limit: {byte_len} bytes "
            f"(path: {resolved})"
        )


def get_socket_dir() -> Path:
    """Get the socket directory path, creating it if necessary.

    Creates ``~/.bmad-assist/sockets/`` with mode 0700 (owner-only access)
    if it does not exist. The home directory ``~`` is expanded.

    On WSL, warns if the socket directory is on a Windows filesystem (DrvFS)
    where Unix socket permissions and IPC may not work correctly.

    Returns:
        Absolute path to the socket directory.

    Raises:
        IPCError: If directory creation fails.

    """
    global _drvfs_warned
    socket_dir = SOCKET_DIR.expanduser()

    # Story 29.7 AC #3: Warn about DrvFS on WSL (once per process)
    if not _drvfs_warned and is_wsl() and str(socket_dir).startswith("/mnt/"):
        logger.warning(
            "Socket directory %s is on a Windows filesystem (DrvFS). "
            "Unix socket permissions and IPC may not work correctly. "
            "Recommend using a Linux filesystem path.",
            socket_dir,
        )
        _drvfs_warned = True

    try:
        socket_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise IPCError(f"Cannot create socket directory {socket_dir}: {exc}") from exc
    return socket_dir


def compute_project_hash(project_root: Path) -> str:
    """Compute a deterministic hash for a project root path.

    Uses SHA-256 of the resolved absolute path string, returning the
    first 32 hex characters. This provides a stable, filesystem-safe
    identifier for socket file naming.

    Args:
        project_root: Path to the project root directory.

    Returns:
        First 32 characters of the SHA-256 hex digest.

    """
    resolved = str(project_root.resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:32]


def get_socket_path(project_root: Path) -> Path:
    """Get the Unix domain socket path for a project.

    Combines the socket directory with a hash-based filename derived
    from the project root path.

    Args:
        project_root: Path to the project root directory.

    Returns:
        Path to the socket file (e.g., ``~/.bmad-assist/sockets/<hash>.sock``).

    """
    return get_socket_dir() / f"{compute_project_hash(project_root)}.sock"
