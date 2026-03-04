"""Renderer protocol for bmad-assist TUI abstraction.

Defines the structural subtyping protocol that all renderers must satisfy.
Uses typing.Protocol (PEP 544) for duck-typing - no inheritance required.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from bmad_assist.core.types import EpicId
from bmad_assist.ipc.types import RunnerState


@runtime_checkable
class Renderer(Protocol):
    """Protocol for rendering loop output.

    Implementations control how phase banners, log messages, and status
    updates are displayed. PlainRenderer delegates to stdout/logging,
    InteractiveRenderer will drive the TUI (Stories 30.2-30.6).

    All methods use primitive types to stay decoupled from IPC internals.
    """

    def start(self) -> None:
        """Initialize the renderer (e.g., enter alternate screen)."""
        ...

    def stop(self) -> None:
        """Tear down the renderer (e.g., restore terminal)."""
        ...

    def render_log(self, level: str, message: str, logger_name: str, timestamp: datetime) -> None:
        """Render a log message.

        Args:
            level: Log level name (DEBUG, INFO, WARNING, ERROR).
            message: Log message text.
            logger_name: Logger name (e.g., "bmad_assist.core.loop").
            timestamp: When the log event occurred.

        """
        ...

    def render_phase_started(self, phase: str, epic_id: EpicId, story_id: str) -> None:
        """Render phase start banner.

        Args:
            phase: Phase name (e.g., "create_story").
            epic_id: Epic identifier (int or str).
            story_id: Story identifier (e.g., "1.1").

        """
        ...

    def render_phase_completed(
        self, phase: str, epic_id: EpicId, story_id: str, duration: float
    ) -> None:
        """Render phase completion with duration.

        Args:
            phase: Phase name (e.g., "create_story").
            epic_id: Epic identifier (int or str).
            story_id: Story identifier (e.g., "1.1").
            duration: Phase duration in seconds.

        """
        ...

    def update_status(self, state: RunnerState) -> None:
        """Update the runner status display.

        Args:
            state: Current runner lifecycle state.

        """
        ...

    def set_log_level(self, level: str) -> None:
        """Change the renderer's log verbosity.

        Args:
            level: Log level name (DEBUG, INFO, WARNING).

        """
        ...
