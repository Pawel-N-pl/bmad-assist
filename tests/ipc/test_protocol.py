"""Unit tests for the IPC protocol module.

Tests cover error codes, serialization/deserialization, socket path utilities,
response/event builders, Pydantic message models, and the public API surface.
"""

import asyncio
import json
import struct
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from bmad_assist.ipc import protocol as proto
from bmad_assist.ipc.protocol import (
    ErrorCode,
    IPCError,
    MAX_MESSAGE_SIZE,
    MessageTooLargeError,
    compute_project_hash,
    deserialize,
    get_socket_dir,
    get_socket_path,
    make_error_response,
    make_event,
    read_message,
    serialize,
    write_message,
)
from bmad_assist.ipc.types import (
    EventPriority,
    GetCapabilitiesResult,
    PingResult,
    RPCEvent,
    RPCRequest,
    RPCResponse,
    RunnerState,
    get_event_priority,
)


# ============================================================================
# Helper: mock transport for async write tests
# ============================================================================


class _MockTransport(asyncio.Transport):
    """Transport that feeds written bytes into an asyncio.StreamReader."""

    def __init__(self, reader: asyncio.StreamReader) -> None:
        super().__init__()
        self._reader = reader

    def write(self, data: bytes) -> None:
        self._reader.feed_data(data)

    def is_closing(self) -> bool:
        return False

    def close(self) -> None:
        pass

    def get_extra_info(self, name, default=None):
        return default


# ============================================================================
# Error codes (Task 2)
# ============================================================================


class TestErrorCodeValues:
    """Verify all error codes are present and have correct numeric values."""

    EXPECTED_CODES = {
        "PARSE_ERROR": -32700,
        "INVALID_REQUEST": -32600,
        "METHOD_NOT_FOUND": -32601,
        "INVALID_PARAMS": -32602,
        "INTERNAL_ERROR": -32603,
        "RUNNER_BUSY": -32000,
        "INVALID_STATE": -32001,
        "CONFIG_INVALID": -32002,
        "VERSION_MISMATCH": -32003,
    }

    def test_error_code_values(self):
        """All error codes present with correct integer values."""
        for name, expected_code in self.EXPECTED_CODES.items():
            member = ErrorCode[name]
            assert member.code == expected_code, (
                f"{name}: expected {expected_code}, got {member.code}"
            )

    def test_error_code_count(self):
        """No extra error codes exist beyond the expected set."""
        assert len(ErrorCode) == len(self.EXPECTED_CODES)

    def test_error_code_message(self):
        """Every ErrorCode has a non-empty human-readable .message property."""
        for member in ErrorCode:
            msg = member.message
            assert isinstance(msg, str)
            assert len(msg) > 0, f"{member.name} has empty message"

    def test_error_code_is_str_enum(self):
        """ErrorCode is a str enum, values are string representations of ints."""
        for member in ErrorCode:
            assert isinstance(member.value, str)
            int(member.value)  # Should not raise


# ============================================================================
# Serialization / Deserialization (Task 7)
# ============================================================================


class TestSerialize:
    """Tests for serialize() - length-prefixed JSON encoding."""

    def test_serialize_request(self):
        """Round-trip serialization for a JSON-RPC request."""
        request = {
            "jsonrpc": "2.0",
            "method": "get_state",
            "params": {},
            "id": 1,
        }
        data = serialize(request)

        # First 4 bytes are length prefix
        assert len(data) > 4
        (length,) = struct.unpack(">I", data[:4])
        payload = data[4:]
        assert len(payload) == length

        # Round-trip
        parsed = json.loads(payload)
        assert parsed == request

    def test_serialize_response(self):
        """Round-trip serialization for a JSON-RPC response."""
        response = {
            "jsonrpc": "2.0",
            "result": {"state": "idle", "running": False},
            "id": 42,
        }
        data = serialize(response)
        (length,) = struct.unpack(">I", data[:4])
        parsed = json.loads(data[4:])
        assert parsed == response
        assert len(data[4:]) == length

    def test_serialize_event_no_id(self):
        """Round-trip for event; verify no 'id' field present."""
        event = make_event("phase_started", {"phase": "create_story"}, seq=1)
        assert "id" not in event

        data = serialize(event)
        parsed = json.loads(data[4:])
        assert "id" not in parsed
        assert parsed["method"] == "event"

    def test_serialize_compact_json(self):
        """Serialized JSON uses compact separators (no spaces)."""
        msg = {"jsonrpc": "2.0", "method": "ping", "id": 1}
        data = serialize(msg)
        payload = data[4:]
        text = payload.decode("utf-8")
        assert ": " not in text
        assert ", " not in text


