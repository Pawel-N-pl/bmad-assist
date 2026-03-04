"""Standalone TUI application with IPC connection to bmad-assist runner.

Launched as a separate process by `bmad-assist tui connect`. Connects
to a running runner via Unix domain socket, displays live status,
and provides keyboard-driven remote control.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TUIApp:
    """Async TUI application connecting to a bmad-assist runner via IPC."""

    def __init__(
        self,
        socket_path: Path | None = None,
        project: str | None = None,
        debug: bool = False,
    ) -> None:
        self._socket_path = socket_path
        self._project = project
        self._debug = debug
        self._shutdown_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_pending: bool = False
        self._stop_pending_time: float = 0.0
        self._STOP_CONFIRM_WINDOW: float = 2.0

        # Set during run() for use by callbacks
        self._client: Any = None
        self._renderer: Any = None
        self._status_bar: Any = None
        self._layout: Any = None
        self._event_bridge: Any = None
        self._log_toggle: Any = None

    _DISCOVERY_INTERVAL: float = 0.2  # seconds between discovery polls

    async def run(self) -> int:
        """Main entry point. Returns exit code."""
        from bmad_assist.ipc.client import SocketClient
        from bmad_assist.tui.event_bridge import EventBridge
        from bmad_assist.tui.input import InputHandler
        from bmad_assist.tui.interactive import InteractiveRenderer
        from bmad_assist.tui.layout import LayoutManager
        from bmad_assist.tui.log_level import LogLevelToggle
        from bmad_assist.tui.status_bar import StatusBar
        from bmad_assist.tui.timer import PauseTimer

        # 1. Capture event loop early (CRITICAL for keyboard callbacks)
        self._loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()
        self._reconnect_to_discovery = asyncio.Event()

        # 2. Create TUI components FIRST (so user sees UI immediately)
        layout = LayoutManager(status_lines=2)
        status_bar = StatusBar(layout)
        log_toggle = LogLevelToggle(status_bar, layout)
        input_handler = InputHandler()
        pause_timer = PauseTimer(status_bar, layout)

        renderer = InteractiveRenderer()
        renderer.set_components(layout, log_toggle, status_bar, input_handler, pause_timer)

        # Store references for callbacks
        self._renderer = renderer
        self._status_bar = status_bar
        self._layout = layout
        self._log_toggle = log_toggle

        # 3. Register quit callback (always active, thread-safe)
        def _on_quit() -> None:
            if self._shutdown_event and self._loop:
                self._loop.call_soon_threadsafe(self._shutdown_event.set)

        input_handler.register("q", _on_quit)

        # 4. Start renderer so TUI is visible
        renderer.start()

        try:
            # 5. Main loop: discover → connect → run → (disconnect → rediscover)
            while not self._shutdown_event.is_set():
                self._reconnect_to_discovery.clear()

                # 5a. Discovery polling loop
                socket_path = await self._discover_with_polling(layout)
                if socket_path is None:
                    # shutdown_event was set during polling
                    break

                # 5b. Create SocketClient for this connection
                client = SocketClient(
                    socket_path=socket_path,
                    auto_reconnect=True,
                    max_retries=50,
                    initial_delay=1.0,
                    max_delay=30.0,
                    on_reconnect=self._on_reconnect,
                    on_disconnect=self._on_disconnect,
                    on_reconnect_failed=self._on_reconnect_failed,
                )
                self._client = client

                # 5c. Create EventBridge for this connection
                event_bridge = EventBridge(renderer, status_bar, client)
                self._event_bridge = event_bridge
                if self._debug:
                    event_bridge.set_session_details_callback(self._show_session_details)

                # 5d. Register connection-aware keyboard callbacks
                loop = self._loop

                def _make_callbacks() -> None:
                    _client = client
                    _layout = layout
                    _pause_timer = pause_timer
                    _log_toggle = log_toggle
                    _loop = loop

                    def _on_resume() -> None:
                        _pause_timer.deactivate()
                        asyncio.run_coroutine_threadsafe(_client.resume(), _loop)

                    def _on_stop() -> None:
                        now = time.monotonic()
                        if self._stop_pending and (now - self._stop_pending_time) < self._STOP_CONFIRM_WINDOW:
                            self._stop_pending = False
                            _layout.write_log("Sending stop command...")
                            asyncio.run_coroutine_threadsafe(_client.stop(), _loop)
                        else:
                            self._stop_pending = True
                            self._stop_pending_time = now
                            _layout.write_log("Press 's' again within 2s to stop the runner")

                    def _on_log_level() -> None:
                        _log_toggle.on_log_level_key()
                        new_level = _log_toggle.get_level()
                        asyncio.run_coroutine_threadsafe(_client.set_log_level(new_level), _loop)

                    input_handler.register("r", _on_resume)
                    input_handler.register("s", _on_stop)
                    input_handler.register("l", _on_log_level)

                _make_callbacks()
                input_handler.register("p", pause_timer.on_pause_key)
                input_handler.register_long_press("p", pause_timer.on_long_press_p)

                pause_timer.set_pause_callback(
                    lambda: asyncio.run_coroutine_threadsafe(client.pause(), loop)
                )
                pause_timer.set_resume_callback(
                    lambda: asyncio.run_coroutine_threadsafe(client.resume(), loop)
                )

                # 5e. Connect, hydrate, subscribe, wait
                try:
                    layout.write_log(f"Connecting to {socket_path.name}...")
                    await client.connect()

                    state = await client.get_state()
                    self._apply_state(state, status_bar, renderer)

                    client.subscribe(event_bridge.on_event)

                    layout.write_log("Connected to runner")

                    # Wait until quit or reconnect-to-discovery
                    _done, _pending = await asyncio.wait(
                        [
                            asyncio.create_task(self._shutdown_event.wait()),
                            asyncio.create_task(self._reconnect_to_discovery.wait()),
                        ],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    # Cancel pending tasks
                    for task in _pending:
                        task.cancel()

                except Exception as exc:
                    logger.warning("Connection failed: %s", exc, exc_info=True)
                    layout.write_log(f"Connection failed: {type(exc).__name__}: {exc}")
                finally:
                    try:
                        event_bridge.stop()
                    except Exception:
                        pass
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                    self._client = None
                    self._event_bridge = None

                # Loop back to discovery if not shutting down

            return 0

        except Exception as exc:
            logger.error("TUI error: %s", exc)
            return 1
        finally:
            try:
                renderer.stop()
            except Exception:
                pass

    async def _discover_with_polling(self, layout: Any) -> Path | None:
        """Poll for runner instances until one is found or quit is pressed."""
        first_attempt = True
        while not self._shutdown_event.is_set():
            socket_path = await self._resolve_socket(quiet=not first_attempt)
            if socket_path is not None:
                return socket_path

            if first_attempt:
                layout.write_log("Waiting for bmad-assist runner... (press q to quit)")
                first_attempt = False

            # Wait with cancellation support
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._DISCOVERY_INTERVAL,
                )
                # shutdown_event was set
                return None
            except asyncio.TimeoutError:
                continue
        return None

    async def _resolve_socket(self, *, quiet: bool = False) -> Path | None:
        """Resolve socket path from args or discovery."""
        if self._socket_path is not None:
            if not self._socket_path.exists():
                if not quiet:
                    logger.debug("Socket not found: %s", self._socket_path)
                return None
            return self._socket_path

        # Auto-discover
        from bmad_assist.ipc.discovery import discover_instances_async

        instances = await discover_instances_async()

        if not instances:
            return None

        if len(instances) == 1:
            logger.debug("Found runner: %s", instances[0].socket_path)
            return instances[0].socket_path

        # Multiple instances - need --project to disambiguate
        if self._project:
            for inst in instances:
                project_path = inst.state.get("project_path", "")
                project_name = inst.state.get("project_name", "")
                if self._project in (project_path, project_name):
                    return inst.socket_path
            # No match
            if not quiet and self._layout:
                self._layout.write_log(f"No runner for '{self._project}'. Waiting...")
            return None

        # Multiple instances, no --project
        names = [inst.state.get("project_name", "?") for inst in instances]
        if not quiet and self._layout:
            self._layout.write_log(
                f"Multiple runners found: {', '.join(names)}. Use --project to select."
            )
        else:
            logger.debug("Multiple runners: %s (quiet mode)", ", ".join(names))
        return None

    def _apply_state(self, state: Any, status_bar: Any, renderer: InteractiveRenderer) -> None:
        """Apply hydrated state to TUI components."""
        from bmad_assist.ipc.types import RunnerState

        # Runner state
        state_str = getattr(state, "state", None) or "idle"
        try:
            runner_state = RunnerState(state_str)
            renderer.update_status(runner_state)
        except ValueError:
            pass

        # Phase info (with elapsed offset for accurate timer on reconnect)
        phase = getattr(state, "current_phase", None)
        epic = getattr(state, "current_epic", None)
        story = getattr(state, "current_story", None)
        phase_elapsed = getattr(state, "phase_elapsed_seconds", 0.0)
        if phase and epic and story:
            status_bar.set_phase_info(phase, epic, story, elapsed=phase_elapsed)

        # Elapsed time
        elapsed = getattr(state, "elapsed_seconds", 0.0)
        if elapsed > 0:
            status_bar.set_run_start_time(time.monotonic() - elapsed)

        # LLM sessions
        llm = getattr(state, "llm_sessions", 0)
        status_bar.set_llm_sessions(llm)

        # Paused state
        paused = getattr(state, "paused", False)
        status_bar.set_paused(paused)

        # Log level (restore to match runner after reconnect)
        log_level = getattr(state, "log_level", None)
        if log_level and self._log_toggle is not None:
            self._log_toggle.set_level(log_level)

        # Debug: show LLM session details
        if self._debug and self._layout:
            self._show_session_details(getattr(state, "session_details", []))

    def _show_session_details(self, details: list[dict[str, Any]]) -> None:
        """Render LLM session details in the fixed debug panel."""
        if not self._layout:
            return

        if not details:
            self._layout.update_debug_panel([])
            return

        cols = shutil.get_terminal_size(fallback=(80, 24)).columns

        # Format each session as "model (provider)"
        items: list[str] = []
        for d in details:
            model = d.get("model", "?")
            provider = d.get("provider", "?")
            items.append(f"{model} ({provider})")

        if not items:
            self._layout.update_debug_panel([])
            return

        max_width = max(len(item) for item in items)
        col_width = max_width + 3
        num_cols = max(1, cols // col_width)

        lines: list[str] = []
        for i in range(0, len(items), num_cols):
            row_items = items[i:i + num_cols]
            row = "  ".join(item.ljust(max_width) for item in row_items)
            lines.append(row)

        self._layout.update_debug_panel(lines)

    async def _on_reconnect(self) -> None:
        """Called after successful reconnection."""
        try:
            state = await self._client.get_state()
            self._renderer.reset()
            self._apply_state(state, self._status_bar, self._renderer)
            if self._layout:
                self._layout.write_log("Reconnected to runner")
        except Exception:
            logger.warning("State re-hydration after reconnect failed", exc_info=True)

    def _on_disconnect(self) -> None:
        """Called on connection loss."""
        if self._status_bar:
            from bmad_assist.ipc.types import RunnerState

            self._status_bar.set_runner_state(RunnerState.IDLE)
        if self._layout:
            self._layout.write_log("Connection lost -- reconnecting...")

    def _on_reconnect_failed(self, error: Exception) -> None:
        """Called when reconnect retries exhausted — fall back to discovery."""
        if self._layout:
            self._layout.write_log(f"Runner not available: {error}")
            self._layout.write_log("Returning to discovery mode...")
        # Signal the main loop to go back to discovery polling
        if hasattr(self, "_reconnect_to_discovery") and self._reconnect_to_discovery:
            self._reconnect_to_discovery.set()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="bmad-assist TUI")
    parser.add_argument("--socket", type=Path, help="Socket path to connect to")
    parser.add_argument("--project", type=str, help="Project path or name to match")
    parser.add_argument("--debug", action="store_true", help="Show LLM session details")
    args = parser.parse_args()

    # Non-TTY guard
    if sys.stdin is None or not sys.stdin.isatty():
        print("TUI requires an interactive terminal", file=sys.stderr)
        sys.exit(1)

    app = TUIApp(socket_path=args.socket, project=args.project, debug=args.debug)
    try:
        exit_code = asyncio.run(app.run())
    except KeyboardInterrupt:
        exit_code = 130
    sys.exit(exit_code)
