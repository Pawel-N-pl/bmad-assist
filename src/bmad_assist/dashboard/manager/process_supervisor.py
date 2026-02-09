"""Process supervisor for multi-project dashboard.

Provides PID monitoring, graceful shutdown, and crash detection for
subprocess management across multiple concurrent projects.

Based on design document: docs/multi-project-dashboard.md Section 5
"""

import asyncio
import logging
import os
import signal
from pathlib import Path
from subprocess import PIPE, STDOUT, Popen
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .project_context import ProjectContext

logger = logging.getLogger(__name__)

# Default timeouts
DEFAULT_WATCHDOG_INTERVAL = 5.0  # seconds between PID checks
DEFAULT_SUBPROCESS_TIMEOUT = 30  # seconds to wait for graceful shutdown
DEFAULT_SIGTERM_WAIT = 5  # seconds between SIGTERM and SIGKILL


class ProcessSupervisor:
    """Manages subprocess lifecycle and health monitoring.

    Provides:
    - Subprocess spawning with proper environment
    - PID monitoring via watchdog
    - Graceful shutdown (stop.flag → SIGTERM → SIGKILL)
    - Crash detection and error state transition
    - Async log streaming to project context

    Attributes:
        watchdog_interval: Seconds between PID health checks.
        subprocess_timeout: Seconds to wait for graceful exit.
        sigterm_wait: Seconds between SIGTERM and SIGKILL.

    """

    def __init__(
        self,
        watchdog_interval: float = DEFAULT_WATCHDOG_INTERVAL,
        subprocess_timeout: int = DEFAULT_SUBPROCESS_TIMEOUT,
        sigterm_wait: int = DEFAULT_SIGTERM_WAIT,
    ) -> None:
        """Initialize process supervisor.

        Args:
            watchdog_interval: Seconds between PID health checks.
            subprocess_timeout: Seconds to wait for graceful exit.
            sigterm_wait: Seconds between SIGTERM and SIGKILL.

        """
        self.watchdog_interval = watchdog_interval
        self.subprocess_timeout = subprocess_timeout
        self.sigterm_wait = sigterm_wait
        self._watchdog_tasks: dict[str, asyncio.Task[None]] = {}
        self._stdout_tasks: dict[str, asyncio.Task[None]] = {}
        self._running = True

    async def spawn_subprocess(
        self,
        context: "ProjectContext",
        on_output: Callable[[str], Any] | None = None,
        on_crash: Callable[[str], Any] | None = None,
    ) -> Popen[bytes]:
        """Spawn bmad-assist run subprocess for a project.

        Args:
            context: Project context to spawn subprocess for.
            on_output: Callback for each stdout line.
            on_crash: Callback when subprocess crashes.

        Returns:
            The spawned subprocess.

        Raises:
            RuntimeError: If subprocess fails to start.

        """
        project_root = context.project_root

        # Create .bmad-assist directory if needed
        bmad_dir = project_root / ".bmad-assist"
        bmad_dir.mkdir(parents=True, exist_ok=True)

        # Build command
        cmd = [
            "bmad-assist",
            "run",
            "--no-interactive",
            "--project",
            str(project_root),
        ]

        logger.info(
            "Spawning subprocess for %s: %s",
            context.display_name,
            " ".join(cmd),
        )

        try:
            process = Popen(
                cmd,
                cwd=project_root,
                stdout=PIPE,
                stderr=STDOUT,
                bufsize=1,  # Line buffered
            )
        except Exception as e:
            logger.exception("Failed to spawn subprocess for %s", context.display_name)
            raise RuntimeError(f"Failed to spawn subprocess: {e}") from e

        # Verify process started
        if process.poll() is not None:
            raise RuntimeError(f"Subprocess exited immediately with code {process.returncode}")

        # Start watchdog and stdout reader
        context.set_running(process)
        self._start_watchdog(context, on_crash)
        self._start_stdout_reader(context, on_output)

        return process

    def _start_watchdog(
        self,
        context: "ProjectContext",
        on_crash: Callable[[str], Any] | None = None,
    ) -> None:
        """Start watchdog task for process health monitoring.

        Args:
            context: Project context to monitor.
            on_crash: Callback when crash detected.

        """

        async def watchdog() -> None:
            while self._running and context.current_process is not None:
                process = context.current_process
                if process.poll() is not None:
                    # Process exited
                    exit_code = process.returncode
                    if exit_code != 0:
                        error_msg = f"Subprocess crashed with exit code {exit_code}"
                        logger.error(
                            "Project %s (%s): %s",
                            context.display_name,
                            context.project_uuid[:8],
                            error_msg,
                        )
                        context.set_error(error_msg)
                        if on_crash:
                            await asyncio.get_event_loop().run_in_executor(
                                None, on_crash, error_msg
                            )
                    else:
                        context.set_idle(success=True)
                    break

                await asyncio.sleep(self.watchdog_interval)

        task = asyncio.create_task(watchdog())
        self._watchdog_tasks[context.project_uuid] = task

    def _start_stdout_reader(
        self,
        context: "ProjectContext",
        on_output: Callable[[str], Any] | None = None,
    ) -> None:
        """Start async stdout reader for subprocess.

        Args:
            context: Project context to read stdout for.
            on_output: Callback for each output line.

        """

        async def read_stdout() -> None:
            process = context.current_process
            if process is None or process.stdout is None:
                return

            loop = asyncio.get_event_loop()

            while self._running and process.poll() is None:
                try:
                    # Read line in executor to avoid blocking
                    line: bytes = await loop.run_in_executor(
                        None, process.stdout.readline
                    )
                    if not line:
                        break

                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    context.add_log(decoded)

                    if on_output:
                        # Run callback (may be async or sync)
                        result = on_output(decoded)
                        if asyncio.iscoroutine(result):
                            await result

                except Exception:
                    logger.exception(
                        "Error reading stdout for %s", context.display_name
                    )
                    break

        task = asyncio.create_task(read_stdout())
        self._stdout_tasks[context.project_uuid] = task

    async def stop_subprocess(
        self,
        context: "ProjectContext",
        force: bool = False,
    ) -> bool:
        """Stop subprocess gracefully or forcefully.

        Follows the stop flow from docs/multi-project-dashboard.md Section 5.2:
        1. Write stop.flag
        2. Wait subprocess_timeout for exit
        3. If still running: SIGTERM
        4. Wait sigterm_wait
        5. If still running: SIGKILL
        6. Clean up flags

        Args:
            context: Project context to stop.
            force: If True, skip graceful shutdown and go straight to SIGTERM.

        Returns:
            True if subprocess was stopped, False if not running.

        """
        process = context.current_process
        if process is None:
            return False

        pid = process.pid
        project_root = context.project_root
        bmad_dir = project_root / ".bmad-assist"
        stop_flag = bmad_dir / "stop.flag"

        logger.info(
            "Stopping subprocess for %s (PID %d, force=%s)",
            context.display_name,
            pid,
            force,
        )

        if not force:
            # Step 1: Write stop.flag
            try:
                bmad_dir.mkdir(parents=True, exist_ok=True)
                stop_flag.touch()
                logger.debug("Created stop.flag for %s", context.display_name)
            except Exception:
                logger.exception("Failed to create stop.flag")

            # Step 2: Wait for graceful exit
            for _ in range(self.subprocess_timeout):
                if process.poll() is not None:
                    logger.info("Subprocess %s exited gracefully", context.display_name)
                    self._cleanup_stop(context, stop_flag)
                    return True
                await asyncio.sleep(1)

        # Step 3: SIGTERM
        if process.poll() is None:
            logger.warning("Sending SIGTERM to %s (PID %d)", context.display_name, pid)
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                logger.warning("Failed to send SIGTERM (process may have exited)")

            # Step 4: Wait for SIGTERM
            for _ in range(self.sigterm_wait):
                if process.poll() is not None:
                    logger.info("Subprocess %s terminated via SIGTERM", context.display_name)
                    self._cleanup_stop(context, stop_flag)
                    return True
                await asyncio.sleep(1)

        # Step 5: SIGKILL
        if process.poll() is None:
            logger.warning("Sending SIGKILL to %s (PID %d)", context.display_name, pid)
            try:
                os.kill(pid, signal.SIGKILL)
                process.wait(timeout=2)
            except Exception:
                logger.exception("Failed to kill subprocess")

        # Step 6: Cleanup
        self._cleanup_stop(context, stop_flag)
        return True

    def _cleanup_stop(self, context: "ProjectContext", stop_flag: Path) -> None:
        """Clean up after stopping subprocess.

        Args:
            context: Project context that was stopped.
            stop_flag: Path to stop.flag file.

        """
        # Cancel watchdog and stdout reader
        for tasks_dict in (self._watchdog_tasks, self._stdout_tasks):
            task = tasks_dict.pop(context.project_uuid, None)
            if task and not task.done():
                task.cancel()

        # Remove stop.flag
        try:
            if stop_flag.exists():
                stop_flag.unlink()
        except Exception:
            logger.exception("Failed to remove stop.flag")

        # Remove pause.flag if present
        pause_flag = stop_flag.parent / "pause.flag"
        try:
            if pause_flag.exists():
                pause_flag.unlink()
        except Exception:
            pass

        # Update context state
        context.set_idle(success=context.current_process.returncode == 0 if context.current_process else False)

    async def write_pause_flag(self, context: "ProjectContext") -> bool:
        """Write pause.flag for graceful pause.

        Args:
            context: Project context to pause.

        Returns:
            True if flag was written.

        """
        bmad_dir = context.project_root / ".bmad-assist"
        pause_flag = bmad_dir / "pause.flag"

        try:
            bmad_dir.mkdir(parents=True, exist_ok=True)
            pause_flag.touch()
            logger.info("Created pause.flag for %s", context.display_name)
            return True
        except Exception:
            logger.exception("Failed to create pause.flag")
            return False

    async def remove_pause_flag(self, context: "ProjectContext") -> bool:
        """Remove pause.flag to resume.

        Args:
            context: Project context to resume.

        Returns:
            True if flag was removed (or didn't exist).

        """
        pause_flag = context.project_root / ".bmad-assist" / "pause.flag"

        try:
            if pause_flag.exists():
                pause_flag.unlink()
            logger.info("Removed pause.flag for %s", context.display_name)
            return True
        except Exception:
            logger.exception("Failed to remove pause.flag")
            return False

    def is_pid_alive(self, pid: int) -> bool:
        """Check if a PID is still running.

        Args:
            pid: Process ID to check.

        Returns:
            True if process is running.

        """
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    async def shutdown(self) -> None:
        """Shutdown supervisor and cancel all tasks."""
        self._running = False

        # Cancel all watchdog tasks
        for task in self._watchdog_tasks.values():
            if not task.done():
                task.cancel()

        # Cancel all stdout reader tasks
        for task in self._stdout_tasks.values():
            if not task.done():
                task.cancel()

        # Wait for cancellation
        all_tasks = list(self._watchdog_tasks.values()) + list(self._stdout_tasks.values())
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)

        self._watchdog_tasks.clear()
        self._stdout_tasks.clear()
        logger.info("Process supervisor shutdown complete")