class TestDeserialize:
    """Tests for deserialize() - JSON bytes to dict."""

    def test_deserialize_valid_json(self):
        """Valid JSON bytes are parsed correctly."""
        obj = {"jsonrpc": "2.0", "method": "ping", "id": 1}
        data = json.dumps(obj).encode("utf-8")
        result = deserialize(data)
        assert result == obj

    def test_deserialize_invalid_json(self):
        """Invalid JSON raises IPCError."""
        with pytest.raises(IPCError, match="Invalid JSON"):
            deserialize(b"not json {{{")

    def test_deserialize_non_object(self):
        """JSON array (not object) raises IPCError."""
        with pytest.raises(IPCError, match="Expected JSON object"):
            deserialize(b"[1, 2, 3]")

    def test_deserialize_missing_fields(self):
        """Deserialize succeeds for any dict - field validation is at model layer."""
        data = json.dumps({"foo": "bar"}).encode("utf-8")
        result = deserialize(data)
        assert result == {"foo": "bar"}


# ============================================================================
# make_error_response
# ============================================================================


class TestMakeErrorResponse:
    """Tests for make_error_response() builder."""

    def test_make_error_response_basic(self):
        """Correct JSON-RPC 2.0 error response format."""
        resp = make_error_response(1, ErrorCode.METHOD_NOT_FOUND)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["error"]["code"] == -32601
        assert resp["error"]["message"] == "Method not found"
        assert "data" not in resp["error"]

    def test_make_error_response_with_data(self):
        """Error response includes optional data field when provided."""
        extra = {"detail": "unknown method 'foo'"}
        resp = make_error_response("req-1", ErrorCode.METHOD_NOT_FOUND, data=extra)
        assert resp["error"]["data"] == extra
        assert resp["id"] == "req-1"

    def test_make_error_response_null_id(self):
        """Error response with None id (e.g., parse errors)."""
        resp = make_error_response(None, ErrorCode.PARSE_ERROR)
        assert resp["id"] is None
        assert resp["error"]["code"] == -32700


# ============================================================================
# make_event
# ============================================================================


class TestMakeEvent:
    """Tests for make_event() builder."""

    def test_event_structure(self):
        """Event is a JSON-RPC notification with correct structure."""
        event = make_event("phase_started", {"phase": "dev_story"}, seq=5)
        assert event["jsonrpc"] == "2.0"
        assert event["method"] == "event"
        assert "id" not in event
        params = event["params"]
        assert params["type"] == "phase_started"
        assert params["data"] == {"phase": "dev_story"}
        assert params["seq"] == 5
        assert "timestamp" in params

    def test_event_sequence_numbers(self):
        """seq field is present and matches the provided value."""
        for i in range(5):
            event = make_event("log", {"message": "test"}, seq=i)
            assert event["params"]["seq"] == i

    def test_event_custom_timestamp(self):
        """Custom timestamp is used when provided."""
        ts = "2026-01-01T00:00:00+00:00"
        event = make_event("test", {}, seq=0, timestamp=ts)
        assert event["params"]["timestamp"] == ts

    def test_event_auto_timestamp(self):
        """Timestamp is auto-generated when not provided."""
        event = make_event("test", {}, seq=0)
        ts = event["params"]["timestamp"]
        assert isinstance(ts, str)
        assert "T" in ts  # ISO 8601 format


# ============================================================================
# Socket path utilities (Task 8)
# ============================================================================


