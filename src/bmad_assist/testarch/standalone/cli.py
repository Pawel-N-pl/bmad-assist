"""TEA CLI command group for standalone workflow execution.

Provides the `bmad-assist tea <workflow>` commands for executing TEA
workflows without requiring a full development loop.

Story 25.13: TEA Standalone Runner & CLI.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from bmad_assist.cli_utils import (
    EXIT_ERROR,
    EXIT_SUCCESS,
    _error,
    _info,
    _setup_logging,
    _success,
    _validate_project_path,
)

console = Console()

# Valid mode values for all TEA workflows
VALID_MODES = {"create", "validate", "edit"}

tea_app = typer.Typer(
    name="tea",
    help="TEA (Test Architecture Enterprise) standalone workflows",
    no_args_is_help=True,
)


def _get_runner(
    project_root: Path,
    output_dir: Path | None,
    evidence_output: Path | None,
    provider: str | None,
) -> "StandaloneRunner":
    """Create StandaloneRunner with validated paths.

    Args:
        project_root: Project root directory.
        output_dir: Output directory override.
        evidence_output: Evidence output path.
        provider: Provider name override.

    Returns:
        Configured StandaloneRunner instance.

    """
    from bmad_assist.testarch.standalone.runner import StandaloneRunner

    return StandaloneRunner(
        project_root=project_root,
        output_dir=output_dir,
        evidence_output=evidence_output,
        provider_name=provider,
    )


def _handle_dry_run(
    workflow_name: str,
    project_path: Path,
    output_dir: Path | None,
) -> None:
    """Handle dry-run mode - compile workflow and display.

    Args:
        workflow_name: Workflow to compile (e.g., "testarch-framework").
        project_path: Project root directory.
        output_dir: Output directory override.

    """
    from rich.syntax import Syntax

    from bmad_assist.compiler import compile_workflow
    from bmad_assist.compiler.types import CompilerContext

    docs_dir = project_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    effective_output = output_dir or (project_path / "_bmad-output" / "standalone")

    context = CompilerContext(
        project_root=project_path,
        output_folder=effective_output,
        project_knowledge=docs_dir,
        cwd=project_path,
        resolved_variables={},
    )

    try:
        result = compile_workflow(workflow_name, context)
        console.print(f"[bold]Compiled {workflow_name} Workflow:[/bold]")
        console.print(Syntax(result.context, "xml", theme="monokai"))
        console.print(f"[dim]Token estimate: ~{result.token_estimate:,}[/dim]")
    except Exception as e:
        _error(f"Failed to compile workflow: {e}")
        raise typer.Exit(code=EXIT_ERROR) from None


@tea_app.command("framework")
def framework_command(
    project_root: Path = typer.Option(
        Path("."),
        "--project-root",
        "-r",
        help="Project root directory",
    ),
    mode: str = typer.Option(
        "create",
        "--mode",
        "-m",
        help="Workflow mode: create, validate, edit",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Output directory (default: ./_bmad-output/standalone/)",
    ),
    evidence_output: Path | None = typer.Option(
        None,
        "--evidence-output",
        "-e",
        help="Optional evidence storage path",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-P",
        help="Provider name override (default: claude-subprocess)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="Compile workflow only, don't execute",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Initialize test framework (Playwright/Cypress).

    Detects existing test framework configuration and creates or updates
    framework setup files.

    Examples:
        $ bmad-assist tea framework                    # Current directory
        $ bmad-assist tea framework -r ./my-project   # Specific project
        $ bmad-assist tea framework --dry-run         # Preview only
    """
    _setup_logging(verbose=verbose, quiet=False)

    # Validate mode parameter
    if mode not in VALID_MODES:
        _error(f"Invalid mode '{mode}'. Valid values: {', '.join(sorted(VALID_MODES))}")
        raise typer.Exit(code=EXIT_ERROR)

    project_path = _validate_project_path(str(project_root))

    if dry_run:
        _handle_dry_run("testarch-framework", project_path, output_dir)
        raise typer.Exit(code=EXIT_SUCCESS)

    runner = _get_runner(project_path, output_dir, evidence_output, provider)

    _info(f"Running TEA framework workflow for {project_path}")
    result = runner.run_framework(mode=mode)

    if result["success"]:
        if result["output_path"]:
            _success(f"Framework workflow complete: {result['output_path']}")
        else:
            _info("Framework workflow skipped (already exists or disabled)")
            if result.get("metrics", {}).get("reason"):
                console.print(f"  Reason: {result['metrics']['reason']}")
        raise typer.Exit(code=EXIT_SUCCESS)
    else:
        _error(f"Framework workflow failed: {result['error']}")
        raise typer.Exit(code=EXIT_ERROR)


