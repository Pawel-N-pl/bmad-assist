"""Configuration file validator with human-readable output.

Validates bmad-assist.yaml configuration files and reports issues
with [OK], [WARN], and [ERR] status markers.

Checks performed:
- YAML syntax validity
- Required fields presence (providers.master.provider, providers.master.model)
- Provider name validity (against registry)
- Settings file paths existence (with ~ expansion)
- Pydantic schema validation

Example:
    >>> from bmad_assist.core.config_validator import validate_config_file
    >>> results = validate_config_file(Path("bmad-assist.yaml"))
    >>> for r in results:
    ...     print(f"[{r.status.upper()}] {r.message}")
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

logger = logging.getLogger(__name__)

StatusType = Literal["ok", "warn", "error"]


@dataclass(frozen=True)
class ValidationResult:
    """Result of a single validation check.

    Attributes:
        status: Validation status ("ok", "warn", or "error").
        field_path: Dot-separated path to the validated field (e.g., "providers.master.provider").
        message: Human-readable description of the check result.
        suggestion: Optional suggestion for fixing the issue.

    """

    status: StatusType
    field_path: str
    message: str
    suggestion: str | None = None


def validate_config_file(config_path: Path) -> list[ValidationResult]:
    """Validate a configuration file and return all check results.

    Performs comprehensive validation including YAML syntax, required fields,
    provider names, settings paths, and Pydantic schema.

    Args:
        config_path: Path to the configuration file.

    Returns:
        List of ValidationResult objects for all checks performed.

    """
    results: list[ValidationResult] = []

    # Check 1: YAML syntax
    try:
        with open(config_path, encoding="utf-8") as f:
            content = f.read()
        config_data = yaml.safe_load(content)
        results.append(
            ValidationResult(
                status="ok",
                field_path="(file)",
                message="YAML syntax is valid",
            )
        )
    except yaml.YAMLError as e:
        results.append(
            ValidationResult(
                status="error",
                field_path="(file)",
                message=f"Invalid YAML syntax: {e}",
                suggestion="Check YAML indentation and formatting",
            )
        )
        # Can't continue if YAML is invalid
        return results

    if config_data is None:
        results.append(
            ValidationResult(
                status="error",
                field_path="(file)",
                message="Config file is empty",
                suggestion="Add at least providers.master configuration",
            )
        )
        return results

    if not isinstance(config_data, dict):
        results.append(
            ValidationResult(
                status="error",
                field_path="(file)",
                message=f"Config must be a YAML mapping, got {type(config_data).__name__}",
            )
        )
        return results

    # Check 2: Required fields
    results.extend(_validate_required_fields(config_data))

    # Check 3: Provider names
    results.extend(_validate_provider_names(config_data))

    # Check 4: Settings paths
    results.extend(_validate_settings_paths(config_data))

    # Check 5: Pydantic schema
    results.extend(_validate_pydantic_schema(config_data, config_path))

    return results


def _validate_required_fields(config_data: dict[str, Any]) -> list[ValidationResult]:
    """Check for required fields in configuration."""
    results: list[ValidationResult] = []

    # providers section
    if "providers" not in config_data:
        results.append(
            ValidationResult(
                status="error",
                field_path="providers",
                message="Missing required 'providers' section",
                suggestion="Add 'providers:' section with master configuration",
            )
        )
        return results

    providers = config_data["providers"]
    if not isinstance(providers, dict):
        results.append(
            ValidationResult(
                status="error",
                field_path="providers",
                message="'providers' must be a mapping",
            )
        )
        return results

    # providers.master
    if "master" not in providers:
        results.append(
            ValidationResult(
                status="error",
                field_path="providers.master",
                message="Missing required 'providers.master' section",
                suggestion="Add master provider configuration",
            )
        )
        return results

    master = providers["master"]
    if not isinstance(master, dict):
        results.append(
            ValidationResult(
                status="error",
                field_path="providers.master",
                message="'providers.master' must be a mapping",
            )
        )
        return results

    # providers.master.provider
    if "provider" not in master:
        results.append(
            ValidationResult(
                status="error",
                field_path="providers.master.provider",
                message="Missing required 'provider' field",
                suggestion="Specify provider name (e.g., 'claude-subprocess', 'gemini')",
            )
        )
    else:
        results.append(
            ValidationResult(
                status="ok",
                field_path="providers.master.provider",
                message=f"Provider: {master['provider']}",
            )
        )

    # providers.master.model
    if "model" not in master:
        results.append(
            ValidationResult(
                status="error",
                field_path="providers.master.model",
                message="Missing required 'model' field",
                suggestion="Specify model name (e.g., 'opus', 'gemini-2.5-flash')",
            )
        )
    else:
        results.append(
            ValidationResult(
                status="ok",
                field_path="providers.master.model",
                message=f"Model: {master['model']}",
            )
        )

    return results


def _validate_provider_names(config_data: dict[str, Any]) -> list[ValidationResult]:
    """Validate provider names against registry."""
    from bmad_assist.providers.registry import list_providers

    results: list[ValidationResult] = []
    valid_providers = list_providers()

    providers = config_data.get("providers", {})
    if not isinstance(providers, dict):
        return results

    # Check master provider
    master = providers.get("master", {})
    if isinstance(master, dict) and "provider" in master:
        provider_name = master["provider"]
        if provider_name not in valid_providers:
            available = ", ".join(sorted(valid_providers))
            results.append(
                ValidationResult(
                    status="error",
                    field_path="providers.master.provider",
                    message=f"Unknown provider: '{provider_name}'",
                    suggestion=f"Available providers: {available}",
                )
            )

    # Check multi providers
    multi = providers.get("multi", [])
    if isinstance(multi, list):
        for i, validator in enumerate(multi):
            if isinstance(validator, dict) and "provider" in validator:
                provider_name = validator["provider"]
                if provider_name not in valid_providers:
                    available = ", ".join(sorted(valid_providers))
                    results.append(
                        ValidationResult(
                            status="error",
                            field_path=f"providers.multi[{i}].provider",
                            message=f"Unknown provider: '{provider_name}'",
                            suggestion=f"Available providers: {available}",
                        )
                    )

    # Check helper provider
    helper = providers.get("helper", {})
    if isinstance(helper, dict) and "provider" in helper:
        provider_name = helper["provider"]
        if provider_name not in valid_providers:
            available = ", ".join(sorted(valid_providers))
            results.append(
                ValidationResult(
                    status="error",
                    field_path="providers.helper.provider",
                    message=f"Unknown provider: '{provider_name}'",
                    suggestion=f"Available providers: {available}",
                )
            )

    return results


def _validate_settings_paths(config_data: dict[str, Any]) -> list[ValidationResult]:
    """Validate settings file paths exist (with ~ expansion)."""
    results: list[ValidationResult] = []

    providers = config_data.get("providers", {})
    if not isinstance(providers, dict):
        return results

    def check_settings(field_path: str, provider_config: dict[str, Any]) -> None:
        """Check settings path for a provider config."""
        if "settings" not in provider_config:
            return

        settings_path_str = provider_config["settings"]
        if not isinstance(settings_path_str, str):
            return

        # Expand ~ to home directory
        settings_path = Path(settings_path_str).expanduser()

        if not settings_path.exists():
            results.append(
                ValidationResult(
                    status="warn",
                    field_path=f"{field_path}.settings",
                    message=f"Settings file not found: {settings_path}",
                    suggestion="Create the settings file or remove the 'settings' field",
                )
            )
        elif not settings_path.is_file():
            results.append(
                ValidationResult(
                    status="warn",
                    field_path=f"{field_path}.settings",
                    message=f"Settings path is not a file: {settings_path}",
                )
            )
        else:
            results.append(
                ValidationResult(
                    status="ok",
                    field_path=f"{field_path}.settings",
                    message=f"Settings file exists: {settings_path}",
                )
            )

    # Check master
    master = providers.get("master", {})
    if isinstance(master, dict):
        check_settings("providers.master", master)

    # Check multi
    multi = providers.get("multi", [])
    if isinstance(multi, list):
        for i, validator in enumerate(multi):
            if isinstance(validator, dict):
                check_settings(f"providers.multi[{i}]", validator)

    # Check helper
    helper = providers.get("helper", {})
    if isinstance(helper, dict):
        check_settings("providers.helper", helper)

    return results


def _validate_pydantic_schema(
    config_data: dict[str, Any], config_path: Path
) -> list[ValidationResult]:
    """Validate configuration against Pydantic schema."""
    from pydantic import ValidationError

    from bmad_assist.core.exceptions import ConfigError

    results: list[ValidationResult] = []

    try:
        from bmad_assist.core.config import load_config_with_project

        # Try loading with Pydantic validation
        load_config_with_project(
            project_path=config_path.parent,
            global_config_path=None,
            cwd_config_path=False,  # Don't load from CWD, use the specific file
        )
        results.append(
            ValidationResult(
                status="ok",
                field_path="(schema)",
                message="Configuration validates against schema",
            )
        )
    except ValidationError as e:
        # Pydantic validation error - extract field info
        error_msg = str(e)
        results.append(
            ValidationResult(
                status="error",
                field_path="(schema)",
                message=f"Schema validation failed: {error_msg}",
            )
        )
    except ConfigError as e:
        # bmad-assist config error
        results.append(
            ValidationResult(
                status="error",
                field_path="(schema)",
                message=f"Configuration error: {e}",
            )
        )
    except (OSError, yaml.YAMLError) as e:
        # File or YAML errors
        results.append(
            ValidationResult(
                status="error",
                field_path="(schema)",
                message=f"Failed to load config: {e}",
            )
        )

    return results


def format_validation_report(
    results: list[ValidationResult], config_path: Path
) -> tuple[str, bool]:
    """Format validation results as human-readable report.

    Args:
        results: List of validation results.
        config_path: Path to the validated config file.

    Returns:
        Tuple of (formatted_report, has_errors).

    """
    lines: list[str] = []
    lines.append(f"\n[bold]Validating:[/bold] {config_path}\n")

    has_errors = False
    has_warnings = False

    for result in results:
        if result.status == "ok":
            status_tag = "[green][OK][/green]"
        elif result.status == "warn":
            status_tag = "[yellow][WARN][/yellow]"
            has_warnings = True
        else:
            status_tag = "[red][ERR][/red]"
            has_errors = True

        field_display = f"[dim]{result.field_path}[/dim]" if result.field_path else ""
        lines.append(f"  {status_tag} {field_display}: {result.message}")

        if result.suggestion:
            lines.append(f"       [dim]→ {result.suggestion}[/dim]")

    # Summary line
    lines.append("")
    if has_errors:
        lines.append("[red]✗ Configuration has errors[/red]")
    elif has_warnings:
        lines.append("[yellow]⚠ Configuration valid with warnings[/yellow]")
    else:
        lines.append("[green]✓ Configuration is valid[/green]")

    return "\n".join(lines), has_errors