class TestSocketPathDeterministic:
    """Socket path generation is deterministic and project-specific."""

    def test_socket_path_deterministic(self, tmp_path):
        """Same project root always produces the same socket path."""
        project = tmp_path / "my-project"
        project.mkdir()
        hash1 = compute_project_hash(project)
        hash2 = compute_project_hash(project)
        assert hash1 == hash2
        assert len(hash1) == 32

    def test_socket_path_different_projects(self, tmp_path):
        """Different project roots produce different socket paths."""
        proj_a = tmp_path / "project-a"
        proj_b = tmp_path / "project-b"
        proj_a.mkdir()
        proj_b.mkdir()
        assert compute_project_hash(proj_a) != compute_project_hash(proj_b)

    def test_socket_path_format(self, tmp_path, monkeypatch):
        """get_socket_path returns socket_dir / '<hash>.sock'."""
        sock_dir = tmp_path / "sockets"
        monkeypatch.setattr(proto, "SOCKET_DIR", sock_dir)

        project = tmp_path / "my-project"
        project.mkdir()
        path = get_socket_path(project)

        expected_hash = compute_project_hash(project)
        assert path == sock_dir / f"{expected_hash}.sock"
        assert path.suffix == ".sock"


class TestSocketDirCreation:
    """Socket directory creation with correct permissions."""

    def test_socket_dir_creation(self, tmp_path, monkeypatch):
        """Creates directory with 0700 permissions if missing."""
        sock_dir = tmp_path / "sockets"
        monkeypatch.setattr(proto, "SOCKET_DIR", sock_dir)

        result = get_socket_dir()
        assert result == sock_dir
        assert sock_dir.exists()
        assert sock_dir.is_dir()
        mode = sock_dir.stat().st_mode & 0o777
        assert mode == 0o700

    def test_socket_dir_existing(self, tmp_path, monkeypatch):
        """Existing directory is returned without error."""
        sock_dir = tmp_path / "sockets"
        sock_dir.mkdir(mode=0o700)
        monkeypatch.setattr(proto, "SOCKET_DIR", sock_dir)

        result = get_socket_dir()
        assert result == sock_dir


# ============================================================================
# Async read/write message (Task 7)
# ============================================================================


class TestLengthPrefixedReadWrite:
    """Tests for async read_message / write_message with length framing."""

    @pytest.mark.asyncio
    async def test_length_prefixed_read_write(self):
        """Round-trip: write_message then read_message recovers original."""
        msg = {"jsonrpc": "2.0", "method": "ping", "id": 1}

        reader = asyncio.StreamReader()
        transport = _MockTransport(reader)
        writer_protocol = asyncio.StreamReaderProtocol(asyncio.StreamReader())
        writer = asyncio.StreamWriter(
            transport, writer_protocol, None, asyncio.get_event_loop()
        )

        await write_message(writer, msg)

        raw = await read_message(reader)
        parsed = deserialize(raw)
        assert parsed == msg


class TestMessageTooLargeRejected:
    """Oversized messages are rejected at serialization and read time."""

    def test_serialize_too_large(self):
        """Serializing a message exceeding MAX_MESSAGE_SIZE raises error."""
        big_data = {"data": "x" * (MAX_MESSAGE_SIZE + 1)}
        with pytest.raises(MessageTooLargeError) as exc_info:
            serialize(big_data)
        assert exc_info.value.size > MAX_MESSAGE_SIZE
        assert exc_info.value.max_size == MAX_MESSAGE_SIZE

    @pytest.mark.asyncio
    async def test_read_message_too_large(self):
        """read_message raises MessageTooLargeError for oversized length prefix."""
        reader = asyncio.StreamReader()
        oversized_length = MAX_MESSAGE_SIZE + 1
        header = struct.pack(">I", oversized_length)
        reader.feed_data(header)

        with pytest.raises(MessageTooLargeError):
            await read_message(reader)

    @pytest.mark.asyncio
    async def test_read_message_zero_length(self):
        """read_message raises IPCError for zero-length message."""
        reader = asyncio.StreamReader()
        header = struct.pack(">I", 0)
        reader.feed_data(header)

        with pytest.raises(IPCError, match="zero-length"):
            await read_message(reader)


# ============================================================================
# Request ID type preservation
# ============================================================================


class TestRequestIdTypePreservation:
    """Request IDs preserve their type through serialization."""

    def test_request_id_type_preservation_int(self):
        """Integer request ID is preserved through serialize/deserialize."""
        msg = {"jsonrpc": "2.0", "method": "ping", "id": 42}
        data = serialize(msg)
        parsed = deserialize(data[4:])
        assert parsed["id"] == 42
        assert isinstance(parsed["id"], int)

    def test_request_id_type_preservation_str(self):
        """String request ID is preserved through serialize/deserialize."""
        msg = {"jsonrpc": "2.0", "method": "ping", "id": "req-abc-123"}
        data = serialize(msg)
        parsed = deserialize(data[4:])
        assert parsed["id"] == "req-abc-123"
        assert isinstance(parsed["id"], str)


