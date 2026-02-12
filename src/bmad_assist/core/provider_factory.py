"""Factory for creating configured provider instances.

This module provides functions to create provider instances from configuration
objects, automatically handling fallback wrapping and specific settings.
"""



from bmad_assist.core.config.models.providers import (
    HelperProviderConfig,
    MasterProviderConfig,
    MultiProviderConfig,
)
from bmad_assist.providers.base import BaseProvider
from bmad_assist.providers.fallback import ConfiguredProvider, FallbackProvider
from bmad_assist.providers.registry import get_provider


def create_provider(
    config: MasterProviderConfig | MultiProviderConfig | HelperProviderConfig,
) -> BaseProvider:
    """Create a provider instance from configuration.

    If the configuration includes fallbacks, returns a FallbackProvider wrapping
    the primary provider and its fallbacks. Otherwise returns the primary provider.

    Args:
        config: Provider configuration object.

    Returns:
        Configured BaseProvider instance.

    """
    # Create primary provider
    primary = get_provider(config.provider)

    # If no fallbacks, return primary directly
    # Note: we access the raw 'fallbacks' field from the pydantic model
    if not config.fallbacks:
        return primary

    # Create configured fallback providers
    fallbacks: list[ConfiguredProvider] = []
    for fb_config in config.fallbacks:
        # Recursively create the base provider for the fallback
        # This allows chains of fallbacks (e.g., Primary -> Fallback1 -> Fallback2)
        fb_provider = create_provider(fb_config)

        # Create ConfiguredProvider wrapper to bind specific model/settings
        configured = ConfiguredProvider(
            provider=fb_provider,
            model=fb_config.model,
            settings_file=fb_config.settings_path,
        )
        fallbacks.append(configured)

    return FallbackProvider(primary, fallbacks)
