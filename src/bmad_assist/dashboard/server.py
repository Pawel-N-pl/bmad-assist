"""Dashboard HTTP server for bmad-assist.

This module implements the main dashboard server using Starlette/Uvicorn:
- Serves static dashboard files
- Provides REST API endpoints
- Manages SSE connections for real-time updates
- Integrates with bmad-assist for task execution

Public API:
    DashboardServer: Main server class
    start_server: Convenience function to start server
"""

import asyncio
import contextlib
import logging
import os
import re
import signal
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import BaseRoute, Mount
from starlette.staticfiles import StaticFiles

from bmad_assist.core.exceptions import DashboardError

# Story 22.9: Dashboard event marker for stdout parsing
from bmad_assist.core.loop.dashboard_events import DASHBOARD_EVENT_MARKER
from bmad_assist.core.state import State, get_state_path, load_state
from bmad_assist.dashboard.routes import API_ROUTES
from bmad_assist.dashboard.sse import SSEBroadcaster

logger = logging.getLogger(__name__)


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if port is available for binding.

    Args:
        port: Port number to check.
        host: Host address to bind to.

    Returns:
        True if port can be bound, False if busy.

    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            return True
    except OSError:
        return False


def find_available_port(
    start_port: int = 9600,
    host: str = "127.0.0.1",
    max_attempts: int = 10,
) -> int:
    """Find available port, incrementing by 2.

    Args:
        start_port: First port to try.
        host: Host address to bind to (must match server's --host).
        max_attempts: Maximum number of ports to try.

    Returns:
        First available port number.

    Raises:
        DashboardError: If no available port found after max_attempts.

    """
    tried: list[int] = []
    for i in range(max_attempts):
        port = start_port + (i * 2)
        tried.append(port)
        if is_port_available(port, host):
            return port

    raise DashboardError(
        f"No available port. Tried: {tried[0]}-{tried[-1]}. "
        f"Free a port or use --port with different value."
    )


# Phase display name mapping (snake_case → human-readable)
# Follows unified convention from docs/project_context.md
# Synthesis phases use shortcuts ("Val Synth", "Rev Synth") for space-constrained UI
PHASE_DISPLAY_NAMES: dict[str, str] = {
    "create_story": "Create Story",
    "validate_story": "Validate Story",
    "validate_story_synthesis": "Val Synth",
    "atdd": "ATDD",
    "dev_story": "Develop Story",
    "code_review": "Code Review",
    "code_review_synthesis": "Rev Synth",
    "test_review": "Test Review",
    "retrospective": "Retrospective",
    "qa_plan_generate": "QA Plan",
    "qa_plan_execute": "QA Exec",
}


def _build_phases_from_config(phase_list: list[str]) -> list[dict[str, str]]:
    """Build phase dictionaries from loop config phase list.

    Converts snake_case phase IDs to display-friendly format.

    Args:
        phase_list: List of phase IDs from LoopConfig.story.

    Returns:
        List of phase dicts with id, name, and status keys.

    Example:
        >>> _build_phases_from_config(["create_story", "dev_story"])
        [{"id": "create_story", "name": "Create Story", "status": "pending"},
         {"id": "dev_story", "name": "Develop Story", "status": "pending"}]

    """
    phases = []
    for phase_id in phase_list:
        display_name = PHASE_DISPLAY_NAMES.get(
            phase_id,
            phase_id.replace("_", " ").title(),  # Fallback: snake_case → Title Case
        )
        phases.append({"id": phase_id, "name": display_name, "status": "pending"})
    return phases


