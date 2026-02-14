"""ProjectContext for multi-project dashboard.

Encapsulates state for one registered project including:
- Project identification (UUID, path, display name)
- Current process state (subprocess management)
- Loop state machine (IDLE, STARTING, RUNNING, PAUSED, ERROR, QUEUED)
- Log ring buffer for SSE history
- Phase timing for stuck process detection

Based on design document: docs/multi-project-dashboard.md Section 4.1
"""

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from subprocess import Popen
from typing import Any

logger = logging.getLogger(__name__)

# Default ring buffer size for log retention
DEFAULT_LOG_BUFFER_SIZE = 500


class LoopState(StrEnum):
    """State machine for project lifecycle.

    Valid transitions:
        IDLE → STARTING (on start)
        IDLE → QUEUED (when max concurrent reached)
        STARTING → RUNNING (when subprocess confirmed alive)
        STARTING → ERROR (on failure)
        RUNNING → PAUSE_REQUESTED (on pause request)
        RUNNING → ERROR (on crash)
        RUNNING → IDLE (on stop or completion)
        PAUSE_REQUESTED → PAUSED (when step completes)
        PAUSED → RUNNING (on resume)
        PAUSED → IDLE (on stop)
        QUEUED → STARTING (when slot available)
        QUEUED → IDLE (on cancel)
        ERROR → IDLE (on stop/clear)
    """

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    QUEUED = "queued"
    ERROR = "error"


