"""Typer CLI entry point for bmad-assist.

This module provides the command-line interface for bmad-assist.
It only parses arguments and delegates to core/loop.py - no business logic here.
"""

import logging
import os
from pathlib import Path

import typer

from bmad_assist.bmad import read_project_state
from bmad_assist.cli_start_point import apply_start_point_override
from bmad_assist.cli_utils import (
    EXIT_CONFIG_ERROR,
    EXIT_ERROR,
    EXIT_SIGINT,
    EXIT_SIGTERM,
    EXIT_SUCCESS,
    EXIT_WARNING,
    _error,
    _info,
    _setup_logging,
    _success,
    _validate_project_path,
    _warning,
    console,
)
from bmad_assist.core.config import (
    GLOBAL_CONFIG_PATH,
    PROJECT_CONFIG_NAME,
    Config,
    load_config_with_project,
)
from bmad_assist.core.config_generator import run_config_wizard
from bmad_assist.core.exceptions import ConfigError
from bmad_assist.core.io import get_original_cwd
from bmad_assist.core.loop import LoopExitReason, run_loop
from bmad_assist.core.loop.interactive import set_non_interactive, set_skip_story_prompts
from bmad_assist.core.paths import init_paths
from bmad_assist.core.state import Phase, get_state_path, load_state, save_state, update_position
from bmad_assist.core.types import EpicId, epic_sort_key, parse_epic_id

# Module logger
logger = logging.getLogger(__name__)