# ============================================================================
# RunnerState enum (types.py)
# ============================================================================


class TestRunnerStateEnum:
    """Verify RunnerState enum has all expected states."""

    def test_runner_state_enum(self):
        """All lifecycle states are present."""
        expected = {"IDLE", "STARTING", "RUNNING", "PAUSED", "STOPPING"}
        actual = {s.name for s in RunnerState}
        assert actual == expected

    def test_runner_state_values(self):
        """Values are lowercase string identifiers."""
        assert RunnerState.IDLE.value == "idle"
        assert RunnerState.RUNNING.value == "running"
        assert RunnerState.PAUSED.value == "paused"
        assert RunnerState.STOPPING.value == "stopping"
        assert RunnerState.STARTING.value == "starting"


# ============================================================================
# EventPriority (types.py)
# ============================================================================


class TestEventPriority:
    """Verify event priority classification."""

    def test_event_priority_essential(self):
        """Essential event types get ESSENTIAL priority."""
        for et in ("phase_started", "phase_completed", "state_changed", "error"):
            assert get_event_priority(et) == EventPriority.ESSENTIAL

    def test_event_priority_metrics(self):
        """Metrics event type gets METRICS priority."""
        assert get_event_priority("metrics") == EventPriority.METRICS

    def test_event_priority_logs(self):
        """Log and unknown event types default to LOGS priority."""
        assert get_event_priority("log") == EventPriority.LOGS
        assert get_event_priority("unknown_type") == EventPriority.LOGS

    def test_event_priority_enum_members(self):
        """EventPriority has exactly three levels."""
        assert {e.name for e in EventPriority} == {"ESSENTIAL", "METRICS", "LOGS"}


# ============================================================================
# Pydantic model validation (types.py)
# ============================================================================


class TestGetCapabilitiesResult:
    """Validate GetCapabilitiesResult Pydantic model."""

    def test_get_capabilities_result_valid(self):
        """Model validates with all required fields."""
        result = GetCapabilitiesResult(
            protocol_version="1.0",
            server_version="0.4.31",
            supported_methods=["ping", "get_state"],
        )
        assert result.protocol_version == "1.0"
        assert result.server_version == "0.4.31"
        assert result.supported_methods == ["ping", "get_state"]
        assert result.connected_clients == []
        assert result.features == {}

    def test_get_capabilities_result_frozen(self):
        """Model is frozen (immutable)."""
        result = GetCapabilitiesResult(
            protocol_version="1.0",
            server_version="0.4.31",
            supported_methods=["ping"],
        )
        with pytest.raises(ValidationError):
            result.protocol_version = "2.0"


class TestPingResult:
    """Validate PingResult Pydantic model."""

    def test_ping_result_valid(self):
        """Model validates with required fields."""
        result = PingResult(server_time="2026-01-01T00:00:00Z")
        assert result.pong is True
        assert result.server_time == "2026-01-01T00:00:00Z"

    def test_ping_result_frozen(self):
        """Model is frozen (immutable)."""
        result = PingResult(server_time="2026-01-01T00:00:00Z")
        with pytest.raises(ValidationError):
            result.pong = False


class TestRPCRequestModel:
    """Validate RPCRequest Pydantic model."""

    def test_rpc_request_valid(self):
        """Request model validates with required fields."""
        req = RPCRequest(method="ping", id=1)
        assert req.jsonrpc == "2.0"
        assert req.method == "ping"
        assert req.id == 1
        assert req.params == {}

    def test_rpc_request_frozen(self):
        """Request model is frozen."""
        req = RPCRequest(method="ping", id=1)
        with pytest.raises(ValidationError):
            req.method = "other"

    def test_rpc_request_missing_id(self):
        """Request model requires id field."""
        with pytest.raises(ValidationError):
            RPCRequest(method="ping")


