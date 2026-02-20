"""LoopController for dashboard integration.

Provides lifecycle management for run_loop() in dashboard context.
Allows start/stop/pause/resume via REST API with proper thread safety.

Threading Model:
    Main Thread (Uvicorn Event Loop)
      ├── HTTP handlers (REST API)
      ├── SSE broadcaster (async queues)
      └── LoopController.start() → run_in_executor()
                      │
                      ▼ ThreadPoolExecutor
    Worker Thread (Orchestrator)
      ├── run_loop() - sync, blocking
      │    ├── execute_phase() → handler.execute()
      │    │    └── provider.invoke()
      │    └── write_progress() → sync_broadcast()
      │
      └── Checks cancel_ctx.is_cancelled at safe points
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.core.loop.cancellation import CancellationContext
from bmad_assist.core.loop.types import LoopExitReason, LoopStatus
from bmad_assist.core.types import EpicId

if TYPE_CHECKING:
    from bmad_assist.core.config import Config

__all__ = [
    "ControllerState",
    "LoopController",
]

logger = logging.getLogger(__name__)


class ControllerState(Enum):
    """State machine for LoopController lifecycle.

    Valid transitions:
        IDLE → STARTING (on start())
        STARTING → RUNNING (when run_loop() begins)
        STARTING → IDLE (on error or stop during start)
        RUNNING → PAUSED (on pause())
        RUNNING → STOPPING (on stop())
        PAUSED → RUNNING (on resume())
        PAUSED → STOPPING (on stop())
        STOPPING → IDLE (when run_loop() exits)
    """

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"


class LoopController:
    """Lifecycle manager for run_loop() in dashboard context.

    Thread-safe via state machine + lock. All public methods acquire lock.
    Runs run_loop() in a ThreadPoolExecutor to avoid blocking the event loop.

    Usage:
        controller = LoopController(project_path, config)
        await controller.start()
        # ... dashboard serves requests ...
        await controller.stop()
        controller.shutdown()

    Attributes:
        project_path: Path to project root directory.

    """

    def __init__(self, project_path: Path, config: Config) -> None:
        """Initialize LoopController with project and config.

        Args:
            project_path: Path to project root directory.
            config: Loaded configuration with provider settings.

        """
        self._project_path = project_path
        self._config = config
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="loop")
        self._future: Any = None  # asyncio.Future or concurrent.futures.Future
        self._cancel_ctx: CancellationContext | None = None
        self._state = ControllerState.IDLE
        self._lock = threading.Lock()
        self._error: str | None = None

        # Tracking current position (updated by callbacks)
        self._current_epic: EpicId | None = None
        self._current_story: str | None = None
        self._current_phase: str | None = None

    def _load_epic_data(self) -> tuple[list[EpicId], Callable[[EpicId], list[str]]]:
        """Load epic list and stories loader. Mirrors cli.py pattern.

        Returns:
            Tuple of (epic_list, epic_stories_loader) where:
            - epic_list: Sorted list of epic IDs
            - epic_stories_loader: Callable that returns story IDs for epic

        Raises:
            FileNotFoundError: If BMAD docs not found.
            StateError: If no stories found.

        """
        from bmad_assist.bmad.state_reader import read_project_state
        from bmad_assist.core.paths import get_paths
        from bmad_assist.core.types import epic_sort_key, parse_epic_id

        paths = get_paths()
        bmad_path = paths.project_knowledge

        logger.debug("Loading BMAD project state from: %s", bmad_path)

        project_state = read_project_state(bmad_path, use_sprint_status=True)

        # Extract unique epic numbers from stories (excluding done stories)
        epic_numbers: set[EpicId] = set()
        stories_by_epic: dict[EpicId, list[str]] = {}

        for story in project_state.all_stories:
            if story.status == "done":
                continue

            epic_part = story.number.split(".")[0]
            epic_id = parse_epic_id(epic_part)
            epic_numbers.add(epic_id)

            if epic_id not in stories_by_epic:
                stories_by_epic[epic_id] = []
            stories_by_epic[epic_id].append(story.number)

        epic_list = sorted(epic_numbers, key=epic_sort_key)

        logger.info(
            "Loaded %d epics with %d total stories",
            len(epic_list),
            len(project_state.all_stories),
        )

        def epic_stories_loader(epic: EpicId) -> list[str]:
            """Return story IDs for given epic (re-reads state).

            Uses dynamic re-read so stories added at runtime (e.g., hardening
            Story 0 written to sprint-status during epic teardown) are picked up.
            """
            fresh_state = read_project_state(bmad_path, use_sprint_status=True)
            fresh_stories: dict[EpicId, list[str]] = {}
            for s in fresh_state.all_stories:
                if s.status == "done":
                    continue
                epart = s.number.split(".")[0]
                eid = parse_epic_id(epart)
                if eid not in fresh_stories:
                    fresh_stories[eid] = []
                fresh_stories[eid].append(s.number)
            return fresh_stories.get(epic, [])

        return epic_list, epic_stories_loader

    async def start(self) -> LoopStatus:
        """Start the loop in executor thread. Thread-safe.

        Initializes paths, loads epic data, creates cancel context,
        and runs run_loop() in ThreadPoolExecutor.

        Returns:
            Current status after start attempt.

        """
        with self._lock:
            if self._state != ControllerState.IDLE:
                logger.warning("Start called while not idle: %s", self._state)
                return self._get_status_unlocked()

            self._state = ControllerState.STARTING
            self._error = None

        try:
            # Initialize paths (required for epic loading)
            from bmad_assist.core.paths import get_paths, init_paths

            try:
                get_paths()  # Check if already initialized
            except RuntimeError:
                paths_config = {}
                if self._config.paths:
                    if self._config.paths.output_folder:
                        paths_config["output_folder"] = self._config.paths.output_folder
                    if self._config.paths.project_knowledge:
                        paths_config["project_knowledge"] = self._config.paths.project_knowledge
                init_paths(self._project_path, paths_config)

            # Load epic data
            epic_list, epic_stories_loader = self._load_epic_data()

            if not epic_list:
                with self._lock:
                    self._state = ControllerState.IDLE
                    self._error = "No epics found in project"
                return self.get_status()

            # Create cancel context
            self._cancel_ctx = CancellationContext()

            # Run in executor
            loop = asyncio.get_event_loop()
            self._future = loop.run_in_executor(
                self._executor,
                lambda: self._run_loop_wrapper(epic_list, epic_stories_loader),
            )

            with self._lock:
                self._state = ControllerState.RUNNING

            logger.info("Loop started with %d epics", len(epic_list))

        except Exception as e:
            logger.exception("Failed to start loop: %s", e)
            with self._lock:
                self._state = ControllerState.IDLE
                self._error = str(e)

        return self.get_status()

    def _run_loop_wrapper(
        self,
        epic_list: list[EpicId],
        epic_stories_loader: Callable[[EpicId], list[str]],
    ) -> LoopExitReason:
        """Wrapper that runs run_loop and handles exceptions.

        Called in executor thread. Updates controller state on exit.

        Args:
            epic_list: List of epic IDs to process.
            epic_stories_loader: Callable to get stories for an epic.

        Returns:
            LoopExitReason from run_loop().

        """
        from bmad_assist.core.loop.runner import run_loop

        try:
            exit_reason = run_loop(
                config=self._config,
                project_path=self._project_path,
                epic_list=epic_list,
                epic_stories_loader=epic_stories_loader,
                cancel_ctx=self._cancel_ctx,
                skip_signal_handlers=True,  # Not main thread!
            )
            logger.info("Loop exited with reason: %s", exit_reason)
            return exit_reason

        except Exception as e:
            logger.exception("Loop failed with exception: %s", e)
            with self._lock:
                self._error = str(e)
            return LoopExitReason.ERROR

        finally:
            with self._lock:
                self._state = ControllerState.IDLE
                self._cancel_ctx = None
                self._current_epic = None
                self._current_story = None
                self._current_phase = None

    async def stop(self) -> LoopStatus:
        """Stop the loop gracefully. Thread-safe.

        Requests cancellation via cancel context and waits for loop to exit.
        Uses timeout to prevent indefinite wait.

        Returns:
            Current status after stop attempt.

        """
        with self._lock:
            if self._state not in (ControllerState.RUNNING, ControllerState.PAUSED):
                logger.warning("Stop called while not running: %s", self._state)
                return self._get_status_unlocked()
            self._state = ControllerState.STOPPING

        logger.info("Stopping loop...")

        # Request cancellation
        if self._cancel_ctx:
            self._cancel_ctx.request_cancel()
            exceptions = self._cancel_ctx.run_cleanup()
            if exceptions:
                logger.warning("Cleanup raised %d exceptions", len(exceptions))

        # Also write stop flag for subprocess compatibility
        stop_flag = self._project_path / ".bmad-assist" / "stop.flag"
        stop_flag.parent.mkdir(parents=True, exist_ok=True)
        stop_flag.touch()

        # Clean up pause flag if present
        pause_flag = self._project_path / ".bmad-assist" / "pause.flag"
        pause_flag.unlink(missing_ok=True)

        # Wait for future with timeout
        if self._future:
            try:
                await asyncio.wait_for(
                    asyncio.wrap_future(self._future),
                    timeout=10.0,
                )
                logger.info("Loop stopped successfully")
            except TimeoutError:
                logger.warning("Stop timeout - thread may be stuck")
                with self._lock:
                    self._error = "Stop timeout - thread may be stuck"
                    self._state = ControllerState.IDLE

        # Clean up stop flag
        stop_flag.unlink(missing_ok=True)

        return self.get_status()

    async def pause(self) -> LoopStatus:
        """Pause at next safe checkpoint. Uses file flag for compatibility.

        Creates pause.flag file which is checked by run_loop() at safe points.

        Returns:
            Current status after pause request.

        """
        with self._lock:
            if self._state != ControllerState.RUNNING:
                logger.warning("Pause called while not running: %s", self._state)
                return self._get_status_unlocked()
            self._state = ControllerState.PAUSED

        # Write pause.flag for hybrid approach
        pause_flag = self._project_path / ".bmad-assist" / "pause.flag"
        pause_flag.parent.mkdir(parents=True, exist_ok=True)
        pause_flag.touch()

        logger.info("Pause requested - will pause after current phase")
        return self.get_status()

    async def resume(self) -> LoopStatus:
        """Resume from pause. Removes file flag.

        Removes pause.flag file which allows run_loop() to continue.

        Returns:
            Current status after resume request.

        """
        with self._lock:
            if self._state != ControllerState.PAUSED:
                logger.warning("Resume called while not paused: %s", self._state)
                return self._get_status_unlocked()
            self._state = ControllerState.RUNNING

        # Remove pause flag
        pause_flag = self._project_path / ".bmad-assist" / "pause.flag"
        pause_flag.unlink(missing_ok=True)

        logger.info("Resumed from pause")
        return self.get_status()

    def get_status(self) -> LoopStatus:
        """Get current status. Thread-safe.

        Returns:
            LoopStatus dict with current state.

        """
        with self._lock:
            return self._get_status_unlocked()

    def _get_status_unlocked(self) -> LoopStatus:
        """Internal status getter (caller must hold lock).

        Returns:
            LoopStatus dict with current state.

        """
        return LoopStatus(
            state=self._state.value,
            running=self._state in (ControllerState.RUNNING, ControllerState.STARTING),
            paused=self._state == ControllerState.PAUSED,
            current_epic=self._current_epic,
            current_story=self._current_story,
            current_phase=self._current_phase,
            error=self._error,
        )

    def update_position(
        self,
        epic: EpicId | None = None,
        story: str | None = None,
        phase: str | None = None,
    ) -> None:
        """Update current position (called from run_loop callbacks).

        Thread-safe position update for status reporting.

        Args:
            epic: Current epic ID.
            story: Current story ID.
            phase: Current phase name.

        """
        with self._lock:
            if epic is not None:
                self._current_epic = epic
            if story is not None:
                self._current_story = story
            if phase is not None:
                self._current_phase = phase

    def shutdown(self) -> None:
        """Shutdown executor. Call on server shutdown.

        Waits for executor to finish and cancels pending futures.
        """
        logger.info("Shutting down LoopController executor")
        self._executor.shutdown(wait=True, cancel_futures=True)

    @property
    def is_running(self) -> bool:
        """Check if loop is currently running."""
        with self._lock:
            return self._state in (ControllerState.RUNNING, ControllerState.STARTING)

    @property
    def is_paused(self) -> bool:
        """Check if loop is currently paused."""
        with self._lock:
            return self._state == ControllerState.PAUSED
