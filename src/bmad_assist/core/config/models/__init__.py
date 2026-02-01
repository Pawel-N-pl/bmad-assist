"""Pydantic configuration models for bmad-assist.

This package contains all configuration model classes organized by domain.
All models are re-exported here for convenient imports.
"""

from bmad_assist.core.config.models.features import (
    AntipatternConfig,
    BenchmarkingConfig,
    CompilerConfig,
    PlaywrightConfig,
    PlaywrightServerConfig,
    QAConfig,
    TimeoutsConfig,
)
from bmad_assist.core.config.models.loop import (
    DEFAULT_LOOP_CONFIG,
    TEA_FULL_LOOP_CONFIG,
    LoopConfig,
    SprintConfig,
    WarningsConfig,
)
from bmad_assist.core.config.models.main import Config
from bmad_assist.core.config.models.paths import (
    BmadPathsConfig,
    PowerPromptConfig,
    ProjectPathsConfig,
)
from bmad_assist.core.config.models.providers import (
    ALL_KNOWN_PHASES,
    MULTI_LLM_PHASES,
    SINGLE_LLM_PHASES,
    HelperProviderConfig,
    MasterProviderConfig,
    MultiProviderConfig,
    PhaseModelsConfig,
    ProviderConfig,
    get_phase_provider_config,
)
from bmad_assist.core.config.models.source_context import (
    SourceContextBudgetsConfig,
    SourceContextConfig,
    SourceContextExtractionConfig,
    SourceContextScoringConfig,
)
from bmad_assist.core.config.models.strategic_context import (
    StrategicContextConfig,
    StrategicContextDefaultsConfig,
    StrategicContextWorkflowConfig,
    StrategicDocType,
    _create_story_defaults,
    _validate_story_defaults,
    _validate_story_synthesis_defaults,
)

__all__ = [
    # providers.py
    "MasterProviderConfig",
    "MultiProviderConfig",
    "HelperProviderConfig",
    "ProviderConfig",
    "PhaseModelsConfig",
    "SINGLE_LLM_PHASES",
    "MULTI_LLM_PHASES",
    "ALL_KNOWN_PHASES",
    "get_phase_provider_config",
    # paths.py
    "PowerPromptConfig",
    "BmadPathsConfig",
    "ProjectPathsConfig",
    # source_context.py
    "SourceContextBudgetsConfig",
    "SourceContextScoringConfig",
    "SourceContextExtractionConfig",
    "SourceContextConfig",
    # strategic_context.py
    "StrategicDocType",
    "StrategicContextDefaultsConfig",
    "StrategicContextWorkflowConfig",
    "StrategicContextConfig",
    "_create_story_defaults",
    "_validate_story_defaults",
    "_validate_story_synthesis_defaults",
    # features.py
    "AntipatternConfig",
    "CompilerConfig",
    "TimeoutsConfig",
    "BenchmarkingConfig",
    "PlaywrightServerConfig",
    "PlaywrightConfig",
    "QAConfig",
    # loop.py
    "LoopConfig",
    "SprintConfig",
    "WarningsConfig",
    "DEFAULT_LOOP_CONFIG",
    "TEA_FULL_LOOP_CONFIG",
    # main.py
    "Config",
]
