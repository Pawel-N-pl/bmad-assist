"""Compile command for bmad-assist CLI.

Compiles BMAD workflows into standalone prompts.
"""

import os
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from bmad_assist.cli_utils import (
    EXIT_AMBIGUOUS_ERROR,
    EXIT_COMPILER_ERROR,
    EXIT_CONFIG_ERROR,
    EXIT_ERROR,
    EXIT_FRAMEWORK_ERROR,
    EXIT_PARSER_ERROR,
    EXIT_TOKEN_BUDGET_ERROR,
    EXIT_VARIABLE_ERROR,
    _error,
    _info,
    _setup_logging,
    _success,
    _validate_project_path,
    _warning,
    console,
)
from bmad_assist.compiler.output import DEFAULT_HARD_LIMIT_TOKENS
from bmad_assist.core.config import load_config_with_project
from bmad_assist.core.exceptions import (
    AmbiguousFileError,
    BmadAssistError,
    CompilerError,
    ConfigError,
    ParserError,
    TokenBudgetError,
    VariableError,
)
from bmad_assist.core.paths import init_paths
from bmad_assist.core.types import EpicId, parse_epic_id

# Epic-level workflows that don't require --story
EPIC_LEVEL_WORKFLOWS = {
    "qa-plan-execute",
    "retrospective",
    "testarch-trace",
    "testarch-atdd",
    "testarch-test-review",
    # New TEA workflows
    "testarch-automate",
    "testarch-ci",
    "testarch-framework",
    "testarch-nfr-assess",
    "testarch-test-design",
}

# Tri-modal workflows that support --mode flag
TRI_MODAL_WORKFLOWS = {
    "testarch-atdd",
    "testarch-trace",
    "testarch-test-review",
    "testarch-automate",
    "testarch-ci",
    "testarch-framework",
    "testarch-nfr-assess",
    "testarch-test-design",
}


