"""Project registry for multi-project dashboard.

Manages lifecycle of all ProjectContext instances with:
- Registration/unregistration
- Persistence to ~/.config/bmad-assist/projects.yaml
- Concurrency limiting and queueing
- Health checking and reconciliation

Based on design document: docs/multi-project-dashboard.md Section 4.2
"""

import logging
import os
from collections import deque
from pathlib import Path
from typing import Any

import yaml

from .project_context import LoopState, ProjectContext

logger = logging.getLogger(__name__)

# XDG-compliant config location
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "bmad-assist"
DEFAULT_PROJECTS_FILE = "projects.yaml"
DEFAULT_SERVER_CONFIG_FILE = "server.yaml"

# Default concurrency limits
DEFAULT_MAX_CONCURRENT_LOOPS = 2
DEFAULT_QUEUE_MAX_SIZE = 10
DEFAULT_SUBPROCESS_TIMEOUT = 30
DEFAULT_LOG_BUFFER_SIZE = 500


class ProjectRegistry:
    """Manages lifecycle of all ProjectContext instances.

    Provides:
    - Project registration with UUID assignment
    - Persistence to projects.yaml
    - Concurrency limiting via max_concurrent_loops
    - FIFO queue when limit reached
    - Health reconciliation on startup

    Attributes:
        config_dir: Directory for registry configuration.
        max_concurrent_loops: Maximum simultaneous running loops.
        queue_max_size: Maximum queue size.
        subprocess_timeout: Timeout for graceful subprocess shutdown.
        log_buffer_size: Size of per-project log ring buffer.

    """

    def __init__(
        self,
        config_dir: Path | None = None,
        max_concurrent_loops: int = DEFAULT_MAX_CONCURRENT_LOOPS,
        queue_max_size: int = DEFAULT_QUEUE_MAX_SIZE,
        subprocess_timeout: int = DEFAULT_SUBPROCESS_TIMEOUT,
        log_buffer_size: int = DEFAULT_LOG_BUFFER_SIZE,
    ) -> None:
        """Initialize project registry.

        Args:
            config_dir: Directory for configuration files.
            max_concurrent_loops: Maximum simultaneous running loops.
            queue_max_size: Maximum queue size.
            subprocess_timeout: Timeout for graceful subprocess shutdown.
            log_buffer_size: Size of per-project log ring buffer.

        """
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self.max_concurrent_loops = max_concurrent_loops
        self.queue_max_size = queue_max_size
        self.subprocess_timeout = subprocess_timeout
        self.log_buffer_size = log_buffer_size

        self._projects: dict[str, ProjectContext] = {}
        self._queue: deque[str] = deque()  # Queue of project UUIDs

        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Load server config if present
        self._load_server_config()

        # Load persisted projects
        self._load_projects()

    def _load_server_config(self) -> None:
        """Load server configuration from server.yaml."""
        config_path = self.config_dir / DEFAULT_SERVER_CONFIG_FILE
        if not config_path.exists():
            return

        try:
            with config_path.open() as f:
                config = yaml.safe_load(f) or {}

            server_config = config.get("server", {})
            if "max_concurrent_loops" in server_config:
                self.max_concurrent_loops = server_config["max_concurrent_loops"]
            if "queue_max_size" in server_config:
                self.queue_max_size = server_config["queue_max_size"]
            if "subprocess_timeout_seconds" in server_config:
                self.subprocess_timeout = server_config["subprocess_timeout_seconds"]
            if "log_buffer_size" in server_config:
                self.log_buffer_size = server_config["log_buffer_size"]

            logger.info(
                "Loaded server config: max_concurrent=%d, queue_max=%d",
                self.max_concurrent_loops,
                self.queue_max_size,
            )
        except Exception:
            logger.exception("Failed to load server config from %s", config_path)

    def _load_projects(self) -> None:
        """Load persisted projects from projects.yaml."""
        projects_path = self.config_dir / DEFAULT_PROJECTS_FILE
        if not projects_path.exists():
            return

        try:
            with projects_path.open() as f:
                data = yaml.safe_load(f) or {}

            projects_list = data.get("projects", [])
            for proj in projects_list:
                try:
                    project_root = Path(proj["path"])
                    context = ProjectContext(
                        project_uuid=proj["uuid"],
                        project_root=project_root,
                        display_name=proj.get("display_name", project_root.name),
                        last_status=proj.get("last_status", "IDLE"),
                    )
                    self._projects[context.project_uuid] = context
                    logger.debug("Loaded project: %s (%s)", context.display_name, context.project_uuid[:8])
                except Exception:
                    logger.exception("Failed to load project: %s", proj)

            logger.info("Loaded %d projects from registry", len(self._projects))
        except Exception:
            logger.exception("Failed to load projects from %s", projects_path)

    def _save_projects(self) -> None:
        """Persist projects to projects.yaml."""
        projects_path = self.config_dir / DEFAULT_PROJECTS_FILE

        projects_list = []
        for ctx in self._projects.values():
            projects_list.append({
                "uuid": ctx.project_uuid,
                "path": str(ctx.project_root),
                "display_name": ctx.display_name,
                "last_seen": ctx.last_seen.isoformat() if ctx.last_seen else None,
                "last_status": ctx.last_status,
            })

        data = {"projects": projects_list}

        try:
            with projects_path.open("w") as f:
                yaml.safe_dump(data, f, default_flow_style=False)
            logger.debug("Saved %d projects to registry", len(projects_list))
        except Exception:
            logger.exception("Failed to save projects to %s", projects_path)

    def register(
        self,
        path: Path,
        display_name: str | None = None,
    ) -> str:
        """Register a new project.

        Args:
            path: Path to project directory.
            display_name: Optional display name for UI.

        Returns:
            The project UUID.

        Raises:
            ValueError: If path doesn't exist or already registered.

        """
        canonical_path = path.resolve()

        # Check if already registered
        for ctx in self._projects.values():
            if ctx.project_root == canonical_path:
                logger.info("Project already registered: %s", ctx.project_uuid)
                return ctx.project_uuid

        # Validate path exists
        if not canonical_path.exists():
            raise ValueError(f"Project path does not exist: {canonical_path}")

        # Create context
        context = ProjectContext.create(
            project_root=canonical_path,
            display_name=display_name,
            log_buffer_size=self.log_buffer_size,
        )

        self._projects[context.project_uuid] = context
        self._save_projects()

        logger.info(
            "Registered project: %s (%s) at %s",
            context.display_name,
            context.project_uuid[:8],
            context.project_root,
        )
        return context.project_uuid

    def unregister(self, project_uuid: str) -> None:
        """Remove a project from the registry.

        Args:
            project_uuid: UUID of project to remove.

        Raises:
            KeyError: If project not found.
            RuntimeError: If project loop is running.

        """
        context = self._projects.get(project_uuid)
        if context is None:
            raise KeyError(f"Project not found: {project_uuid}")

        if context.is_active():
            raise RuntimeError(
                f"Cannot unregister project {context.display_name}: loop is active"
            )

        del self._projects[project_uuid]
        self._save_projects()

        logger.info("Unregistered project: %s (%s)", context.display_name, project_uuid[:8])

    def get(self, project_uuid: str) -> ProjectContext:
        """Get project context by UUID.

        Args:
            project_uuid: UUID of project.

        Returns:
            ProjectContext instance.

        Raises:
            KeyError: If project not found.

        """
        context = self._projects.get(project_uuid)
        if context is None:
            raise KeyError(f"Project not found: {project_uuid}")
        return context

    def get_by_path(self, path: Path) -> ProjectContext | None:
        """Get project context by path.

        Args:
            path: Project path to look up.

        Returns:
            ProjectContext if found, None otherwise.

        """
        canonical_path = path.resolve()
        for ctx in self._projects.values():
            if ctx.project_root == canonical_path:
                return ctx
        return None

    def list_all(self) -> list[dict[str, Any]]:
        """Get summary of all registered projects.

        Returns:
            List of project summaries for API response.

        """
        return [ctx.to_summary() for ctx in self._projects.values()]

    def reconcile(self) -> list[str]:
        """Check for broken paths and stale states.

        Cleans up:
        - Projects with non-existent paths (marks as BROKEN)
        - Stale flag files from crashed processes

        Returns:
            List of project UUIDs that are broken (path doesn't exist).

        """
        broken_uuids: list[str] = []

        for uuid, ctx in self._projects.items():
            # Check path exists
            if not ctx.project_root.exists():
                logger.warning(
                    "Project path no longer exists: %s (%s)",
                    ctx.display_name,
                    ctx.project_root,
                )
                broken_uuids.append(uuid)
                ctx.set_error("Project path does not exist")
                continue

            # Clean up stale flags on startup
            bmad_dir = ctx.project_root / ".bmad-assist"
            for flag_name in ("pause.flag", "stop.flag"):
                flag_path = bmad_dir / flag_name
                try:
                    if flag_path.exists():
                        flag_path.unlink()
                        logger.info("Cleaned up stale %s for %s", flag_name, ctx.display_name)
                except Exception:
                    logger.exception("Failed to clean up %s", flag_path)

            # Reset any non-idle states to idle (server restart scenario)
            if ctx.state != LoopState.IDLE and ctx.state != LoopState.ERROR:
                logger.info(
                    "Resetting state for %s from %s to IDLE (server restart)",
                    ctx.display_name,
                    ctx.state,
                )
                ctx.set_idle(success=False)

        self._save_projects()
        return broken_uuids

    def can_start_loop(self) -> bool:
        """Check if a new loop can start immediately.

        Returns:
            True if under max_concurrent_loops limit.

        """
        active_count = sum(
            1 for ctx in self._projects.values()
            if ctx.state in (LoopState.STARTING, LoopState.RUNNING, LoopState.PAUSE_REQUESTED)
        )
        return active_count < self.max_concurrent_loops

    def get_queue_position(self, project_uuid: str) -> int | None:
        """Get queue position for a project.

        Args:
            project_uuid: UUID of project.

        Returns:
            1-based queue position, or None if not queued.

        """
        try:
            idx = list(self._queue).index(project_uuid)
            return idx + 1
        except ValueError:
            return None

    def enqueue(self, project_uuid: str) -> int:
        """Add project to start queue.

        Args:
            project_uuid: UUID of project to queue.

        Returns:
            1-based queue position.

        Raises:
            KeyError: If project not found.
            ValueError: If queue is full.

        """
        context = self.get(project_uuid)

        if project_uuid in self._queue:
            return self.get_queue_position(project_uuid) or 1

        if len(self._queue) >= self.queue_max_size:
            raise ValueError(f"Queue is full (max {self.queue_max_size})")

        self._queue.append(project_uuid)
        position = len(self._queue)
        context.set_queued(position)

        logger.info(
            "Queued project %s at position %d",
            context.display_name,
            position,
        )
        return position

    def dequeue(self) -> str | None:
        """Remove and return next project from queue.

        Returns:
            Project UUID, or None if queue is empty.

        """
        if not self._queue:
            return None

        project_uuid = self._queue.popleft()

        # Update remaining queue positions
        for idx, uuid in enumerate(self._queue):
            ctx = self._projects.get(uuid)
            if ctx and ctx.state == LoopState.QUEUED:
                ctx.queue_position = idx + 1

        return project_uuid

    def cancel_queue(self, project_uuid: str) -> bool:
        """Remove project from queue.

        Args:
            project_uuid: UUID of project to remove from queue.

        Returns:
            True if removed, False if not in queue.

        """
        if project_uuid not in self._queue:
            return False

        self._queue.remove(project_uuid)
        context = self._projects.get(project_uuid)
        if context:
            context.set_idle(success=False)

        # Update remaining queue positions
        for idx, uuid in enumerate(self._queue):
            ctx = self._projects.get(uuid)
            if ctx and ctx.state == LoopState.QUEUED:
                ctx.queue_position = idx + 1

        logger.info("Cancelled queue for project %s", project_uuid[:8])
        return True

    def get_running_count(self) -> int:
        """Get count of currently running loops.

        Returns:
            Number of loops in STARTING, RUNNING, or PAUSE_REQUESTED state.

        """
        return sum(
            1 for ctx in self._projects.values()
            if ctx.state in (LoopState.STARTING, LoopState.RUNNING, LoopState.PAUSE_REQUESTED)
        )

    def scan_directory(self, directory: Path) -> list[str]:
        """Scan directory for bmad-assist projects.

        Looks for directories containing .bmad-assist/ subdirectory.

        Args:
            directory: Directory to scan.

        Returns:
            List of project UUIDs for newly registered projects.

        """
        discovered_uuids: list[str] = []

        if not directory.exists():
            logger.warning("Scan directory does not exist: %s", directory)
            return discovered_uuids

        for entry in directory.iterdir():
            if not entry.is_dir():
                continue

            bmad_dir = entry / ".bmad-assist"
            if bmad_dir.exists() and bmad_dir.is_dir():
                # Check if already registered
                existing = self.get_by_path(entry)
                if existing:
                    logger.debug("Already registered: %s", existing.display_name)
                    continue

                try:
                    uuid = self.register(entry)
                    discovered_uuids.append(uuid)
                    logger.info("Discovered project: %s", entry.name)
                except Exception:
                    logger.exception("Failed to register discovered project: %s", entry)

        return discovered_uuids
