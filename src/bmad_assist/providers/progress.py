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

import logging
import os
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
DIM = "\033[2m"  # Dim/faint text for text preview lines
CLEAR_EOL = "\033[K"  # Clear from cursor to end of line

CURSOR_UP = "\033[A"  # Move cursor up one line

# Shared state
_active_agents: dict[str, dict] = {}  # agent_id -> state dict
_agents_lock = threading.Lock()
_spinner_tick = 0
_last_render_lines = 0  # Number of lines rendered in last draw
_spinner_stop = threading.Event()  # Signals spinner thread to stop
_spinner_thread: threading.Thread | None = None  # Background spinner thread
_show_text_preview: bool = False  # Show latest streamed text per agent


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
            "last_text": "",  # Latest streamed text snippet for preview
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

    Thread-safe: acquires _agents_lock to coordinate with the spinner
    thread's stdout writes and _last_render_lines access.
    """
    with _agents_lock:
        _clear_progress_unlocked()


def print_completion(agent_id: str, model: str, elapsed_secs: int, out_tokens: int) -> None:
    """Print a completion message for an agent.

    Args:
        agent_id: Agent identifier (unused, for consistency).
        model: Model name that completed.
        elapsed_secs: Total elapsed time in seconds.
        out_tokens: Estimated output tokens.

    """
    with _agents_lock:
        _clear_progress_unlocked()
        sys.stdout.write(f"\033[32m✓\033[0m {model}: {elapsed_secs}s, ~{out_tokens} tokens\n")
        sys.stdout.flush()


def print_error(model: str, message: str) -> None:
    """Print an error message for an agent, clearing the spinner first.

    Args:
        model: Model name that errored.
        message: Short error description.

    """
    with _agents_lock:
        _clear_progress_unlocked()
        sys.stdout.write(f"\033[31m✗\033[0m {model}: {message}\n")
        sys.stdout.flush()


def _clear_progress_unlocked() -> None:
    """Clear all rendered progress lines (caller MUST hold _agents_lock)."""
    global _last_render_lines
    if _last_render_lines <= 0:
        sys.stdout.write("\r" + CLEAR_EOL)
        sys.stdout.flush()
        return
    lines_to_clear = _last_render_lines
    _last_render_lines = 0
    output = ""
    for _ in range(lines_to_clear - 1):
        output += CURSOR_UP
    output += "\r"
    for i in range(lines_to_clear):
        output += CLEAR_EOL
        if i < lines_to_clear - 1:
            output += "\n"
    for _ in range(lines_to_clear - 1):
        output += CURSOR_UP
    output += "\r"
    sys.stdout.write(output)
    sys.stdout.flush()


def render_all_agents() -> str:
    """Render all active agents (public wrapper, acquires lock).

    Returns:
        Multi-line status string, or empty string if no agents are active.

    """
    with _agents_lock:
        return _render_all_agents_unlocked()


def get_active_count() -> int:
    """Return number of currently active agents."""
    with _agents_lock:
        return len(_active_agents)


def get_agents_lock() -> threading.Lock:
    """Return the agents lock for external synchronization."""
    return _agents_lock


def set_text_preview(enabled: bool) -> None:
    """Enable or disable text preview in the spinner display.

    When enabled, each agent's spinner line includes a second line showing
    a truncated preview of the latest streamed text, fitting within the
    terminal width.

    Args:
        enabled: True to show text previews, False for stats only.

    """
    global _show_text_preview
    _show_text_preview = enabled


def is_text_preview() -> bool:
    """Check if text preview mode is enabled."""
    return _show_text_preview


def ensure_spinner_running() -> None:
    """Start the shared spinner thread if not already running.

    Safe to call from multiple agents in different threads — only the
    first call creates the thread.  The spinner runs until
    stop_spinner_if_last() is called by the last active agent.

    Uses a daemon thread so it won't prevent process exit.
    """
    global _spinner_thread, _spinner_stop
    with _agents_lock:
        if _spinner_thread is not None and _spinner_thread.is_alive():
            return  # Already running
        _spinner_stop = threading.Event()
        _spinner_thread = threading.Thread(
            target=_spinner_loop, args=(_spinner_stop,), daemon=True
        )
        _spinner_thread.start()


def stop_spinner_if_last() -> None:
    """Stop the shared spinner if this is the last active agent.

    Should be called AFTER unregister_agent() so that get_active_count()
    reflects the removal.  If other agents are still running, this is a
    no-op and the spinner keeps going.

    Clears the final spinner render after stopping the thread so no
    ghost lines remain on screen.

    This is a synchronous call (no await needed).
    """
    global _spinner_thread
    with _agents_lock:
        if len(_active_agents) > 0:
            return  # Other agents still running
    # No lock needed for stop/join — only one thread can be "last"
    _spinner_stop.set()
    if _spinner_thread is not None:
        _spinner_thread.join(timeout=2)
        _spinner_thread = None
    # Clear final render (lock released, safe to re-acquire in clear_progress_line)
    clear_progress_line()


def _spinner_loop(stop_event: threading.Event) -> None:
    """Background thread that renders all active agents every 333ms.

    Holds _agents_lock while building AND writing render output to stdout.
    This prevents interleaving with clear_progress_line() and log filter
    clear operations, which also acquire the lock before writing.

    Args:
        stop_event: threading.Event that signals when to stop rendering.

    """
    while not stop_event.is_set():
        stop_event.wait(timeout=0.333)
        if stop_event.is_set():
            break
        # Lock covers both render and stdout write to prevent interleaving
        with _agents_lock:
            status = _render_all_agents_unlocked()
            if status:
                sys.stdout.write(status)
                sys.stdout.flush()


def _render_all_agents_unlocked() -> str:
    """Render all active agents (caller MUST hold _agents_lock).

    Each agent gets its own line with a colored block prefix for visual
    separation. Uses ANSI cursor control to overwrite previous render.

    When text preview is enabled, each agent gets an additional line
    showing the latest streamed text, truncated to the terminal width.

    Returns:
        Multi-line status string, or empty string if no agents are active.

    """
    global _spinner_tick, _last_render_lines
    _spinner_tick += 1

    if not _active_agents:
        return ""

    # Get terminal width for text preview truncation
    try:
        term_width = shutil.get_terminal_size().columns
    except Exception:
        term_width = 80

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

        # Text preview line (optional, enabled via set_text_preview)
        if _show_text_preview:
            last_text = state.get("last_text", "")
            if last_text:
                # Prefix: 5 chars for "   > " indent under the colored block
                prefix = f"   {DIM}> "
                suffix = RESET + CLEAR_EOL
                # Available width for text: terminal width minus prefix/suffix overhead
                # prefix visible chars = 5 ("   > "), suffix has no visible chars
                max_text = term_width - 6
                if max_text < 20:
                    max_text = 20
                # Sanitize: replace newlines, collapse whitespace
                preview = last_text.replace("\n", " ").replace("\r", "")
                if len(preview) > max_text:
                    preview = "…" + preview[-(max_text - 1):]
                lines.append(f"{prefix}{preview}{suffix}")
            else:
                # Empty text line placeholder so line count stays consistent
                lines.append(f"   {DIM}> waiting...{RESET}{CLEAR_EOL}")

    total_lines = len(lines)
    output += "\n".join(lines)
    _last_render_lines = total_lines

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
