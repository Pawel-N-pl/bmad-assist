"""Deep Verify subcommand group for bmad-assist CLI.

Commands for standalone Deep Verify verification of code artifacts.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import typer

from bmad_assist.cli_utils import (
    EXIT_CONFIG_ERROR,
    EXIT_ERROR,
    EXIT_SUCCESS,
    _error,
    _info,
    _setup_logging,
    _validate_project_path,
    _warning,
    console,
)
from bmad_assist.core.config import load_config_with_project
from bmad_assist.core.exceptions import ConfigError
from bmad_assist.deep_verify.config import DeepVerifyConfig
from bmad_assist.deep_verify.core.domain_detector import DomainDetector
from bmad_assist.deep_verify.core.engine import DeepVerifyEngine, VerificationContext
from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    DomainConfidence,
    DomainDetectionResult,
    Severity,
    Verdict,
    VerdictDecision,
)

logger = logging.getLogger(__name__)

verify_app = typer.Typer(
    name="verify",
    help="Deep Verify standalone verification commands",
    no_args_is_help=True,
)

# Map method IDs to their config attribute names
METHOD_ID_MAP: dict[str, str] = {
    "#153": "method_153_pattern_match",
    "#154": "method_154_boundary_analysis",
    "#155": "method_155_assumption_surfacing",
    "#157": "method_157_temporal_consistency",
    "#201": "method_201_adversarial_review",
    "#203": "method_203_domain_expert",
    "#204": "method_204_integration_analysis",
    "#205": "method_205_worst_case",
}

# Valid domain names for validation
VALID_DOMAINS = [d.value for d in ArtifactDomain]

# Language detection map
LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".go": "go",
    ".ts": "typescript",
    ".js": "javascript",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
}

# Exit codes for verdicts
EXIT_REJECT = 1
EXIT_UNCERTAIN = 2


def _detect_language(file_path: str) -> str | None:
    """Detect programming language from file extension.

    Args:
        file_path: Path to the file.

    Returns:
        Language identifier or None if unknown.

    """
    ext = Path(file_path).suffix.lower()
    return LANGUAGE_MAP.get(ext)


def _read_artifact_text(file: str) -> str:
    """Read artifact text from file or stdin.

    Args:
        file: File path or "-" for stdin.

    Returns:
        Content as string.

    Raises:
        typer.Exit: If file cannot be read.

    """
    if file == "-":
        return sys.stdin.read()

    file_path = Path(file)
    try:
        return file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _error(f"File not found: {file}")
        raise typer.Exit(code=EXIT_ERROR) from None
    except PermissionError:
        _error(f"Permission denied: {file}")
        raise typer.Exit(code=EXIT_ERROR) from None
    except UnicodeDecodeError:
        _error(f"Cannot decode file (not valid UTF-8): {file}")
        raise typer.Exit(code=EXIT_ERROR) from None


def _parse_domains(domains_str: str | None) -> list[ArtifactDomain] | None:
    """Parse comma-separated domain list.

    Args:
        domains_str: Comma-separated domain names.

    Returns:
        List of ArtifactDomain enums or None if input is None.

    Raises:
        typer.Exit: If invalid domain provided.

    """
    if not domains_str:
        return None

    domains = []
    for d in domains_str.split(","):
        d = d.strip().lower()
        if d not in VALID_DOMAINS:
            _error(f"Invalid domain: '{d}'. Valid domains: {', '.join(VALID_DOMAINS)}")
            raise typer.Exit(code=EXIT_CONFIG_ERROR)
        domains.append(ArtifactDomain(d))

    return domains


def _parse_methods(methods_str: str | None) -> list[str] | None:
    """Parse comma-separated method ID list.

    Args:
        methods_str: Comma-separated method IDs.

    Returns:
        List of method IDs or None if input is None.

    Raises:
        typer.Exit: If invalid method ID provided.

    """
    if not methods_str:
        return None

    methods = []
    for m in methods_str.split(","):
        m = m.strip()
        if m not in METHOD_ID_MAP:
            valid_methods = ", ".join(sorted(METHOD_ID_MAP.keys()))
            _error(f"Invalid method ID: '{m}'. Valid methods: {valid_methods}")
            raise typer.Exit(code=EXIT_CONFIG_ERROR)
        methods.append(m)

    return methods


class OverrideDomainDetector:
    """Domain detector that returns predefined domains (skips LLM)."""

    def __init__(self, override_domains: list[ArtifactDomain]) -> None:
        """Initialize with override domains.

        Args:
            override_domains: List of domains to return.

        """
        self._override_domains = override_domains

    def detect(
        self,
        artifact_text: str,
        language_hint: str | None = None,
    ) -> DomainDetectionResult:
        """Return predefined domains without LLM call.

        Args:
            artifact_text: Text to analyze (ignored).
            language_hint: Optional language hint (ignored).

        Returns:
            DomainDetectionResult with override domains.

        """
        confidences = [
            DomainConfidence(domain=d, confidence=1.0, signals=["override"])
            for d in self._override_domains
        ]
        return DomainDetectionResult(
            domains=confidences,
            reasoning=f"Domain override: {[d.value for d in self._override_domains]}",
            ambiguity="none",
        )


def _create_config_with_methods(
    base_config: DeepVerifyConfig | None,
    enabled_methods: list[str] | None,
) -> DeepVerifyConfig:
    """Create config with only specified methods enabled.

    Args:
        base_config: Base configuration or None for defaults.
        enabled_methods: List of method IDs to enable, or None for all.

    Returns:
        DeepVerifyConfig with methods configured.

    """
    if base_config is None:
        base_config = DeepVerifyConfig()

    if enabled_methods is None:
        return base_config

    # Create new config with only specified methods enabled
    config_dict = base_config.model_dump()

    # Disable all methods first
    for method_id in METHOD_ID_MAP:
        attr_name = METHOD_ID_MAP[method_id]
        if attr_name in config_dict:
            config_dict[attr_name]["enabled"] = False

    # Enable specified methods
    for method_id in enabled_methods:
        attr_name = METHOD_ID_MAP[method_id]
        if attr_name in config_dict:
            config_dict[attr_name]["enabled"] = True

    return DeepVerifyConfig(**config_dict)


def _format_text_output(
    verdict: Verdict,
    file: str,
    domains: Sequence[str],
    methods: Sequence[str],
    duration_ms: int,
) -> None:
    """Format verdict as human-readable text output.

    Args:
        verdict: Verdict object.
        file: File path that was verified.
        domains: List of detected domain names.
        methods: List of executed method IDs.
        duration_ms: Execution duration in milliseconds.

    """
    from rich.panel import Panel
    from rich.table import Table

    # Color based on verdict
    border_color = {
        VerdictDecision.ACCEPT: "green",
        VerdictDecision.REJECT: "red",
        VerdictDecision.UNCERTAIN: "yellow",
    }.get(verdict.decision, "white")

    # Summary panel
    summary = (
        f"[bold]{verdict.decision.value}[/bold] verdict "
        f"(score: {verdict.score:.1f})\n"
        f"{len(verdict.findings)} finding(s) detected\n"
        f"Duration: {duration_ms}ms"
    )
    panel = Panel(
        summary,
        title=f"Deep Verify Results: {file}",
        border_style=border_color,
    )
    console.print(panel)

    # Domains and methods
    console.print(f"[bold]Domains:[/bold] {', '.join(domains) if domains else 'none'}")
    console.print(f"[bold]Methods:[/bold] {', '.join(methods) if methods else 'none'}")
    console.print()

    # Findings table
    if verdict.findings:
        table = Table(title="Findings")
        table.add_column("ID", style="cyan", width=6)
        table.add_column("Severity", width=10)
        table.add_column("Title", width=40)
        table.add_column("Domain", width=12)
        table.add_column("Method", width=10)

        severity_colors = {
            Severity.CRITICAL: "red",
            Severity.ERROR: "dark_orange",
            Severity.WARNING: "yellow",
            Severity.INFO: "blue",
        }

        for finding in verdict.findings:
            severity_color = severity_colors.get(finding.severity, "white")
            domain_str = finding.domain.value if finding.domain else "-"
            table.add_row(
                finding.id,
                f"[{severity_color}]{finding.severity.value}[/{severity_color}]",
                finding.title,
                domain_str,
                finding.method_id,
            )
        console.print(table)
        console.print()

        # Detailed findings
        console.print("[bold]Detailed Findings:[/bold]")
        for finding in verdict.findings:
            severity_color = severity_colors.get(finding.severity, "white")
            # Use Rich's escape to safely include the color
            from rich.markup import escape

            title_escaped = escape(finding.title)
            console.print(
                f"\n[{severity_color}]{finding.id}: [bold]{title_escaped}[/bold][/{severity_color}]"
            )
            console.print(f"  Severity: {finding.severity.value}")
            console.print(f"  Method: {finding.method_id}")
            if finding.domain:
                console.print(f"  Domain: {finding.domain.value}")
            if finding.pattern_id:
                console.print(f"  Pattern: {finding.pattern_id}")
            console.print(f"  Description: {finding.description}")

            if finding.evidence:
                console.print("  Evidence:")
                for ev in finding.evidence:
                    line_info = f" (line {ev.line_number})" if ev.line_number else ""
                    console.print(
                        f"    - {ev.quote[:100]}{'...' if len(ev.quote) > 100 else ''}{line_info}"
                    )


@verify_app.command("run")
def verify_run(
    file: str = typer.Argument(
        ...,
        help="Path to file to verify, or '-' for stdin",
    ),
    project: str = typer.Option(
        ".",
        "--project",
        "-p",
        help="Path to project directory for config loading",
    ),
    domains: str | None = typer.Option(
        None,
        "--domains",
        "-d",
        help="Comma-separated domains to use (skip auto-detection)",
    ),
    methods: str | None = typer.Option(
        None,
        "--methods",
        "-m",
        help="Comma-separated method IDs to run",
    ),
    patterns: str | None = typer.Option(
        None,
        "--patterns",
        "-P",
        help="Path to additional pattern YAML file(s), comma-separated",
    ),
    output: str = typer.Option(
        "text",
        "--output",
        "-o",
        help="Output format: text or json",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force ACCEPT even with ERROR findings (CRITICAL still blocks)",
    ),
    timeout: int = typer.Option(
        90,
        "--timeout",
        "-t",
        help="Maximum seconds for verification",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output with debug logging",
    ),
) -> None:
    """Verify a code artifact using Deep Verify.

    Analyzes code for security, concurrency, API, and other issues using
    multiple verification methods. Returns verdict: ACCEPT, REJECT, or UNCERTAIN.

    Examples:
        bmad-assist verify run myfile.py
        bmad-assist verify run myfile.go --domains security,api
        bmad-assist verify run myfile.py --methods '#153,#201'
        bmad-assist verify run myfile.py --output json
        cat myfile.py | bmad-assist verify run -

    Exit codes:
        0 = ACCEPT (clean)
        1 = REJECT (issues found)
        2 = UNCERTAIN or config error

    """
    _setup_logging(verbose=verbose, quiet=False)

    # Validate output format
    if output not in ("text", "json"):
        _error(f"Invalid output format: '{output}'. Use 'text' or 'json'.")
        raise typer.Exit(code=EXIT_CONFIG_ERROR)

    # Validate project path
    project_path = _validate_project_path(project)

    # Parse domain override
    domain_override = _parse_domains(domains)
    if domain_override and output != "json":
        _info(f"Domain override: {', '.join(d.value for d in domain_override)}")

    # Parse method override
    method_override = _parse_methods(methods)
    if method_override and output != "json":
        _info(f"Method override: {', '.join(method_override)}")

    # Load configuration
    try:
        loaded_config = load_config_with_project(project_path=project_path)
        dv_config = loaded_config.deep_verify if loaded_config.deep_verify else DeepVerifyConfig()
    except ConfigError as e:
        if output != "json":
            _warning(f"Config error, using defaults: {e}")
        dv_config = DeepVerifyConfig()

    # Apply method override to config
    if method_override:
        dv_config = _create_config_with_methods(dv_config, method_override)

    # Read artifact
    try:
        artifact_text = _read_artifact_text(file)
    except typer.Exit:
        raise
    except (OSError, ValueError) as e:
        _error(f"Failed to read artifact: {e}")
        raise typer.Exit(code=EXIT_ERROR) from None

    # Detect language for context
    language = _detect_language(file) if file != "-" else None

    # Create context
    context = VerificationContext(
        file_path=Path(file) if file != "-" else None,
        language=language,
    )

    # Create engine with domain override if specified
    if domain_override:
        detector: DomainDetector | OverrideDomainDetector = OverrideDomainDetector(domain_override)
        engine = DeepVerifyEngine(
            project_root=project_path,
            config=dv_config,
            domain_detector=detector,  # type: ignore[arg-type]
        )
    else:
        engine = DeepVerifyEngine(
            project_root=project_path,
            config=dv_config,
        )

    # Run verification with progress indicator
    import time

    start_time = time.time()

    async def run_verification() -> Verdict:
        """Run verification with optional progress."""
        if verbose:
            # No progress indicator in verbose mode
            return await engine.verify(artifact_text, context=context, timeout=timeout)

        from rich.status import Status

        with Status("[bold green]Running Deep Verify...") as status:
            status.update("[green]Detecting domains...")
            # Small delay to show progress
            await asyncio.sleep(0.1)

            status.update("[green]Running verification methods...")
            result = await engine.verify(artifact_text, context=context, timeout=timeout)
            return result

    try:
        verdict = asyncio.run(run_verification())
    except (OSError, RuntimeError) as e:
        _error(f"Verification failed: {e}")
        if verbose:
            console.print_exception()
        raise typer.Exit(code=EXIT_ERROR) from None

    duration_ms = int((time.time() - start_time) * 1000)

    # Handle force option for ERROR-only REJECT (BEFORE output so displayed verdict matches exit code)
    if force and verdict.decision == VerdictDecision.REJECT:
        has_critical = any(f.severity == Severity.CRITICAL for f in verdict.findings)
        if not has_critical:
            if output != "json":
                _warning("Force flag set: Downgrading REJECT to UNCERTAIN")
            verdict = replace(verdict, decision=VerdictDecision.UNCERTAIN)

    # Extract domain and method info
    domain_names = [d.domain.value for d in verdict.domains_detected]
    domain_confidences = [
        {
            "domain": d.domain.value,
            "confidence": d.confidence,
            "signals": d.signals,
        }
        for d in verdict.domains_detected
    ]
    method_ids = list(verdict.methods_executed)

    # Output results
    if output == "json":
        # Use plain print for JSON to avoid Rich markup/wrapping
        import json as json_module

        output_dict = {
            "verdict": verdict.decision.value,
            "score": verdict.score,
            "file": file,
            "duration_ms": duration_ms,
            "domains": domain_confidences,
            "methods": method_ids,
            "findings": [
                {
                    "id": f.id,
                    "severity": f.severity.value,
                    "title": f.title,
                    "description": f.description,
                    "method_id": f.method_id,
                    "pattern_id": f.pattern_id,
                    "domain": f.domain.value if f.domain else None,
                    "evidence": [
                        {
                            "quote": e.quote,
                            "line_number": e.line_number,
                            "source": e.source,
                            "confidence": e.confidence,
                        }
                        for e in f.evidence
                    ],
                }
                for f in verdict.findings
            ],
            "summary": verdict.summary,
        }
        # Use print directly to avoid Rich's wrapping behavior
        print(json_module.dumps(output_dict, indent=2))
    else:
        _format_text_output(verdict, file, domain_names, method_ids, duration_ms)

    # Exit with appropriate code
    if verdict.decision == VerdictDecision.ACCEPT:
        raise typer.Exit(code=EXIT_SUCCESS)
    elif verdict.decision == VerdictDecision.REJECT:
        raise typer.Exit(code=EXIT_REJECT)
    else:  # UNCERTAIN
        raise typer.Exit(code=EXIT_UNCERTAIN)
