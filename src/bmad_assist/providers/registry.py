"""Provider registry for string-based provider lookup.

This module provides functions to register, lookup, and list CLI providers
by name. Configuration files specify provider names as strings (e.g.,
`provider: "claude"`) which are resolved to concrete Provider instances.

Default Providers:
    - "claude": ClaudeSDKProvider (primary, uses claude-agent-sdk)
    - "claude-subprocess": ClaudeSubprocessProvider (benchmarking only)
    - "codex": CodexProvider (Codex CLI subprocess)
    - "gemini": GeminiProvider (Gemini CLI subprocess)

Example:
    >>> from bmad_assist.providers import get_provider, list_providers
    >>> provider = get_provider("claude")
    >>> isinstance(provider, BaseProvider)
    True
    >>> "claude" in list_providers()
    True

"""

import logging
from typing import TYPE_CHECKING

# Import directly from exceptions module to avoid loading entire core package
# which would trigger core/__init__.py -> run_loop -> heavy imports
from bmad_assist.core.exceptions import ConfigError

if TYPE_CHECKING:
    from bmad_assist.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Registry mapping: name -> provider class
_REGISTRY: dict[str, type["BaseProvider"]] = {}


def _init_default_providers() -> None:
    """Initialize registry with built-in providers.

    This function populates the registry with the default provider mappings.
    Called lazily on first registry access to avoid circular imports.

    Note: Uses dict.update() instead of assignment to preserve reference
    identity for code that imports _REGISTRY directly (e.g., tests).
    """
    # Import here to avoid circular imports
    from bmad_assist.providers.amp import AmpProvider
    from bmad_assist.providers.claude import ClaudeSubprocessProvider
    from bmad_assist.providers.claude_sdk import ClaudeSDKProvider
    from bmad_assist.providers.codex import CodexProvider
    from bmad_assist.providers.copilot import CopilotProvider
    from bmad_assist.providers.copilot_sdk import CopilotSDKProvider
    from bmad_assist.providers.cursor_agent import CursorAgentProvider
    from bmad_assist.providers.gemini import GeminiProvider
    from bmad_assist.providers.kimi import KimiProvider
    from bmad_assist.providers.opencode import OpenCodeProvider
    from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider

    # Use update() to preserve reference identity (not assignment)
    _REGISTRY.update(
        {
            "amp": AmpProvider,
            "claude": ClaudeSDKProvider,
            "claude-subprocess": ClaudeSubprocessProvider,
            "codex": CodexProvider,
            "copilot": CopilotProvider,
            "copilot-sdk": CopilotSDKProvider,
            "cursor-agent": CursorAgentProvider,
            "gemini": GeminiProvider,
            "kimi": KimiProvider,
            "opencode": OpenCodeProvider,
            "opencode-sdk": OpenCodeSDKProvider,
        }
    )
    logger.debug(
        "Initialized provider registry with %d providers: %s",
        len(_REGISTRY),
        ", ".join(sorted(_REGISTRY.keys())),
    )


def get_provider(name: str) -> "BaseProvider":
    """Get a provider instance by name.

    Creates and returns a new instance of the requested provider.
    Each call returns a fresh instance (providers are stateless).

    Args:
        name: Provider name (e.g., "claude", "codex", "gemini").

    Returns:
        New instance of the requested provider.

    Raises:
        ConfigError: If provider name is empty or not registered.
            Error message includes list of available providers.

    Example:
        >>> provider = get_provider("claude")
        >>> provider.provider_name
        'claude'

    """
    if not _REGISTRY:
        _init_default_providers()

    # Validate non-empty provider name
    if not name or not name.strip():
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise ConfigError(f"Provider name cannot be empty. Available: {available}")

    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys()))
        logger.debug("Provider lookup failed: '%s' not found", name)
        raise ConfigError(f"Unknown provider: '{name}'. Available: {available}")

    provider_class = _REGISTRY[name]
    logger.debug("Instantiating provider: %s -> %s", name, provider_class.__name__)
    return provider_class()


def list_providers() -> frozenset[str]:
    """List all registered provider names.

    Returns an immutable set of all registered provider names.
    The result is a frozenset to prevent accidental modification.

    Returns:
        Immutable frozenset of registered provider names.

    Example:
        >>> providers = list_providers()
        >>> "claude" in providers
        True
        >>> len(providers)
        4

    """
    if not _REGISTRY:
        _init_default_providers()
    return frozenset(_REGISTRY.keys())


def is_valid_provider(name: str) -> bool:
    """Check if a provider name is registered.

    Args:
        name: Provider name to check.

    Returns:
        True if provider is registered, False otherwise.

    Example:
        >>> is_valid_provider("claude")
        True
        >>> is_valid_provider("invalid")
        False

    """
    if not _REGISTRY:
        _init_default_providers()
    return name in _REGISTRY


def register_provider(name: str, provider_class: type["BaseProvider"]) -> None:
    """Register a custom provider.

    Adds a new provider to the registry. The provider class must inherit
    from BaseProvider. Duplicate registrations are not allowed.

    Args:
        name: Name to register the provider under (non-empty string).
        provider_class: Provider class (must inherit from BaseProvider).

    Raises:
        ConfigError: If name is empty or already registered.
        TypeError: If provider_class doesn't inherit from BaseProvider.

    Example:
        >>> class MyProvider(BaseProvider): ...
        >>> register_provider("my-custom", MyProvider)
        >>> provider = get_provider("my-custom")

    """
    if not _REGISTRY:
        _init_default_providers()

    # Validate non-empty provider name
    if not name or not name.strip():
        raise ConfigError("Provider name cannot be empty")

    # Import here to avoid circular imports
    from bmad_assist.providers.base import BaseProvider

    if not isinstance(provider_class, type) or not issubclass(provider_class, BaseProvider):
        raise TypeError(
            f"provider_class must be a subclass of BaseProvider, got {type(provider_class)}"
        )

    if name in _REGISTRY:
        raise ConfigError(f"Provider '{name}' is already registered")

    _REGISTRY[name] = provider_class
    logger.info("Registered custom provider: %s -> %s", name, provider_class.__name__)


def normalize_model_name(name: str) -> str:
    """Convert config model name to CLI format.

    Configuration files use underscores (YAML-friendly), CLI tools use hyphens.
    This function converts underscores to hyphens for CLI compatibility.

    Args:
        name: Model name from config (e.g., "opus_4", "claude_sonnet_4").

    Returns:
        CLI-formatted name (e.g., "opus-4", "claude-sonnet-4").

    Example:
        >>> normalize_model_name("opus_4")
        'opus-4'
        >>> normalize_model_name("claude_sonnet_4")
        'claude-sonnet-4'
        >>> normalize_model_name("")
        ''
        >>> normalize_model_name("opus-4")  # Already normalized
        'opus-4'

    """
    return name.replace("_", "-")


def denormalize_model_name(name: str) -> str:
    """Convert CLI model name to config format.

    CLI tools use hyphens, configuration files use underscores (YAML-friendly).
    This function converts hyphens to underscores for config compatibility.

    Args:
        name: Model name from CLI (e.g., "opus-4", "claude-sonnet-4").

    Returns:
        Config-formatted name (e.g., "opus_4", "claude_sonnet_4").

    Example:
        >>> denormalize_model_name("opus-4")
        'opus_4'
        >>> denormalize_model_name("claude-sonnet-4")
        'claude_sonnet_4'
        >>> denormalize_model_name("")
        ''
        >>> denormalize_model_name("opus_4")  # Already denormalized
        'opus_4'

    """
    return name.replace("-", "_")
