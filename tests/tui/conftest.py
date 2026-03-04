"""Shared test fixtures for TUI tests.

Provides event factory functions and FakeEventSource for replaying
IPC event sequences in tests. Does NOT override existing local fixtures
in test_interactive.py.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Event factory functions
# ---------------------------------------------------------------------------


def make_log_event(
    seq: int,
    level: str = "INFO",
    message: str = "test",
    logger: str = "test.logger",
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Create a log event params dict."""
    return {
        "seq": seq,
        "type": "log",
        "data": {"level": level, "message": message, "logger": logger},
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }


def make_phase_started_event(
    seq: int,
    phase: str = "create_story",
    epic_id: int | str | None = 1,
    story_id: str | None = "1.1",
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Create a phase_started event params dict."""
    return {
        "seq": seq,
        "type": "phase_started",
        "data": {"phase": phase, "epic_id": epic_id, "story_id": story_id},
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }


def make_phase_completed_event(
    seq: int,
    phase: str = "create_story",
    epic_id: int | str | None = 1,
    story_id: str | None = "1.1",
    duration_seconds: float = 42.0,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Create a phase_completed event params dict."""
    return {
        "seq": seq,
        "type": "phase_completed",
        "data": {
            "phase": phase,
            "epic_id": epic_id,
            "story_id": story_id,
            "duration_seconds": duration_seconds,
        },
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }


def make_state_changed_event(
    seq: int,
    field: str = "state",
    old_value: Any = "idle",
    new_value: Any = "running",
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Create a state_changed event params dict."""
    return {
        "seq": seq,
        "type": "state_changed",
        "data": {"field": field, "old_value": old_value, "new_value": new_value},
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }


def make_metrics_event(
    seq: int,
    llm_sessions: int = 3,
    elapsed_seconds: float = 120.0,
    phase: str | None = "dev_story",
    pause_state: bool = False,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Create a metrics event params dict."""
    return {
        "seq": seq,
        "type": "metrics",
        "data": {
            "llm_sessions": llm_sessions,
            "elapsed_seconds": elapsed_seconds,
            "phase": phase,
            "pause_state": pause_state,
        },
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }


def make_goodbye_event(
    seq: int,
    reason: str = "normal",
    message: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Create a goodbye event params dict."""
    return {
        "seq": seq,
        "type": "goodbye",
        "data": {"reason": reason, "message": message},
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }


def make_error_event(
    seq: int,
    code: int = -32000,
    message: str = "Something went wrong",
    data: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Create an error event params dict."""
    return {
        "seq": seq,
        "type": "error",
        "data": {"code": code, "message": message, "data": data},
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# FakeEventSource
# ---------------------------------------------------------------------------


class FakeEventSource:
    """Replays recorded IPC event sequences for testing.

    Takes a list of (delay_ms, event_dict) tuples and replays them
    to a callback function, supporting both sync and async modes.

    Supports:
    - Synchronous replay for unit tests (no event loop needed)
    - Async replay with asyncio.sleep for integration tests
    - Abrupt termination at index N
    - Seq gap injection (just provide non-contiguous seq values)

    Args:
        events: List of (delay_ms, event_dict) tuples.

    """

    def __init__(self, events: list[tuple[int, dict[str, Any]]]) -> None:  # noqa: D107
        self._events = events

    def replay_sync(
        self,
        callback: Callable[[dict[str, Any]], None],
        *,
        terminate_at: int | None = None,
    ) -> int:
        """Synchronous replay for unit tests (no delays applied).

        Args:
            callback: Called with each event dict.
            terminate_at: If set, stop after processing this many events
                (simulates abrupt termination).

        Returns:
            Number of events dispatched.

        """
        count = 0
        for _delay_ms, event in self._events:
            if terminate_at is not None and count >= terminate_at:
                break
            callback(event)
            count += 1
        return count

    async def replay_async(
        self,
        callback: Callable[[dict[str, Any]], Any],
        *,
        terminate_at: int | None = None,
        time_scale: float = 1.0,
    ) -> int:
        """Async replay with delays for integration tests.

        Args:
            callback: Called with each event dict. Can be sync or async.
            terminate_at: If set, stop after processing this many events.
            time_scale: Multiplier for delay_ms (0.0 = no delay, 1.0 = real-time).

        Returns:
            Number of events dispatched.

        """
        count = 0
        for delay_ms, event in self._events:
            if terminate_at is not None and count >= terminate_at:
                break
            if delay_ms > 0 and time_scale > 0:
                await asyncio.sleep(delay_ms / 1000.0 * time_scale)
            result = callback(event)
            if asyncio.iscoroutine(result):
                await result
            count += 1
        return count


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_event_source() -> type[FakeEventSource]:
    """Return the FakeEventSource class for constructing sources in tests."""
    return FakeEventSource
