"""Patch subcommand group for bmad-assist CLI.

Commands for workflow patch compilation and management.
"""

from pathlib import Path

import typer

from bmad_assist.cli_utils import (
    EXIT_ERROR,
    EXIT_PATCH_ERROR,
    EXIT_PATCH_VALIDATION_ERROR,
    _error,
    _setup_logging,
    _validate_project_path,
    console,
)
from bmad_assist.core.config import load_config_with_project
from bmad_assist.core.exceptions import ConfigError, PatchError
from bmad_assist.core.paths import init_paths

patch_app = typer.Typer(
    name="patch",
    help="Workflow patch compilation commands",
    no_args_is_help=True,
)


def _find_workflow_files(workflow: str, project_root: Path) -> tuple[Path, Path]:
    """Find workflow.yaml and instructions.xml for a workflow.

    Searches in _bmad/bmm/workflows/*/{workflow}/ (new) or .bmad/bmm/workflows/*/{workflow}/ (legacy).

    Args:
        workflow: Workflow name (e.g., "create-story").
        project_root: Project root directory.

    Returns:
        Tuple of (workflow_yaml_path, instructions_xml_path).

    Raises:
        PatchError: If workflow files not found.

    """
    # Try new structure first (_bmad/), then legacy (.bmad/)
    bmad_dirs = [
        project_root / "_bmad" / "bmm" / "workflows",
        project_root / ".bmad" / "bmm" / "workflows",
    ]

    for bmad_dir in bmad_dirs:
        if not bmad_dir.exists():
            continue

        # Search in phase subdirectories
        for phase_dir in bmad_dir.iterdir():
            if not phase_dir.is_dir():
                continue
            workflow_dir = phase_dir / workflow
            if workflow_dir.exists():
                workflow_yaml = workflow_dir / "workflow.yaml"
                instructions_xml = workflow_dir / "instructions.xml"

                if not workflow_yaml.exists():
                    raise PatchError(f"workflow.yaml not found in {workflow_dir}")
                if not instructions_xml.exists():
                    raise PatchError(f"instructions.xml not found in {workflow_dir}")

                return workflow_yaml, instructions_xml

    raise PatchError(
        f"Workflow '{workflow}' not found.\n"
        f"  Searched in: {project_root}/_bmad/bmm/workflows/*/{workflow}/\n"
        f"  And legacy:  {project_root}/.bmad/bmm/workflows/*/{workflow}/"
    )


def compile_patch(
    workflow: str,
    project_root: Path,
    debug: bool = False,
    cwd: Path | None = None,
) -> tuple[str, Path, int]:
    """Compile a workflow patch into a template.

    Delegates to the centralized compile_patch() in compiler.patching.compiler.

    Args:
        workflow: Workflow name to compile.
        project_root: Project root directory.
        debug: Whether to enable debug logging.
        cwd: Current working directory (for CWD-based patch/cache discovery).

    Returns:
        Tuple of (compiled_content, output_path, warning_count).

    Raises:
        PatchError: If compilation fails.

    """
    from bmad_assist.compiler.patching import compile_patch as _compile_patch

    return _compile_patch(workflow, project_root, cwd=cwd, debug=debug)


