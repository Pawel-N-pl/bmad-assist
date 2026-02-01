"""Shared CLI utilities for bmad-assist.

This module contains exit codes, console singleton, and helper functions
shared across CLI command modules.
"""

import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler

# Exit codes following Unix conventions
EXIT_SUCCESS: int = 0
EXIT_ERROR: int = 1  # General error (file not found, etc.)
EXIT_CONFIG_ERROR: int = 2  # Configuration/usage error (compile, etc.)
EXIT_WARNING: int = 2  # Success with warnings (run/init - workflows skipped)
EXIT_SIGINT: int = 130  # 128 + SIGINT (2) - Interrupted by Ctrl+C
EXIT_SIGTERM: int = 143  # 128 + SIGTERM (15) - Terminated by kill signal

# Compiler exit codes (starting at 10 to avoid collision with existing CLI codes)
# Existing: EXIT_SUCCESS=0, EXIT_ERROR=1, EXIT_CONFIG_ERROR=2, EXIT_SIGINT=130, EXIT_SIGTERM=143
EXIT_PARSER_ERROR: int = 10  # ParserError - file parsing issues
EXIT_VARIABLE_ERROR: int = 11  # VariableError - variable resolution issues
EXIT_AMBIGUOUS_ERROR: int = 12  # AmbiguousFileError - multiple file matches
EXIT_COMPILER_ERROR: int = 13  # CompilerError - general compilation error
EXIT_FRAMEWORK_ERROR: int = 14  # BmadAssistError - unexpected framework error
EXIT_TOKEN_BUDGET_ERROR: int = 15  # TokenBudgetError - prompt too large

# Patch exit codes (story 10.12)
EXIT_PATCH_ERROR: int = 16  # PatchError - general patch compilation error
EXIT_PATCH_VALIDATION_ERROR: int = 17  # Validation failure after retries

# TTY detection for Rich markup
# When stdout is piped, Rich automatically strips ANSI codes
_is_tty = sys.stdout.isatty()

# Rich console for output
console = Console(force_terminal=_is_tty, no_color=not _is_tty)

# Module logger
logger = logging.getLogger(__name__)


def _error(message: str) -> None:
    """Display error message with red styling.

    Args:
        message: Error message to display.

    """
    console.print(f"[red]Error:[/red] {message}")


def _info(message: str) -> None:
    """Display info message with blue styling.

    Args:
        message: Info message to display.

    """
    console.print(f"[blue]Info:[/blue] {message}")


def _success(message: str) -> None:
    """Display success message with green styling.

    Args:
        message: Success message to display.

    """
    console.print(f"[green]✓[/green] {message}")


def _warning(message: str) -> None:
    """Display warning message with yellow styling.

    Args:
        message: Warning message to display.

    """
    console.print(f"[yellow]Warning:[/yellow] {message}")


def format_duration_cli(seconds: float) -> str:
    """Format duration for CLI output.

    Uses human-friendly format: Xh Ym Zs, Ym Zs, or Zs.

    Args:
        seconds: Duration in seconds.

    Returns:
        Human-readable duration string.

    """
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def _setup_logging(verbose: bool, quiet: bool) -> None:
    """Configure logging based on verbosity flags.

    Args:
        verbose: If True, set DEBUG level.
        quiet: If True, set ERROR level.

    Note:
        verbose and quiet are mutually exclusive. If both are True,
        verbose takes precedence.

        Default log level is WARNING (changed from INFO to reduce noise).
        Phase banners are always shown regardless of log level.

    """
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.ERROR
    else:
        level = logging.WARNING  # Changed from INFO to reduce log noise

    # Clear any existing handlers to avoid duplicates
    logging.root.handlers.clear()

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )

    # Suppress HTTP client loggers (security: prevent secret leakage)
    # These loggers can expose sensitive URLs (Telegram bot tokens, Discord webhooks)
    for logger_name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _validate_project_path(project: str) -> Path:
    """Validate and resolve project path.

    Args:
        project: Path to project directory.

    Returns:
        Resolved absolute Path.

    Raises:
        typer.Exit: If path doesn't exist or isn't a directory.

    """
    project_path = Path(project).resolve()

    if not project_path.exists():
        _error(f"Project directory not found: {project}")
        raise typer.Exit(code=EXIT_ERROR)

    if not project_path.is_dir():
        _error(f"Project path must be a directory, got file: {project}")
        raise typer.Exit(code=EXIT_ERROR)

    return project_path


def _get_benchmarks_dir(project_path: Path) -> Path:
    """Get benchmarks directory, using paths singleton if available.

    Args:
        project_path: Project root path.

    Returns:
        Path to benchmarks directory.

    """
    try:
        from bmad_assist.core.paths import get_paths

        return get_paths().benchmarks_dir
    except RuntimeError:
        # Paths not initialized - use legacy location
        return project_path / "docs" / "sprint-artifacts" / "benchmarks"


def _get_output_folder(project_path: Path) -> Path:
    """Get output folder, using paths singleton if available.

    Args:
        project_path: Project root path.

    Returns:
        Path to output folder.

    """
    try:
        from bmad_assist.core.paths import get_paths

        return get_paths().output_folder
    except RuntimeError:
        # Paths not initialized - use legacy location
        return project_path / "docs"