class DashboardServer:
    """Main dashboard server for bmad-assist.

    Provides web interface for:
    - Viewing sprint status and stories
    - Streaming live output
    - Triggering workflow actions

    Attributes:
        host: Server bind address.
        port: Server bind port.
        project_root: Path to bmad-assist project.
        sse_broadcaster: SSE broadcaster instance.

    """

    def __init__(
        self,
        project_root: Path,
        host: str = "127.0.0.1",
        port: int = 9600,
    ) -> None:
        """Initialize dashboard server.

        Args:
            project_root: Path to bmad-assist project root.
            host: Address to bind server to.
            port: Port to bind server to.

        Raises:
            DashboardError: If sprint-status.yaml is not found.

        """
        self.host = host
        self.port = port
        self.project_root = project_root

        # Initialize paths singleton if not already done
        self._ensure_paths_initialized()

        # Find or auto-generate sprint-status.yaml
        self._sprint_status_path = self._find_sprint_status()
        if self._sprint_status_path is None:
            logger.info("sprint-status.yaml not found, auto-generating from epics...")
            self._sprint_status_path = self._generate_sprint_status()
            if self._sprint_status_path is None:
                from bmad_assist.core.paths import get_paths

                paths = get_paths()
                searched = paths.get_sprint_status_search_locations()
                paths_list = "\n".join(f"  - {p}" for p in searched)
                raise DashboardError(
                    f"sprint-status.yaml not found and auto-generation failed!\n\n"
                    f"Searched locations:\n{paths_list}\n\n"
                    f"This project has no epic files to generate from.\n"
                    f"Create an epic file in docs/epics/ first."
                )

        self.sse_broadcaster = SSEBroadcaster()
        self._app: Starlette | None = None
        self._server: Any = None
        self._shutdown_event = asyncio.Event()
        self._loop_running = False
        self._pause_requested = False  # Pause after current workflow completes
        self._stop_requested = False  # Stop immediately (terminate current workflow)
        self._loop_task: asyncio.Task[None] | None = None
        self._current_process: asyncio.subprocess.Process | None = None

        # Story 22.9: Run ID tracking for SSE events
        self._run_id: str = ""

        # Experiment run tracking (Story 19.6)
        self._experiment_lock = asyncio.Lock()
        self._active_experiment_run_id: str | None = None
        self._active_experiment_cancel_event: asyncio.Event | None = None

    def _ensure_paths_initialized(self) -> None:
        """Initialize paths singleton if not already done.

        Loads config to get external paths if configured, otherwise uses defaults.
        """
        from bmad_assist.core.paths import get_paths, init_paths

        try:
            get_paths()  # Check if already initialized
        except RuntimeError:
            # Initialize paths if not already done (e.g., standalone serve)
            from bmad_assist.core.config import load_config_with_project
            from bmad_assist.core.exceptions import ConfigError

            try:
                config = load_config_with_project(project_path=self.project_root)
                paths_config = {}
                if config.paths:
                    if config.paths.output_folder:
                        paths_config["output_folder"] = config.paths.output_folder
                    if config.paths.project_knowledge:
                        paths_config["project_knowledge"] = config.paths.project_knowledge
                init_paths(self.project_root, paths_config)
            except ConfigError:
                # No config - use defaults
                init_paths(self.project_root, {})

    def _find_sprint_status(self) -> Path | None:
        """Find sprint-status.yaml using paths singleton.

        Returns:
            Path to sprint-status.yaml or None if not found.

        """
        from bmad_assist.core.paths import get_paths

        return get_paths().find_sprint_status()

    def _generate_sprint_status(self) -> Path | None:
        """Auto-generate sprint-status.yaml from epic files.

        Scans epic files and creates sprint-status.yaml in implementation-artifacts/.
        Returns None if no epic files found or generation fails.

        Returns:
            Path to generated sprint-status.yaml, or None on failure.

        """
        from bmad_assist.core.paths import get_paths
        from bmad_assist.sprint import generate_from_epics, write_sprint_status

        paths = get_paths()
        target_dir = paths.implementation_artifacts
        target_path = target_dir / "sprint-status.yaml"

        try:
            # Generate entries from epic files
            result = generate_from_epics(self.project_root, auto_exclude_legacy=True)

            if not result.entries:
                logger.warning("No entries generated from epic files")
                return None

            # Build SprintStatus from generated entries
            # Convert list of entries to dict as required by SprintStatus
            entries_dict = {entry.key: entry for entry in result.entries}

            # Create SprintStatus with generated entries
            from bmad_assist.sprint.models import SprintStatus, SprintStatusMetadata

            status = SprintStatus(
                metadata=SprintStatusMetadata(generated=datetime.now(UTC)),
                entries=entries_dict,
            )

            # Ensure target directory exists
            target_dir.mkdir(parents=True, exist_ok=True)

            # Write sprint-status.yaml
            write_sprint_status(status, target_path)

            logger.info(
                "Auto-generated sprint-status.yaml with %d entries from %d epic files",
                len(result.entries),
                result.files_processed,
            )

            return target_path

        except Exception as e:
            logger.exception("Failed to auto-generate sprint-status.yaml: %s", e)
            return None

    async def start_loop(self) -> dict[str, Any]:
        """Start the BMAD development loop.

        Runs `bmad-assist run` as subprocess which will:
        - Load sprint-status.yaml to find current position
        - Continue from last story/phase
        - Update sprint-status.yaml as it progresses

        The dashboard loops workflows until pause/stop is requested.

        Returns:
            Status dict with loop state.

        """
        if self._loop_running:
            return {"status": "already_running", "message": "Loop is already running"}

        # Reset flags
        self._loop_running = True
        self._pause_requested = False
        self._stop_requested = False

        # Story 22.10 - AC #7: Clean up any existing pause flags on fresh start
        pause_flag = self.project_root / ".bmad-assist" / "pause.flag"
        pause_flag.unlink(missing_ok=True)

        # Broadcast start message
        await self.sse_broadcaster.broadcast_output(
            "🚀 Starting bmad-assist run loop...", provider="dashboard"
        )

        # Start loop in background
        self._loop_task = asyncio.create_task(self._run_workflow_loop())

        return {"status": "started", "message": "Loop started"}

    async def pause_loop(self) -> dict[str, Any]:
        """Pause after current workflow completes.

        Story 22.10 - Task 2: Write pause flag file for subprocess to detect.

        Does NOT interrupt the current workflow. After it finishes,
        no more workflows will be started.

        Returns:
            Status dict with loop state.

        """
        if not self._loop_running:
            return {"status": "not_running", "message": "Loop is not running"}

        if self._pause_requested:
            return {"status": "already_paused", "message": "Pause already requested"}

        self._pause_requested = True

        # Write pause flag file for subprocess to detect (Story 22.10 - Task 3)
        pause_flag = self.project_root / ".bmad-assist" / "pause.flag"
        pause_flag.parent.mkdir(parents=True, exist_ok=True)
        pause_flag.touch()

        await self.sse_broadcaster.broadcast_output(
            "⏸️ Pause requested - will pause after current phase completes...", provider="dashboard"
        )

        return {"status": "pause_requested", "message": "Pause requested"}

    async def resume_loop(self) -> dict[str, Any]:
        """Resume a paused development loop (Story 22.10 - Task 2).

        Clears the pause_requested flag and removes the pause.flag file,
        allowing the main loop subprocess to continue from where it paused.

        Returns:
            Status dict with loop state.

        """
        if not self._loop_running:
            return {"status": "not_running", "message": "Loop is not running"}

        if not self._pause_requested:
            return {"status": "not_paused", "message": "Loop is not paused"}

        # Clear internal flag
        self._pause_requested = False

        # Remove pause flag file (signals subprocess to resume)
        pause_flag = self.project_root / ".bmad-assist" / "pause.flag"
        pause_flag.unlink(missing_ok=True)

        logger.info("Loop resumed - cleared pause flag")

        # Note: LOOP_RESUMED SSE event is emitted by the subprocess (runner.py)
        # when it actually exits the wait loop. This ensures the event is emitted
        # at the correct time (when subprocess resumes) rather than prematurely.

        await self.sse_broadcaster.broadcast_output(
            "▶️ Resumed - continuing loop...", provider="dashboard"
        )

        return {"status": "resumed", "message": "Loop resumed"}

    async def stop_loop(self) -> dict[str, Any]:
        """Stop immediately - terminate current workflow.

        Sends SIGTERM to the subprocess to interrupt current workflow.

        Story 22.10 - AC #6: When stopping while paused, also removes pause.flag
        to prevent orphaned flag files.

        Returns:
            Status dict with loop state.

        """
        if not self._loop_running:
            return {"status": "not_running", "message": "Loop is not running"}

        self._stop_requested = True
        self._loop_running = False

        # Write stop.flag for subprocess to detect (Story 22.10 - Task 3)
        stop_flag = self.project_root / ".bmad-assist" / "stop.flag"
        stop_flag.parent.mkdir(parents=True, exist_ok=True)
        stop_flag.touch()

        # Clean up pause flag if present (AC #6)
        pause_flag = self.project_root / ".bmad-assist" / "pause.flag"
        pause_flag.unlink(missing_ok=True)

        # Terminate the subprocess
        await self._cancel_process()

        # Cancel the loop task
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task

        await self.sse_broadcaster.broadcast_output("⏹️ Loop stopped.", provider="dashboard")

        return {"status": "stopped", "message": "Loop stopped"}

    async def _run_workflow_loop(self) -> None:
        """Loop through workflows until pause/stop requested.

        Each iteration runs `bmad-assist run` which processes one workflow
        from sprint-status.yaml. After each workflow completes, check if
        pause/stop was requested before starting the next one.
        """
        while self._loop_running and not self._pause_requested and not self._stop_requested:
            await self.sse_broadcaster.broadcast_output(
                "📋 Starting workflow...", provider="dashboard"
            )

            # Use installed CLI command (works in both dev and installed modes)
            cmd = [
                "bmad-assist",
                "run",
                "--project",
                str(self.project_root),
                "--no-interactive",
            ]

            # Set BMAD_DASHBOARD_MODE to enable dashboard event emission in subprocess
            # Set BMAD_ORIGINAL_CWD to preserve original working directory for patch/cache lookup
            import os

            subprocess_env = os.environ.copy()
            subprocess_env["BMAD_DASHBOARD_MODE"] = "1"
            subprocess_env["BMAD_ORIGINAL_CWD"] = str(Path.cwd())

            self._current_process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.project_root,
                env=subprocess_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
            )

            try:
                if self._current_process.stdout is not None:
                    async for line in self._current_process.stdout:
                        if self._stop_requested:
                            await self._cancel_process()
                            break

                        text = line.decode(errors="replace").rstrip()

                        # Story 22.9: Parse dashboard event markers from stdout
                        if text.startswith(DASHBOARD_EVENT_MARKER):
                            await self._handle_dashboard_event(text)
                            continue

                        await self.sse_broadcaster.broadcast_output(text, provider="workflow")

                # Story 22.11 Task 1: Stdout EOF reached - subprocess has closed stdout
                # Log EOF event for observability before waiting for process exit
                logger.info("Subprocess stdout EOF - waiting for process exit")

                # Now wait for process to fully exit
                await self._current_process.wait()

                # Story 22.11: Log subprocess exit details
                returncode = self._current_process.returncode
                logger.info("Subprocess exited with code %d", returncode)

                if returncode != 0:
                    await self.sse_broadcaster.broadcast_output(
                        f"❌ Workflow exited with code {returncode}", provider="dashboard"
                    )
                    # On error, stop the loop
                    break
                else:
                    await self.sse_broadcaster.broadcast_output(
                        "✅ Workflow completed", provider="dashboard"
                    )

            except asyncio.CancelledError:
                await self._cancel_process()
                break

            # Check if we should continue
            if self._pause_requested:
                await self.sse_broadcaster.broadcast_output(
                    "⏸️ Pausing after workflow completion (no more workflows will be started)",
                    provider="dashboard",
                )
                break
            if self._stop_requested:
                break

        # Loop ended
        self._loop_running = False
        self._pause_requested = False
        self._stop_requested = False

        await self.sse_broadcaster.broadcast_output("🏁 Loop ended", provider="dashboard")

    async def _run_bmad_assist_loop(self) -> None:
        """Run workflow loop (deprecated, use _run_workflow_loop instead)."""
        await self._run_workflow_loop()

    async def _cancel_process(self) -> None:
        """Gracefully terminate current subprocess with SIGKILL fallback.

        Sends SIGTERM first, waits up to 5 seconds for graceful exit,
        then sends SIGKILL if the process is still running.
        """
        if self._current_process is None:
            return

        self._current_process.terminate()  # SIGTERM
        try:
            await asyncio.wait_for(self._current_process.wait(), timeout=5.0)
        except TimeoutError:
            self._current_process.kill()  # SIGKILL after 5s
            await self._current_process.wait()

    async def _handle_dashboard_event(self, line: str) -> None:
        """Parse and broadcast dashboard event from stdout marker.

        Story 22.9: Parse DASHBOARD_EVENT:{json} markers from subprocess stdout
        and broadcast validated events via SSE.

        Args:
            line: Stdout line containing DASHBOARD_EVENT marker.

        """
        import json

        try:
            # Extract JSON payload from marker
            json_str = line[len(DASHBOARD_EVENT_MARKER) :]
            event_data = json.loads(json_str)

            # Validate required fields
            required_fields = ["type", "timestamp", "run_id", "sequence_id", "data"]
            missing_fields = [f for f in required_fields if f not in event_data]
            if missing_fields:
                logger.warning(
                    "Dashboard event missing required fields: %s. Event: %s",
                    missing_fields,
                    event_data.get("type", "unknown"),
                )
                return

            # Broadcast event via SSE
            event_type = event_data["type"]
            await self.sse_broadcaster.broadcast_event(event_type, event_data)

            logger.debug(
                "Broadcast dashboard event: type=%s sequence_id=%s",
                event_type,
                event_data["sequence_id"],
            )

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse dashboard event JSON: %s. Line: %s", e, line[:200])
        except Exception as e:
            logger.warning("Error handling dashboard event: %s", e)

    async def execute_experiment(
        self,
        run_id: str,
        fixture: str,
        config: str,
        patch_set: str,
        loop: str,
    ) -> None:
        """Execute an experiment run with progress streaming.

        This method runs in the background and broadcasts
        progress updates via SSE.

        Args:
            run_id: Unique experiment run identifier.
            fixture: Fixture template name.
            config: Config template name.
            patch_set: Patch-set template name.
            loop: Loop template name.

        Raises:
            RuntimeError: If experiment execution fails.

        """
        from bmad_assist.experiments import (
            ExperimentInput,
            ExperimentRunner,
            ExperimentStatus,
        )

        # Set active experiment state
        self._active_experiment_run_id = run_id
        self._active_experiment_cancel_event = asyncio.Event()

        try:
            # Initialize runner with project experiments directory
            experiments_dir = self.project_root / "experiments"
            runner = ExperimentRunner(experiments_dir)

            # Create input
            experiment_input = ExperimentInput(
                fixture=fixture,
                config=config,
                patch_set=patch_set,
                loop=loop,
                run_id=run_id,
            )

            # Broadcast starting status
            await self.sse_broadcaster.broadcast_event(
                "status",
                {
                    "run_id": run_id,
                    "status": "running",
                    "phase": "initializing",
                    "story": None,
                    "position": None,
                },
            )

            # Run experiment (blocking - runs in thread pool)
            output = await asyncio.get_running_loop().run_in_executor(
                None,
                runner.run,
                experiment_input,
            )

            # Check if cancelled
            if self._active_experiment_cancel_event.is_set():
                await self.sse_broadcaster.broadcast_event(
                    "status",
                    {
                        "run_id": run_id,
                        "status": "cancelled",
                        "phase": None,
                        "story": None,
                        "position": None,
                    },
                )
                return

            # Broadcast completion
            final_status = "completed" if output.status == ExperimentStatus.COMPLETED else "failed"
            await self.sse_broadcaster.broadcast_event(
                "status",
                {
                    "run_id": run_id,
                    "status": final_status,
                    "phase": None,
                    "story": None,
                    "position": None,
                },
            )

            # Broadcast final progress
            stories_total = output.stories_attempted or 0
            stories_completed = output.stories_completed or 0
            percent = int((stories_completed / stories_total) * 100) if stories_total > 0 else 100
            await self.sse_broadcaster.broadcast_event(
                "progress",
                {
                    "run_id": run_id,
                    "percent": percent,
                    "stories_completed": stories_completed,
                    "stories_total": stories_total,
                },
            )

        except Exception as e:
            logger.exception("Experiment execution failed: %s", e)
            await self.sse_broadcaster.broadcast_event(
                "status",
                {
                    "run_id": run_id,
                    "status": "failed",
                    "phase": None,
                    "story": None,
                    "position": None,
                },
            )
            raise RuntimeError(f"Experiment failed: {e}") from e
        finally:
            # Clear active experiment state
            self._active_experiment_run_id = None
            self._active_experiment_cancel_event = None

    def create_app(self) -> Starlette:
        """Create and configure Starlette application.

        Returns:
            Configured Starlette app instance.

        """
        # Static files directory
        static_dir = Path(__file__).parent / "static"

        middleware = [
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],  # Local dev only
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ]

        routes: list[BaseRoute] = list(API_ROUTES)

        # Mount static files if directory exists
        if static_dir.exists():
            routes.append(
                Mount("/", app=StaticFiles(directory=str(static_dir), html=True), name="static")
            )

        app = Starlette(
            debug=True,
            routes=routes,
            middleware=middleware,
            on_startup=[self._on_startup],
            on_shutdown=[self._on_shutdown],
        )

        # Store server reference in app state
        app.state.server = self

        self._app = app
        return app

    async def _on_startup(self) -> None:
        """Handle server startup."""
        from bmad_assist.dashboard import (
            register_output_bridge,
            set_output_hook,
            sync_broadcast,
        )

        # Register output bridge with current event loop and broadcaster
        loop = asyncio.get_running_loop()
        register_output_bridge(loop, self.sse_broadcaster)

        # Set output hook to broadcast via SSE
        set_output_hook(sync_broadcast)

        logger.info(
            "Dashboard server starting at http://%s:%d",
            self.host,
            self.port,
        )

    async def _on_shutdown(self) -> None:
        """Handle server shutdown."""
        # Cancel the loop task if running
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task

        # Cancel any running subprocess (redundant if loop task handled it, but safe)
        if self._current_process is not None:
            await self._cancel_process()

        from bmad_assist.dashboard import set_output_hook, unregister_output_bridge

        # Clear output hook before shutdown
        set_output_hook(None)
        unregister_output_bridge()

        logger.info("Dashboard server shutting down...")
        await self.sse_broadcaster.shutdown()

    def get_current_state(self) -> State | None:
        """Load current execution state from state.yaml.

        Reads state from {project_root}/.bmad-assist/state.yaml which contains
        current execution position (epic, story, phase) maintained by the loop.

        Returns:
            State instance if file exists and is valid, None otherwise.
            Returns None without logging if file doesn't exist (normal case).
            Logs warning if file exists but is corrupted or unreadable.

        """
        state_path = get_state_path(project_root=self.project_root)

        if not state_path.exists():
            return None  # No state file - normal case, no logging needed

        try:
            return load_state(state_path)
        except Exception as e:
            # File exists but failed to load - log the error
            logger.warning("Failed to load state from %s: %s", state_path, e)
            return None

    def get_sprint_status(self) -> dict[str, Any]:
        """Get current sprint status from project state.

        Returns:
            Sprint status dictionary.

        """
        from bmad_assist.bmad.state_reader import read_project_state
        from bmad_assist.core.paths import get_paths

        # Try implementation artifacts first, then project_knowledge
        paths = get_paths()
        bmad_paths = [
            paths.implementation_artifacts,
            paths.project_knowledge,
        ]

        for bmad_path in bmad_paths:
            if bmad_path.exists():
                try:
                    state = read_project_state(bmad_path, use_sprint_status=True)
                    # Filter out non-epic files (summary docs without epic_num)
                    valid_epics = [e for e in state.epics if e.epic_num is not None]

                    # Continue searching if no valid epics found
                    if not valid_epics:
                        continue

                    return {
                        "current_epic": state.current_epic,
                        "current_story": state.current_story,
                        "epics": [
                            {
                                "id": epic.epic_num,
                                "title": epic.title,
                                "status": epic.status,
                                "stories": [
                                    {
                                        "id": s.number.split(".")[-1],
                                        "title": s.title,
                                        "status": s.status or "backlog",
                                    }
                                    for s in epic.stories
                                ],
                            }
                            for epic in valid_epics
                        ],
                    }
                except FileNotFoundError:
                    continue

        # Fallback: Read sprint-status.yaml directly (for UI fixtures without epic files)
        return self._get_sprint_status_from_file()

    def get_stories(self) -> dict[str, Any]:
        """Get story hierarchy with workflow phases.

        Uses state.yaml for current execution position when available,
        falling back to sprint-status.yaml story status inference.

        Returns:
            Hierarchical structure of epics, stories, and phases.

        """
        status = self.get_sprint_status()
        if "error" in status:
            return status

        # Load execution state for accurate phase status
        state = self.get_current_state()

        epics = status.get("epics", [])
        result: dict[str, Any] = {"epics": []}

        for epic in epics:
            epic_data = {
                "id": epic.get("id"),
                "title": epic.get("title"),
                "status": epic.get("status"),
                "stories": [],
            }

            # Collect stories and sort by id
            stories_list = []
            for story in epic.get("stories", []):
                story_status: str = story.get("status") or "backlog"
                story_data = {
                    "id": story.get("id"),
                    "title": story.get("title"),
                    "status": story_status,
                    "phases": self._get_story_phases(
                        epic.get("id"), story.get("id"), story_status, state
                    ),
                }
                stories_list.append(story_data)

            # Sort stories by id (convert to int for numeric sorting)
            stories_list.sort(key=lambda s: (int(s["id"]) if str(s["id"]).isdigit() else s["id"]))
            epic_data["stories"] = stories_list

            result["epics"].append(epic_data)

        # Sort epics by id (numeric first, then string)
        result["epics"].sort(key=lambda e: (0, int(e["id"])) if str(e["id"]).isdigit() else (1, str(e["id"])))

        return result

    def get_epic_details(self, epic_id: int | str) -> dict[str, Any] | None:
        """Get epic details with full content from epic file.

        Reads epic content from epics.md or sharded epic file.
        Returns None if epic not found.

        Args:
            epic_id: Epic ID (int or str like "testarch").

        Returns:
            Dict with epic metadata and content, or None if not found.

        """
        import frontmatter

        from bmad_assist.bmad.sharding import resolve_doc_path

        try:
            # Convert epic_id to string for path construction
            epic_id_str = str(epic_id)

            # Check for sharded epic first (epics/epic-{id}.md)
            bmad_path = self.project_root / "docs"
            epics_path, is_sharded = resolve_doc_path(bmad_path, "epics")

            if is_sharded:
                # Sharded pattern: use glob to find epic-{id}-*.md files
                possible_files = list(epics_path.glob(f"epic-{epic_id_str}-*.md"))
                # Also try exact match for epic-{id}.md
                exact_file = epics_path / f"epic-{epic_id_str}.md"
                if exact_file.exists() and exact_file not in possible_files:
                    possible_files.append(exact_file)
                # Also try {id}.md
                id_file = epics_path / f"{epic_id_str}.md"
                if id_file.exists() and id_file not in possible_files:
                    possible_files.append(id_file)
            else:
                # Single file pattern - epics.md file (might be named epics.md or epic.md)
                # epics_path might be the file itself or a directory containing it
                if epics_path.is_file():
                    possible_files = [epics_path]
                else:
                    # Try common filenames
                    possible_files = [
                        epics_path / "epics.md",
                        epics_path / "epic.md",
                        bmad_path / "epics.md",
                        bmad_path / "epic.md",
                    ]

            for epic_file in possible_files:
                if not epic_file.exists():
                    continue

                content = epic_file.read_text(encoding="utf-8")

                if is_sharded:
                    # Sharded file is the full epic content
                    post = frontmatter.loads(content)
                    return {
                        "id": epic_id,
                        "title": post.metadata.get("title", f"Epic {epic_id}"),
                        "status": post.metadata.get("status", "unknown"),
                        "metadata": dict(post.metadata),
                        "content": post.content,
                        "path": str(epic_file.relative_to(self.project_root)),
                    }
                else:
                    # Single file - find the epic by heading
                    # Format: # Epic {id} or ## Epic {id} (single or double #)
                    lines = content.split("\n")
                    epic_start = -1
                    epic_end = len(lines)

                    for i, line in enumerate(lines):
                        # Check if this is an epic heading (single or double #)
                        # Match: "# Epic 1:", "## Epic 1", "# 1 Title", "## 1 Title"
                        if line.startswith("# ") or line.startswith("## "):
                            # Strip leading #
                            heading = line.lstrip("#").strip()
                            # Check if matches our epic
                            if (
                                heading.startswith(f"Epic {epic_id_str}")
                                or heading.startswith(f"{epic_id_str} ")
                                or heading.startswith(f"{epic_id_str}:")
                            ):
                                epic_start = i
                                # Find next epic heading (same level or higher)
                                current_level = line.count(
                                    "#", 0, line.find("Epic") if "Epic" in line else 2
                                )
                                for j in range(i + 1, len(lines)):
                                    next_level = lines[j].count("#", 0, min(3, len(lines[j])))
                                    if next_level > 0 and next_level <= current_level:
                                        epic_end = j
                                        break
                                break

                    if epic_start >= 0:
                        # Extract epic content (from heading to next epic)
                        epic_content = "\n".join(lines[epic_start:epic_end])

                        # Parse frontmatter if present (use frontmatter.loads for string content)
                        post = frontmatter.loads(epic_content)

                        # Extract title from heading if not in metadata
                        title = post.metadata.get("title")
                        if not title:
                            heading_line = lines[epic_start]
                            # Strip leading #
                            heading = heading_line.lstrip("#").strip()
                            # Remove "Epic N:" or "Epic N" prefix
                            heading = re.sub(
                                rf"^Epic\s+{epic_id_str}:\s*", "", heading, flags=re.IGNORECASE
                            )
                            heading = re.sub(
                                rf"^Epic\s+{epic_id_str}\s*", "", heading, flags=re.IGNORECASE
                            )
                            heading = re.sub(rf"^{epic_id_str}\s*", "", heading)
                            heading = heading.strip(":-")
                            title = heading or f"Epic {epic_id}"

                        return {
                            "id": epic_id,
                            "title": title or f"Epic {epic_id}",
                            "status": post.metadata.get("status", "unknown"),
                            "metadata": dict(post.metadata),
                            "content": post.content,
                            "path": str(epic_file.relative_to(self.project_root)),
                        }

            # Epic not found
            return None

        except Exception:
            logger.exception("Failed to get epic details for %s", epic_id)
            return None

    def get_story_in_epic(self, epic_id: int | str, story_id: int | str) -> dict[str, Any] | None:
        """Get a specific story's content from within an epic file.

        Parses the epic file and extracts only the content for the specified story.
        Returns None if epic or story not found.

        Args:
            epic_id: Epic ID (int or str like "testarch").
            story_id: Story ID (int or str).

        Returns:
            Dict with story metadata and content, or None if not found.

        """
        import re

        try:
            # First get the epic content
            epic_details = self.get_epic_details(epic_id)
            if epic_details is None:
                return None

            epic_content = epic_details.get("content", "")
            if not epic_content:
                return None

            # Parse the epic content to find the specific story
            # Story headers can be:
            # ### Story {epic}.{story}: Title
            # ### Story {epic}.{story} Title
            # ### {story}. Title (sometimes in shorthand)
            lines = epic_content.split("\n")
            story_start = -1
            story_end = len(lines)

            # Build patterns to match story headers
            epic_id_str = str(epic_id)
            story_id_str = str(story_id)

            # Pattern 1: ### Story {epic}.{story}: {title}
            # Pattern 2: ### Story {epic}.{story} {title}
            # Pattern 3: ### {story}. {title} (if epic context is implicit)
            # Pattern 4: ## Story {epic}.{story}: {title} (some epics use level 2)
            # Build patterns using escaped IDs
            eid, sid = re.escape(epic_id_str), re.escape(story_id_str)
            patterns = [
                rf"^###\s+Story\s+{eid}\.{sid}\s*:",  # Story 16.1:
                rf"^###\s+Story\s+{eid}\.{sid}\s+",  # Story 16.1 (space)
                rf"^###\s+Story\s+{eid}\.{sid}$",  # Story 16.1 (exact)
                rf"^##\s+Story\s+{eid}\.{sid}\s*:",  # Level 2 with colon
                rf"^##\s+Story\s+{eid}\.{sid}\s+",  # Level 2 with space
                rf"^##\s+Story\s+{eid}\.{sid}$",  # Level 2 exact
                rf"^###\s+{sid}\.",  # Numbered list style
                rf"^##\s+{sid}\.",  # Level 2 numbered
            ]

            for i, line in enumerate(lines):
                # Check if this line matches any of our patterns
                for pattern in patterns:
                    if re.match(pattern, line, re.IGNORECASE):
                        story_start = i
                        # Find next story heading (###) or epic section end
                        for j in range(i + 1, len(lines)):
                            if lines[j].startswith("### ") and "Story" in lines[j]:
                                story_end = j
                                break
                            # Also stop at next major section (##)
                            if lines[j].startswith("## ") and not lines[j].startswith("###"):
                                story_end = j
                                break
                        break
                if story_start >= 0:
                    break

            if story_start >= 0:
                # Extract story content
                story_lines = lines[story_start:story_end]
                story_content = "\n".join(story_lines)

                # Extract title from first line
                title_line = story_lines[0] if story_lines else ""
                title_match = re.search(
                    rf"Story\s+{re.escape(epic_id_str)}\.{re.escape(story_id_str)}\s*:?\s*(.+)",
                    title_line,
                    re.IGNORECASE,
                )
                title = title_match.group(1).strip() if title_match else f"Story {story_id}"

                # Extract metadata (points, priority) if present
                points = None
                priority = None
                for line in story_lines[:20]:  # Check first 20 lines for metadata
                    points_match = re.search(r"\*\*Points?\*\*:\s*(\d+)", line, re.IGNORECASE)
                    if points_match:
                        points = int(points_match.group(1))
                    priority_match = re.search(r"\*\*Priority?\*\*:\s*(\w+)", line, re.IGNORECASE)
                    if priority_match:
                        priority = priority_match.group(1).upper()

                return {
                    "id": story_id,
                    "epic_id": epic_id,
                    "title": title,
                    "content": story_content,
                    "points": points,
                    "priority": priority,
                    "epic_path": epic_details.get("path"),
                }

            # Story not found in epic
            return None

        except Exception:
            logger.exception("Failed to get story %s in epic %s", story_id, epic_id)
            return None

    def get_story_file_content(
        self, epic_id: str, story_id: str
    ) -> dict[str, Any] | None:
        """Get story file content from implementation-artifacts directory.

        Story 24.5: Searches for story files matching pattern {epic}-{story}-*.md
        and returns the content along with title and file path.

        Args:
            epic_id: Epic identifier (e.g., "24" or "testarch").
            story_id: Story number (e.g., "5" or "1").

        Returns:
            Dictionary with content, file_path, and title, or None if not found.
            On success: {"content": "...", "file_path": "...", "title": "..."}

        """
        from bmad_assist.core.paths import get_paths

        try:
            # Validate inputs to prevent glob injection and path traversal
            # Only allow alphanumeric characters, hyphens, and underscores
            if not re.match(r"^[a-zA-Z0-9_-]+$", str(epic_id)):
                logger.warning("Invalid epic_id format: %s", epic_id)
                return None
            if not re.match(r"^[a-zA-Z0-9_-]+$", str(story_id)):
                logger.warning("Invalid story_id format: %s", story_id)
                return None

            impl_dir = get_paths().implementation_artifacts

            # Search for story files with pattern {epic}-{story}-*.md
            pattern = f"{epic_id}-{story_id}-*.md"
            matching_files = list(impl_dir.glob(pattern))

            if not matching_files:
                logger.debug("No story files found for pattern %s in %s", pattern, impl_dir)
                return None

            # If multiple matches, select the one with most recent mtime
            if len(matching_files) > 1:
                logger.warning(
                    "Found %d matches for %s, using most recent",
                    len(matching_files),
                    pattern,
                )
                matching_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

            story_file = matching_files[0]
            content = story_file.read_text(encoding="utf-8")

            # Extract title with fallback hierarchy
            title = self._extract_story_title(content, story_file.name, epic_id, story_id)

            # Return relative path from project root
            try:
                relative_path = str(story_file.relative_to(self.project_root))
            except ValueError:
                relative_path = str(story_file)

            return {
                "content": content,
                "file_path": relative_path,
                "title": title,
            }

        except Exception:
            logger.exception(
                "Failed to get story file content for %s.%s", epic_id, story_id
            )
            return None

    def _extract_story_title(
        self, content: str, filename: str, epic_id: str, story_id: str
    ) -> str:
        """Extract story title with fallback hierarchy.

        Story 24.5: Title extraction order:
        1. Primary: Extract from first H1 heading (# Story X.Y: Title)
        2. Fallback: Convert filename slug to title (kebab-case -> Title Case)
        3. Last resort: "Story {epic}.{story}"

        Args:
            content: Story file content.
            filename: Story filename.
            epic_id: Epic identifier.
            story_id: Story number.

        Returns:
            Extracted or fallback title.

        """
        # Primary: Extract from first H1 heading
        # Pattern matches: "# Story 24.5: Title" or "# Title"
        lines = content.split("\n")
        for line in lines[:20]:  # Check first 20 lines
            line = line.strip()
            if line.startswith("# "):
                heading = line[2:].strip()
                # Try pattern "Story X.Y: Title"
                match = re.match(
                    rf"Story\s+{re.escape(epic_id)}\.{re.escape(story_id)}\s*:\s*(.+)",
                    heading,
                    re.IGNORECASE,
                )
                if match:
                    return match.group(1).strip()
                # Just use the heading as title
                return heading

        # Fallback: Convert filename slug to title
        # Filename pattern: {epic}-{story}-{slug}.md
        # Extract slug and convert to Title Case
        match = re.match(rf"^{re.escape(epic_id)}-{re.escape(story_id)}-(.+)\.md$", filename)
        if match:
            slug = match.group(1)
            if slug:
                # Convert kebab-case to Title Case
                return slug.replace("-", " ").replace("_", " ").title()

        # Last resort: generic title
        return f"Story {epic_id}.{story_id}"

    def get_epic_metrics(self, epic_id: int | str) -> dict[str, Any] | None:
        """Get aggregated benchmark metrics for an epic.

        Scans benchmarks directory for all evaluation files matching this epic
        and aggregates timing and workflow statistics.

        Args:
            epic_id: Epic identifier (numeric or string like 'testarch').

        Returns:
            Dictionary with aggregated metrics or None if no benchmarks found.

        """
        import yaml

        from bmad_assist.core.paths import get_paths

        benchmarks_dir = get_paths().benchmarks_dir
        if not benchmarks_dir.exists():
            return None

        epic_id_str = str(epic_id)
        metrics: dict[str, Any] = {
            "epic_id": epic_id,
            "total_duration_ms": 0,
            "story_count": 0,
            "workflow_breakdown": {},
            "stories": {},
        }

        # Scan all subdirectories (YYYY-MM format)
        for month_dir in benchmarks_dir.iterdir():
            if not month_dir.is_dir():
                continue

            # Pattern: eval-{epic}-{story}-{role}-{timestamp}.yaml
            for eval_file in month_dir.glob(f"eval-{epic_id_str}-*.yaml"):
                try:
                    data = yaml.safe_load(eval_file.read_text(encoding="utf-8"))
                    if not data:
                        continue

                    story_num = data.get("story", {}).get("story_num")
                    workflow_id = data.get("workflow", {}).get("id", "unknown")
                    duration_ms = data.get("execution", {}).get("duration_ms", 0)
                    role = data.get("evaluator", {}).get("role", "unknown")

                    # Aggregate totals
                    metrics["total_duration_ms"] += duration_ms

                    # Per-workflow breakdown
                    if workflow_id not in metrics["workflow_breakdown"]:
                        metrics["workflow_breakdown"][workflow_id] = {
                            "count": 0,
                            "total_duration_ms": 0,
                        }
                    metrics["workflow_breakdown"][workflow_id]["count"] += 1
                    metrics["workflow_breakdown"][workflow_id]["total_duration_ms"] += duration_ms

                    # Per-story tracking
                    story_key = str(story_num)
                    if story_key not in metrics["stories"]:
                        metrics["stories"][story_key] = {
                            "story_num": story_num,
                            "title": data.get("story", {}).get("title", f"Story {story_num}"),
                            "total_duration_ms": 0,
                            "workflows": {},
                        }
                    metrics["stories"][story_key]["total_duration_ms"] += duration_ms

                    # Per-story workflow tracking
                    if workflow_id not in metrics["stories"][story_key]["workflows"]:
                        metrics["stories"][story_key]["workflows"][workflow_id] = {
                            "duration_ms": 0,
                            "roles": [],
                        }
                    wf = metrics["stories"][story_key]["workflows"][workflow_id]
                    wf["duration_ms"] += duration_ms
                    if role not in wf["roles"]:
                        wf["roles"].append(role)

                except Exception as e:
                    logger.warning("Failed to parse benchmark file %s: %s", eval_file, e)
                    continue

        metrics["story_count"] = len(metrics["stories"])

        # Return None if no benchmarks found
        if metrics["story_count"] == 0:
            return None

        # Convert stories dict to sorted list
        metrics["stories"] = sorted(
            metrics["stories"].values(),
            key=lambda s: (s.get("story_num") or 0),
        )

        return metrics

    def _get_sprint_status_from_file(self) -> dict[str, Any]:
        """Read sprint-status.yaml directly when epic files don't exist.

        Fallback for UI fixtures and projects without epic files.
        Reads sprint-status.yaml and builds minimal epic structure.

        Returns:
            Sprint status dictionary with epic hierarchy.

        """
        from bmad_assist.sprint import parse_sprint_status

        try:
            if self._sprint_status_path is None:
                return {"epics": [], "total_stories": 0, "completed_stories": 0}
            sprint_status = parse_sprint_status(self._sprint_status_path)

            # Group stories by epic
            epic_stories: dict[int | str, list[dict[str, Any]]] = {}
            epic_meta: dict[int | str, dict[str, Any]] = {}

            for key, entry in sprint_status.entries.items():
                # Skip non-story entries (epic meta entries)
                if entry.entry_type.value in ("epic_meta",):
                    # Extract epic number from key like "epic-1"
                    meta_epic_str = key.replace("epic-", "")
                    meta_epic_num: int | str
                    try:
                        meta_epic_num = int(meta_epic_str)
                    except ValueError:
                        meta_epic_num = meta_epic_str
                    epic_meta[meta_epic_num] = {
                        "id": meta_epic_num,
                        "title": f"Epic {meta_epic_str}",
                        "status": entry.status,
                    }
                    continue

                # Parse story key like "1-2-hero-section" or "testarch-1-config"
                parts = key.split("-", 2)
                if len(parts) < 3:
                    continue

                epic_num_str = parts[0]
                story_num = parts[1]
                slug = parts[2] if len(parts) > 2 else ""

                # Convert epic num to int if possible
                epic_num: int | str
                try:
                    epic_num = int(epic_num_str)
                except ValueError:
                    epic_num = epic_num_str

                # Build story title from slug
                title = slug.replace("-", " ").replace("_", " ").title()

                if epic_num not in epic_stories:
                    epic_stories[epic_num] = []

                epic_stories[epic_num].append(
                    {
                        "id": story_num,
                        "title": title,
                        "status": entry.status,
                    }
                )

            # Build final structure
            epics = []
            for epic_num, stories in epic_stories.items():
                epic_data = epic_meta.get(
                    epic_num,
                    {
                        "id": epic_num,
                        "title": f"Epic {epic_num}",
                        "status": "backlog",
                    },
                )
                epic_data["stories"] = stories
                epics.append(epic_data)

            return {
                "current_epic": None,
                "current_story": None,
                "epics": epics,
            }
        except Exception as e:
            logger.exception("Failed to read sprint-status.yaml: %s", e)
            return {"error": f"Failed to read sprint-status.yaml: {e}"}

    def _get_story_phases(
        self,
        epic_id: str | int,
        story_id: str | int,
        status: str,
        state: State | None = None,
    ) -> list[dict[str, str]]:
        """Get workflow phases for a story.

        Uses state.yaml to determine current phase when available.
        Falls back to inferring from story status if state not available.

        Args:
            epic_id: Epic identifier.
            story_id: Story identifier (just the number part).
            status: Story status from sprint-status.yaml.
            state: Optional execution state from state.yaml.

        Returns:
            List of phase dictionaries with status.

        """
        # Get phases from loop config (hot-reload on each request)
        from bmad_assist.core.config import load_loop_config

        loop_config = load_loop_config(self.project_root)
        phases = _build_phases_from_config(loop_config.story)

        # Build story key for comparison with state (e.g., "22.3")
        story_key = f"{epic_id}.{story_id}"

        # If we have state and this is the current story, use state for phase status
        if state and state.current_story == story_key and state.current_phase:
            current_phase_id = state.current_phase.value
            phase_order = [p["id"] for p in phases]

            # Build dynamic phase position map from loop config
            # Phases in LoopConfig.story are displayed, others map to end position
            phase_position_map: dict[str, int] = {}
            for i, phase_id in enumerate(loop_config.story):
                phase_position_map[phase_id] = i

            # Non-displayed phases (epic_teardown, etc.) map to after all story phases
            # This ensures they show all story phases as completed
            end_position = len(loop_config.story)
            for phase_id in loop_config.epic_teardown:
                if phase_id not in phase_position_map:
                    phase_position_map[phase_id] = end_position

            # Also handle any Phase enum values not in config (legacy/testarch phases)
            # These map to positions based on their typical location in the workflow
            legacy_phase_positions = {
                "atdd": 3,  # Between val_synth and dev
                "test_review": end_position,  # After all story phases
            }
            for phase_id, pos in legacy_phase_positions.items():
                if phase_id not in phase_position_map:
                    phase_position_map[phase_id] = pos

            if current_phase_id in phase_position_map:
                current_idx = phase_position_map[current_phase_id]
                is_displayed_phase = current_phase_id in phase_order

                for i, phase in enumerate(phases):
                    if i < current_idx:
                        phase["status"] = "completed"
                    elif i == current_idx and is_displayed_phase:
                        phase["status"] = "in-progress"
                    # else: stays "pending"
                return phases

            # Unknown phase - log and fall through to status-based inference
            logger.debug(
                "Phase %s not in display mapping, using status-based inference",
                current_phase_id,
            )

        # Fallback: determine phase statuses based on story status
        if status == "done":
            for phase in phases:
                phase["status"] = "completed"
            return phases

        # Map story status to number of completed phases (0-indexed)
        # Phase indices: 0=create, 1=validate, 2=val_synth, 3=dev, 4=review, 5=rev_synth
        status_progression = {
            "backlog": 0,  # No phases completed
            "ready-for-dev": 3,  # create + validate + synthesis done (phases 0-2)
            "in-progress": 3,  # Same 3 done, dev_story (index 3) in-progress
            "review": 4,  # First 4 done, code_review (index 4) in-progress
        }

        completed_phases = status_progression.get(status, 0)

        for i, phase in enumerate(phases):
            if i < completed_phases:
                phase["status"] = "completed"
            elif i == completed_phases and status not in ("backlog",):
                phase["status"] = "in-progress"

        return phases

    def get_prompt_path(self, epic: str, story: str, phase: str) -> Path | None:
        """Get path to saved prompt file.

        Prompts are saved per-story in .bmad-assist/prompts/{epic}-{story}-{phase}.xml
        Falls back to cached templates in .bmad-assist/cache/ for backward compatibility.

        Args:
            epic: Epic identifier.
            story: Story number.
            phase: Workflow phase name (e.g., 'create-story', 'dev-story').

        Returns:
            Path to prompt file or None if not found.

        """
        from bmad_assist.core.io import get_prompt_path

        # Try new location first: .bmad-assist/prompts/{epic}-{story}-{phase}.xml
        try:
            prompt_path = get_prompt_path(self.project_root, epic, story, phase)
            if prompt_path is not None and prompt_path.exists():
                return prompt_path
        except Exception:
            pass  # Fall through to legacy cache

        # Fallback: Legacy cached templates in .bmad-assist/cache/
        # Map phase IDs (snake_case) to template file names (kebab-case)
        phase_mapping = {
            "create_story": "create-story",
            "validate_story": "validate-story",
            "validate_story_synthesis": "validate-story",  # Uses same template
            "dev_story": "dev-story",
            "code_review": "code-review",
            "code_review_synthesis": "code-review",  # Uses same template
        }
        template_phase = phase_mapping.get(phase, phase.replace("_", "-"))

        # Valid phases per AC 1.3
        valid_phases = {"create-story", "dev-story", "validate-story", "code-review"}
        if template_phase not in valid_phases:
            return None

        cache_dir = self.project_root / ".bmad-assist/cache"

        # Primary pattern: {phase}.tpl.xml (per AC 1.2)
        template_path = cache_dir / f"{template_phase}.tpl.xml"
        if template_path.exists():
            return template_path

        return None

    def get_validation_reports(self, epic: str, story: str) -> dict[str, Any]:
        """Get validation reports for a story.

        Searches archive/ subdirectory for individual reports and root for synthesis.
        Extracts provider name from filename using regex pattern.

        Args:
            epic: Epic identifier.
            story: Story number.

        Returns:
            Dictionary with reports list and synthesis object.
            Returns empty list (not error) if no reports found (AC 2.5).

        """
        from bmad_assist.core.paths import get_paths

        reports_dir = get_paths().validations_dir

        reports: list[dict[str, str | None]] = []
        synthesis: dict[str, str | None] | None = None

        # AC 2.1: Search archive/ subdirectory for individual validation reports
        archive_dir = reports_dir / "archive"
        archive_pattern = f"validation-{epic}-{story}-*.md"
        if archive_dir.exists():
            for report_path in sorted(archive_dir.glob(archive_pattern)):
                # AC 2.3: Extract provider from filename using regex
                provider = self._extract_provider(report_path.name)
                reports.append(
                    {
                        "path": str(report_path),
                        "name": report_path.name,
                        "provider": provider,  # AC 2.4
                    }
                )

        # AC 2.2: Search root for synthesis report
        synthesis_pattern = f"synthesis-{epic}-{story}-*.md"
        for synth_path in sorted(reports_dir.glob(synthesis_pattern)):
            synthesis = {
                "path": str(synth_path),
                "name": synth_path.name,
                "provider": None,  # Synthesis has no single provider
            }
            break  # Take first (should only be one)

        result: dict[str, Any] = {"reports": reports, "synthesis": synthesis}

        return result

    def _extract_provider(self, filename: str) -> str | None:
        """Extract role_id from validation filename.

        New pattern: validation-{epic}-{story}-{role_id}-{timestamp}.md
        role_id is a single letter (a, b, c...)
        Timestamp format: YYYYMMDDTHHMMSSZ (ISO format)

        Legacy pattern: validation-{epic}-{story}-{provider}-{timestamp}.md
        Provider may contain underscores (e.g., validator-a, claude_opus_4_5)
        Timestamp format: YYYYMMDD_HHMM

        Args:
            filename: Validation report filename.

        Returns:
            Role ID or provider name, or None if pattern doesn't match.

        """
        # Try new format first: single letter role_id with ISO timestamp
        match = re.match(
            r"validation-[a-z0-9]+-[a-z0-9]+-([a-z])-\d{8}T\d{6}Z?\.md", filename, re.IGNORECASE
        )
        if match:
            return match.group(1)

        # Try legacy format: multi-char provider with underscore timestamp
        match = re.match(r"validation-\d+-\d+-(.+)-\d{8}_\d{4}\.md", filename)
        return match.group(1) if match else None

    def get_code_review_reports(self, epic: str, story: str) -> dict[str, Any]:
        """Get code review reports for a story.

        Searches archive/ subdirectory for individual reports and root for synthesis.
        Similar to get_validation_reports but for code-reviews directory.

        Args:
            epic: Epic identifier.
            story: Story number.

        Returns:
            Dictionary with reports list and synthesis object.

        """
        from bmad_assist.core.paths import get_paths

        reports_dir = get_paths().code_reviews_dir

        reports: list[dict[str, str | None]] = []
        synthesis: dict[str, str | None] | None = None

        # Search archive/ subdirectory for individual code review reports
        archive_dir = reports_dir / "archive"
        archive_pattern = f"code-review-{epic}-{story}-*.md"
        if archive_dir.exists():
            for report_path in sorted(archive_dir.glob(archive_pattern)):
                # Extract provider from filename
                provider = self._extract_code_review_provider(report_path.name)
                reports.append(
                    {
                        "path": str(report_path),
                        "name": report_path.name,
                        "provider": provider,
                    }
                )

        # Search root for synthesis report
        synthesis_pattern = f"synthesis-{epic}-{story}-*.md"
        for synth_path in sorted(reports_dir.glob(synthesis_pattern)):
            synthesis = {
                "path": str(synth_path),
                "name": synth_path.name,
                "provider": None,
            }
            break  # Take first (should only be one)

        return {"reports": reports, "synthesis": synthesis}

    def _extract_code_review_provider(self, filename: str) -> str | None:
        """Extract provider from code review filename.

        Pattern: code-review-{epic}-{story}-{provider}-{timestamp}.md
        Provider may contain underscores (e.g., claude_opus_4_5, gemini_3_flash_preview)
        Timestamp format: YYYYMMDD_HHMM

        Args:
            filename: Code review report filename.

        Returns:
            Provider name, or None if pattern doesn't match.

        """
        # Pattern: code-review-{epic}-{story}-{provider}-{timestamp}.md
        pattern = r"code-review-[a-z0-9]+-[a-z0-9]+-(.+)-\d{8}_\d{4}\.md"
        match = re.match(pattern, filename, re.IGNORECASE)
        return match.group(1) if match else None

    def get_all_reviews(self, epic: str, story: str) -> dict[str, Any]:
        """Get all review reports (validation + code-review) for a story.

        Combines validation and code review reports into a single response
        with separate sections for each type.

        Args:
            epic: Epic identifier.
            story: Story number.

        Returns:
            Dictionary with validation and code_review sections.

        """
        validation = self.get_validation_reports(epic, story)
        code_review = self.get_code_review_reports(epic, story)

        return {
            "validation": validation,
            "code_review": code_review,
        }

    async def run(self, log_level: str = "info") -> None:
        """Start the server and run until shutdown.

        This is the main entry point for running the server.

        Args:
            log_level: Uvicorn log level (debug, info, warning, error).

        """
        import uvicorn

        app = self.create_app()

        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level=log_level,
        )
        self._server = uvicorn.Server(config)

        # Setup signal handlers - use synchronous handler for immediate exit
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown_signal)

        await self._server.serve()

    def _handle_shutdown_signal(self) -> None:
        """Handle shutdown signal (SIGINT/SIGTERM) by force-exiting.

        Uvicorn's graceful shutdown often hangs waiting for connections.
        We force-kill the process immediately on Ctrl+C.
        """
        logger.info("Shutdown signal received, force-exiting...")
        # os._exit() terminates immediately without cleanup handlers
        # This is intentional - Ctrl+C should stop the server instantly
        os._exit(0)


def start_server(
    project_root: Path | str,
    host: str = "127.0.0.1",
    port: int = 9600,
) -> None:
    """Start dashboard server.

    Args:
        project_root: Path to bmad-assist project.
        host: Address to bind to.
        port: Port to bind to.

    """
    server = DashboardServer(
        project_root=Path(project_root),
        host=host,
        port=port,
    )

    asyncio.run(server.run())
