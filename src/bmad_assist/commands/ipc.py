"""CLI commands for IPC socket management.

Story 29.6: `bmad-assist ipc cleanup` and `bmad-assist ipc list` commands
for managing orphaned IPC socket files.
Story 29.8: `bmad-assist ipc status` command for instance discovery and
state inspection.
Story 29.11: `bmad-assist ipc pause/resume/stop/log-level/reload` commands
for remote runner control.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from bmad_assist.ipc.client import SyncSocketClient

from rich.table import Table

from bmad_assist.cli_utils import (
    EXIT_SUCCESS,
    _error,
    _info,
    _success,
    _warning,
    console,
)

ipc_app = typer.Typer(help="IPC socket management utilities")


@ipc_app.command(name="cleanup")
def cleanup_command(
    force: bool = typer.Option(
        False,
        "--force",
        help="Also remove sockets that fail connect probe even if PID appears alive",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="List orphaned sockets without removing them",
    ),
) -> None:
    """Remove orphaned IPC socket files.

    Scans ~/.bmad-assist/sockets/ for stale socket files left by crashed
    or killed bmad-assist processes and removes them.
    """
    from bmad_assist.ipc.cleanup import (
        cleanup_orphaned_sockets,
        find_orphaned_sockets,
    )
    from bmad_assist.ipc.protocol import SOCKET_DIR

    socket_dir = SOCKET_DIR.expanduser()
    if not socket_dir.exists():
        _info("No socket directory found (nothing to clean)")
        raise typer.Exit(code=EXIT_SUCCESS)

    # Find orphaned sockets (basic scan: dead PIDs and missing lock files)
    orphans = find_orphaned_sockets()

    if not orphans and not force:
        _info("No orphaned sockets found")
        raise typer.Exit(code=EXIT_SUCCESS)

    # Display table of orphaned sockets (if any found by basic scan)
    if orphans:
        table = Table(title="Orphaned Sockets")
        table.add_column("Socket", style="cyan")
        table.add_column("PID", style="yellow")
        table.add_column("Reason", style="red")

        for sock_path, pid, reason in orphans:
            table.add_row(
                sock_path.name,
                str(pid) if pid is not None else "N/A",
                reason,
            )

        console.print(table)

    if dry_run:
        if orphans:
            _info(f"Found {len(orphans)} orphaned socket(s) (dry-run, not removing)")
        else:
            _info("No dead-PID orphans found (use --force to probe live-PID sockets)")
        raise typer.Exit(code=EXIT_SUCCESS)

    # Remove orphaned sockets (force=True also probes live-PID sockets)
    cleaned = cleanup_orphaned_sockets(force=force)

    if cleaned:
        _success(f"Removed {len(cleaned)} orphaned socket(s)")
    elif force:
        _info("No orphaned sockets found (all live-PID sockets responded to probe)")
    else:
        _warning("No sockets were removed (use --force to remove connect-failed sockets)")

    raise typer.Exit(code=EXIT_SUCCESS)


@ipc_app.command(name="list")
def list_command(
    probe: bool = typer.Option(
        False,
        "--probe",
        help="Probe active sockets for runner state (adds latency)",
    ),
) -> None:
    """List all IPC socket files with their status.

    Shows all socket files in ~/.bmad-assist/sockets/ with their
    status (active/stale), PID, project hash, and lock file age.

    With --probe: additionally connects to each active socket to query
    runner state (idle/running/paused/stopping).
    """
    import asyncio

    from bmad_assist.ipc.cleanup import is_socket_stale, read_socket_pid
    from bmad_assist.ipc.protocol import SOCKET_DIR

    socket_dir = SOCKET_DIR.expanduser()
    if not socket_dir.exists():
        _info("No socket directory found")
        raise typer.Exit(code=EXIT_SUCCESS)

    sock_files = sorted(socket_dir.glob("*.sock"))
    if not sock_files:
        _info("No socket files found")
        raise typer.Exit(code=EXIT_SUCCESS)

    # If probing, discover instances to get their state
    probed_states: dict[str, str] = {}  # socket_name -> runner state
    if probe:
        from bmad_assist.ipc.discovery import discover_instances_async

        try:
            instances = asyncio.run(discover_instances_async(probe_timeout=2.0))
            for inst in instances:
                state_val = inst.state.get("state", "?") if inst.state else "?"
                probed_states[inst.socket_path.name] = state_val
        except (OSError, RuntimeError):
            pass  # Probe failure — continue without state info

    table = Table(title="IPC Sockets")
    table.add_column("Socket", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("PID", style="yellow")
    table.add_column("Hash", style="dim")
    table.add_column("State", style="white")
    table.add_column("Age", style="dim")

    for sock_path in sock_files:
        lock_path = Path(f"{sock_path}.lock")
        pid = read_socket_pid(lock_path)
        project_hash = sock_path.stem  # filename without .sock

        # Determine status
        stale = is_socket_stale(sock_path)
        status = "[red]stale[/red]" if stale else "[green]active[/green]"

        # Determine state (from probe or dash)
        if probe:
            if stale:
                state_str = "–"
            elif sock_path.name in probed_states:
                state_str = probed_states[sock_path.name]
            else:
                state_str = "?"
        else:
            state_str = "–"

        # Calculate age from lock file mtime
        age_str = "N/A"
        if lock_path.exists():
            try:
                mtime = lock_path.stat().st_mtime
                age_seconds = max(0, datetime.now(UTC).timestamp() - mtime)
                if age_seconds < 60:
                    age_str = f"{int(age_seconds)}s"
                elif age_seconds < 3600:
                    age_str = f"{int(age_seconds / 60)}m"
                elif age_seconds < 86400:
                    age_str = f"{int(age_seconds / 3600)}h"
                else:
                    age_str = f"{int(age_seconds / 86400)}d"
            except OSError:
                age_str = "?"

        table.add_row(
            sock_path.name,
            status,
            str(pid) if pid is not None else "N/A",
            project_hash[:12] + "...",
            state_str,
            age_str,
        )

    console.print(table)
    raise typer.Exit(code=EXIT_SUCCESS)


@ipc_app.command(name="status")
def status_command(
    project: Path | None = typer.Option(
        None,
        "--project",
        help="Project path to query; if omitted, discovers all running instances",
    ),
) -> None:
    """Show status of running bmad-assist instances.

    With --project: connects to the specific project's runner and shows
    detailed state (runner state, epic, story, phase, elapsed time, etc.).

    Without --project: discovers ALL running instances and shows a summary
    table with status (active/stale/unreachable) for all socket files.
    """
    if project is not None:
        _status_single_project(project)
    else:
        _status_all_instances()
    raise typer.Exit(code=EXIT_SUCCESS)


def _format_elapsed(seconds: float, fallback: str = "–") -> str:
    """Format elapsed seconds as human-readable string.

    Args:
        seconds: Elapsed time in seconds.
        fallback: String to return for non-positive values.

    Returns:
        Formatted string like "1h 5m 30s" or the fallback.

    """
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return fallback
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def _format_runner_state(state_val: str) -> str:
    """Apply Rich color coding to runner state values.

    Args:
        state_val: Runner state string (running, paused, idle, stopping).

    Returns:
        Rich-formatted state string with color markup.

    """
    if state_val == "running":
        return "[green]running[/green]"
    elif state_val == "paused":
        return "[yellow]paused[/yellow]"
    elif state_val == "idle":
        return "[dim]idle[/dim]"
    elif state_val == "stopping":
        return "[red]stopping[/red]"
    return state_val


def _status_single_project(project: Path) -> None:
    """Show detailed status for a single project's runner."""
    import asyncio

    from bmad_assist.ipc.protocol import SOCKET_DIR, compute_project_hash

    # Avoid calling get_socket_path() which creates the directory as a
    # side effect via get_socket_dir(). Status is a read-only command.
    socket_dir = SOCKET_DIR.expanduser()
    project_hash = compute_project_hash(project)
    sock_path = socket_dir / f"{project_hash}.sock"

    if not sock_path.exists():
        _warning(f"No socket found for project: {project}")
        _info("Is a bmad-assist runner active for this project?")
        return

    # Probe the socket for state
    from bmad_assist.ipc.discovery import probe_instance

    state = asyncio.run(probe_instance(sock_path, timeout=5.0))
    if state is None:
        _warning(f"Socket exists but runner is not responding: {sock_path.name}")
        return

    # Display detailed state
    _info(f"Runner status for: {project}")
    console.print()

    table = Table(title="Runner State", show_header=False)
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")

    # Story 29.9: Show project identity when available
    project_name = state.get("project_name")
    project_path_str = state.get("project_path")
    if project_name:
        table.add_row("Project", project_name)
    if project_path_str:
        table.add_row("Path", project_path_str)

    table.add_row("State", state.get("state", "N/A"))
    table.add_row("Running", str(state.get("running", "N/A")))
    table.add_row("Paused", str(state.get("paused", "N/A")))
    table.add_row("Current Epic", str(state.get("current_epic", "N/A")))
    table.add_row("Current Story", str(state.get("current_story", "N/A")))
    table.add_row("Current Phase", str(state.get("current_phase", "N/A")))
    table.add_row("Elapsed", _format_elapsed(state.get("elapsed_seconds", 0.0), fallback="N/A"))
    table.add_row("LLM Sessions", str(state.get("llm_sessions", "N/A")))

    error = state.get("error")
    if error:
        table.add_row("Error", f"[red]{error}[/red]")

    console.print(table)