@dataclass
class ProjectContext:
    """Encapsulates state for one registered project.

    Attributes:
        project_uuid: Stable UUID, generated once on first registration.
        project_root: Absolute canonical path to project directory.
        display_name: User-friendly name for UI display.
        current_process: Running subprocess or None if idle.
        state: Current loop state machine value.
        log_buffer: Ring buffer for SSE history (maxlen=log_buffer_size).
        phase_start_time: When current phase started (for stuck detection).
        last_seen: Last activity timestamp (for registry health checks).
        last_status: Last known completion status (SUCCESS, FAILED, IDLE).
        current_epic: Current epic being processed (if running).
        current_story: Current story being processed (if running).
        current_phase: Current phase being executed (if running).
        error_message: Error message if state is ERROR.
        queue_position: Position in queue if state is QUEUED.

    """

    project_uuid: str
    project_root: Path
    display_name: str
    current_process: Popen[bytes] | None = None
    state: LoopState = LoopState.IDLE
    log_buffer: deque[str] = field(default_factory=lambda: deque(maxlen=DEFAULT_LOG_BUFFER_SIZE))
    phase_start_time: datetime | None = None
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_status: str = "IDLE"
    current_epic: int | str | None = None
    current_story: str | None = None
    current_phase: str | None = None
    error_message: str | None = None
    queue_position: int | None = None

    @classmethod
    def create(
        cls,
        project_root: Path,
        display_name: str | None = None,
        log_buffer_size: int = DEFAULT_LOG_BUFFER_SIZE,
    ) -> "ProjectContext":
        """Create a new ProjectContext with generated UUID.

        Args:
            project_root: Absolute path to project directory.
            display_name: Optional display name (defaults to directory basename).
            log_buffer_size: Size of log ring buffer (default 500).

        Returns:
            New ProjectContext instance.

        Raises:
            ValueError: If project_root does not exist.

        """
        if not project_root.exists():
            raise ValueError(f"Project path does not exist: {project_root}")

        canonical_path = project_root.resolve()
        name = display_name or canonical_path.name

        return cls(
            project_uuid=str(uuid.uuid4()),
            project_root=canonical_path,
            display_name=name,
            log_buffer=deque(maxlen=log_buffer_size),
        )

    def add_log(self, line: str) -> None:
        """Add a log line to the ring buffer.

        Args:
            line: Log line to add.

        """
        self.log_buffer.append(line)
        self.last_seen = datetime.now(UTC)

    def get_logs(self, count: int | None = None) -> list[str]:
        """Get logs from the ring buffer.

        Args:
            count: Number of recent logs to return (None for all).

        Returns:
            List of log lines (oldest first).

        """
        if count is None:
            return list(self.log_buffer)
        return list(self.log_buffer)[-count:]

    def clear_logs(self) -> None:
        """Clear the log buffer."""
        self.log_buffer.clear()

    def set_running(self, process: Popen[bytes]) -> None:
        """Transition to RUNNING state with subprocess.

        Args:
            process: The running subprocess.

        """
        self.current_process = process
        self.state = LoopState.RUNNING
        self.phase_start_time = datetime.now(UTC)
        self.last_seen = datetime.now(UTC)
        self.error_message = None
        self.queue_position = None
        logger.info("Project %s (%s) started running", self.display_name, self.project_uuid[:8])

    def set_paused(self) -> None:
        """Transition to PAUSED state."""
        self.state = LoopState.PAUSED
        self.last_seen = datetime.now(UTC)
        logger.info("Project %s (%s) paused", self.display_name, self.project_uuid[:8])

    def set_error(self, message: str) -> None:
        """Transition to ERROR state.

        Args:
            message: Error message describing the failure.

        """
        self.state = LoopState.ERROR
        self.error_message = message
        self.current_process = None
        self.last_seen = datetime.now(UTC)
        self.last_status = "FAILED"
        logger.error("Project %s (%s) error: %s", self.display_name, self.project_uuid[:8], message)

    def set_idle(self, success: bool = True) -> None:
        """Transition to IDLE state.

        Args:
            success: Whether the loop completed successfully.

        """
        self.state = LoopState.IDLE
        self.current_process = None
        self.phase_start_time = None
        self.current_epic = None
        self.current_story = None
        self.current_phase = None
        self.error_message = None
        self.queue_position = None
        self.last_seen = datetime.now(UTC)
        self.last_status = "SUCCESS" if success else "FAILED"
        logger.info(
            "Project %s (%s) now idle (status: %s)",
            self.display_name,
            self.project_uuid[:8],
            self.last_status,
        )

    def set_queued(self, position: int) -> None:
        """Transition to QUEUED state.

        Args:
            position: Position in the queue (1-based).

        """
        self.state = LoopState.QUEUED
        self.queue_position = position
        self.last_seen = datetime.now(UTC)
        logger.info(
            "Project %s (%s) queued at position %d",
            self.display_name,
            self.project_uuid[:8],
            position,
        )

    def update_position(
        self,
        epic: int | str | None = None,
        story: str | None = None,
        phase: str | None = None,
    ) -> None:
        """Update current execution position.

        Args:
            epic: Current epic ID.
            story: Current story ID.
            phase: Current phase name.

        """
        if epic is not None:
            self.current_epic = epic
        if story is not None:
            self.current_story = story
        if phase is not None:
            self.current_phase = phase
            self.phase_start_time = datetime.now(UTC)
        self.last_seen = datetime.now(UTC)

    def get_phase_duration_seconds(self) -> float | None:
        """Get time spent in current phase.

        Returns:
            Seconds since phase started, or None if not in a phase.

        """
        if self.phase_start_time is None:
            return None
        delta = datetime.now(UTC) - self.phase_start_time.replace(tzinfo=UTC)
        return delta.total_seconds()

    def to_summary(self) -> dict[str, Any]:
        """Get summary dict for API response.

        Returns:
            Dictionary with project summary for UI.

        """
        return {
            "uuid": self.project_uuid,
            "path": str(self.project_root),
            "display_name": self.display_name,
            "state": self.state.value,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "last_status": self.last_status,
            "current_epic": self.current_epic,
            "current_story": self.current_story,
            "current_phase": self.current_phase,
            "phase_duration_seconds": self.get_phase_duration_seconds(),
            "error_message": self.error_message,
            "queue_position": self.queue_position,
        }

    def is_active(self) -> bool:
        """Check if project has an active loop.

        Returns:
            True if running, paused, or queued.

        """
        return self.state in (
            LoopState.STARTING,
            LoopState.RUNNING,
            LoopState.PAUSE_REQUESTED,
            LoopState.PAUSED,
            LoopState.QUEUED,
        )
