"""PlainRenderer - passes through to current stdout/Rich logging behavior.

This renderer replicates the existing loop output format (phase banners via
Rich console, log messages via Python logging) for CI/pipes/non-TTY contexts.
"""

from __future__ import annotations

import logging
from datetime import datetime

from bmad_assist.cli_utils import console, format_duration_cli, update_log_level
from bmad_assist.core.types import EpicId
from bmad_assist.ipc.types import RunnerState

logger = logging.getLogger("bmad_assist.tui.plain")


class PlainRenderer:
    """Renderer that delegates to stdout/Rich logging.

    Produces output equivalent to the current loop behavior:
    - Phase banners via Rich console (bold bright_white)
    - Log messages via Python logging module
    - No status bar (plain mode)
    """

    def start(self) -> None:
        """No-op - plain mode needs no initialization."""

    def stop(self) -> None:
        """No-op - plain mode needs no teardown."""

    def render_log(self, level: str, message: str, logger_name: str, timestamp: datetime) -> None:
        """Delegate to Python logging at the appropriate level.

        The timestamp parameter is ignored - Python logging manages its own
        timestamps via the configured formatter.

        Args:
            level: Log level name (DEBUG, INFO, WARNING, ERROR).
            message: Log message text.
            logger_name: Logger name for the log record.
            timestamp: Ignored (Python logging uses its own timestamp).

        """
        log = logging.getLogger(logger_name) # Use provided logger_name
        numeric_level = getattr(logging, level.upper(), logging.INFO)
        log.log(numeric_level, message)

    def render_phase_started(self, phase: str, epic_id: EpicId, story_id: str) -> None:
        """Print phase banner matching _print_phase_banner() format.

        Format: [PHASE NAME] Epic {epic_id} Story {story_id}
        Rendered via Rich console with bold bright_white styling,
        with a bare print() fallback on error.

        Args:
            phase: Phase name (e.g., "create_story").
            epic_id: Epic identifier (int or str).
            story_id: Story identifier (e.g., "1.1").

        """
        banner = f"[{phase.upper().replace('_', ' ')}] Epic {epic_id} Story {story_id}"
        try:
            console.print(banner, style="bold bright_white")
        except Exception:
            # Fallback to plain print (matches _print_phase_banner pattern)
            print(banner)


    def render_phase_completed(
        self, phase: str, epic_id: EpicId, story_id: str, duration: float
    ) -> None:
        """Log phase completion with formatted duration.

        Args:
            phase: Phase name (e.g., "create_story").
            epic_id: Epic identifier (int or str).
            story_id: Story identifier (e.g., "1.1").
            duration: Phase duration in seconds.

        """
        duration_str = format_duration_cli(duration)
        logger.info(
            "[%s] Epic %s Story %s completed in %s",
            phase.upper().replace("_", " "),
            epic_id,
            story_id,
            duration_str,
        )

    def update_status(self, state: RunnerState) -> None:
        """No-op - plain mode has no status bar."""

    def set_log_level(self, level: str) -> None:
        """Update root logger AND all handlers via cli_utils.

        Args:
            level: Log level name (DEBUG, INFO, WARNING).

        """
        update_log_level(level)
