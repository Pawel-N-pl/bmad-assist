"""Fallback provider implementation.

This module provides the FallbackProvider which wraps a primary provider and
a list of fallback providers. It implements automatic failover when the
primary provider encounters transient errors (e.g., rate limits, timeouts).
"""

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers.base import (
    BaseProvider,
    ProviderResult,
    is_transient_error,
)

if TYPE_CHECKING:
    from bmad_assist.providers.tool_guard import ToolCallGuard

logger = logging.getLogger(__name__)


class ConfiguredProvider:
    """A provider with pre-configured settings.

    Wraps a BaseProvider instance with specific model and settings configuration.
    Used by FallbackProvider to invoke fallbacks with their specific configs.
    """

    def __init__(
        self,
        provider: BaseProvider,
        model: str | None = None,
        settings_file: Path | None = None,
    ) -> None:
        """Initialize with provider and optional overrides.

        Args:
            provider: The underlying provider to wrap.
            model: Optional model to override on invocation.
            settings_file: Optional settings file to override on invocation.

        """
        self.provider = provider
        self.model = model
        self.settings_file = settings_file

    def invoke(self, prompt: str, **kwargs: object) -> ProviderResult:
        """Invoke the provider with configured settings overriding defaults.

        Args:
            prompt: The prompt text.
            **kwargs: Arguments to pass to invoke. 'model' and 'settings_file'
                will be overridden by configured values if they exist.

        """
        # Create a copy of kwargs to modify
        invoke_kwargs = kwargs.copy()

        # Override model and settings_file if configured
        if self.model:
            invoke_kwargs["model"] = self.model
        if self.settings_file:
            invoke_kwargs["settings_file"] = self.settings_file

        return self.provider.invoke(prompt, **invoke_kwargs)  # type: ignore


class FallbackProvider(BaseProvider):
    """Provider wrapper that implements fallback logic.

    Wraps a primary provider and a list of fallback providers. Attempts to use
    the primary provider first. If it fails with a transient error (rate limit,
    timeout, etc.), it attempts to use the fallback providers in order.

    Attributes:
        primary: The primary provider instance.
        fallbacks: List of ConfiguredProvider instances to try in order.

    """

    def __init__(
        self,
        primary: BaseProvider,
        fallbacks: list[ConfiguredProvider],
    ) -> None:
        """Initialize with primary and fallback providers.

        Args:
            primary: The main provider to use.
            fallbacks: List of backup configured providers.

        """
        self.primary = primary
        self.fallbacks = fallbacks

    @property
    def provider_name(self) -> str:
        """Return provider name (proxies to primary)."""
        return self.primary.provider_name

    @property
    def default_model(self) -> str | None:
        """Return default model (proxies to primary)."""
        return self.primary.default_model

    def supports_model(self, model: str) -> bool:
        """Check if provider supports model (proxies to primary)."""
        return self.primary.supports_model(model)

    def cancel(self) -> None:
        """Cancel current operation on all providers."""
        self.primary.cancel()
        for fb in self.fallbacks:
            fb.provider.cancel()

    def invoke(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout: int | None = None,
        settings_file: Path | None = None,
        cwd: Path | None = None,
        disable_tools: bool = False,
        allowed_tools: list[str] | None = None,
        no_cache: bool = False,
        color_index: int | None = None,
        display_model: str | None = None,
        thinking: bool | None = None,
        cancel_token: threading.Event | None = None,
        reasoning_effort: str | None = None,
        guard: "ToolCallGuard | None" = None,
    ) -> ProviderResult:
        """Invoke provider with fallback logic.

        Attempts to invoke the primary provider. If it fails with a transient
        error, logs a warning and attempts the next provider in the fallback list.

        Args:
            prompt: The prompt text.
            model: Model identifier (passed to primary).
            **kwargs: Other arguments passed to invoke.

        Returns:
            ProviderResult from the first successful provider.

        Raises:
            ProviderError: If all providers fail. The exception from the
                last provider is raised.

        """
        last_error: Exception | None = None

        # 1. Try Primary
        try:
            logger.info("Invoking primary %s (model=%s)", self.primary.provider_name, model)
            return self.primary.invoke(
                prompt,
                model=model,
                timeout=timeout,
                settings_file=settings_file,
                cwd=cwd,
                disable_tools=disable_tools,
                allowed_tools=allowed_tools,
                no_cache=no_cache,
                color_index=color_index,
                display_model=display_model,
                thinking=thinking,
                cancel_token=cancel_token,
                reasoning_effort=reasoning_effort,
                guard=guard,
            )
        except (ProviderTimeoutError, ProviderExitCodeError) as e:
            if not self._is_transient(e):
                raise
            logger.warning("Primary provider failed with transient error: %s", e)
            last_error = e
        except (ProviderError, OSError) as e:
            logger.warning("Primary provider failed with operational error: %s", e)
            last_error = e

        # 2. Try Fallbacks
        for i, fallback in enumerate(self.fallbacks):
            try:
                logger.info(
                    "Invoking fallback %d/%d: %s (model=%s)",
                    i + 1,
                    len(self.fallbacks),
                    fallback.provider.provider_name,
                    fallback.model,
                )
                result = fallback.invoke(
                    prompt,
                    timeout=timeout,
                    cwd=cwd,
                    disable_tools=disable_tools,
                    allowed_tools=allowed_tools,
                    no_cache=no_cache,
                    color_index=color_index,
                    display_model=display_model,
                    thinking=thinking,
                    cancel_token=cancel_token,
                    reasoning_effort=reasoning_effort,
                    guard=guard,
                )
                logger.info(
                    "Fallback provider %s succeeded (model=%s)",
                    fallback.provider.provider_name,
                    fallback.model,
                )
                return result
            except (ProviderTimeoutError, ProviderExitCodeError) as e:
                if not self._is_transient(e):
                    logger.error("Fallback provider failed permanently: %s", e)
                    last_error = e
                    continue
                logger.warning("Fallback provider failed with transient error: %s", e)
                last_error = e
            except Exception as e:
                logger.warning("Fallback provider failed with unexpected error: %s", e)
                last_error = e

        # If we get here, all providers failed
        msg = f"All providers failed. Last error: {last_error}"
        logger.error(msg)
        if last_error:
            raise last_error
        raise ProviderError(msg)

    def _is_transient(self, e: Exception) -> bool:
        """Check if exception is transient."""
        if isinstance(e, ProviderTimeoutError):
            return True
        if isinstance(e, ProviderExitCodeError):
            return is_transient_error(e.stderr, e.exit_status)
        return False

    def parse_output(self, result: ProviderResult) -> str:
        """Parse output using the primary provider.

        We use the primary provider's parser because we assume fallbacks
        produce compatible output (text/json) that the primary expects.
        Most CLI providers just strip whitespace in parse_output.
        """
        return self.primary.parse_output(result)