def list_patches(project_root: Path) -> list[dict[str, str | None]]:
    """List all available patches and their status.

    Args:
        project_root: Project root directory.

    Returns:
        List of patch info dicts with keys:
        workflow, version, status, last_compiled.

    """
    from bmad_assist.compiler.patching import TemplateCache

    # Search for patch files
    patches = []
    cache = TemplateCache()

    # Check project patches directory
    project_patches = project_root / ".bmad-assist" / "patches"
    if project_patches.exists():
        for patch_file in project_patches.glob("*.patch.yaml"):
            workflow = patch_file.stem.replace(".patch", "")

            # Try to load patch for version info
            try:
                from bmad_assist.compiler.patching import load_patch

                patch = load_patch(patch_file)
                version = patch.config.version
            except Exception:
                version = "unknown"

            # Check cache status - use per-workflow meta file to avoid collision
            cache_path = cache.get_cache_path(workflow, project_root)
            meta_path = cache_path.with_suffix(cache_path.suffix + ".meta.yaml")

            if cache_path.exists() and meta_path.exists():
                # Cache exists - check if valid
                try:
                    import yaml

                    with meta_path.open() as f:
                        meta = yaml.safe_load(f)
                    status = "compiled"
                    last_compiled = meta.get("compiled_at")
                except Exception:
                    status = "stale"
                    last_compiled = None
            else:
                status = "missing"
                last_compiled = None

            patches.append(
                {
                    "workflow": workflow,
                    "version": version,
                    "status": status,
                    "last_compiled": last_compiled,
                }
            )

    # Also check global patches
    global_patches = Path.home() / ".bmad-assist" / "patches"
    if global_patches.exists():
        for patch_file in global_patches.glob("*.patch.yaml"):
            workflow = patch_file.stem.replace(".patch", "")
            # Skip if already found in project
            if any(p["workflow"] == workflow for p in patches):
                continue

            try:
                from bmad_assist.compiler.patching import load_patch

                patch = load_patch(patch_file)
                version = patch.config.version
            except Exception:
                version = "unknown"

            # Use per-workflow meta file to avoid collision
            cache_path = cache.get_cache_path(workflow, None)  # Global cache
            meta_path = cache_path.with_suffix(cache_path.suffix + ".meta.yaml")

            if cache_path.exists() and meta_path.exists():
                try:
                    import yaml

                    with meta_path.open() as f:
                        meta = yaml.safe_load(f)
                    status = "compiled"
                    last_compiled = meta.get("compiled_at")
                except Exception:
                    status = "stale"
                    last_compiled = None
            else:
                status = "missing"
                last_compiled = None

            patches.append(
                {
                    "workflow": workflow,
                    "version": version,
                    "status": status,
                    "last_compiled": last_compiled,
                }
            )

    return patches


@patch_app.command("compile")
def patch_compile(
    workflow: str = typer.Option(
        ...,
        "--workflow",
        "-w",
        help="Workflow to compile (e.g., 'create-story')",
    ),
    project: str = typer.Option(
        ".",
        "--project",
        "-p",
        help="Path to project directory",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable verbose output and JSONL debug logging",
    ),
) -> None:
    """Compile a workflow patch into an optimized template.

    Loads the patch definition for the specified workflow and applies
    transforms via LLM to produce an optimized template.
    """
    # Validate project path
    project_path = _validate_project_path(project)

    # Enable debug logging if requested (enables JSONL debug output)
    if debug:
        _setup_logging(verbose=True, quiet=False)
        console.print("[dim]Debug mode enabled - logs saved to ~/.bmad-assist/debug/json/[/dim]")

    # Load configuration (required for provider access)
    try:
        loaded_config = load_config_with_project(project_path=project_path)
        # Initialize project paths singleton
        paths_config = {
            "output_folder": loaded_config.paths.output_folder,
            "planning_artifacts": loaded_config.paths.planning_artifacts,
            "implementation_artifacts": loaded_config.paths.implementation_artifacts,
            "project_knowledge": loaded_config.paths.project_knowledge,
        }
        init_paths(project_path, paths_config)
    except ConfigError as e:
        console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(code=EXIT_ERROR) from None

    try:
        content, output_path, warnings = compile_patch(workflow, project_path, debug)

        if warnings > 0:
            console.print(f"Compiled: {output_path} (warnings: {warnings} transforms failed)")
        else:
            console.print(f"Compiled: {output_path}")

    except PatchError as e:
        # Check if it's a validation error
        is_validation_error = getattr(e, "is_validation_error", False)
        _error(str(e))
        if is_validation_error:
            raise typer.Exit(code=EXIT_PATCH_VALIDATION_ERROR) from None
        raise typer.Exit(code=EXIT_PATCH_ERROR) from None


