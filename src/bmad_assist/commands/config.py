"""Config command group for bmad-assist.

Provides interactive configuration wizard and verification commands:
- `bmad-assist config wizard`: Interactive setup with arrow-key navigation
- `bmad-assist config verify`: Validate existing configuration files

Example:
    $ bmad-assist config wizard
    $ bmad-assist config verify
    $ bmad-assist config verify --config ~/my-project/bmad-assist.yaml
"""

import logging
from pathlib import Path

import typer
from rich.console import Console

from bmad_assist.cli_utils import EXIT_CONFIG_ERROR, EXIT_ERROR, EXIT_SUCCESS

logger = logging.getLogger(__name__)

config_app = typer.Typer(
    name="config",
    help="Configuration management commands",
    no_args_is_help=True,
)

# Shared console for output
console = Console()


@config_app.command(name="wizard")
def wizard_command(
    project: Path = typer.Option(
        Path("."),
        "--project",
        "-p",
        help="Path to project directory (default: current directory)",
    ),
) -> None:
    """Interactive configuration wizard with arrow-key navigation.

    Guides through provider/model selection using scrollable lists.
    Creates a valid bmad-assist.yaml configuration file.

    Exits with code 0 on success, 1 on non-interactive environment,
    130 on user cancellation (Ctrl+C).
    """
    from bmad_assist.core.config_generator import run_config_wizard

    project_path = project.resolve()

    # Ensure project directory exists
    if not project_path.exists():
        console.print(f"[red]Error:[/red] Directory does not exist: {project_path}")
        raise typer.Exit(code=EXIT_ERROR)

    if not project_path.is_dir():
        console.print(f"[red]Error:[/red] Not a directory: {project_path}")
        raise typer.Exit(code=EXIT_ERROR)

    try:
        config_path = run_config_wizard(project_path, console)
        logger.info("Config wizard completed: %s", config_path)
    except typer.Exit:
        # Re-raise typer exits (already handled with correct codes)
        raise
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled[/yellow]")
        raise typer.Exit(code=130) from None
    except OSError as e:
        console.print(f"[red]Error saving configuration:[/red] {e}")
        raise typer.Exit(code=EXIT_CONFIG_ERROR) from None


@config_app.command(name="verify")
def verify_command(
    config: Path = typer.Argument(
        None,
        help="Path to config file (default: ./bmad-assist.yaml)",
    ),
) -> None:
    """Verify configuration file for errors and warnings.

    Checks YAML syntax, required fields, provider names, and settings paths.
    Shows [OK], [WARN], or [ERR] status for each check.

    Exits with code 0 if valid (warnings allowed), 1 if errors found.
    """
    from bmad_assist.core.config_validator import format_validation_report, validate_config_file

    # Default to bmad-assist.yaml in current directory
    if config is None:
        config = Path("bmad-assist.yaml")

    config_path = config.resolve()

    if not config_path.exists():
        console.print(f"[red][ERR][/red] Config file not found: {config_path}")
        raise typer.Exit(code=EXIT_CONFIG_ERROR)

    if not config_path.is_file():
        console.print(f"[red][ERR][/red] Not a file: {config_path}")
        raise typer.Exit(code=EXIT_CONFIG_ERROR)

    # Run validation
    results = validate_config_file(config_path)

    # Format and display report
    report, has_errors = format_validation_report(results, config_path)
    console.print(report)

    # Exit with appropriate code
    if has_errors:
        raise typer.Exit(code=EXIT_CONFIG_ERROR)
    raise typer.Exit(code=EXIT_SUCCESS)
