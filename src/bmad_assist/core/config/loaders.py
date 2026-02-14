"""Configuration loading functions and singleton management."""

import copy
import logging
import random
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from bmad_assist.core.config.constants import (
    GLOBAL_CONFIG_PATH,
    MAX_CONFIG_SIZE,
    PROJECT_CONFIG_NAME,
)
from bmad_assist.core.config.env import load_env_file
from bmad_assist.core.config.models.main import Config
from bmad_assist.core.exceptions import ConfigError

logger = logging.getLogger(__name__)

# Module-level singleton for configuration
_config: Config | None = None


# Keys whose dict children should be replaced atomically, not deep-merged.
# phase_models entries are complete provider configs — merging fields from
# different tiers (CWD vs project) produces invalid hybrid configs.
_SHALLOW_MERGE_KEYS: frozenset[str] = frozenset({"phase_models"})


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base dictionary.

    Rules:
    - Dicts are merged recursively (except _SHALLOW_MERGE_KEYS)
    - For _SHALLOW_MERGE_KEYS: children are replaced atomically, not merged
    - Lists are replaced (NOT merged/appended)
    - Scalar values are replaced by override
    - Keys only in base are preserved
    - Keys only in override are added

    Args:
        base: Base configuration dictionary.
        override: Override dictionary with higher priority.

    Returns:
        Merged dictionary (new dict, does not modify inputs).

    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            if key in _SHALLOW_MERGE_KEYS:
                # Shallow merge: each child key is replaced atomically.
                # The parent dict itself is merged (preserving keys from both),
                # but each child value is a complete unit, not a partial override.
                merged = copy.deepcopy(result[key])
                for child_key, child_value in value.items():
                    merged[child_key] = copy.deepcopy(child_value)
                result[key] = merged
            else:
                result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load and parse a YAML file with safety checks.

    Args:
        path: Path to YAML file.

    Returns:
        Parsed YAML content as dictionary.

    Raises:
        ConfigError: If file cannot be read, is too large, is empty,
            is a directory, or YAML is invalid.

    """
    try:
        # Read with size limit to avoid TOCTOU vulnerability
        # (stat-then-read allows file swap between calls)
        with path.open("r", encoding="utf-8") as f:
            content = f.read(MAX_CONFIG_SIZE + 1)

        if len(content) > MAX_CONFIG_SIZE:
            raise ConfigError(
                f"Config file {path} exceeds 1MB limit "
                f"(read {len(content):,} bytes before stopping)."
            )

        parsed = yaml.safe_load(content)

        # Explicit empty file detection for better error messages
        if parsed is None:
            raise ConfigError(
                f"Config file {path} is empty or contains only whitespace. "
                f"At minimum, the 'providers.master' section must be present."
            )

        if not isinstance(parsed, dict):
            raise ConfigError(
                f"Config file {path} must contain a YAML mapping, got {type(parsed).__name__}."
            )

        return parsed
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e
    except IsADirectoryError as e:
        raise ConfigError(f"{path} is a directory, not a config file.") from e
    except PermissionError as e:
        raise ConfigError(f"Permission denied reading {path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"Cannot read config file {path}: {e}") from e


def _identify_error_source(
    error_msg: str,
    global_data: dict[str, Any] | None,
    cwd_data: dict[str, Any] | None,
    project_data: dict[str, Any] | None,
    global_path: Path | None,
    cwd_path: Path | None,
    project_path: Path | None,
) -> str | None:
    """Try to identify which config file caused a validation error.

    Parses Pydantic error messages to extract the field path, then checks
    which config file contains that field to identify the source.

    Args:
        error_msg: The error message from Pydantic validation.
        global_data: Parsed global config data (or None).
        cwd_data: Parsed CWD config data (or None).
        project_data: Parsed project config data (or None).
        global_path: Path to global config file.
        cwd_path: Path to CWD config file.
        project_path: Path to project config file.

    Returns:
        Human-readable source identifier (e.g., "project (/path/to/config.yaml)")
        or None if source cannot be determined.

    """
    import re

    # Extract field path from Pydantic error message
    # Examples:
    #   "paths.project_knowledge\n  value is not..."
    #   "providers.master.model\n  Field required..."
    field_match = re.search(r"(\w+(?:\.\w+)*)\s*\n\s*", error_msg)
    if not field_match:
        return None

    field_path = field_match.group(1)
    field_parts = field_path.split(".")

    def has_field(data: dict[str, Any] | None, parts: list[str]) -> bool:
        """Check if data contains the field path."""
        if data is None:
            return False
        current = data
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        return True

    # Check configs in reverse priority order (project overrides cwd overrides global)
    # Return the LAST one that has the field (highest priority = source of final value)
    sources: list[tuple[dict[str, Any] | None, Path | None, str]] = [
        (global_data, global_path, "global"),
        (cwd_data, cwd_path, "CWD"),
        (project_data, project_path, "project"),
    ]

    found_source: str | None = None
    for data, path, name in sources:
        if has_field(data, field_parts) and path is not None:
            found_source = f"{name} ({path})"

    return found_source


def load_config(config_data: dict[str, Any]) -> Config:
    """Load and validate configuration from a dictionary.

    This function validates the configuration dictionary using Pydantic models
    and stores the result in a module-level singleton. File loading (YAML)
    will be added in Story 1.3, which will call this function after parsing.

    Args:
        config_data: Configuration dictionary to validate.

    Returns:
        Validated Config instance.

    Raises:
        ConfigError: If config_data is not a dict or validation fails.

    """
    global _config
    if not isinstance(config_data, dict):
        raise ConfigError(f"config_data must be a dict, got {type(config_data).__name__}")
    try:
        _config = Config.model_validate(config_data)
        return _config
    except ValidationError as e:
        _config = None
        raise ConfigError(f"Configuration validation failed: {e}") from e


def get_config() -> Config:
    """Get the loaded configuration singleton.

    Returns:
        The loaded Config instance.

    Raises:
        ConfigError: If config has not been loaded yet.

    """
    if _config is None:
        raise ConfigError("Config not loaded. Call load_config() first.")
    return _config


def _reset_config() -> None:
    """Reset config singleton for testing purposes only.

    This function should only be used in tests to ensure clean state
    between test cases.
    """
    global _config
    _config = None


def load_global_config(path: str | Path | None = None) -> Config:
    """Load global configuration from YAML file.

    Loads configuration from the specified path or the default global
    config location (~/.bmad-assist/config.yaml). The YAML content is
    validated against Pydantic models and stored in the module singleton.

    Args:
        path: Optional custom path to config file (string or Path object).
            Strings with ~ are expanded. Defaults to ~/.bmad-assist/config.yaml

    Returns:
        Validated Config instance.

    Raises:
        ConfigError: If file doesn't exist, cannot be read, is too large,
            contains invalid YAML, or fails validation.

    Example:
        >>> load_global_config()  # Uses default ~/.bmad-assist/config.yaml
        Config(providers=...)

        >>> load_global_config("/custom/config.yaml")  # Custom string path
        Config(providers=...)

        >>> load_global_config(Path.home() / "my-config.yaml")  # Path object
        Config(providers=...)

    """
    global _config

    config_path = GLOBAL_CONFIG_PATH if path is None else Path(path).expanduser()

    if not config_path.exists():
        raise ConfigError(
            f"Global config not found at {config_path}.\nRun 'bmad-assist init' to create one."
        )

    if not config_path.is_file():
        raise ConfigError(f"Config path {config_path} exists but is not a file.")

    try:
        config_data = _load_yaml_file(config_path)
    except ConfigError:
        # Clear singleton on YAML parse error to prevent stale state
        _config = None
        raise

    try:
        return load_config(config_data)
    except ConfigError as e:
        # Singleton already cleared by load_config on validation failure
        # Re-raise with path context
        raise ConfigError(f"Invalid configuration in {config_path}: {e}") from e


def _load_project_config(project_path: Path) -> dict[str, Any] | None:
    """Load project configuration from a directory.

    Attempts to load bmad-assist.yaml from the specified project directory.
    Returns None if the file doesn't exist (not an error).

    Args:
        project_path: Path to project directory (must be a directory).

    Returns:
        Parsed configuration dictionary, or None if file doesn't exist.

    Raises:
        ConfigError: If file exists but contains invalid YAML.
            Error message includes "project config" to distinguish from global config errors.

    """
    config_file = project_path / PROJECT_CONFIG_NAME

    if not config_file.exists():
        return None

    if not config_file.is_file():
        raise ConfigError(f"Project config path {config_file} exists but is not a file.")

    try:
        return _load_yaml_file(config_file)
    except ConfigError as e:
        # Re-raise with "project config" prefix to distinguish from global config errors
        raise ConfigError(f"Failed to parse project config at {config_file}: {e}") from e


def load_config_with_project(
    project_path: str | Path | None = None,
    *,
    global_config_path: str | Path | None = None,
    cwd_config_path: str | Path | None | Literal[False] = None,
) -> Config:
    """Load configuration with three-tier hierarchy support.

    Configuration is loaded and merged from three sources (in order of precedence):
    1. Global: ~/.bmad-assist/config.yaml (base defaults)
    2. CWD: {cwd}/bmad-assist.yaml (workspace-level overrides, if different from project)
    3. Project: {project_path}/bmad-assist.yaml (project-specific overrides)

    This allows running `bmad-assist run --project experiments/fixtures/foo` from
    the main bmad-assist directory and having the main bmad-assist.yaml config
    apply, with fixture-specific overrides taking precedence.

    Also loads environment variables from {project_path}/.env before config
    validation, so CLI providers can use credentials immediately.

    Args:
        project_path: Path to project directory. Defaults to current working directory.
            MUST be a directory, not a file.
        global_config_path: Custom global config path (for testing).
        cwd_config_path: CWD config path override. Use False to disable CWD tier
            entirely (for testing). Defaults to None (auto-detect from cwd).

    Returns:
        Validated Config instance with merged configuration.

    Raises:
        ConfigError: If no config exists at any tier, if config is invalid YAML,
            if project_path is not a directory, or if Pydantic validation fails.
            Error messages list which config sources were merged.

    Example:
        >>> # From /home/user/bmad-assist-22 with bmad-assist.yaml
        >>> load_config_with_project("experiments/fixtures/simple")
        # Merges: global <- cwd (bmad-assist.yaml) <- project (if exists)

        >>> load_config_with_project()  # Uses cwd as project path
        Config(providers=...)

    """
    global _config

    # Resolve project path
    resolved_project = Path.cwd() if project_path is None else Path(project_path).expanduser()

    # Load .env file BEFORE config validation (AC9: env vars available for CLI providers)
    # This is done early so credentials are available even if config fails
    if resolved_project.exists() and resolved_project.is_dir():
        load_env_file(resolved_project)

    # Validate project_path is a directory
    if resolved_project.exists() and not resolved_project.is_dir():
        raise ConfigError(f"project_path must be a directory, got file: {resolved_project}")

    # Resolve global config path
    resolved_global = (
        GLOBAL_CONFIG_PATH if global_config_path is None else Path(global_config_path).expanduser()
    )

    # Check existence - three-tier hierarchy:
    # 1. Global (~/.bmad-assist/config.yaml) - base defaults
    # 2. CWD (current working directory) - workspace-level overrides
    # 3. Project (--project flag) - project-specific overrides
    global_exists = resolved_global.exists() and resolved_global.is_file()

    # CWD config (only if different from project and not disabled)
    cwd_exists = False
    resolved_cwd_config: Path | None = None
    if cwd_config_path is not False:  # False = disabled entirely
        if cwd_config_path is not None:
            # Custom path provided (for testing)
            resolved_cwd_config = Path(cwd_config_path).expanduser()
        else:
            # Auto-detect from cwd, respecting BMAD_ORIGINAL_CWD env var
            # (set by dashboard subprocess to preserve original working directory)
            from bmad_assist.core.io import get_original_cwd

            cwd_path = get_original_cwd()
            resolved_cwd_config = cwd_path / PROJECT_CONFIG_NAME
            # Only use if different from project path (don't load twice)
            if cwd_path.resolve() == resolved_project.resolve():
                resolved_cwd_config = None

        if resolved_cwd_config is not None:
            cwd_exists = resolved_cwd_config.exists() and resolved_cwd_config.is_file()

    project_config_path = resolved_project / PROJECT_CONFIG_NAME
    project_exists = project_config_path.exists() and project_config_path.is_file()

    # Handle no config scenario
    if not global_exists and not cwd_exists and not project_exists:
        raise ConfigError("No configuration found. Run 'bmad-assist init' to create config.")

    global_data: dict[str, Any] = {}
    cwd_data: dict[str, Any] | None = None
    project_data: dict[str, Any] | None = None

    # Load global config if exists (tier 1 - base)
    if global_exists:
        try:
            global_data = _load_yaml_file(resolved_global)
        except ConfigError as e:
            # Clear singleton on YAML parse error to prevent stale state
            _config = None
            raise ConfigError(f"Failed to parse global config at {resolved_global}: {e}") from e

    # Load CWD config if exists (tier 2 - workspace overrides)
    if cwd_exists and resolved_cwd_config is not None:
        try:
            cwd_data = _load_yaml_file(resolved_cwd_config)
            logger.debug("Loaded CWD config from %s", resolved_cwd_config)
        except ConfigError as e:
            _config = None
            raise ConfigError(f"Failed to parse CWD config at {resolved_cwd_config}: {e}") from e

    # Load project config if exists (tier 3 - project overrides)
    if project_exists:
        try:
            project_data = _load_project_config(resolved_project)
            logger.debug("Loaded project config from %s", project_config_path)
        except ConfigError:
            # Clear singleton on YAML parse error to prevent stale state
            _config = None
            raise

    # Merge configurations: global <- cwd <- project
    merged_data = global_data
    if cwd_data is not None:
        merged_data = _deep_merge(merged_data, cwd_data)
    if project_data is not None:
        merged_data = _deep_merge(merged_data, project_data)

    # Validate and load
    try:
        return load_config(merged_data)
    except ConfigError as e:
        # Singleton already cleared by load_config on validation failure
        # Try to identify which config file caused the error
        error_source = _identify_error_source(
            str(e),
            global_data if global_exists else None,
            cwd_data,
            project_data,
            resolved_global if global_exists else None,
            resolved_cwd_config if cwd_exists else None,
            project_config_path if project_exists else None,
        )

        if error_source:
            raise ConfigError(f"Invalid configuration in {error_source}: {e}") from e

        # Fallback: list all sources if we can't identify the specific one
        sources = []
        if global_exists:
            sources.append(f"global ({resolved_global})")
        if cwd_exists and resolved_cwd_config is not None:
            sources.append(f"CWD ({resolved_cwd_config})")
        if project_exists:
            sources.append(f"project ({project_config_path})")

        if len(sources) > 1:
            merged = " + ".join(sources)
            raise ConfigError(f"Invalid configuration (merged from {merged}): {e}") from e
        elif sources:
            raise ConfigError(f"Invalid configuration in {sources[0]}: {e}") from e
        else:
            raise ConfigError(f"Invalid configuration: {e}") from e


def get_phase_timeout(config: Config, phase: str) -> int:
    """Get timeout for a specific workflow phase.

    Provides backward-compatible timeout resolution:
    1. If config.timeouts is set, use phase-specific or default timeout
    2. Otherwise, fall back to legacy config.timeout

    Args:
        config: Application configuration.
        phase: Phase name (e.g., 'validate_story', 'code_review').
               Hyphens are normalized to underscores.

    Returns:
        Timeout in seconds for the specified phase.

    Example:
        >>> timeout = get_phase_timeout(config, "validate_story")
        >>> timeout = get_phase_timeout(config, "code_review")
        >>> # Hyphens also work: get_phase_timeout(config, "code-review")

    """
    if config.timeouts is not None:
        return config.timeouts.get_timeout(phase)
    return config.timeout


def get_phase_retries(config: Config, phase: str) -> int | None:
    """Get retry count for a specific workflow phase on timeout.

    Args:
        config: Application configuration.
        phase: Phase name (e.g., 'validate_story', 'code_review').

    Returns:
        retries value (None = skip retry, 0 = infinite, N = specific count).

    Example:
        >>> retries = get_phase_retries(config, "dev_story")
        >>> if retries is None:
        ...     # No retry on timeout
        ...     pass
        >>> elif retries == 0:
        ...     # Infinite retry (until overall timeout)
        ...     pass
        >>> else:
        ...     # Specific number of retries
        ...     pass

    """
    if config.timeouts is not None:
        return config.timeouts.get_retries(phase)
    return None  # No retry by default for legacy config


def reload_config(project_path: Path | None = None) -> Config:
    """Reload configuration singleton without restart.

    This function performs an atomic swap of the global config singleton,
    allowing configuration changes to take effect without restarting
    the application.

    Args:
        project_path: Path to project directory for merging with global config.
            If None, only global config is loaded.

    Returns:
        The new Config instance after reload.

    Raises:
        ConfigError: If configuration loading or validation fails.

    Note:
        - Running tasks continue with old config (Python GC keeps reference)
        - New tasks use new config immediately
        - Thread-safe: uses simple assignment (Python GIL protects)
        - Clears schema cache to ensure fresh schema on next call

    Example:
        >>> reload_config()  # Reload global config only
        Config(providers=...)

        >>> reload_config(Path("/path/to/project"))  # Reload with project override
        Config(providers=...)

    """
    global _config

    # Import here to avoid circular dependency
    from bmad_assist.core.config.loop_config import _reset_loop_config
    from bmad_assist.core.config.schema import get_config_schema

    if project_path is not None:
        new_config = load_config_with_project(
            project_path=project_path,
            global_config_path=GLOBAL_CONFIG_PATH,
        )
    else:
        new_config = load_global_config(GLOBAL_CONFIG_PATH)

    # Atomic swap of singleton
    _config = new_config

    # Clear schema cache to ensure fresh schema reflects new config
    get_config_schema.cache_clear()

    # Reset loop config singleton so it gets reloaded on next access
    _reset_loop_config()

    logger.info("Configuration reloaded")

    return _config


class ParallelDelayError(ValueError):
    """Invalid parallel_delay configuration."""

    pass


def parse_parallel_delay(value: str | float | None) -> float:
    """Parse parallel_delay config value.

    Returns delay in seconds. If range (e.g., '0.5-1.5'), returns random value.
    Warns if > 5.0 seconds.

    IMPORTANT: Call this at RUNTIME (per-invocation), not at config load time,
    to ensure range values are randomized for each parallel call.

    Args:
        value: Fixed delay (float/int), range string ('min-max'), or None.

    Returns:
        Delay in seconds.

    Raises:
        ParallelDelayError: If value is negative, malformed, or invalid.

    Example:
        >>> parse_parallel_delay(1.0)
        1.0
        >>> parse_parallel_delay('0.5-1.5')  # Returns random value in range
        0.823...
        >>> parse_parallel_delay(None)
        1.0

    """
    if value is None:
        return 1.0

    try:
        if isinstance(value, (int, float)):
            delay = float(value)
        elif isinstance(value, str) and "-" in value:
            parts = value.split("-")
            if len(parts) != 2:
                raise ParallelDelayError(
                    f"Invalid range format: {value!r}. Use 'min-max' (e.g., '0.5-1.5')"
                )
            min_val, max_val = float(parts[0]), float(parts[1])
            if min_val < 0 or max_val < 0:
                raise ParallelDelayError(f"Negative delay not allowed: {value!r}")
            if min_val > max_val:
                raise ParallelDelayError(f"Min > max in range: {value!r}")
            delay = random.uniform(min_val, max_val)
        else:
            delay = float(value)
    except ValueError as e:
        raise ParallelDelayError(f"Invalid parallel_delay value: {value!r}") from e

    # Validate non-negative
    if delay < 0:
        raise ParallelDelayError(f"Negative delay not allowed: {delay}")

    if delay > 5.0:
        logger.warning("parallel_delay > 5s may cause slow multi-LLM phases")

    return delay
