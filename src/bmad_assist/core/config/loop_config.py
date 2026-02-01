"""Loop configuration singleton and loading functions."""

import logging
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bmad_assist.core.config.constants import (
    GLOBAL_CONFIG_PATH,
    MAX_CONFIG_SIZE,
    MAX_LOOP_CONFIG_PARENT_DEPTH,
    PROJECT_CONFIG_NAME,
)
from bmad_assist.core.config.models.loop import (
    DEFAULT_LOOP_CONFIG,
    TEA_FULL_LOOP_CONFIG,
    LoopConfig,
)

logger = logging.getLogger(__name__)

# Module-level singleton for loop configuration
_loop_config: LoopConfig | None = None


def _load_yaml_file_for_loop(path: Path) -> dict[str, Any] | None:
    """Load YAML file for loop config extraction.

    Simplified version that returns None on any error instead of raising.
    """
    import yaml

    if not path.exists() or not path.is_file():
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            content = f.read(MAX_CONFIG_SIZE + 1)

        if len(content) > MAX_CONFIG_SIZE:
            logger.warning("Config file %s exceeds 1MB limit", path)
            return None

        parsed = yaml.safe_load(content)
        if not isinstance(parsed, dict):
            return None

        return parsed
    except Exception as e:
        logger.warning("Failed to parse %s: %s", path, e)
        return None


def _try_load_loop_config_from_yaml(path: Path) -> LoopConfig | None:
    """Attempt to load loop config from a YAML file.

    Returns None if file doesn't exist, doesn't contain 'loop' key,
    or validation fails. Logs warnings on validation failures.

    Args:
        path: Path to YAML file (bmad-assist.yaml or config.yaml).

    Returns:
        LoopConfig if found and valid, None otherwise.

    """
    data = _load_yaml_file_for_loop(path)
    if data is None:
        return None

    loop_data = data.get("loop")
    if loop_data is None:
        return None

    if not isinstance(loop_data, dict):
        logger.warning(
            "Invalid loop config in %s: expected dict, got %s", path, type(loop_data).__name__
        )
        return None

    try:
        config = LoopConfig.model_validate(loop_data)
        logger.debug("Loaded loop config from %s", path)
        return config
    except ValidationError as e:
        logger.warning("Loop config validation failed in %s: %s", path, e)
        return None


def load_loop_config(project_path: Path | None = None) -> LoopConfig:
    """Load loop configuration with fallback chain.

    Searches for loop config in the following order:
    1. {project_path}/bmad-assist.yaml -> check for 'loop:' key
    2. Parent directories (up to 10 levels) -> check for 'loop:' key
    3. ~/.bmad-assist/config.yaml -> check for 'loop:' key
    4. DEFAULT_LOOP_CONFIG constant

    Each file is only used if it contains a valid 'loop:' key with valid LoopConfig.
    Invalid YAML or validation errors log warnings and continue to next fallback.

    Detects symlink cycles by tracking visited directories (resolved paths).

    Args:
        project_path: Path to project directory. If None, uses current working directory.

    Returns:
        LoopConfig instance from first valid source, or DEFAULT_LOOP_CONFIG.

    Example:
        >>> config = load_loop_config(Path("/my/project"))
        >>> "create_story" in config.story
        True

    """
    if project_path is None:
        resolved_project = Path.cwd()
    else:
        resolved_project = Path(project_path).expanduser().resolve()
    visited: set[Path] = set()

    # Step 1: Check project-level bmad-assist.yaml
    if resolved_project.is_dir():
        project_config_path = resolved_project / PROJECT_CONFIG_NAME
        config = _try_load_loop_config_from_yaml(project_config_path)
        if config is not None:
            return config
        visited.add(resolved_project.resolve())

    # Step 2: Search parent directories (up to MAX_LOOP_CONFIG_PARENT_DEPTH levels)
    if resolved_project.is_dir():
        current = resolved_project.parent.resolve()
    else:
        current = resolved_project.resolve()
    depth = 0

    while depth < MAX_LOOP_CONFIG_PARENT_DEPTH:
        # Detect symlink cycle
        if current in visited:
            logger.warning("Symlink cycle detected at %s, stopping parent search", current)
            break

        visited.add(current)

        # Stop at filesystem root
        if current == current.parent:
            break

        parent_config_path = current / PROJECT_CONFIG_NAME
        config = _try_load_loop_config_from_yaml(parent_config_path)
        if config is not None:
            return config

        current = current.parent.resolve()
        depth += 1

    if depth >= MAX_LOOP_CONFIG_PARENT_DEPTH:
        logger.debug("Parent search stopped at max depth %d", MAX_LOOP_CONFIG_PARENT_DEPTH)

    # Step 3: Check global config (~/.bmad-assist/config.yaml)
    config = _try_load_loop_config_from_yaml(GLOBAL_CONFIG_PATH)
    if config is not None:
        return config

    # Step 4: Use default (check for --tea flag via env var)
    if os.environ.get("BMAD_TEA_LOOP") == "1":
        logger.debug("No loop config found, using TEA_FULL_LOOP_CONFIG (--tea flag)")
        return TEA_FULL_LOOP_CONFIG

    logger.debug("No loop config found, using DEFAULT_LOOP_CONFIG")
    return DEFAULT_LOOP_CONFIG


def get_loop_config() -> LoopConfig:
    """Get the loaded loop configuration singleton.

    For CLI use only - loads and caches loop config on first call.
    Dashboard should call load_loop_config() directly for hot-reload.

    Returns:
        The cached LoopConfig instance.

    Note:
        If config hasn't been loaded yet, loads from current working directory.
        To load from a specific project path, call load_loop_config() first.

    Example:
        >>> config = get_loop_config()
        >>> "create_story" in config.story
        True

    """
    global _loop_config

    if _loop_config is None:
        _loop_config = load_loop_config()

    return _loop_config


def _reset_loop_config() -> None:
    """Reset loop config singleton for testing purposes only.

    This function should only be used in tests to ensure clean state
    between test cases.
    """
    global _loop_config
    _loop_config = None


def set_loop_config(config: LoopConfig) -> None:
    """Set loop config singleton explicitly.

    Used by runner.py to set loop config at startup, ensuring
    all components use the same config instance.

    Args:
        config: LoopConfig instance to set as singleton.

    """
    global _loop_config
    _loop_config = config