class TestRPCResponseModel:
    """Validate RPCResponse Pydantic model."""

    def test_rpc_response_success(self):
        """Response model with result."""
        resp = RPCResponse(result={"state": "idle"}, id=1)
        assert resp.jsonrpc == "2.0"
        assert resp.result == {"state": "idle"}
        assert resp.error is None

    def test_rpc_response_frozen(self):
        """Response model is frozen."""
        resp = RPCResponse(result={"ok": True}, id=1)
        with pytest.raises(ValidationError):
            resp.id = 2


class TestRPCEventModel:
    """Validate RPCEvent Pydantic model."""

    def test_rpc_event_from_make_event(self):
        """RPCEvent model validates output from make_event()."""
        raw = make_event(
            "phase_started",
            {"phase": "dev_story"},
            seq=1,
            timestamp="2026-01-01T00:00:00Z",
        )
        event = RPCEvent(**raw)
        assert event.jsonrpc == "2.0"
        assert event.method == "event"
        assert event.params.type == "phase_started"
        assert event.params.seq == 1


# ============================================================================
# Public API (__init__.py __all__ exports)
# ============================================================================


class TestPublicAPI:
    """Verify __all__ exports from the ipc package."""

    def test_init_all_exports(self):
        """All names in __all__ are actually importable from bmad_assist.ipc."""
        import bmad_assist.ipc as ipc_pkg

        for name in ipc_pkg.__all__:
            assert hasattr(ipc_pkg, name), f"{name} in __all__ but not importable"

    def test_protocol_all_exports(self):
        """All names in protocol.__all__ are importable."""
        for name in proto.__all__:
            assert hasattr(proto, name), f"{name} in protocol.__all__ but not importable"

    def test_types_all_exports(self):
        """All names in types.__all__ are importable."""
        from bmad_assist.ipc import types as types_mod

        for name in types_mod.__all__:
            assert hasattr(types_mod, name), f"{name} in types.__all__ but not importable"


# ============================================================================
# Exceptions
# ============================================================================


class TestExceptions:
    """Test IPC exception hierarchy."""

    def test_ipc_error_is_bmad_error(self):
        """IPCError inherits from BmadAssistError."""
        from bmad_assist.core.exceptions import BmadAssistError

        assert issubclass(IPCError, BmadAssistError)

    def test_message_too_large_is_ipc_error(self):
        """MessageTooLargeError inherits from IPCError."""
        assert issubclass(MessageTooLargeError, IPCError)

    def test_message_too_large_attributes(self):
        """MessageTooLargeError stores size and max_size."""
        err = MessageTooLargeError(size=100000, max_size=65536)
        assert err.size == 100000
        assert err.max_size == 65536
        assert "100000" in str(err)
        assert "65536" in str(err)

    def test_serialize_non_serializable(self):
        """Serializing non-JSON-serializable data raises IPCError."""
        with pytest.raises(IPCError, match="Cannot serialize"):
            serialize({"func": lambda x: x})


# ============================================================================
# Socket path length validation (Story 29.7, AC #2)
# ============================================================================


