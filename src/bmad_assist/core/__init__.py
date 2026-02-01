"""Core module for bmad-assist configuration and utilities.

This module provides:
- Configuration models and singleton access via get_config()
- File-based configuration loading via load_global_config()
- Custom exception hierarchy with BmadAssistError as base
- Main loop orchestration via run_loop()

NOTE: This module uses lazy loading for heavy imports (run_loop) to avoid
slow startup times. The loop module pulls in providers -> claude_sdk -> mcp/scipy.
"""

from typing import TYPE_CHECKING

# Light imports - exceptions are always fast
from bmad_assist.core.exceptions import (
    BmadAssistError,
    ConfigError,
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)

# Type hints only - no runtime import for heavy modules
if TYPE_CHECKING:
    from bmad_assist.core.config import (
        ENV_CREDENTIAL_KEYS as ENV_CREDENTIAL_KEYS,
        ENV_FILE_NAME as ENV_FILE_NAME,
        GLOBAL_CONFIG_PATH as GLOBAL_CONFIG_PATH,
        MAX_CONFIG_SIZE as MAX_CONFIG_SIZE,
        PROJECT_CONFIG_NAME as PROJECT_CONFIG_NAME,
        BmadPathsConfig as BmadPathsConfig,
        Config as Config,
        MasterProviderConfig as MasterProviderConfig,
        MultiProviderConfig as MultiProviderConfig,
        PowerPromptConfig as PowerPromptConfig,
        ProviderConfig as ProviderConfig,
        _check_env_file_permissions as _check_env_file_permissions,
        _mask_credential as _mask_credential,
        get_config as get_config,
        load_config as load_config,
        load_config_with_project as load_config_with_project,
        load_env_file as load_env_file,
        load_global_config as load_global_config,
        reload_config as reload_config,
    )
    from bmad_assist.core.config_editor import (
        ConfigEditor as ConfigEditor,
        ProvenanceTracker as ProvenanceTracker,
    )
    from bmad_assist.core.config_generator import (
        AVAILABLE_PROVIDERS as AVAILABLE_PROVIDERS,
        CONFIG_FILENAME as CONFIG_FILENAME,
        ConfigGenerator as ConfigGenerator,
        run_config_wizard as run_config_wizard,
    )
    from bmad_assist.core.loop import run_loop as run_loop

__all__ = [
    # Config constants
    "ENV_CREDENTIAL_KEYS",
    "ENV_FILE_NAME",
    "GLOBAL_CONFIG_PATH",
    "MAX_CONFIG_SIZE",
    "PROJECT_CONFIG_NAME",
    # Config models
    "BmadPathsConfig",
    "Config",
    "MasterProviderConfig",
    "MultiProviderConfig",
    "PowerPromptConfig",
    "ProviderConfig",
    # Config functions
    "get_config",
    "load_config",
    "load_config_with_project",
    "load_env_file",
    "load_global_config",
    "reload_config",
    # Config editor
    "ConfigEditor",
    "ProvenanceTracker",
    # Config generator
    "AVAILABLE_PROVIDERS",
    "CONFIG_FILENAME",
    "ConfigGenerator",
    "run_config_wizard",
    # Credential helpers
    "_check_env_file_permissions",
    "_mask_credential",
    # Exceptions
    "BmadAssistError",
    "ConfigError",
    "ProviderError",
    "ProviderExitCodeError",
    "ProviderTimeoutError",
    # Loop orchestration
    "run_loop",
]

# Lazy loading mapping
_lazy_imports = {
    # Config constants
    "ENV_CREDENTIAL_KEYS": ".config",
    "ENV_FILE_NAME": ".config",
    "GLOBAL_CONFIG_PATH": ".config",
    "MAX_CONFIG_SIZE": ".config",
    "PROJECT_CONFIG_NAME": ".config",
    # Config models
    "BmadPathsConfig": ".config",
    "Config": ".config",
    "MasterProviderConfig": ".config",
    "MultiProviderConfig": ".config",
    "PowerPromptConfig": ".config",
    "ProviderConfig": ".config",
    # Config functions
    "get_config": ".config",
    "load_config": ".config",
    "load_config_with_project": ".config",
    "load_env_file": ".config",
    "load_global_config": ".config",
    "reload_config": ".config",
    "_check_env_file_permissions": ".config",
    "_mask_credential": ".config",
    # Config editor
    "ConfigEditor": ".config_editor",
    "ProvenanceTracker": ".config_editor",
    # Config generator
    "AVAILABLE_PROVIDERS": ".config_generator",
    "CONFIG_FILENAME": ".config_generator",
    "ConfigGenerator": ".config_generator",
    "run_config_wizard": ".config_generator",
    # Loop orchestration (HEAVY - triggers providers -> mcp -> scipy)
    "run_loop": ".loop",
}


def __getattr__(name: str):
    """Lazy load attributes on first access."""
    if name in _lazy_imports:
        import importlib

        module = importlib.import_module(_lazy_imports[name], __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
