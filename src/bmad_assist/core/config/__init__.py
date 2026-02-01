"""Pydantic configuration models and singleton access for bmad-assist.

This package provides type-safe configuration models with validation,
ensuring configuration errors are caught early with clear error messages.

Usage:
    from bmad_assist.core import get_config, load_config, load_global_config

    # Load configuration from file (typical startup)
    load_global_config()  # Loads from ~/.bmad-assist/config.yaml

    # Or load from dictionary (for testing/programmatic use)
    config_dict = {"providers": {"master": {"provider": "claude", "model": "opus_4"}}}
    load_config(config_dict)

    # Access configuration from anywhere
    config = get_config()
    print(config.providers.master.provider)  # "claude"
"""

# Constants
from bmad_assist.core.config.constants import (
    GLOBAL_CONFIG_PATH,
    MAX_CONFIG_SIZE,
    MAX_LOOP_CONFIG_PARENT_DEPTH,
    PROJECT_CONFIG_NAME,
)
from bmad_assist.core.config.env import (
    ENV_CREDENTIAL_KEYS,
    ENV_FILE_NAME,
    _check_env_file_permissions,
    _mask_credential,
    load_env_file,
)
from bmad_assist.core.config.loaders import (
    _deep_merge,
    _load_yaml_file,
    _reset_config,
    get_config,
    get_phase_timeout,
    load_config,
    load_config_with_project,
    load_global_config,
    reload_config,
)
from bmad_assist.core.config.loop_config import (
    _reset_loop_config,
    get_loop_config,
    load_loop_config,
    set_loop_config,
)

# Models (all from models/)
from bmad_assist.core.config.models import (
    ALL_KNOWN_PHASES,
    DEFAULT_LOOP_CONFIG,
    TEA_FULL_LOOP_CONFIG,
    MULTI_LLM_PHASES,
    SINGLE_LLM_PHASES,
    BenchmarkingConfig,
    BmadPathsConfig,
    CompilerConfig,
    Config,
    HelperProviderConfig,
    LoopConfig,
    MasterProviderConfig,
    MultiProviderConfig,
    PhaseModelsConfig,
    PlaywrightConfig,
    PlaywrightServerConfig,
    PowerPromptConfig,
    ProjectPathsConfig,
    ProviderConfig,
    QAConfig,
    SourceContextBudgetsConfig,
    SourceContextConfig,
    SourceContextExtractionConfig,
    SourceContextScoringConfig,
    SprintConfig,
    StrategicContextConfig,
    StrategicContextDefaultsConfig,
    StrategicContextWorkflowConfig,
    StrategicDocType,
    TimeoutsConfig,
    WarningsConfig,
    _create_story_defaults,
    _validate_story_defaults,
    _validate_story_synthesis_defaults,
    get_phase_provider_config,
)

# Schema (Dashboard)
from bmad_assist.core.config.schema import (
    DEFAULT_SECURITY_LEVEL,
    get_config_schema,
    get_field_security,
    get_field_widget,
)

# Re-export ConfigError for convenience (it's from exceptions, not config)
from bmad_assist.core.exceptions import ConfigError

__all__ = [
    # Constants
    "GLOBAL_CONFIG_PATH",
    "MAX_CONFIG_SIZE",
    "PROJECT_CONFIG_NAME",
    "MAX_LOOP_CONFIG_PARENT_DEPTH",
    "ENV_CREDENTIAL_KEYS",
    "ENV_FILE_NAME",
    "DEFAULT_SECURITY_LEVEL",
    # Internal utilities (exported for tests)
    "_deep_merge",
    "_load_yaml_file",
    # Exceptions (re-exported for convenience)
    "ConfigError",
    # Environment
    "load_env_file",
    "_check_env_file_permissions",
    "_mask_credential",
    # Models - Providers
    "MasterProviderConfig",
    "MultiProviderConfig",
    "HelperProviderConfig",
    "ProviderConfig",
    "PhaseModelsConfig",
    # Phase constants
    "SINGLE_LLM_PHASES",
    "MULTI_LLM_PHASES",
    "ALL_KNOWN_PHASES",
    "get_phase_provider_config",
    # Models - Paths
    "PowerPromptConfig",
    "BmadPathsConfig",
    "ProjectPathsConfig",
    # Models - Source Context
    "SourceContextBudgetsConfig",
    "SourceContextScoringConfig",
    "SourceContextExtractionConfig",
    "SourceContextConfig",
    # Models - Strategic Context
    "StrategicDocType",
    "StrategicContextDefaultsConfig",
    "StrategicContextWorkflowConfig",
    "StrategicContextConfig",
    "_create_story_defaults",
    "_validate_story_defaults",
    "_validate_story_synthesis_defaults",
    # Models - Features
    "CompilerConfig",
    "TimeoutsConfig",
    "BenchmarkingConfig",
    "PlaywrightServerConfig",
    "PlaywrightConfig",
    "QAConfig",
    # Models - Loop
    "LoopConfig",
    "SprintConfig",
    "WarningsConfig",
    "DEFAULT_LOOP_CONFIG",
    "TEA_FULL_LOOP_CONFIG",
    # Models - Main
    "Config",
    # Loaders & Singletons
    "get_config",
    "load_config",
    "load_global_config",
    "load_config_with_project",
    "reload_config",
    "get_phase_timeout",
    "_reset_config",
    # Loop Config
    "get_loop_config",
    "load_loop_config",
    "set_loop_config",
    "_reset_loop_config",
    # Schema
    "get_config_schema",
    "get_field_security",
    "get_field_widget",
]
