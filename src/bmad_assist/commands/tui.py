"""CLI commands for TUI management.

Provides `bmad-assist tui` subcommand group with:
- connect (default): Launch TUI process connected to a runner
- list: Show running instances
- reset: Emergency terminal restoration
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer

from bmad_assist.cli_utils import EXIT_ERROR, EXIT_SUCCESS, _error, _info, _success, console

tui_app = typer.Typer(
    help="Interactive TUI for monitoring and controlling bmad-assist runners",
    invoke_without_command=True,
)


@tui_app.callback(invoke_without_command=True)
def tui_default(
    ctx: typer.Context,
    project: str | None = typer.Option(None, "--project", "-p", help="Project path or name"),
    socket: Path | None = typer.Option(None, "--socket", "-s", help="Socket path to connect to"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Show LLM session details"),
) -> None:
    """Launch TUI (default: auto-connect to running instance)."""
    if ctx.invoked_subcommand is not None:
        return
    # Default action: connect
    _do_connect(project=project, socket=socket, debug=debug)


@tui_app.command(name="connect")
def connect_command(
    project: str | None = typer.Option(None, "--project", "-p", help="Project path or name"),
    socket: Path | None = typer.Option(None, "--socket", "-s", help="Socket path to connect to"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Show LLM session details"),
) -> None:
    """Connect to a running bmad-assist instance with interactive TUI."""
    _do_connect(project=project, socket=socket, debug=debug)


def _do_connect(
    project: str | None = None,
    socket: Path | None = None,
    debug: bool = False,
) -> None:
    """Internal connect implementation."""
    # Check TTY
    if sys.stdin is None or not sys.stdin.isatty():
        _error("TUI requires an interactive terminal")
        raise typer.Exit(code=EXIT_ERROR)

    # Build command
    cmd = [sys.executable, "-m", "bmad_assist.tui.app"]
    if socket:
        cmd.extend(["--socket", str(socket)])
    if project:
        cmd.extend(["--project", project])
    if debug:
        cmd.append("--debug")

    try:
        proc = subprocess.Popen(cmd, close_fds=True)
        proc.wait()
        raise typer.Exit(code=proc.returncode or 0)
    except FileNotFoundError:
        _error("Failed to launch TUI process")
        raise typer.Exit(code=EXIT_ERROR) from None
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None


@tui_app.command(name="list")
def list_command() -> None:
    """List running bmad-assist instances."""
    from rich.table import Table

    from bmad_assist.ipc.discovery import discover_instances

    instances = discover_instances()
    if not instances:
        _info("No running bmad-assist instances found")
        raise typer.Exit(code=EXIT_SUCCESS)

    table = Table(title="Running Instances")
    table.add_column("Project", style="cyan")
    table.add_column("Path", style="white")
    table.add_column("State", style="bold")
    table.add_column("PID", style="yellow")
    table.add_column("Socket", style="dim")

    for inst in instances:
        name = (
            inst.state.get("project_name", inst.project_hash[:12])
            if inst.state
            else inst.project_hash[:12]
        )
        path = inst.state.get("project_path", "?") if inst.state else "?"
        state = inst.state.get("state", "?") if inst.state else "?"
        table.add_row(
            str(name),
            str(path),
            str(state),
            str(inst.pid) if inst.pid else "N/A",
            str(inst.socket_path),
        )

    console.print(table)
    raise typer.Exit(code=EXIT_SUCCESS)


@tui_app.command(name="reset")
def reset_command() -> None:
    """Reset terminal after TUI crash (emergency recovery)."""
    os.system("stty sane 2>/dev/null")  # noqa: S605, S607
    # Print reset escape sequences
    sys.stdout.write("\033c")  # RIS - Reset to Initial State
    sys.stdout.write("\033[?25h")  # Show cursor
    sys.stdout.flush()
    _success("Terminal reset complete")
    raise typer.Exit(code=EXIT_SUCCESS)
