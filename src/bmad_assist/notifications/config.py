"""Configuration models for notification system.

This module provides Pydantic models for notification configuration:
- ProviderConfigItem: Configuration for a single notification provider
- NotificationConfig: Root configuration with enabled, providers, events

Environment variable substitution is supported via ${VAR} syntax.

Example:
    >>> from bmad_assist.notifications.config import NotificationConfig, ProviderConfigItem
    >>> config = NotificationConfig(
    ...     enabled=True,
    ...     providers=[ProviderConfigItem(type="telegram", bot_token="${TOKEN}", chat_id="123")],
    ...     events=["story_started", "story_completed"]
    ... )

"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from .events import EventType

logger = logging.getLogger(__name__)

# Pattern for env var substitution: ${VAR_NAME}
ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _substitute_env_vars(value: str) -> str:
    """Substitute ${VAR} patterns with environment variable values.

    Args:
        value: String potentially containing ${VAR} patterns.

    Returns:
        String with env vars substituted. Missing vars become empty string.

    """

    def replace_var(match: re.Match[str]) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name, "")
        if not env_value:
            logger.debug("Environment variable %s not set", var_name)
        return env_value

    return ENV_VAR_PATTERN.sub(replace_var, value)


class ProviderConfigItem(BaseModel):
    """Configuration for a single notification provider.

    Attributes:
        type: Provider type identifier ("telegram" or "discord").
        bot_token: Telegram bot token (required for telegram, supports ${VAR}).
        chat_id: Telegram chat ID (required for telegram, supports ${VAR}).
        webhook_url: Discord webhook URL (required for discord, supports ${VAR}).

    """

    model_config = ConfigDict(frozen=True)

    type: str = Field(
        ...,
        description="Provider type: telegram, discord",
        json_schema_extra={"security": "safe", "ui_widget": "dropdown"},
    )
    bot_token: str | None = Field(
        None,
        description="Telegram bot token (${VAR} supported)",
        json_schema_extra={"security": "dangerous"},
    )
    chat_id: str | None = Field(
        None,
        description="Telegram chat ID (${VAR} supported)",
        json_schema_extra={"security": "risky", "ui_widget": "text"},
    )
    webhook_url: str | None = Field(
        None,
        description="Discord webhook URL (${VAR} supported)",
        json_schema_extra={"security": "dangerous"},
    )

    @field_validator("bot_token", "chat_id", "webhook_url", mode="before")
    @classmethod
    def substitute_env_vars(cls, v: str | None) -> str | None:
        """Substitute ${VAR} patterns with environment variable values."""
        if v is None:
            return None
        return _substitute_env_vars(v)


class NotificationConfig(BaseModel):
    """Configuration for notification system.

    Attributes:
        enabled: Whether notifications are enabled.
        providers: List of provider configurations.
        events: List of event types to send notifications for.

    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Enable notifications",
        json_schema_extra={"security": "safe", "ui_widget": "toggle"},
    )
    providers: list[ProviderConfigItem] = Field(
        default_factory=list,
        description="List of notification provider configurations",
    )
    events: list[str] = Field(
        default_factory=list,
        description="Event types to send (e.g., ['story_started', 'error_occurred'])",
        json_schema_extra={"security": "safe", "ui_widget": "text"},
    )

    @property
    def enabled_events(self) -> frozenset[EventType]:
        """Return configured events as EventType frozenset."""
        # Import at runtime to avoid circular import
        from .events import EventType as _EventType

        result: set[_EventType] = set()
        for event_str in self.events:
            try:
                result.add(_EventType(event_str))
            except ValueError:
                logger.warning("Unknown event type in config: %s", event_str)
        return frozenset(result)
