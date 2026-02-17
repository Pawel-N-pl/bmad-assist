"""Shared progress indicator for parallel provider execution.

This module provides a unified progress display for multiple LLM providers
running in parallel. Each provider registers itself and updates its state,
while a single background task renders all active providers with one line
per agent, using the full terminal width.

Example output:
    ⠋ CC sonnet: 12s, in≈21857, out≈47
    ⠹ GH claude-sonnet-4.5: 8s...
    ⠸ GH GPT-5.3-Codex: 6s, in≈500, out≈120

Features:
- Thread-safe registration/update via threading.Lock
- Per-agent spinner animation (phase offset by index)
- One line per agent with colored left-edge indicator
- ANSI cursor control to overwrite previous render
- Clear-to-EOL to prevent ghost characters
- Shared render task management across providers

Usage:
    from bmad_assist.providers.progress import (
        register_agent, update_agent, unregister_agent,
        ensure_spinner_running, stop_spinner_if_last,
    )

    # Register when starting
    color_idx = register_agent("abc123", "claude-sonnet", start_time)
    ensure_spinner_running()  # starts shared spinner if not running

    # Update during streaming
    update_agent("abc123", in_tokens=100, out_tokens=50, status="streaming")

    # Unregister when done
    unregister_agent("abc123")

"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Spinner characters for streaming progress indicator
SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

# ANSI escape codes
BG_COLORS = (
    "\033[44m",   # Blue
    "\033[42m",   # Green
    "\033[45m",   # Magenta
    "\033[43m",   # Yellow
    "\033[46m",   # Cyan
    "\033[41m",   # Red
)
RESET = "\033[0m"
CLEAR_EOL = "\033[K"  # Clear from cursor to end of line

CURSOR_UP = "\033[A"  # Move cursor up one line

# Shared state
_active_agents: dict[str, dict] = {}  # agent_id -> state dict
_agents_lock = threading.Lock()
_spinner_tick = 0
_last_render_lines = 0  # Number of lines rendered in last draw
_render_task: asyncio.Task | None = None  # Single shared render task
_spinner_done: asyncio.Event | None = None  # Shared done event for spinner


def register_agent(
    agent_id: str, model: str, start_time: float, provider_tag: str = ""
) -> int:
    """Register an agent and return its color index.

    Args:
        agent_id: Unique identifier for this agent instance.
        model: Model name to display (e.g., "claude-sonnet-4.5").
        start_time: Start time from time.perf_counter().
        provider_tag: Short provider identifier (e.g., "CC", "GH").

    Returns:
        Color index assigned to this agent (0-5).

    """
    with _agents_lock:
        color_idx = len(_active_agents) % len(BG_COLORS)
        _active_agents[agent_id] = {
            "model": model,
            "start_time": start_time,
            "in_tokens": 0,
            "out_tokens": 0,
            "status": "waiting",
            "provider_tag": provider_tag,
        }
        return color_idx


def update_agent(agent_id: str, **kwargs) -> None:
    """Update agent state (in_tokens, out_tokens, status).

    Args:
        agent_id: Agent identifier from register_agent().
        **kwargs: State fields to update. Common fields:
            - in_tokens (int): Input token count estimate
            - out_tokens (int): Output token count estimate
            - status (str): "waiting" or "streaming"

    """
    with _agents_lock:
        if agent_id in _active_agents:
            _active_agents[agent_id].update(kwargs)


def unregister_agent(agent_id: str) -> None:
    """Remove agent from registry.

    Args:
        agent_id: Agent identifier from register_agent().

    """
    with _agents_lock:
        _active_agents.pop(agent_id, None)


def clear_progress_line() -> None:
    """Clear all rendered progress lines and move cursor back.

    Handles multi-line spinner output by moving cursor up and clearing
    each line that was previously rendered.
    """
    global _last_render_lines
    if _last_render_lines <= 0:
        # Fallback: just clear current line
        sys.stdout.write("\r" + CLEAR_EOL)
        sys.stdout.flush()
        return
    # Move up to the first rendered line and clear each
    lines_to_clear = _last_render_lines
    _last_render_lines = 0
    # Move up (lines - 1) times since cursor is on the last rendered line
    output = ""
    for _ in range(lines_to_clear - 1):
        output += CURSOR_UP
    output += "\r"
    for i in range(lines_to_clear):
        output += CLEAR_EOL
        if i < lines_to_clear - 1:
            output += "\n"
    # Move back up to start position
    for _ in range(lines_to_clear - 1):
        output += CURSOR_UP
    output += "\r"
    sys.stdout.write(output)
    sys.stdout.flush()


def print_completion(agent_id: str, model: str, elapsed_secs: int, out_tokens: int) -> None:
    """Print a completion message for an agent.

    Args:
        agent_id: Agent identifier (unused, for consistency).
        model: Model name that completed.
        elapsed_secs: Total elapsed time in seconds.
        out_tokens: Estimated output tokens.

    """
    clear_progress_line()
    # Green checkmark for completion
    sys.stdout.write(f"\033[32m✓\033[0m {model}: {elapsed_secs}s, ~{out_tokens} tokens\n")
    sys.stdout.flush()


def print_error(model: str, message: str) -> None:
    """Print an error message for an agent, clearing the spinner first.

    Args:
        model: Model name that errored.
        message: Short error description.

    """
    clear_progress_line()
    # Red cross for error
    sys.stdout.write(f"\033[31m✗\033[0m {model}: {message}\n")
    sys.stdout.flush()


def get_active_count() -> int:
    """Return number of currently active agents."""
    with _agents_lock:
        return len(_active_agents)


def get_agents_lock() -> threading.Lock:
    """Return the agents lock for external synchronization."""
    return _agents_lock


def get_render_task() -> asyncio.Task | None:
    """Return the current render task, if any."""
    return _render_task


def set_render_task(task: asyncio.Task | None) -> None:
    """Set the shared render task."""
    global _render_task
    _render_task = task


def ensure_spinner_running() -> None:
    """Start the shared spinner task if not already running.

    Safe to call from multiple agents — only the first call creates the
    task.  The spinner runs until stop_spinner_if_last() is called by the
    last active agent.
    """
    global _render_task, _spinner_done
    with _agents_lock:
        if _render_task is not None and not _render_task.done():
            return  # Already running
        _spinner_done = asyncio.Event()
        _render_task = asyncio.create_task(_run_spinner(_spinner_done))


async def stop_spinner_if_last() -> None:
    """Stop the shared spinner if this is the last active agent.

    Should be called AFTER unregister_agent() so that get_active_count()
    reflects the removal.  If other agents are still running, this is a
    no-op and the spinner keeps going.
    """
    global _render_task, _spinner_done
    with _agents_lock:
        if get_active_count() > 0:
            return  # Other agents still running
        if _spinner_done is not None:
            _spinner_done.set()
        if _render_task is not None:
            _render_task.cancel()
            try:
                await _render_task
            except asyncio.CancelledError:
                pass
            _render_task = None
            _spinner_done = None


async def _run_spinner(done_event: asyncio.Event) -> None:
    """Internal spinner render loop.

    Renders all active agents every 333ms until done_event is set.
    """
    while not done_event.is_set():
        await asyncio.sleep(0.333)
        if done_event.is_set():
            break
        status = render_all_agents()
        if status:
            sys.stdout.write(status)
            sys.stdout.flush()


def render_all_agents() -> str:
    """Render all active agents, one per line with colored left-edge indicator.

    Each agent gets its own line with a colored block prefix for visual
    separation. Uses ANSI cursor control to overwrite previous render.

    Returns:
        Multi-line status string, or empty string if no agents are active.

    """
    global _spinner_tick, _last_render_lines
    _spinner_tick += 1

    with _agents_lock:
        if not _active_agents:
            return ""

        n_agents = len(_active_agents)

        # Move cursor up to overwrite previous render
        output = ""
        if _last_render_lines > 0:
            for _ in range(_last_render_lines - 1):
                output += CURSOR_UP
            output += "\r"

        lines = []
        for idx, (agent_id, state) in enumerate(_active_agents.items()):
            bg = BG_COLORS[idx % len(BG_COLORS)]
            # Each agent gets its own spinner phase (offset by index)
            spinner = SPINNER[(_spinner_tick + idx * 2) % len(SPINNER)]
            elapsed = int(time.perf_counter() - state["start_time"])
            model = state["model"]

            tag = state.get("provider_tag", "")
            label = f"{tag} {model}" if tag else model

            if state["status"] == "waiting":
                info = f"{spinner} {label}: {elapsed}s..."
            else:
                in_tok = state["in_tokens"]
                out_tok = state["out_tokens"]
                info = f"{spinner} {label}: {elapsed}s, in≈{in_tok}, out≈{out_tok}"

            # Colored block prefix + text + clear to end of line
            lines.append(f"{bg}  {RESET} {info}{CLEAR_EOL}")

        output += "\n".join(lines)
        _last_render_lines = n_agents

        return output


class _SpinnerClearFilter(logging.Filter):
    """Logging filter that clears the spinner progress line before log output.

    When active agents are registered (spinner is rendering), any log message
    would interleave with the spinner on stdout. This filter clears the spinner
    line before each log message so it appears on its own clean line.
    The spinner redraws on its next tick.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if _active_agents:  # Quick check without lock for performance
            clear_progress_line()
        return True


def install_log_intercept() -> None:
    """Install spinner-aware filter on all root logger handlers.

    Call this after logging is configured (e.g., after basicConfig).
    When the progress spinner is active, log messages will automatically
    clear the spinner line before printing.
    """
    filt = _SpinnerClearFilter()
    for handler in logging.root.handlers:
        handler.addFilter(filt)