class TestValidateSocketPathLength:
    """Tests for validate_socket_path_length() — 107-byte sun_path limit."""

    def test_short_path_passes(self, tmp_path):
        """Short path (~70 bytes, typical WSL2 home) passes silently."""
        from bmad_assist.ipc.protocol import validate_socket_path_length

        # Typical: /home/user/.bmad-assist/sockets/<32-char-hash>.sock
        short_sock = tmp_path / ("a" * 10) / "test.sock"
        short_sock.parent.mkdir(parents=True, exist_ok=True)
        short_sock.touch()
        # tmp_path is typically ~30 chars + 10 + 9 = ~49 bytes — well within limit
        validate_socket_path_length(short_sock)  # Should not raise

    def test_long_path_raises(self, tmp_path):
        """Long path (~120 bytes) raises IPCError."""
        from bmad_assist.ipc.protocol import validate_socket_path_length

        # Build a path that exceeds 107 bytes when resolved
        long_dir = tmp_path / ("x" * 80)
        long_dir.mkdir(parents=True, exist_ok=True)
        long_sock = long_dir / ("y" * 30 + ".sock")
        long_sock.touch()
        resolved_len = len(str(long_sock.resolve()).encode("utf-8"))
        assert resolved_len > 107, f"Test setup error: path only {resolved_len} bytes"

        with pytest.raises(IPCError, match="107-byte sun_path limit"):
            validate_socket_path_length(long_sock)

    def test_exactly_107_bytes_passes(self, tmp_path):
        """Path of exactly 107 UTF-8 bytes passes (boundary case)."""
        from bmad_assist.ipc.protocol import validate_socket_path_length

        # We need to create a real file whose resolved path is exactly 107 bytes
        resolved_base = str(tmp_path.resolve())
        base_len = len(resolved_base.encode("utf-8"))
        # We need: base_len + 1 (/) + filename_len = 107
        needed = 107 - base_len - 1
        if needed <= 0:
            pytest.skip("tmp_path too long for this boundary test")

        boundary_file = tmp_path / ("b" * needed)
        boundary_file.touch()
        resolved_len = len(str(boundary_file.resolve()).encode("utf-8"))
        assert resolved_len == 107, f"Expected 107, got {resolved_len}"

        validate_socket_path_length(boundary_file)  # Should not raise

    def test_108_bytes_raises(self, tmp_path):
        """Path of 108 UTF-8 bytes raises IPCError (boundary case)."""
        from bmad_assist.ipc.protocol import validate_socket_path_length

        resolved_base = str(tmp_path.resolve())
        base_len = len(resolved_base.encode("utf-8"))
        needed = 108 - base_len - 1
        if needed <= 0:
            pytest.skip("tmp_path too long for this boundary test")

        boundary_file = tmp_path / ("c" * needed)
        boundary_file.touch()
        resolved_len = len(str(boundary_file.resolve()).encode("utf-8"))
        assert resolved_len == 108, f"Expected 108, got {resolved_len}"

        with pytest.raises(IPCError, match="107-byte sun_path limit"):
            validate_socket_path_length(boundary_file)

    def test_non_ascii_multibyte_path(self, tmp_path):
        """Non-ASCII path where char count ≤ 107 but byte count > 107 raises IPCError."""
        from bmad_assist.ipc.protocol import validate_socket_path_length

        # 'é' is 2 bytes in UTF-8. Build a path that is short in chars but long in bytes.
        resolved_base = str(tmp_path.resolve())
        base_len = len(resolved_base.encode("utf-8"))

        # We need byte length > 107. Each 'é' is 2 bytes, 1 char.
        # So we need (107 - base_len - 1) / 2 + some extra 'é' chars
        # to push byte count over 107 while char count stays ≤ 107
        char_budget = 107 - base_len - 1  # chars we can use
        if char_budget <= 0:
            pytest.skip("tmp_path too long for this multibyte test")

        # Use all 'é' chars — each is 2 bytes
        # char_count = char_budget, byte_count = base_len + 1 + char_budget * 2
        # We need byte_count > 107 → base_len + 1 + char_budget * 2 > 107
        # → char_budget * 2 > 107 - base_len - 1 = char_budget → char_budget > 0 (always true)
        try:
            accent_dir = tmp_path / ("é" * char_budget)
            accent_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pytest.skip("Filesystem does not support accented characters")

        resolved_path = str(accent_dir.resolve())
        byte_len = len(resolved_path.encode("utf-8"))
        char_len = len(resolved_path)

        assert char_len <= 107 or byte_len > 107, (
            f"Test setup: chars={char_len}, bytes={byte_len}"
        )
        if byte_len <= 107:
            pytest.skip(f"Could not create path with byte_len > 107 (got {byte_len})")

        with pytest.raises(IPCError, match="107-byte sun_path limit"):
            validate_socket_path_length(accent_dir)

    def test_typical_wsl2_path_safe(self, tmp_path: Path) -> None:
        """Typical WSL2-style socket path passes validation.

        Constructs a realistic path structure and verifies validate_socket_path_length()
        accepts it without raising — not just that the byte count is low.
        """
        from bmad_assist.ipc.protocol import validate_socket_path_length

        # Simulate a typical ~/.bmad-assist/sockets/<32-char-hash>.sock path
        sock_dir = tmp_path / ".bmad-assist" / "sockets"
        sock_dir.mkdir(parents=True, exist_ok=True)
        sock_file = sock_dir / ("a" * 32 + ".sock")
        sock_file.touch()

        resolved_len = len(str(sock_file.resolve()).encode("utf-8"))
        # Sanity: confirm test setup created a safe-length path
        if resolved_len >= 107:
            pytest.skip(
                f"tmp_path too long for this test ({resolved_len} bytes); "
                "cannot simulate typical WSL2 path"
            )

        # Should not raise — this is the actual validation function under test
        validate_socket_path_length(sock_file)


