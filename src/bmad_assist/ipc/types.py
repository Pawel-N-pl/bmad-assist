"""IPC message types for the bmad-assist JSON-RPC 2.0 protocol.

Defines all request, response, event, and control message models used
by the IPC layer. Models are frozen (immutable) for thread safety.
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    # Enums
    "RunnerState",
    "EventPriority",
    # Request types
    "RPCRequest",
    "PauseParams",
    "ResumeParams",
    "StopParams",
    "SetLogLevelParams",
    "ReloadConfigParams",
    "GetStateParams",
    "GetCapabilitiesParams",
    "PingParams",
    # Response types
    "RPCError",
    "RPCResponse",
    "PauseResult",
    "ResumeResult",
    "StopResult",
    "SetLogLevelResult",
    "ReloadConfigResult",
    "GetStateResult",
    "GetCapabilitiesResult",
    "PingResult",
    # Event types
    "EventParams",
    "RPCEvent",
    "PhaseStartedData",
    "PhaseCompletedData",
    "LogData",
    "StateChangedData",
    "MetricsData",
    "ErrorData",
    "GoodbyeData",
    # Helpers
    "get_event_priority",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RunnerState(str, Enum):
    """Runner lifecycle states."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"


class EventPriority(str, Enum):
    """Event priority levels for filtering and back-pressure."""

    ESSENTIAL = "essential"
    METRICS = "metrics"
    LOGS = "logs"


# ---------------------------------------------------------------------------
# Request types (Task 4)
# ---------------------------------------------------------------------------


class RPCRequest(BaseModel):
    """JSON-RPC 2.0 request message."""

    model_config = ConfigDict(frozen=True)

    jsonrpc: Literal["2.0"] = "2.0"
    method: str = Field(description="RPC method name to invoke")
    params: dict[str, Any] = Field(default_factory=dict, description="Method parameters")
    id: str | int = Field(description="Request identifier for correlating responses")
    protocol_version: str | None = Field(
        default=None, description="IPC protocol version for capability negotiation"
    )
    client_id: str | None = Field(
        default=None, description="Unique identifier for the calling client"
    )


class PauseParams(BaseModel):
    """Parameters for the pause method."""

    model_config = ConfigDict(frozen=True)


class ResumeParams(BaseModel):
    """Parameters for the resume method."""

    model_config = ConfigDict(frozen=True)


class StopParams(BaseModel):
    """Parameters for the stop method."""

    model_config = ConfigDict(frozen=True)


class SetLogLevelParams(BaseModel):
    """Parameters for the set_log_level method."""

    model_config = ConfigDict(frozen=True)

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        description="Target log level"
    )


class ReloadConfigParams(BaseModel):
    """Parameters for the reload_config method."""

    model_config = ConfigDict(frozen=True)


class GetStateParams(BaseModel):
    """Parameters for the get_state method."""

    model_config = ConfigDict(frozen=True)


class GetCapabilitiesParams(BaseModel):
    """Parameters for the get_capabilities method."""

    model_config = ConfigDict(frozen=True)


class PingParams(BaseModel):
    """Parameters for the ping method."""

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Response types (Task 5)
# ---------------------------------------------------------------------------


class RPCError(BaseModel):
    """JSON-RPC 2.0 error object."""

    model_config = ConfigDict(frozen=True)

    code: int = Field(description="Numeric error code")
    message: str = Field(description="Human-readable error description")
    data: dict[str, Any] | None = Field(default=None, description="Additional error context")


class RPCResponse(BaseModel):
    """JSON-RPC 2.0 response message."""

    model_config = ConfigDict(frozen=True)

    jsonrpc: Literal["2.0"] = "2.0"
    result: dict[str, Any] | None = Field(
        default=None, description="Success result (mutually exclusive with error)"
    )
    error: RPCError | None = Field(
        default=None, description="Error object (mutually exclusive with result)"
    )
    id: str | int | None = Field(description="Request ID this response correlates to")


class PauseResult(BaseModel):
    """Result of a pause operation."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(description="Resulting runner state")
    was_already: bool = Field(default=False, description="True if runner was already paused")


class ResumeResult(BaseModel):
    """Result of a resume operation."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(description="Resulting runner state")
    was_already: bool = Field(default=False, description="True if runner was already running")


