"""Shared progress indicator for parallel provider execution.

This module provides a unified progress display for multiple LLM providers
running in parallel. Each provider registers itself and updates its state,
while a single background task renders all active providers on one line
with colored backgrounds.

Example output (wide terminal):
    ⠋ claude-sonnet-4.5: 5s, in≈1000, out≈200   ⠹ GPT-5.2: 3s...

Example output (narrow terminal - compact mode):
    ⠋ sonnet:5s,200   ⠹ 5.2:3s,0

Features:
- Thread-safe registration/update via threading.Lock
- Per-agent spinner animation (phase offset by index)
- Auto-compact mode when line exceeds terminal width
- ANSI background colors for visual separation
- Clear-to-EOL to prevent ghost characters
- Shared render task management across providers

Usage:
    from bmad_assist.providers.progress import (
        register_agent, update_agent, unregister_agent, render_all_agents,
        get_render_task, set_render_task, get_agents_lock
    )

    # Register when starting
    color_idx = register_agent("abc123", "claude-sonnet", start_time)

    # Update during streaming
    update_agent("abc123", in_tokens=100, out_tokens=50, status="streaming")

    # Unregister when done
    unregister_agent("abc123")

"""

from __future__ import annotations

import asyncio
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

# Shared state
_active_agents: dict[str, dict] = {}  # agent_id -> state dict
_agents_lock = threading.Lock()
_spinner_tick = 0
_render_task: asyncio.Task | None = None  # Single shared render task


def register_agent(agent_id: str, model: str, start_time: float) -> int:
    """Register an agent and return its color index.

    Args:
        agent_id: Unique identifier for this agent instance.
        model: Model name to display (e.g., "claude-sonnet-4.5").
        start_time: Start time from time.perf_counter().

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
    """Clear the current progress line and move cursor to start.

    Call this after all agents are done to remove the spinner display.
    """
    # Overwrite with spaces and return to start
    try:
        term_width = shutil.get_terminal_size().columns
    except Exception:
        term_width = 120
    sys.stdout.write("\r" + " " * (term_width - 1) + "\r")
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


async def run_spinner(done_event: asyncio.Event) -> None:
    """Run the shared spinner render loop until done_event is set.

    This function should be called as an asyncio task. It renders all
    active agents every 333ms (3 updates per second).

    Args:
        done_event: asyncio.Event that signals when to stop rendering.

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
    """Render all active agents into a single status line, truncated to terminal width.

    Returns:
        Status line starting with \\r for carriage return, or empty string if
        no agents are active.

    """
    global _spinner_tick
    _spinner_tick += 1

    with _agents_lock:
        if not _active_agents:
            return ""

        # Get terminal width for truncation
        try:
            term_width = shutil.get_terminal_size().columns
        except Exception:
            term_width = 120  # Fallback

        parts = []
        for idx, (agent_id, state) in enumerate(_active_agents.items()):
            bg = BG_COLORS[idx % len(BG_COLORS)]
            # Each agent gets its own spinner phase (offset by index)
            spinner = SPINNER[(_spinner_tick + idx * 2) % len(SPINNER)]
            elapsed = int(time.perf_counter() - state["start_time"])
            model = state["model"]

            if state["status"] == "waiting":
                text = f" {spinner} {model}: {elapsed}s... "
            else:
                in_tok = state["in_tokens"]
                out_tok = state["out_tokens"]
                text = f" {spinner} {model}: {elapsed}s, in≈{in_tok}, out≈{out_tok} "

            parts.append(f"{bg}{text}{RESET}")

        line = "\r" + " ".join(parts)

        # Calculate visible length (exclude ANSI escape codes)
        visible_len = sum(len(p) - len(BG_COLORS[0]) - len(RESET) for p in parts) + len(parts) - 1

        # If too wide, use compact format
        if visible_len > term_width - 5:
            parts = []
            for idx, (agent_id, state) in enumerate(_active_agents.items()):
                bg = BG_COLORS[idx % len(BG_COLORS)]
                spinner = SPINNER[(_spinner_tick + idx * 2) % len(SPINNER)]
                elapsed = int(time.perf_counter() - state["start_time"])
                # Shorter model name (last part only)
                model = state["model"]
                if "-" in model:
                    model = model.split("-")[-1]
                else:
                    model = model[:8]
                out_tok = state["out_tokens"]
                text = f" {spinner} {model}:{elapsed}s,{out_tok} "
                parts.append(f"{bg}{text}{RESET}")
            line = "\r" + " ".join(parts)

        return line + CLEAR_EOL
