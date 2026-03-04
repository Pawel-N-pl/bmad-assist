"""ToolCallGuard — LLM tool call watchdog.

Per-invocation watchdog that observes tool call patterns in provider streams
and terminates sessions when runaway behavior is detected.

Three detection mechanisms:
1. Hard budget cap on total tool calls (default: 300)
2. Per-file interaction cap — read+write+edit combined (default: 15)
3. Sliding-window per-minute rate cap (default: 90/min)

Thread safety: check() and get_stats() are protected by an internal lock,
safe for concurrent calls from stream-reader and main threads.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# Prefix used by providers to tag guard-triggered termination_reason.
# Consumers (handlers, orchestrators) check startswith(GUARD_TERMINATION_PREFIX).
GUARD_TERMINATION_PREFIX = "guard:"

logger = logging.getLogger(__name__)

# Tool names recognized as file-operating tools across all providers
_FILE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        # Claude-style
        "Read",
        "Write",
        "Edit",
        # Generic / other providers
        "read_file",
        "write_file",
        "edit_file",
        "file_read",
        "file_write",
        "file_edit",
    }
)

# Keys to search for file path in tool_input (priority order)
_FILE_PATH_KEYS: tuple[str, ...] = ("file_path", "path", "file", "filename")


@dataclass(frozen=True)
class GuardVerdict:
    """Result of a single guard check.

    Attributes:
        allowed: Whether the tool call is permitted.
        reason: Human-readable reason if denied, None if allowed.

    """

    allowed: bool
    reason: str | None = None


@dataclass(frozen=True)
class GuardStats:
    """Snapshot of guard state for diagnostics.

    Attributes:
        total_calls: Number of allowed tool calls so far.
        max_file: Tuple of (path, count) for the file with most interactions,
            or None if no file tools observed.
        rate_triggered: Whether rate cap was the trigger.
        terminated: Whether guard has been triggered.
        terminated_reason: Reason string if terminated.

    """

    total_calls: int
    max_file: tuple[str, int] | None
    rate_triggered: bool
    terminated: bool
    terminated_reason: str | None


class ToolCallGuard:
    """Per-invocation watchdog for LLM tool call patterns.

    Observes tool calls reported by providers and detects runaway loops.
    When triggered, signals the provider to terminate the session.

    Args:
        max_total_calls: Hard cap on total tool calls (any type).
        max_interactions_per_file: Max combined read+write+edit per file path.
        max_calls_per_minute: Sliding-window rate cap.
        _clock: Injectable clock function for deterministic testing.

    """

    def __init__(  # noqa: D107
        self,
        max_total_calls: int = 300,
        max_interactions_per_file: int = 15,
        max_calls_per_minute: int = 90,
        _clock: Callable[[], float] | None = None,
    ) -> None:
        if max_total_calls < 1:
            raise ValueError(f"max_total_calls must be >= 1, got {max_total_calls}")
        if max_interactions_per_file < 1:
            raise ValueError(
                f"max_interactions_per_file must be >= 1, got {max_interactions_per_file}"
            )
        if max_calls_per_minute < 1:
            raise ValueError(f"max_calls_per_minute must be >= 1, got {max_calls_per_minute}")

        self.max_total_calls = max_total_calls
        self.max_interactions_per_file = max_interactions_per_file
        self.max_calls_per_minute = max_calls_per_minute
        self._clock = _clock or time.monotonic
        self._lock = threading.Lock()

        # Counters
        self._total_calls: int = 0
        self._file_interactions: dict[str, int] = {}
        self._call_timestamps: deque[float] = deque()

        # Termination state
        self._terminated: bool = False
        self._terminated_reason: str | None = None

        logger.info(
            "ToolCallGuard active: budget=%d, file_cap=%d, rate=%d/min",
            max_total_calls,
            max_interactions_per_file,
            max_calls_per_minute,
        )

    @property
    def is_triggered(self) -> bool:
        """Whether the guard has been triggered (read-only)."""
        return self._terminated

    def check(self, tool_name: str, tool_input: dict | None = None) -> GuardVerdict:
        """Check a tool call against guard thresholds.

        Evaluates thresholds BEFORE incrementing counters. A denied call
        is never counted in total_calls, _file_interactions, or rate deque.
        Thread-safe via internal lock.

        Args:
            tool_name: Name of the tool being called.
            tool_input: Tool input dict, or None for tools without input.

        Returns:
            GuardVerdict indicating whether the call is allowed.

        """
        with self._lock:
            return self._check_unlocked(tool_name, tool_input)

    def _check_unlocked(
        self, tool_name: str, tool_input: dict | None
    ) -> GuardVerdict:
        """Internal check implementation (must hold _lock)."""
        if self._terminated:
            return GuardVerdict(
                allowed=False,
                reason=f"already_terminated:{self._terminated_reason}",
            )

        # --- Check budget BEFORE increment ---
        would_be = self._total_calls + 1
        if would_be > self.max_total_calls:
            reason = f"budget_exceeded:would_be_{would_be}/{self.max_total_calls}"
            self._terminated = True
            self._terminated_reason = reason
            return GuardVerdict(allowed=False, reason=reason)

        # --- Check per-file interaction cap ---
        file_path = self._extract_file_path(tool_name, tool_input)
        if file_path is not None:
            current_count = self._file_interactions.get(file_path, 0)
            would_be_file = current_count + 1
            if would_be_file > self.max_interactions_per_file:
                reason = (
                    f"file_interaction_cap:{file_path}"
                    f"(would_be_{would_be_file}/{self.max_interactions_per_file})"
                )
                self._terminated = True
                self._terminated_reason = reason
                return GuardVerdict(allowed=False, reason=reason)

        # --- Check sliding-window rate cap ---
        now = self._clock()
        # Trim timestamps older than 60 seconds
        while self._call_timestamps and self._call_timestamps[0] < now - 60:
            self._call_timestamps.popleft()
        if len(self._call_timestamps) >= self.max_calls_per_minute:
            reason = (
                f"rate_exceeded:would_be_"
                f"{len(self._call_timestamps) + 1}/{self.max_calls_per_minute}"
            )
            self._terminated = True
            self._terminated_reason = reason
            return GuardVerdict(allowed=False, reason=reason)

        # --- All checks passed — increment counters ---
        self._total_calls += 1
        self._call_timestamps.append(now)
        if file_path is not None:
            self._file_interactions[file_path] = (
                self._file_interactions.get(file_path, 0) + 1
            )

        return GuardVerdict(allowed=True)

    def get_stats(self) -> GuardStats:
        """Return snapshot of guard state for diagnostics (thread-safe)."""
        with self._lock:
            max_file: tuple[str, int] | None = None
            if self._file_interactions:
                top_path = max(self._file_interactions, key=self._file_interactions.get)  # type: ignore[arg-type]
                max_file = (top_path, self._file_interactions[top_path])

            return GuardStats(
                total_calls=self._total_calls,
                max_file=max_file,
                rate_triggered=(
                    self._terminated_reason is not None
                    and self._terminated_reason.startswith("rate_exceeded")
                ),
                terminated=self._terminated,
                terminated_reason=self._terminated_reason,
            )

    def reset_for_retry(self) -> None:
        """Reset rate deque for retry while preserving counters.

        Clears rate timestamps to avoid false positives from stale data.
        Preserves total_calls and _file_interactions across retry boundary.
        Clears termination state so guard can continue monitoring.
        """
        with self._lock:
            self._call_timestamps.clear()
            self._terminated = False
            self._terminated_reason = None
        logger.info(
            "ToolCallGuard reset for retry: total_calls=%d, tracked_files=%d",
            self._total_calls,
            len(self._file_interactions),
        )

    def _extract_file_path(
        self, tool_name: str, tool_input: dict | None
    ) -> str | None:
        """Extract and normalize file path from tool input.

        Only extracts paths for recognized file-operating tools.
        Uses os.path.realpath for normalization (resolves symlinks, ./, ../).

        Args:
            tool_name: Name of the tool.
            tool_input: Tool input dict.

        Returns:
            Normalized file path, or None for non-file tools or missing paths.

        """
        if tool_name not in _FILE_TOOL_NAMES:
            return None

        if not tool_input or not isinstance(tool_input, dict):
            return None

        for key in _FILE_PATH_KEYS:
            raw_path = tool_input.get(key)
            if raw_path and isinstance(raw_path, str):
                return os.path.realpath(raw_path)

        return None


def build_termination_fields(
    guard: ToolCallGuard | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Build (termination_info, termination_reason) for ProviderResult.

    Consolidates the 12-line block duplicated across all guarded providers
    into a single helper. Call after invoke completes to populate the
    ProviderResult's termination fields.

    Returns:
        (termination_info dict, termination_reason string) or (None, None).

    """
    if guard is None:
        return None, None
    stats = guard.get_stats()
    if stats.terminated:
        return dataclasses.asdict(stats), f"{GUARD_TERMINATION_PREFIX}{stats.terminated_reason}"
    if stats.total_calls > 0:
        return dataclasses.asdict(stats), None
    return None, None


def start_guard_monitor(
    process: subprocess.Popen,
    guard_kill_event: threading.Event,
    guard_done_event: threading.Event,
) -> threading.Thread:
    """Start daemon thread that terminates process when guard fires.

    Used by blocking-wait subprocess providers (gemini, amp, opencode, kimi)
    that cannot poll for guard triggers in their main loop.

    Uses graceful termination: SIGTERM first, then SIGKILL after 3s if the
    process does not exit voluntarily.

    After process.wait() completes, caller MUST set guard_done_event
    to unblock the monitor thread, then join it.

    Args:
        process: The subprocess to terminate on guard trigger.
        guard_kill_event: Set by reader thread when guard.check() denies a call.
        guard_done_event: Set by caller after process.wait() to signal
            the monitor that normal completion occurred.

    Returns:
        The started daemon monitor thread.

    """

    def _monitor() -> None:
        while not guard_kill_event.is_set() and not guard_done_event.is_set():
            guard_kill_event.wait(timeout=0.5)
        if guard_kill_event.is_set():
            # Graceful: SIGTERM first, then SIGKILL after 3s
            with contextlib.suppress(OSError):
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):
                    process.kill()

    thread = threading.Thread(target=_monitor, daemon=True)
    thread.start()
    return thread