app = typer.Typer(
    name="bmad-assist",
    help="CLI tool for automating BMAD methodology development loop",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """CLI tool for automating BMAD methodology development loop."""
    if ctx.invoked_subcommand is None:
        # Show help when no subcommand is provided
        raise typer.Exit()


def _load_epic_data(
    config: Config, project_path: Path
) -> tuple[list[EpicId], dict[EpicId, list[str]]]:
    """Load epic list and story mapping from BMAD files.

    Reads project state from BMAD documentation and extracts:
    - Sorted list of unique epic numbers
    - Mapping of epic number to list of story IDs

    Args:
        config: Loaded configuration with bmad_paths.
        project_path: Path to project root directory.

    Returns:
        Tuple of (epic_list, stories_by_epic) where:
        - epic_list: Sorted list of epic numbers [1, 2, 3, ...]
        - stories_by_epic: Dict mapping epic -> story IDs {1: ["1.1", "1.2"], ...}

    Raises:
        FileNotFoundError: If BMAD docs directory doesn't exist.

    """
    # Use paths singleton which auto-discovers epics location
    from bmad_assist.core.paths import get_paths

    paths = get_paths()
    # project_knowledge resolves to planning_artifacts or docs/ fallback
    bmad_path = paths.project_knowledge

    logger.debug("Loading BMAD project state from: %s", bmad_path)

    # Read project state (handles both sharded and single-file patterns, and sprint-status)
    project_state = read_project_state(bmad_path, use_sprint_status=True)

    # Extract unique epic numbers from stories
    # CRITICAL: Only include NON-DONE stories to prevent premature RETROSPECTIVE trigger
    # When all stories in epic are done, epic should transition to RETROSPECTIVE
    epic_numbers: set[EpicId] = set()
    stories_by_epic: dict[EpicId, list[str]] = {}

    for story in project_state.all_stories:
        # Skip stories that are already done - they should not be in the active list
        if story.status == "done":
            continue

        epic_part = story.number.split(".")[0]
        epic_id = parse_epic_id(epic_part)  # Supports int and string epic IDs
        epic_numbers.add(epic_id)

        if epic_id not in stories_by_epic:
            stories_by_epic[epic_id] = []
        stories_by_epic[epic_id].append(story.number)

    epic_list = sorted(epic_numbers, key=epic_sort_key)

    logger.info(
        "Loaded %d epics with %d total stories",
        len(epic_list),
        len(project_state.all_stories),
    )

    return epic_list, stories_by_epic


def _handle_debug_vars(config: Config, project_path: Path) -> None:
    """Display resolved variables for current phase without running LLM.

    Args:
        config: Loaded configuration.
        project_path: Project root path.

    """
    import xml.etree.ElementTree as ET

    from bmad_assist.compiler import compile_workflow
    from bmad_assist.compiler.types import CompilerContext
    from bmad_assist.core.state import get_state_path, load_state

    # Load current state (from project directory)
    state_path = get_state_path(config, project_root=project_path)
    try:
        state = load_state(state_path)
    except Exception as e:
        _error(f"Cannot load state: {e}")
        return

    # Get workflow name from phase
    if state.current_phase is None:
        _error("No current phase set in state")
        return

    workflow_name = state.current_phase.value.replace("_", "-")
    console.print(f"[bold]Phase:[/bold] {workflow_name}")
    console.print(f"[bold]Epic:[/bold] {state.current_epic}")
    console.print(f"[bold]Story:[/bold] {state.current_story}")
    console.print()

    # Extract story number
    story_num = state.current_story
    if story_num and "." in story_num:
        story_num = story_num.split(".")[-1]

    # Build compiler context
    # Use get_original_cwd() to preserve original CWD when running as subprocess
    from bmad_assist.core.paths import get_paths

    paths = get_paths()
    context = CompilerContext(
        project_root=project_path,
        output_folder=paths.output_folder,
        project_knowledge=paths.project_knowledge,
        cwd=get_original_cwd(),
        resolved_variables={
            "epic_num": state.current_epic,
            "story_num": story_num,
        },
    )

    try:
        result = compile_workflow(workflow_name, context)
    except Exception as e:
        _error(f"Cannot compile workflow: {e}")
        return

    # Extract variables from XML
    try:
        root = ET.fromstring(result.context)
        vars_el = root.find("variables")
        if vars_el is not None:
            console.print("[bold]Resolved Variables:[/bold]")
            for var in vars_el:
                name = var.get("name", "?")
                value = var.text or ""
                # Truncate long values
                if len(value) > 100:
                    value = value[:100] + "..."
                console.print(f"  {name}: [dim]{value}[/dim]")
        else:
            console.print("[yellow]No variables found in compiled output[/yellow]")
    except ET.ParseError as e:
        _error(f"Cannot parse compiled XML: {e}")

    console.print()
    console.print(f"[dim]Token estimate: ~{result.token_estimate:,}[/dim]")


def _config_exists(project_path: Path, global_config_path: Path | None) -> bool:
    """Check if any configuration file exists.

    Args:
        project_path: Path to project directory.
        global_config_path: Custom global config path, or None for default.

    Returns:
        True if either global or project config exists.

    """
    # Check global config
    resolved_global = global_config_path if global_config_path is not None else GLOBAL_CONFIG_PATH
    if resolved_global.exists() and resolved_global.is_file():
        return True

    # Check project config
    project_config = project_path / PROJECT_CONFIG_NAME
    return project_config.exists() and project_config.is_file()


@app.command()
def run(
    project: str = typer.Option(
        ".",
        "--project",
        "-p",
        help="Path to the project directory",
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file (defaults to ~/.bmad-assist/config.yaml)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show INFO-level logs (phase progress, provider status)",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress non-error output (only show errors and final result)",
    ),
    no_interactive: bool = typer.Option(
        False,
        "--no-interactive",
        "-n",
        help="Disable interactive prompts (fail if config missing)",
    ),
    skip_story_prompts: bool = typer.Option(
        False,
        "--skip-story-prompts",
        help="Skip continuation prompts between stories (but still prompt at epic boundaries)",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug JSONL logging to ~/.bmad-assist/debug/json/",
    ),
    debug_links: bool = typer.Option(
        False,
        "--debug-links",
        help="Show file paths only in compiled prompts (implies --debug)",
    ),
    debug_vars: bool = typer.Option(
        False,
        "--debug-vars",
        help="Show resolved variables only (no LLM execution)",
    ),
    full_stream: bool = typer.Option(
        False,
        "--full-stream",
        help="Show full untruncated LLM stream output (requires --debug or --stream)",
    ),
    stream: str | None = typer.Option(
        None,
        "--stream",
        help="Enable LLM streaming at --verbose level: 'preview' (spinner only), "
        "'text' (spinner + per-agent text preview), or 'full' (all output). "
        "Also accepts a number (e.g. '300') to set preview character limit.",
    ),
    stream_chars: int | None = typer.Option(
        None,
        "--stream-chars",
        help="Characters to show in stream preview mode (default: 150, min: 10)",
    ),
    disable_compiler: bool = typer.Option(
        False,
        "--disable-compiler",
        help="Use legacy YAML handlers instead of compiled prompts",
    ),
    git_commit: bool = typer.Option(
        False,
        "--git",
        "-g",
        help="Auto-commit changes after create-story, dev-story, code-review-synthesis phases",
    ),
    epic: str | None = typer.Option(
        None,
        "--epic",
        "-e",
        help="Start from specified epic (e.g., '22' or 'testarch'). Overrides state.yaml.",
    ),
    story: str | None = typer.Option(
        None,
        "--story",
        "-s",
        help="Start from specified story (e.g., '3' for story 22-3). Requires --epic.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force restart if story is 'done'. Otherwise prompts/auto-skips.",
    ),
    phase_override: str | None = typer.Option(
        None,
        "--phase",
        help="Override starting phase. Requires --epic/--story. See docs for values.",
    ),
    qa_enabled: bool = typer.Option(
        False,
        "--qa",
        hidden=True,  # Experimental feature - not documented yet
        help="Enable QA phases (qa-plan-generate, qa-plan-execute) after retrospective.",
    ),
    csv_output: bool = typer.Option(
        False,
        "--csv",
        help="Export run logs as CSV in addition to YAML (.bmad-assist/runs/)",
    ),
    tea: bool = typer.Option(
        False,
        "--tea",
        help="Enable full TEA (Test Architect Enterprise) loop with all phases",
    ),
) -> None:
    """Execute the main BMAD development loop.

    Loads configuration, validates project path, and delegates to the main loop.
    If no configuration exists and interactive mode is enabled, launches the
    setup wizard to create one.
    """
    # Validate mutually exclusive flags
    if verbose and quiet:
        _warning("Both --verbose and --quiet specified, --verbose takes precedence")

    # Process debug flags (--debug-links implies --debug)
    debug_jsonl = debug or debug_links

    # Setup logging: --debug = DEBUG, --verbose = INFO, default = WARNING
    _setup_logging(verbose, quiet, debug=debug_jsonl)

    # Stream output configuration
    from bmad_assist.providers.base import set_stream_mode

    # Parse --stream flag: 'preview', 'text', 'full', or a number for preview chars
    stream_verbose = False
    stream_full_from_flag = False
    stream_text_preview = False
    preview_chars_from_flag: int | None = stream_chars

    if stream is not None:
        stream_lower = stream.strip().lower()
        if stream_lower == "full":
            stream_verbose = True
            stream_full_from_flag = True
        elif stream_lower == "text":
            stream_verbose = True
            stream_text_preview = True
        elif stream_lower == "preview":
            stream_verbose = True
        elif stream_lower.isdigit():
            stream_verbose = True
            preview_chars_from_flag = int(stream_lower)
        else:
            _warning(f"Unknown --stream value '{stream}', expected 'preview', 'text', 'full', or a number")

    if full_stream and not debug_jsonl and not stream_verbose:
        _warning("--full-stream has no effect without --debug or --stream")

    set_stream_mode(
        enabled=debug_jsonl,
        full=full_stream or stream_full_from_flag,
        verbose=stream_verbose,
        preview_chars=preview_chars_from_flag,
    )

    # Enable text preview in spinner if --stream text
    if stream_text_preview:
        from bmad_assist.providers.progress import set_text_preview
        set_text_preview(True)

    if stream_verbose:
        if stream_text_preview:
            mode = "text"
        elif full_stream or stream_full_from_flag:
            mode = "full"
        else:
            mode = "preview"
        console.print(f"[dim]Stream: {mode} mode enabled[/dim]")

    # Set non-interactive mode if -n flag is passed
    # This must be set early, before any interactive prompts can occur
    if no_interactive:
        set_non_interactive(True)

    # Set skip-story-prompts mode if flag is passed
    if skip_story_prompts:
        set_skip_story_prompts(True)

    # Set environment variables for flags
    if debug_jsonl:
        console.print("[dim]Debug: JSONL logs → ~/.bmad-assist/debug/json/[/dim]")
    if debug_links:
        os.environ["BMAD_DEBUG_LINKS"] = "1"
        console.print("[dim]Debug: showing file paths only (no content)[/dim]")
    if debug_vars:
        os.environ["BMAD_DEBUG_VARS"] = "1"
        console.print("[dim]Debug: showing variables only (no LLM)[/dim]")
    if disable_compiler:
        os.environ["BMAD_FORCE_YAML"] = "1"
        console.print("[dim]Compiler disabled: using legacy YAML handlers[/dim]")
    if git_commit:
        os.environ["BMAD_GIT_COMMIT"] = "1"
        console.print("[dim]Git: auto-commit enabled after phases[/dim]")
    if qa_enabled:
        os.environ["BMAD_QA_ENABLED"] = "1"
        console.print("[dim]QA: E2E test phases enabled after retrospective[/dim]")
    if csv_output:
        os.environ["BMAD_CSV_OUTPUT"] = "1"
        console.print("[dim]Run logs: CSV export enabled[/dim]")
    if tea:
        os.environ["BMAD_TEA_LOOP"] = "1"
        console.print("[dim]TEA: Full Test Architect Enterprise loop enabled[/dim]")

    try:
        # Validate project path
        project_path = _validate_project_path(project)
        logger.debug("Project path resolved to: %s", project_path)

        # Early branch switch: ensure correct branch BEFORE loading any state files
        # This MUST happen before sprint-status.yaml and state.yaml are read,
        # otherwise we read stale data from the wrong branch
        if git_commit and epic:
            from bmad_assist.core.types import parse_epic_id
            from bmad_assist.git.branch import ensure_epic_branch, is_git_enabled

            epic_id = parse_epic_id(epic.strip())
            if is_git_enabled():
                logger.info("Early branch switch to epic-%s before loading state", epic_id)
                if not ensure_epic_branch(epic_id, project_path):
                    _warning(
                        f"Could not switch to branch epic-{epic_id}, continuing on current branch"
                    )

        # Prepare global config path
        global_config_path: Path | None = None
        if config is not None:
            global_config_path = Path(config).expanduser()
            logger.debug("Using custom config path: %s", global_config_path)

        # Check if config exists; if not, handle based on interactive mode
        if not _config_exists(project_path, global_config_path):
            if no_interactive:
                _error("No configuration found. Run without --no-interactive for setup wizard.")
                raise typer.Exit(code=EXIT_CONFIG_ERROR)

            # Run interactive wizard
            logger.debug("No config found, launching setup wizard...")
            try:
                run_config_wizard(project_path, console)
            except KeyboardInterrupt:
                _warning("Setup cancelled by user")
                raise typer.Exit(code=EXIT_ERROR) from None
            except EOFError:
                _warning("Setup cancelled - no input available")
                raise typer.Exit(code=EXIT_ERROR) from None
            except OSError as e:
                # Config generation failure = EXIT_CONFIG_ERROR per story requirements
                _error(f"Failed to save configuration: {e}")
                raise typer.Exit(code=EXIT_CONFIG_ERROR) from None
            # SystemExit from wizard rejection propagates naturally

        # Load configuration (includes .env loading per Story 1.5)
        # When --config is explicitly provided, disable CWD tier to avoid interference
        logger.debug("Loading configuration...")
        loaded_config = load_config_with_project(
            project_path=project_path,
            global_config_path=global_config_path,
            cwd_config_path=False if config is not None else None,
        )
        logger.debug("Configuration loaded successfully")

        # Apply config-based stream settings (CLI flags override config)
        if stream is None and not debug_jsonl:
            # No CLI stream flags — apply config defaults
            stream_cfg = loaded_config.stream
            if stream_cfg.mode != "off":
                cfg_verbose = True
                cfg_full = stream_cfg.mode == "full"
                cfg_preview = stream_chars if stream_chars is not None else stream_cfg.preview_chars
                set_stream_mode(
                    enabled=False,
                    full=cfg_full,
                    verbose=cfg_verbose,
                    preview_chars=cfg_preview,
                )
                mode_label = "full" if cfg_full else f"preview ({cfg_preview} chars)"
                console.print(f"[dim]Stream: {mode_label} (from config)[/dim]")

        # Initialize project paths singleton
        paths_config: dict[str, str | None] = {
            "output_folder": loaded_config.paths.output_folder,
            "planning_artifacts": loaded_config.paths.planning_artifacts,
            "implementation_artifacts": loaded_config.paths.implementation_artifacts,
            "project_knowledge": loaded_config.paths.project_knowledge,
        }
        # Add bmad_paths.epics if configured (supports custom epic locations)
        if loaded_config.bmad_paths and loaded_config.bmad_paths.epics:
            paths_config["epics"] = loaded_config.bmad_paths.epics
        project_paths = init_paths(project_path, paths_config)
        project_paths.ensure_directories()
        logger.debug("Project paths initialized: %s", project_paths)

        # Implicit project setup (without gitignore modification)
        from bmad_assist.core.project_setup import check_gitignore_warning, ensure_project_setup

        setup_result = ensure_project_setup(
            project_path,
            include_gitignore=False,  # run never modifies gitignore
            force=no_interactive,  # In non-interactive, skip differing files silently
            console=console if not quiet else None,
        )

        # Show gitignore warning (respects config)
        if not quiet:
            check_gitignore_warning(project_path, loaded_config, console)

        # CI-friendly: warn about skipped files
        if setup_result.has_skipped:
            skipped_count = len(setup_result.workflows_skipped)
            _warning(f"{skipped_count} workflow(s) skipped (local differs from bundled)")
            if no_interactive:
                _info("Run interactively or use 'bmad-assist init --reset-workflows' to update")

        # Validate sprint-status.yaml exists - auto-generate if missing
        sprint_path = project_paths.find_sprint_status()
        if sprint_path is None:
            # Auto-generate sprint-status from epic files
            _warning("sprint-status.yaml not found - generating from epic files...")
            try:
                from bmad_assist.sprint import (
                    ArtifactIndex,
                    SprintStatus,
                    generate_from_epics,
                    reconcile,
                    write_sprint_status,
                )

                # Create empty sprint-status
                existing = SprintStatus.empty(project=project_path.name)

                # Generate entries from epic files
                generated = generate_from_epics(project_path, auto_exclude_legacy=True)

                if generated.entries:
                    # Reconcile and write
                    index = ArtifactIndex()
                    reconciliation = reconcile(existing, generated, index)
                    output_path = project_paths.sprint_status_file
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    write_sprint_status(reconciliation.status, output_path, preserve_comments=True)
                    entry_count = len(reconciliation.status.entries)
                    _success(f"Generated sprint-status.yaml with {entry_count} entries")
                    console.print(f"  Output: {output_path}")
                    # Re-find the sprint path now that it exists
                    sprint_path = project_paths.find_sprint_status()
                else:
                    _error("No epic files found to generate sprint-status!")
                    _error("Ensure your project has epic files in docs/epics/")
                    raise typer.Exit(code=EXIT_ERROR)
            except ImportError as e:
                _error(f"Failed to import sprint module: {e}")
                raise typer.Exit(code=EXIT_ERROR) from None
            except Exception as e:
                _error(f"Failed to generate sprint-status: {e}")
                raise typer.Exit(code=EXIT_ERROR) from None

        # Initialize notification dispatcher (optional - only if config.notifications set)
        from bmad_assist.notifications.dispatcher import init_dispatcher

        init_dispatcher(loaded_config.notifications)

        # Load epic list and story mapping from BMAD files
        try:
            epic_list, stories_by_epic = _load_epic_data(loaded_config, project_path)
        except FileNotFoundError as e:
            _error(f"BMAD documentation not found: {e}")
            _error("Ensure your project has a docs/ directory with epics.md")
            raise typer.Exit(code=EXIT_ERROR) from None

        def epic_stories_loader(epic: EpicId) -> list[str]:
            """Return story IDs for given epic number."""
            return stories_by_epic.get(epic, [])

        # Validate: --story requires --epic
        if story and not epic:
            _error("--story requires --epic")
            raise typer.Exit(code=EXIT_CONFIG_ERROR)

        # Validate --phase
        if phase_override and not epic:
            _error("--phase requires --epic")
            raise typer.Exit(code=EXIT_CONFIG_ERROR)

        # For epic-level phases (teardown/setup), --story is optional.
        # For story-level phases, --story is required.
        _is_epic_level_phase = False
        if phase_override:
            try:
                _override_phase_check = Phase(phase_override)
            except ValueError:
                valid_phases = [p.value for p in Phase]
                _error(f"Invalid phase '{phase_override}'. Valid values: {', '.join(valid_phases)}")
                raise typer.Exit(code=EXIT_CONFIG_ERROR) from None

            from bmad_assist.core.config import load_loop_config

            _lc = load_loop_config(project_path)
            _epic_phases = set(_lc.epic_setup) | set(_lc.epic_teardown)
            _is_epic_level_phase = phase_override in _epic_phases

            if not _is_epic_level_phase and not story:
                _error(f"--phase {phase_override} is a story-level phase and requires --story")
                raise typer.Exit(code=EXIT_CONFIG_ERROR)

        # Apply start point override if --epic specified
        if epic:
            # Use project_knowledge for BMAD files - same as _load_epic_data()
            # epics_dir.parent would fail for monolithic epics.md in docs/
            apply_start_point_override(
                loaded_config,
                project_path,
                project_paths.project_knowledge,
                epic,
                story,
                epic_list,
                stories_by_epic,
                force,
            )

        # Apply phase override if --phase specified (overrides status-derived phase)
        if phase_override:
            override_phase = Phase(phase_override)

            state_path = get_state_path(loaded_config, project_root=project_path)
            state = load_state(state_path)

            # For epic-level phases without --story, ensure we have a valid story
            # in state (use last story from the epic)
            if _is_epic_level_phase and not story and state.current_story is None:
                # epic is guaranteed non-None (validated above)
                assert epic is not None
                resolved_epic = parse_epic_id(epic.strip())
                epic_story_list = stories_by_epic.get(resolved_epic, [])
                if epic_story_list:
                    last_story = epic_story_list[-1]
                    update_position(state, story=last_story)
                    logger.debug("Auto-selected last story %s for epic-level phase", last_story)

            update_position(state, phase=override_phase)
            save_state(state, state_path)
            console.print(f"[dim]Phase override: starting from {override_phase.value}[/dim]")

        # Handle debug vars mode - display variables and exit without LLM
        if debug_vars:
            _handle_debug_vars(loaded_config, project_path)
            raise typer.Exit(code=EXIT_SUCCESS)

        # Delegate to main loop
        exit_reason = run_loop(loaded_config, project_path, epic_list, epic_stories_loader)

        # Story 6.6: Handle exit reasons from run_loop
        if exit_reason == LoopExitReason.INTERRUPTED_SIGINT:
            _warning("Loop interrupted by Ctrl+C, state saved")
            raise typer.Exit(code=EXIT_SIGINT)
        elif exit_reason == LoopExitReason.INTERRUPTED_SIGTERM:
            _warning("Loop terminated by kill signal, state saved")
            raise typer.Exit(code=EXIT_SIGTERM)
        elif exit_reason == LoopExitReason.GUARDIAN_HALT:
            # Phase failed - error already logged above, just exit with error code
            raise typer.Exit(code=EXIT_ERROR)

        # COMPLETED exit reason - show success message
        # Final success message always shown (AC11 - quiet mode shows final result)
        _success("Completed successfully")

        # Exit with code 2 if workflows were skipped (CI warning)
        if setup_result.has_skipped:
            raise typer.Exit(code=EXIT_WARNING)

    except ConfigError as e:
        _error(str(e))
        raise typer.Exit(code=EXIT_CONFIG_ERROR) from None
    except typer.Exit:
        # Re-raise typer exits (already handled)
        raise
    except Exception as e:
        _error(f"Unexpected error: {e}")
        if verbose:
            console.print_exception()
        raise typer.Exit(code=EXIT_ERROR) from None


# ============================================================================
# Reset Lock Command
# ============================================================================


@app.command(name="reset-lock")
def reset_lock_command(
    project: Path = typer.Option(
        Path("."),
        "--project",
        "-p",
        help="Path to project directory (default: current directory)",
        exists=False,  # Don't require directory to exist - we'll check for lock file
    ),
) -> None:
    """Remove stale running.lock file to allow new runs.

    Use this when bmad-assist reports another run is active but
    the process has actually terminated (stale lock).
    """
    from bmad_assist.core.loop.locking import _is_pid_alive, _read_lock_file

    # Resolve project path
    project_path = project.resolve()
    lock_path = project_path / ".bmad-assist" / "running.lock"

    if not lock_path.exists():
        _info(f"No lock file found at {lock_path}")
        raise typer.Exit(code=EXIT_SUCCESS)

    # Read lock file to report what we're removing
    pid, timestamp = _read_lock_file(lock_path)

    # Check if process is actually alive
    if pid is not None and _is_pid_alive(pid):
        _warning(f"Process {pid} is still running! Lock file is valid.")
        _warning("If you're sure no bmad-assist run is active, use --force (not implemented yet)")
        raise typer.Exit(code=EXIT_WARNING)

    # Remove the lock file
    try:
        lock_path.unlink()
        if pid is not None:
            _success(f"Removed stale lock file (PID {pid}, locked at {timestamp})")
        else:
            _success(f"Removed lock file at {lock_path}")
    except OSError as e:
        _error(f"Failed to remove lock file: {e}")
        raise typer.Exit(code=EXIT_ERROR) from None


# ============================================================================
# Register commands from commands/ modules
# ============================================================================

from bmad_assist.commands.compile import compile_command  # noqa: E402
from bmad_assist.commands.init import init_command  # noqa: E402
from bmad_assist.commands.serve import serve_command  # noqa: E402

# Register standalone commands
app.command(name="compile")(compile_command)
app.command(name="serve")(serve_command)
app.command(name="init")(init_command)

# Register sub-apps (command groups)
from bmad_assist.commands.benchmark import benchmark_app  # noqa: E402
from bmad_assist.commands.config import config_app  # noqa: E402
from bmad_assist.commands.experiment import experiment_app  # noqa: E402
from bmad_assist.commands.patch import patch_app  # noqa: E402
from bmad_assist.commands.qa import qa_app  # noqa: E402
from bmad_assist.commands.sprint import sprint_app  # noqa: E402
from bmad_assist.commands.test import test_app  # noqa: E402
from bmad_assist.commands.verify import verify_app  # noqa: E402
from bmad_assist.testarch.standalone.cli import tea_app  # noqa: E402

app.add_typer(config_app, name="config")
app.add_typer(patch_app, name="patch")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(sprint_app, name="sprint")
app.add_typer(experiment_app, name="experiment")
app.add_typer(qa_app, name="qa")
app.add_typer(test_app, name="test")
app.add_typer(verify_app, name="verify")
app.add_typer(tea_app, name="tea")


if __name__ == "__main__":
    app()