def _status_all_instances() -> None:
    """Show summary table of all socket files with health status.

    Shows ALL socket files (not just active ones) with status
    (active/stale/unreachable) per AC #4.
    """
    from bmad_assist.ipc.cleanup import is_socket_stale, read_socket_pid
    from bmad_assist.ipc.discovery import discover_instances
    from bmad_assist.ipc.protocol import SOCKET_DIR

    socket_dir = SOCKET_DIR.expanduser()
    if not socket_dir.exists():
        _info("No running bmad-assist instances found")
        return

    sock_files = sorted(socket_dir.glob("*.sock"))
    if not sock_files:
        _info("No running bmad-assist instances found")
        return

    # Discover active instances and index by socket name for lookup
    active_map = {
        inst.socket_path.name: inst for inst in discover_instances()
    }

    table = Table(title="Running Instances")
    table.add_column("Socket", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("PID", style="yellow")
    table.add_column("Project", style="white")
    table.add_column("State", style="white")
    table.add_column("Phase", style="white")
    table.add_column("Elapsed", style="dim")

    for sock_path in sock_files:
        lock_path = Path(f"{sock_path}.lock")
        inst = active_map.get(sock_path.name)
        pid = inst.pid if inst else read_socket_pid(lock_path)
        project_hash = sock_path.stem

        # Determine health status (AC #4: active/stale/unreachable)
        if inst is not None:
            status_display = "[green]active[/green]"
        elif is_socket_stale(sock_path):
            status_display = "[red]stale[/red]"
        else:
            # PID alive but probe failed — unreachable
            status_display = "[yellow]unreachable[/yellow]"

        # Extract state info from discovered instance (or defaults)
        if inst and inst.state:
            state_val = inst.state.get("state", "?")
            phase = inst.state.get("current_phase")
            elapsed = inst.state.get("elapsed_seconds", 0.0)
        else:
            state_val = "?" if inst is not None else "–"
            phase = None
            elapsed = 0.0

        # Story 29.9: Show project_name from state, fallback to hash prefix
        project_display = project_hash[:12] + "..."
        if inst and inst.state:
            pname = inst.state.get("project_name")
            if pname:
                project_display = pname

        phase_str = str(phase) if phase else "–"
        state_display = _format_runner_state(state_val) if state_val not in ("?", "–") else state_val

        table.add_row(
            sock_path.name,
            status_display,
            str(pid) if pid is not None else "N/A",
            project_display,
            state_display,
            phase_str,
            _format_elapsed(elapsed),
        )

    console.print(table)


# =============================================================================
# Story 29.11: IPC control commands (pause/resume/stop/log-level/reload)
# =============================================================================


def _connect_to_project(project: Path, timeout: float = 5.0) -> SyncSocketClient:
    """Connect to a project's runner via IPC.

    Args:
        project: Project root path.
        timeout: Connection timeout in seconds.

    Returns:
        Connected SyncSocketClient.

    Raises:
        typer.Exit: If connection fails (with user-friendly error message).

    """
    from bmad_assist.ipc.client import IPCConnectionError, SyncSocketClient
    from bmad_assist.ipc.protocol import SOCKET_DIR, compute_project_hash

    socket_dir = SOCKET_DIR.expanduser()
    project_hash = compute_project_hash(project)
    sock_path = socket_dir / f"{project_hash}.sock"

    if not sock_path.exists():
        _warning(f"No socket found for project: {project}")
        _info("Is a bmad-assist runner active for this project?")
        raise typer.Exit(code=1)

    client = SyncSocketClient(socket_path=sock_path)
    try:
        client.connect(timeout=timeout)
    except IPCConnectionError as e:
        _error(f"Cannot connect to runner: {e}")
        raise typer.Exit(code=1)

    return client


@ipc_app.command(name="pause")
def pause_command(
    project: Path = typer.Option(..., "--project", help="Project path to pause"),
) -> None:
    """Pause a running bmad-assist instance."""
    from bmad_assist.ipc.client import IPCCommandError

    client = _connect_to_project(project)
    try:
        result = client.pause()
        if result.was_already:
            _info("Runner was already paused")
        else:
            _success("Runner paused")
    except IPCCommandError as e:
        _error(f"Pause failed: {e.message}")
        raise typer.Exit(code=1)
    finally:
        client.disconnect()
    raise typer.Exit(code=EXIT_SUCCESS)


@ipc_app.command(name="resume")
def resume_command(
    project: Path = typer.Option(..., "--project", help="Project path to resume"),
) -> None:
    """Resume a paused bmad-assist instance."""
    from bmad_assist.ipc.client import IPCCommandError

    client = _connect_to_project(project)
    try:
        result = client.resume()
        if result.was_already:
            _info("Runner was already running")
        else:
            _success("Runner resumed")
    except IPCCommandError as e:
        _error(f"Resume failed: {e.message}")
        raise typer.Exit(code=1)
    finally:
        client.disconnect()
    raise typer.Exit(code=EXIT_SUCCESS)


@ipc_app.command(name="stop")
def stop_command(
    project: Path = typer.Option(..., "--project", help="Project path to stop"),
) -> None:
    """Stop a running bmad-assist instance."""
    from bmad_assist.ipc.client import IPCCommandError

    client = _connect_to_project(project)
    try:
        result = client.stop()
        if result.was_already:
            _info("Runner was already idle")
        else:
            _success("Runner stopped")
    except IPCCommandError as e:
        _error(f"Stop failed: {e.message}")
        raise typer.Exit(code=1)
    finally:
        client.disconnect()
    raise typer.Exit(code=EXIT_SUCCESS)


@ipc_app.command(name="log-level")
def log_level_command(
    project: Path = typer.Option(..., "--project", help="Project path"),
    level: str = typer.Option(
        ...,
        "--level",
        help="Log level to set (DEBUG/INFO/WARNING/ERROR/CRITICAL)",
    ),
) -> None:
    """Set the log level of a running bmad-assist instance."""
    from bmad_assist.ipc.client import IPCCommandError

    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    level_upper = level.upper()
    if level_upper not in valid_levels:
        _error(f"Invalid log level: {level}. Must be one of: {', '.join(sorted(valid_levels))}")
        raise typer.Exit(code=1)

    client = _connect_to_project(project)
    try:
        result = client.set_log_level(level_upper)  # type: ignore[arg-type]
        if result.changed:
            _success(f"Log level set to {result.level}")
        else:
            _info(f"Log level was already {result.level}")
    except IPCCommandError as e:
        _error(f"Set log level failed: {e.message}")
        raise typer.Exit(code=1)
    finally:
        client.disconnect()
    raise typer.Exit(code=EXIT_SUCCESS)


@ipc_app.command(name="reload")
def reload_command(
    project: Path = typer.Option(..., "--project", help="Project path to reload config for"),
) -> None:
    """Reload configuration of a running bmad-assist instance."""
    from bmad_assist.ipc.client import IPCCommandError

    client = _connect_to_project(project)
    try:
        result = client.reload_config()
        if result.reloaded:
            _success("Configuration reloaded")
        else:
            _info("Configuration reload completed (no changes)")

        if result.changes:
            console.print("\n[bold]Changes applied:[/bold]")
            for change in result.changes:
                console.print(f"  • {change}")

        if result.ignored:
            console.print("\n[yellow]Ignored (require restart):[/yellow]")
            for ignored in result.ignored:
                console.print(f"  • {ignored}")

        if result.warnings:
            console.print("\n[yellow]Warnings:[/yellow]")
            for warn_msg in result.warnings:
                console.print(f"  • {warn_msg}")
    except IPCCommandError as e:
        _error(f"Reload failed: {e.message}")
        raise typer.Exit(code=1)
    finally:
        client.disconnect()
    raise typer.Exit(code=EXIT_SUCCESS)