class StopResult(BaseModel):
    """Result of a stop operation."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(description="Resulting runner state")
    was_already: bool = Field(default=False, description="True if runner was already idle")


class SetLogLevelResult(BaseModel):
    """Result of a set_log_level operation."""

    model_config = ConfigDict(frozen=True)

    level: str = Field(description="The log level that was set")
    changed: bool = Field(description="True if level actually changed")


class ReloadConfigResult(BaseModel):
    """Result of a reload_config operation."""

    model_config = ConfigDict(frozen=True)

    reloaded: bool = Field(description="Whether config was successfully reloaded")
    changes: list[dict[str, Any]] = Field(
        default_factory=list, description="Config keys that changed"
    )
    ignored: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Config keys that require restart and were ignored",
    )
    warnings: list[str] = Field(
        default_factory=list, description="Non-fatal warnings during reload"
    )


class GetStateResult(BaseModel):
    """Result of a get_state query."""

    model_config = ConfigDict(frozen=True)

    state: Literal["idle", "starting", "running", "paused", "stopping"] = Field(
        description="Current runner state"
    )
    running: bool = Field(description="True if loop is actively running")
    paused: bool = Field(description="True if loop is paused")
    current_epic: int | str | None = Field(
        default=None, description="Currently active epic identifier"
    )
    current_story: str | None = Field(default=None, description="Currently active story identifier")
    current_phase: str | None = Field(default=None, description="Currently executing phase")
    elapsed_seconds: float = Field(default=0.0, description="Total elapsed run time in seconds")
    phase_elapsed_seconds: float = Field(
        default=0.0, description="Elapsed seconds for current phase (computed at request time)"
    )
    llm_sessions: int = Field(default=0, description="Total LLM provider invocations so far")
    log_level: str | None = Field(default=None, description="Current runner log level")
    session_details: list[dict] = Field(
        default_factory=list,
        description="Per-phase LLM session details: provider, model, phase, status, provider_count",
    )
    error: str | None = Field(default=None, description="Last error message, if any")
    project_name: str | None = Field(
        default=None, description="Project directory name (e.g., 'my-project')"
    )
    project_path: str | None = Field(
        default=None, description="Absolute project root path as string"
    )


class GetCapabilitiesResult(BaseModel):
    """Result of a get_capabilities query."""

    model_config = ConfigDict(frozen=True)

    protocol_version: str = Field(description="IPC protocol version")
    server_version: str = Field(description="bmad-assist server version")
    supported_methods: list[str] = Field(description="List of supported RPC method names")
    connected_clients: list[str] = Field(
        default_factory=list, description="Currently connected client IDs"
    )
    features: dict[str, bool] = Field(default_factory=dict, description="Optional feature flags")


class PingResult(BaseModel):
    """Result of a ping health check."""

    model_config = ConfigDict(frozen=True)

    pong: bool = Field(default=True, description="Always true for successful pings")
    server_time: str = Field(description="Server timestamp in ISO 8601 format")


# ---------------------------------------------------------------------------
# Event types (Task 6)
# ---------------------------------------------------------------------------


class EventParams(BaseModel):
    """Parameters for an RPC event notification."""

    model_config = ConfigDict(frozen=True)

    seq: int = Field(description="Monotonically increasing event sequence number")
    type: str = Field(description="Event type identifier")
    data: dict[str, Any] = Field(description="Event-specific payload")
    timestamp: str = Field(description="Event timestamp in ISO 8601 format")


class RPCEvent(BaseModel):
    """JSON-RPC 2.0 event notification (no id, no response expected)."""

    model_config = ConfigDict(frozen=True)

    jsonrpc: Literal["2.0"] = "2.0"
    method: Literal["event"] = "event"
    params: EventParams = Field(description="Event parameters")


class PhaseStartedData(BaseModel):
    """Event data for phase_started events."""

    model_config = ConfigDict(frozen=True)

    phase: str = Field(description="Phase identifier that started")
    epic_id: int | str | None = Field(default=None, description="Epic being processed")
    story_id: str | None = Field(default=None, description="Story being processed")


class PhaseCompletedData(BaseModel):
    """Event data for phase_completed events."""

    model_config = ConfigDict(frozen=True)

    phase: str = Field(description="Phase identifier that completed")
    epic_id: int | str | None = Field(default=None, description="Epic that was processed")
    story_id: str | None = Field(default=None, description="Story that was processed")
    duration_seconds: float = Field(description="Wall-clock duration of the phase in seconds")


class LogData(BaseModel):
    """Event data for log events."""

    model_config = ConfigDict(frozen=True)

    level: str = Field(description="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    message: str = Field(description="Log message text")
    logger: str | None = Field(default=None, description="Logger name that emitted the message")


class StateChangedData(BaseModel):
    """Event data for state_changed events."""

    model_config = ConfigDict(frozen=True)

    field: str = Field(description="Name of the state field that changed")
    old_value: Any = Field(default=None, description="Previous value")
    new_value: Any = Field(default=None, description="New value")


class MetricsData(BaseModel):
    """Event data for periodic metrics snapshots."""

    model_config = ConfigDict(frozen=True)

    llm_sessions: int = Field(description="Total LLM sessions invoked")
    elapsed_seconds: float = Field(description="Total elapsed run time in seconds")
    phase: str | None = Field(default=None, description="Currently executing phase, if any")
    pause_state: bool = Field(default=False, description="True if runner is currently paused")


class ErrorData(BaseModel):
    """Event data for error events."""

    model_config = ConfigDict(frozen=True)

    code: int = Field(description="Numeric error code")
    message: str = Field(description="Human-readable error description")
    data: dict[str, Any] | None = Field(default=None, description="Additional error context")


class GoodbyeData(BaseModel):
    """Event data for goodbye (shutdown) events.

    Broadcast by the runner just before IPC server shutdown to notify
    connected clients of graceful disconnection.
    """

    model_config = ConfigDict(frozen=True)

    reason: Literal["normal", "stop_command", "error"] = Field(
        description="Shutdown reason"
    )
    message: str | None = Field(
        default=None, description="Optional human-readable message (e.g., error description)"
    )


# ---------------------------------------------------------------------------
# Helpers (Task 11)
# ---------------------------------------------------------------------------

_ESSENTIAL_EVENT_TYPES = frozenset({"phase_started", "phase_completed", "state_changed", "error", "goodbye"})
_METRICS_EVENT_TYPES = frozenset({"metrics"})


def get_event_priority(event_type: str) -> EventPriority:
    """Determine the priority level of an event type.

    Args:
        event_type: The event type string to classify.

    Returns:
        EventPriority for the given event type. Unknown types default to LOGS.

    """
    if event_type in _ESSENTIAL_EVENT_TYPES:
        return EventPriority.ESSENTIAL
    if event_type in _METRICS_EVENT_TYPES:
        return EventPriority.METRICS
    return EventPriority.LOGS