@patch_app.command("list")
def patch_list(
    project: str = typer.Option(
        ".",
        "--project",
        "-p",
        help="Path to project directory",
    ),
) -> None:
    """List available patches and their compilation status.

    Shows a table of all discovered patches with their version,
    compilation status, and last compiled timestamp.
    """
    from rich.table import Table

    # Validate project path
    project_path = _validate_project_path(project)

    patches = list_patches(project_path)

    if not patches:
        console.print("No patches found.")
        return

    # Create Rich table
    table = Table(title="Workflow Patches")
    table.add_column("Workflow", style="cyan")
    table.add_column("Patch Version", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Last Compiled", style="dim")

    for p in patches:
        # Format status with color
        status = p["status"]
        if status == "compiled":
            status_str = "[green]compiled[/green]"
        elif status == "stale":
            status_str = "[yellow]stale[/yellow]"
        else:
            status_str = "[red]missing[/red]"

        last_compiled = p["last_compiled"] or "-"

        table.add_row(
            p["workflow"],
            p["version"],
            status_str,
            last_compiled,
        )

    console.print(table)


@patch_app.command("compile-all")
def patch_compile_all(
    project: str = typer.Option(
        ".",
        "--project",
        "-p",
        help="Path to project directory",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable verbose output and JSONL debug logging",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Recompile all patches even if cache is valid",
    ),
) -> None:
    """Compile all patches that don't have a valid cache.

    Discovers all patches in project and global directories, checks their
    cache status, and compiles those with missing or stale cache.
    """
    # Validate project path
    project_path = _validate_project_path(project)

    # Enable debug logging if requested
    if debug:
        _setup_logging(verbose=True, quiet=False)
        console.print("[dim]Debug mode enabled - logs saved to ~/.bmad-assist/debug/json/[/dim]")

    # Load configuration (required for provider access)
    try:
        loaded_config = load_config_with_project(project_path=project_path)
        # Initialize project paths singleton
        paths_config = {
            "output_folder": loaded_config.paths.output_folder,
            "planning_artifacts": loaded_config.paths.planning_artifacts,
            "implementation_artifacts": loaded_config.paths.implementation_artifacts,
            "project_knowledge": loaded_config.paths.project_knowledge,
        }
        init_paths(project_path, paths_config)
    except ConfigError as e:
        console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(code=EXIT_ERROR) from None

    # Get all patches with their status
    patches = list_patches(project_path)

    if not patches:
        console.print("No patches found.")
        return

    # Filter patches that need compilation
    if force:
        to_compile = patches
    else:
        to_compile = [p for p in patches if p["status"] in ("missing", "stale")]

    if not to_compile:
        console.print("[green]All patches are up to date.[/green]")
        return

    console.print(f"Found {len(to_compile)} patch(es) to compile:")
    for p in to_compile:
        console.print(f"  - {p['workflow']} ({p['status']})")
    console.print()

    # Compile each patch
    compiled = 0
    errors: list[tuple[str, str]] = []

    for p in to_compile:
        workflow = p["workflow"]
        if workflow is None:
            continue  # Skip entries without workflow name
        console.print(f"Compiling [cyan]{workflow}[/cyan]...", end=" ")

        try:
            _, _, warnings = compile_patch(workflow, project_path, debug)

            if warnings > 0:
                console.print(f"[yellow]done[/yellow] (warnings: {warnings})")
            else:
                console.print("[green]done[/green]")
            compiled += 1

        except PatchError as e:
            console.print("[red]error[/red]")
            errors.append((workflow, str(e)))

    # Summary
    console.print()
    console.print("[bold]Summary:[/bold]")
    console.print(f"  Compiled: [green]{compiled}[/green]")
    if errors:
        console.print(f"  Errors:   [red]{len(errors)}[/red]")
        for workflow, error in errors:
            console.print(f"    - {workflow}: {error[:80]}...")

    if errors:
        raise typer.Exit(code=EXIT_PATCH_ERROR)