def compile_command(
    workflow: str = typer.Option(
        ...,
        "--workflow",
        "-w",
        help="Workflow to compile (e.g., 'create-story', 'qa-plan-execute')",
    ),
    epic: str = typer.Option(
        ...,
        "--epic",
        "-e",
        help="Epic ID (numeric like '17' or string like 'testarch')",
    ),
    story: int | None = typer.Option(
        None,
        "--story",
        "-s",
        help="Story number within epic (required for story-level workflows)",
    ),
    category: str | None = typer.Option(
        None,
        "--category",
        "-c",
        help="Test category for qa-plan-execute (A, B, or all)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Custom output file path",
    ),
    project: str = typer.Option(
        ".",
        "--project",
        "-p",
        help="Path to project directory",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="Print to stdout instead of writing file",
    ),
    max_tokens: int = typer.Option(
        DEFAULT_HARD_LIMIT_TOKENS,
        "--max-tokens",
        "-m",
        help=f"Maximum token limit (default: {DEFAULT_HARD_LIMIT_TOKENS}, 0 to disable validation)",
    ),
    debug: str | None = typer.Option(
        None,
        "--debug",
        help="Debug mode: 'v|var|vars|variables' (show only variables), "
        "'l|link|links' (show file paths without content)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable debug output",
    ),
    mode: str | None = typer.Option(
        None,
        "--mode",
        help="Workflow mode for tri-modal workflows: c|create, v|validate, e|edit (default: create)",
    ),
) -> None:
    """Compile a BMAD workflow into a standalone prompt.

    Compiles the specified workflow with epic/story context into an XML prompt
    suitable for LLM consumption. Output can be written to a file or printed
    to stdout for piping.
    """
    # Import compiler lazily to avoid circular imports
    from bmad_assist.compiler import CompilerContext, compile_workflow

    # Setup logging if verbose
    if verbose:
        _setup_logging(verbose=True, quiet=False)

    is_epic_level = workflow in EPIC_LEVEL_WORKFLOWS

    # Validate epic
    if not epic.strip():
        _error("Epic ID cannot be empty")
        raise typer.Exit(code=EXIT_CONFIG_ERROR)

    # Validate story (required for story-level workflows)
    if not is_epic_level:
        if story is None:
            _error(
                f"--story is required for workflow '{workflow}'\n"
                f"  Epic-level workflows (no --story needed): {', '.join(sorted(EPIC_LEVEL_WORKFLOWS))}" # noqa: E501
            )
            raise typer.Exit(code=EXIT_CONFIG_ERROR)
        if story < 1:
            _error(f"Story number must be a positive integer (got: {story})")
            raise typer.Exit(code=EXIT_CONFIG_ERROR)

    # Parse epic ID (returns int if numeric, str otherwise)
    epic_id: EpicId = parse_epic_id(epic.strip())

    # Validate numeric epic IDs are positive
    if isinstance(epic_id, int) and epic_id < 1:
        _error(f"Epic number must be a positive integer (got: {epic_id})")
        raise typer.Exit(code=EXIT_CONFIG_ERROR)

    if max_tokens < 0:
        _error(f"--max-tokens must be >= 0 (got: {max_tokens})")
        raise typer.Exit(code=EXIT_CONFIG_ERROR)

    # Parse debug mode
    debug_mode: str | None = None
    links_only = False
    if debug:
        debug_lower = debug.lower().strip()
        if debug_lower in ("v", "var", "vars", "variables"):
            debug_mode = "variables"
        elif debug_lower in ("l", "link", "links"):
            debug_mode = "links"
            links_only = True
        else:
            _error(
                f"Invalid --debug value: '{debug}'\n"
                f"  Valid options: v|var|vars|variables, l|link|links"
            )
            raise typer.Exit(code=EXIT_ERROR)

    # Validate and normalize mode flag
    normalized_mode: str | None = None
    if mode:
        # Normalize mode name
        from bmad_assist.compiler.tri_modal import normalize_mode

        try:
            normalized_mode = normalize_mode(mode)
        except CompilerError as e:
            _error(str(e))
            raise typer.Exit(code=EXIT_CONFIG_ERROR) from None

        # Check if workflow supports modes
        if workflow not in TRI_MODAL_WORKFLOWS:
            _error(
                f"--mode flag is not supported for workflow '{workflow}'\n"
                f"  Tri-modal workflows: {', '.join(sorted(TRI_MODAL_WORKFLOWS))}"
            )
            raise typer.Exit(code=EXIT_CONFIG_ERROR)

    # Validate project path
    project_path = _validate_project_path(project)

    # Load configuration (needed for patch compilation if patch exists)
    try:
        loaded_config = load_config_with_project(project_path=project_path)
        # Initialize project paths singleton
        paths_config = {
            "output_folder": loaded_config.paths.output_folder,
            "planning_artifacts": loaded_config.paths.planning_artifacts,
            "implementation_artifacts": loaded_config.paths.implementation_artifacts,
            "project_knowledge": loaded_config.paths.project_knowledge,
        }
        # Add bmad_paths.epics if configured (supports custom epic locations)
        if loaded_config.bmad_paths and loaded_config.bmad_paths.epics:
            paths_config["epics"] = loaded_config.bmad_paths.epics
        init_paths(project_path, paths_config)
    except ConfigError as e:
        _error(f"Config error: {e}")
        raise typer.Exit(code=EXIT_CONFIG_ERROR) from None

    # Resolve output path
    if output is not None:
        # User-provided path: resolve relative to CWD (not project)
        output_path = Path(output)
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
    else:
        # Default path depends on workflow type
        if is_epic_level:
            output_path = project_path / "compiled-prompts" / f"{workflow}-{epic}.xml"
        else:
            output_path = project_path / "compiled-prompts" / f"{workflow}-{epic}-{story}.xml"

    # Build compiler context
    from bmad_assist.core.paths import get_paths

    cwd = Path.cwd()

    # Build resolved_variables based on workflow type
    resolved_vars: dict[str, Any] = {"epic_num": epic_id}

    if not is_epic_level and story is not None:
        resolved_vars["story_num"] = story

    # Add category for qa-plan-execute
    if workflow == "qa-plan-execute" and category:
        resolved_vars["category"] = category

    # Add mode for tri-modal workflows
    if normalized_mode:
        resolved_vars["workflow_mode"] = normalized_mode

    # Display available modes if tri-modal workflow and no mode specified
    if not mode and workflow in TRI_MODAL_WORKFLOWS:
        _info(f"Available modes for {workflow}: c (create), v (validate), e (edit)")

    context = CompilerContext(
        project_root=project_path,
        output_folder=get_paths().output_folder,
        project_knowledge=get_paths().project_knowledge,
        cwd=cwd,
        resolved_variables=resolved_vars,
        links_only=links_only,
    )

    # Create stderr console for dry-run mode stats
    stderr_console = Console(file=sys.stderr, force_terminal=False)

    # Note: Patch auto-compilation is now handled by compile_workflow() via
    # load_workflow_ir() → ensure_template_compiled() in compiler.patching.compiler

    try:
        # Delegate to compiler module
        result = compile_workflow(workflow, context)

        # Validate token budget BEFORE any I/O (writing file or printing to stdout)
        from bmad_assist.compiler import validate_token_budget

        warnings = validate_token_budget(result.token_estimate, max_tokens)
        for warning in warnings:
            if dry_run:
                # Dry-run: warnings to stderr to keep stdout clean for piping
                stderr_console.print(f"[yellow]Warning:[/yellow] {warning}")
            else:
                # Normal mode: warnings to stdout via helper
                _warning(warning)

        # compile_workflow returns CompiledWorkflow with XML in .context field
        xml_content = result.context

        # Handle debug modes
        if debug_mode == "variables":
            # Extract only the <variables> section using ElementTree
            import xml.etree.ElementTree as ET

            try:
                root = ET.fromstring(xml_content)
                vars_el = root.find("variables")
                if vars_el is not None:
                    xml_content = ET.tostring(vars_el, encoding="unicode")
                else:
                    xml_content = "<variables></variables>"
            except ET.ParseError:
                # Fallback: try regex on last occurrence (skip documentation examples)
                import re

                pattern = r"<variables>\n<var.*?</variables>"
                matches = list(re.finditer(pattern, xml_content, re.DOTALL))
                xml_content = matches[-1].group(0) if matches else "<variables></variables>"

        if dry_run:
            # XML to stdout (pipe-friendly) - use sys.stdout directly, NOT Rich
            sys.stdout.write(xml_content)
            sys.stdout.flush()
            # Stats to stderr (visible even when piping)
            stderr_console.print(f"[dim]Tokens: ~{result.token_estimate:,}[/dim]")
        else:
            # Write to file using atomic pattern (temp file + rename)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = output_path.with_suffix(".tmp")
            try:
                temp_path.write_text(xml_content, encoding="utf-8")
                # Atomic replace (portable across POSIX and Windows)
                os.replace(temp_path, output_path)
            except OSError:
                # Clean up temp file on I/O error
                temp_path.unlink(missing_ok=True)
                raise

            _success(f"Compiled {workflow} workflow")
            console.print(f"  Output: {output_path}")
            console.print(f"  Tokens: ~{result.token_estimate:,} (estimated)")

    except ParserError as e:
        _error(str(e))
        if verbose:
            console.print_exception()
        raise typer.Exit(code=EXIT_PARSER_ERROR) from None
    except VariableError as e:
        _error(str(e))
        if verbose:
            console.print_exception()
        raise typer.Exit(code=EXIT_VARIABLE_ERROR) from None
    except AmbiguousFileError as e:
        _error(str(e))
        if verbose:
            console.print_exception()
        raise typer.Exit(code=EXIT_AMBIGUOUS_ERROR) from None
    except TokenBudgetError as e:
        # TokenBudgetError must be caught BEFORE CompilerError (it's a subclass)
        if dry_run:
            stderr_console.print(f"[red]Error:[/red] {e}")
        else:
            _error(str(e))
        if verbose:
            console.print_exception()
        raise typer.Exit(code=EXIT_TOKEN_BUDGET_ERROR) from None
    except CompilerError as e:
        _error(str(e))
        if verbose:
            console.print_exception()
        raise typer.Exit(code=EXIT_COMPILER_ERROR) from None
    except BmadAssistError as e:
        _error(str(e))
        if verbose:
            console.print_exception()
        raise typer.Exit(code=EXIT_FRAMEWORK_ERROR) from None