@tea_app.command("ci")
def ci_command(
    project_root: Path = typer.Option(
        Path("."),
        "--project-root",
        "-r",
        help="Project root directory",
    ),
    ci_platform: str | None = typer.Option(
        None,
        "--ci-platform",
        "-c",
        help="CI platform: github, gitlab, circleci, auto (default: auto-detect)",
    ),
    mode: str = typer.Option(
        "create",
        "--mode",
        "-m",
        help="Workflow mode: create, validate, edit",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Output directory (default: ./_bmad-output/standalone/)",
    ),
    evidence_output: Path | None = typer.Option(
        None,
        "--evidence-output",
        "-e",
        help="Optional evidence storage path",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-P",
        help="Provider name override (default: claude-subprocess)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="Compile workflow only, don't execute",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Create CI pipeline configuration.

    Auto-detects CI platform from git remote or existing CI files,
    or use --ci-platform to specify explicitly.

    Examples:
        $ bmad-assist tea ci                          # Auto-detect platform
        $ bmad-assist tea ci --ci-platform github     # Force GitHub Actions
        $ bmad-assist tea ci -r ./my-project -d       # Dry-run for project
    """
    _setup_logging(verbose=verbose, quiet=False)

    # Validate mode parameter
    if mode not in VALID_MODES:
        _error(f"Invalid mode '{mode}'. Valid values: {', '.join(sorted(VALID_MODES))}")
        raise typer.Exit(code=EXIT_ERROR)

    project_path = _validate_project_path(str(project_root))

    if dry_run:
        _handle_dry_run("testarch-ci", project_path, output_dir)
        raise typer.Exit(code=EXIT_SUCCESS)

    runner = _get_runner(project_path, output_dir, evidence_output, provider)

    platform_info = f" (platform: {ci_platform})" if ci_platform else " (auto-detect)"
    _info(f"Running TEA CI workflow for {project_path}{platform_info}")

    result = runner.run_ci(ci_platform=ci_platform, mode=mode)

    if result["success"]:
        if result["output_path"]:
            _success(f"CI workflow complete: {result['output_path']}")
        else:
            _info("CI workflow skipped (already exists or disabled)")
            if result.get("metrics", {}).get("reason"):
                console.print(f"  Reason: {result['metrics']['reason']}")
        raise typer.Exit(code=EXIT_SUCCESS)
    else:
        _error(f"CI workflow failed: {result['error']}")
        raise typer.Exit(code=EXIT_ERROR)


@tea_app.command("test-design")
def test_design_command(
    project_root: Path = typer.Option(
        Path("."),
        "--project-root",
        "-r",
        help="Project root directory",
    ),
    level: str = typer.Option(
        "system",
        "--level",
        "-l",
        help="Design level: system (architecture docs) or epic (per-epic plan)",
    ),
    mode: str = typer.Option(
        "create",
        "--mode",
        "-m",
        help="Workflow mode: create, validate, edit",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Output directory (default: ./_bmad-output/standalone/)",
    ),
    evidence_output: Path | None = typer.Option(
        None,
        "--evidence-output",
        "-e",
        help="Optional evidence storage path",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-P",
        help="Provider name override (default: claude-subprocess)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="Compile workflow only, don't execute",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Generate test design documents.

    Creates test architecture and QA documentation at the specified level.

    System level creates:
      - test-design-architecture.md (system-wide test strategy)
      - test-design-qa.md (QA processes and standards)

    Epic level creates:
      - test-design-epic-standalone.md (per-epic test planning)

    Examples:
        $ bmad-assist tea test-design                     # System level (default)
        $ bmad-assist tea test-design --level epic        # Epic level
        $ bmad-assist tea test-design -r ./project -d     # Dry-run
    """
    _setup_logging(verbose=verbose, quiet=False)

    # Validate mode parameter
    if mode not in VALID_MODES:
        _error(f"Invalid mode '{mode}'. Valid values: {', '.join(sorted(VALID_MODES))}")
        raise typer.Exit(code=EXIT_ERROR)

    project_path = _validate_project_path(str(project_root))

    # Validate level
    valid_levels = {"system", "epic"}
    if level not in valid_levels:
        _error(f"Invalid level '{level}'. Valid values: {', '.join(valid_levels)}")
        raise typer.Exit(code=EXIT_ERROR)

    if dry_run:
        _handle_dry_run("testarch-test-design", project_path, output_dir)
        raise typer.Exit(code=EXIT_SUCCESS)

    runner = _get_runner(project_path, output_dir, evidence_output, provider)

    _info(f"Running TEA test-design workflow for {project_path} (level: {level})")

    result = runner.run_test_design(level=level, mode=mode)

    if result["success"]:
        if result["output_path"]:
            _success(f"Test-design workflow complete: {result['output_path']}")
        else:
            _info("Test-design workflow skipped (already exists or disabled)")
            if result.get("metrics", {}).get("reason"):
                console.print(f"  Reason: {result['metrics']['reason']}")
        raise typer.Exit(code=EXIT_SUCCESS)
    else:
        _error(f"Test-design workflow failed: {result['error']}")
        raise typer.Exit(code=EXIT_ERROR)


@tea_app.command("automate")
def automate_command(
    project_root: Path = typer.Option(
        Path("."),
        "--project-root",
        "-r",
        help="Project root directory",
    ),
    component: str | None = typer.Option(
        None,
        "--component",
        "-c",
        help="Optional component/feature to focus on",
    ),
    mode: str = typer.Option(
        "create",
        "--mode",
        "-m",
        help="Workflow mode: create, validate, edit",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Output directory (default: ./_bmad-output/standalone/)",
    ),
    evidence_output: Path | None = typer.Option(
        None,
        "--evidence-output",
        "-e",
        help="Optional evidence storage path",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-P",
        help="Provider name override (default: claude-subprocess)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="Compile workflow only, don't execute",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Generate test automation specifications.

    Analyzes the codebase and generates test automation specifications,
    optionally focused on a specific component or feature.

    Creates automation-summary.md with:
      - Test coverage analysis
      - Recommended test patterns
      - Generated test specifications

    Examples:
        $ bmad-assist tea automate                         # Analyze full codebase
        $ bmad-assist tea automate --component auth        # Focus on auth module
        $ bmad-assist tea automate -r ./project -d         # Dry-run
    """
    _setup_logging(verbose=verbose, quiet=False)

    # Validate mode parameter
    if mode not in VALID_MODES:
        _error(f"Invalid mode '{mode}'. Valid values: {', '.join(sorted(VALID_MODES))}")
        raise typer.Exit(code=EXIT_ERROR)

    project_path = _validate_project_path(str(project_root))

    if dry_run:
        _handle_dry_run("testarch-automate", project_path, output_dir)
        raise typer.Exit(code=EXIT_SUCCESS)

    runner = _get_runner(project_path, output_dir, evidence_output, provider)

    component_info = f" (component: {component})" if component else ""
    _info(f"Running TEA automate workflow for {project_path}{component_info}")

    result = runner.run_automate(component=component, mode=mode)

    if result["success"]:
        if result["output_path"]:
            _success(f"Automate workflow complete: {result['output_path']}")
        else:
            _info("Automate workflow skipped (disabled or no changes needed)")
            if result.get("metrics", {}).get("reason"):
                console.print(f"  Reason: {result['metrics']['reason']}")
        raise typer.Exit(code=EXIT_SUCCESS)
    else:
        _error(f"Automate workflow failed: {result['error']}")
        raise typer.Exit(code=EXIT_ERROR)


@tea_app.command("nfr-assess")
def nfr_assess_command(
    project_root: Path = typer.Option(
        Path("."),
        "--project-root",
        "-r",
        help="Project root directory",
    ),
    category: str | None = typer.Option(
        None,
        "--category",
        "-c",
        help="NFR category: performance, security, reliability, maintainability, all",
    ),
    mode: str = typer.Option(
        "create",
        "--mode",
        "-m",
        help="Workflow mode: create, validate, edit",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Output directory (default: ./_bmad-output/standalone/)",
    ),
    evidence_output: Path | None = typer.Option(
        None,
        "--evidence-output",
        "-e",
        help="Optional evidence storage path",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-P",
        help="Provider name override (default: claude-subprocess)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="Compile workflow only, don't execute",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Assess non-functional requirements.

    Evaluates NFRs and provides a quality gate decision (PASS/CONCERNS/FAIL/WAIVED).

    Categories:
      - performance: Response times, throughput, resource usage
      - security: OWASP compliance, vulnerability assessment
      - reliability: Error handling, availability, fault tolerance
      - maintainability: Code quality, documentation, testability
      - all: Comprehensive assessment of all categories

    Creates nfr-assessment.md with:
      - Category assessments with evidence
      - Quality gate decision
      - Recommendations for improvements

    Examples:
        $ bmad-assist tea nfr-assess                       # Assess all categories
        $ bmad-assist tea nfr-assess --category security   # Security only
        $ bmad-assist tea nfr-assess -r ./project -d       # Dry-run
    """
    _setup_logging(verbose=verbose, quiet=False)

    # Validate mode parameter
    if mode not in VALID_MODES:
        _error(f"Invalid mode '{mode}'. Valid values: {', '.join(sorted(VALID_MODES))}")
        raise typer.Exit(code=EXIT_ERROR)

    project_path = _validate_project_path(str(project_root))

    # Validate category if provided
    valid_categories = {"performance", "security", "reliability", "maintainability", "all"}
    if category and category not in valid_categories:
        _error(
            f"Invalid category '{category}'. "
            f"Valid values: {', '.join(sorted(valid_categories))}"
        )
        raise typer.Exit(code=EXIT_ERROR)

    if dry_run:
        _handle_dry_run("testarch-nfr", project_path, output_dir)
        raise typer.Exit(code=EXIT_SUCCESS)

    runner = _get_runner(project_path, output_dir, evidence_output, provider)

    category_info = f" (category: {category})" if category else " (all categories)"
    _info(f"Running TEA NFR assessment for {project_path}{category_info}")

    result = runner.run_nfr_assess(category=category, mode=mode)

    if result["success"]:
        if result["output_path"]:
            _success(f"NFR assessment complete: {result['output_path']}")
            # Show quality gate decision if available
            metrics = result.get("metrics", {})
            if "gate_decision" in metrics:
                console.print(f"  Quality Gate: {metrics['gate_decision']}")
        else:
            _info("NFR assessment skipped (disabled or prerequisites not met)")
            if result.get("metrics", {}).get("reason"):
                console.print(f"  Reason: {result['metrics']['reason']}")
        raise typer.Exit(code=EXIT_SUCCESS)
    else:
        _error(f"NFR assessment failed: {result['error']}")
        raise typer.Exit(code=EXIT_ERROR)
