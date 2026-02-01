"""Notification system for bmad-assist.

This module provides the notification infrastructure including:
- EventType enum for all notification event types
- Pydantic payload models for validated event data
- NotificationProvider ABC for implementing notification backends
- TelegramProvider for sending notifications via Telegram Bot API
- DiscordProvider for sending notifications via Discord webhook embeds
- NotificationConfig for YAML configuration of notifications
- EventDispatcher for routing events to configured providers
- Global accessor functions (init_dispatcher, get_dispatcher, reset_dispatcher)
- format_duration for human-readable time formatting
- Workflow label resolution (get_workflow_icon, get_workflow_label, etc.)

Example:
    >>> from bmad_assist.notifications import (
    ...     EventType,
    ...     StoryStartedPayload,
    ...     NotificationProvider,
    ...     TelegramProvider,
    ...     DiscordProvider,
    ...     NotificationConfig,
    ...     EventDispatcher,
    ...     init_dispatcher,
    ...     get_dispatcher,
    ...     is_high_priority,
    ...     format_duration,
    ... )
    >>> is_high_priority(EventType.ERROR_OCCURRED)
    True
    >>> format_duration(2_820_000)  # 47 minutes
    '47m'

"""

from .base import NotificationProvider
from .config import NotificationConfig, ProviderConfigItem
from .discord import DiscordProvider
from .dispatcher import EventDispatcher, get_dispatcher, init_dispatcher, reset_dispatcher
from .events import (
    HIGH_PRIORITY_EVENTS,
    PAYLOAD_MODELS,
    SIGNAL_NAMES,
    AnomalyDetectedPayload,
    CLICrashedPayload,
    EpicCompletedPayload,
    ErrorOccurredPayload,
    EventPayload,
    EventType,
    FatalErrorPayload,
    PhaseCompletedPayload,
    ProjectCompletedPayload,
    QueueBlockedPayload,
    StoryCompletedPayload,
    StoryStartedPayload,
    TimeoutWarningPayload,
    get_signal_name,
    is_high_priority,
)
from .formatter import format_notification
from .telegram import TelegramProvider
from .time_format import format_duration
from .workflow_labels import (
    WorkflowNotificationConfig,
    clear_workflow_label_cache,
    get_workflow_icon,
    get_workflow_label,
    get_workflow_notification_config,
)

__all__ = [
    # Providers
    "NotificationProvider",
    "TelegramProvider",
    "DiscordProvider",
    # Events
    "EventType",
    "EventPayload",
    "StoryStartedPayload",
    "StoryCompletedPayload",
    "PhaseCompletedPayload",
    "AnomalyDetectedPayload",
    "QueueBlockedPayload",
    "ErrorOccurredPayload",
    # Completion events (Story standalone-03)
    "EpicCompletedPayload",
    "ProjectCompletedPayload",
    # Infrastructure events (Story 21.4)
    "TimeoutWarningPayload",
    "CLICrashedPayload",
    "FatalErrorPayload",
    "get_signal_name",
    "SIGNAL_NAMES",
    # Registry and helpers
    "PAYLOAD_MODELS",
    "HIGH_PRIORITY_EVENTS",
    "is_high_priority",
    # Configuration
    "NotificationConfig",
    "ProviderConfigItem",
    # Dispatcher
    "EventDispatcher",
    "init_dispatcher",
    "get_dispatcher",
    "reset_dispatcher",
    # Time formatting
    "format_duration",
    # Workflow labels
    "WorkflowNotificationConfig",
    "get_workflow_icon",
    "get_workflow_label",
    "get_workflow_notification_config",
    "clear_workflow_label_cache",
    # Message formatting
    "format_notification",
]