# ============================================================================
# DrvFS detection warning (Story 29.7, AC #3)
# ============================================================================


class TestDrvFSWarning:
    """Tests for DrvFS warning in get_socket_dir() on WSL."""

    def setup_method(self) -> None:
        """Reset the _drvfs_warned flag before each test."""
        import bmad_assist.ipc.protocol as proto_mod

        proto_mod._drvfs_warned = False

    def teardown_method(self) -> None:
        """Reset the _drvfs_warned flag after each test to prevent cross-test contamination."""
        import bmad_assist.ipc.protocol as proto_mod

        proto_mod._drvfs_warned = False

    def test_drvfs_warning_on_wsl_with_mnt_path(self, monkeypatch):
        """When on WSL and socket dir starts with /mnt/, warning is logged."""
        import bmad_assist.ipc.protocol as proto_mod

        monkeypatch.setattr("bmad_assist.ipc.protocol.is_wsl", lambda: True)

        mnt_path = Path("/mnt/c/Users/test/.bmad-assist/sockets")

        class FakeSocketDir:
            def expanduser(self) -> Path:
                return mnt_path

        monkeypatch.setattr(proto_mod, "SOCKET_DIR", FakeSocketDir())

        with patch.object(Path, "mkdir"):
            with patch("bmad_assist.ipc.protocol.logger") as mock_logger:
                get_socket_dir()
                mock_logger.warning.assert_called_once()
                call_args = str(mock_logger.warning.call_args)
                assert "Windows filesystem" in call_args or "DrvFS" in call_args

    def test_drvfs_warning_not_repeated(self, monkeypatch):
        """DrvFS warning is logged only once (suppressed on subsequent calls)."""
        import bmad_assist.ipc.protocol as proto_mod

        monkeypatch.setattr("bmad_assist.ipc.protocol.is_wsl", lambda: True)

        mnt_path = Path("/mnt/c/Users/test/.bmad-assist/sockets")

        class FakeSocketDir:
            def expanduser(self) -> Path:
                return mnt_path

        monkeypatch.setattr(proto_mod, "SOCKET_DIR", FakeSocketDir())

        with patch.object(Path, "mkdir"):
            with patch("bmad_assist.ipc.protocol.logger") as mock_logger:
                try:
                    get_socket_dir()
                except Exception:
                    pass
                first_count = mock_logger.warning.call_count

                try:
                    get_socket_dir()
                except Exception:
                    pass
                second_count = mock_logger.warning.call_count

                # Warning should only be logged once
                assert first_count == 1
                assert second_count == 1

    def test_no_warning_on_native_linux(self, tmp_path, monkeypatch):
        """On native Linux (not WSL), no DrvFS warning even with /mnt/ path."""
        import bmad_assist.ipc.protocol as proto_mod

        monkeypatch.setattr("bmad_assist.ipc.protocol.is_wsl", lambda: False)
        monkeypatch.setattr(proto_mod, "SOCKET_DIR", tmp_path / "sockets")

        with patch("bmad_assist.ipc.protocol.logger") as mock_logger:
            get_socket_dir()
            # No warning should be logged about DrvFS
            for call in mock_logger.warning.call_args_list:
                assert "DrvFS" not in str(call)
                assert "Windows filesystem" not in str(call)

    def test_no_warning_on_linux_filesystem_wsl(self, tmp_path, monkeypatch):
        """On WSL with Linux filesystem path, no DrvFS warning."""
        import bmad_assist.ipc.protocol as proto_mod

        monkeypatch.setattr("bmad_assist.ipc.protocol.is_wsl", lambda: True)
        monkeypatch.setattr(proto_mod, "SOCKET_DIR", tmp_path / "sockets")

        with patch("bmad_assist.ipc.protocol.logger") as mock_logger:
            get_socket_dir()
            # No warning about DrvFS for Linux-native paths
            for call in mock_logger.warning.call_args_list:
                assert "DrvFS" not in str(call)
                assert "Windows filesystem" not in str(call)
