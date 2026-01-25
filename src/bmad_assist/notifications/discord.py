"""Discord notification provider using webhook embeds.

This module implements the DiscordProvider class for sending notifications
via Discord's Execute Webhook API with rich embed formatting.

Credentials are passed via NotificationConfig (with env var substitution at load time):
    - webhook_url: Full webhook URL from Discord server settings

Example:
    >>> import asyncio
    >>> from bmad_assist.notifications.discord import DiscordProvider
    >>> from bmad_assist.notifications.events import EventType, StoryStartedPayload
    >>> provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/...")
    >>> payload = StoryStartedPayload(
    ...     project="my-project", epic=1, story="1-1", phase="DEV_STORY"
    ... )
    >>> asyncio.run(provider.send(EventType.STORY_STARTED, payload))
    True

"""

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from .base import NotificationProvider
from .events import EventPayload, EventType, is_high_priority
from .formatter import format_notification

logger = logging.getLogger(__name__)

# Discord embed colors (decimal values)
COLOR_NORMAL = 3447003  # Blue #3498db
COLOR_HIGH_PRIORITY = 15158332  # Red #e74c3c


def _format_embed(event: EventType, payload: EventPayload) -> dict[str, object]:
    """Format notification as Discord embed using Epic 21 format.

    Uses the centralized format_notification() for the description,
    removing the verbose fields array in favor of compact info-dense format.

    Args:
        event: Event type being sent.
        payload: Event payload with details.

    Returns:
        Discord embed dict for JSON serialization.

    Note:
        If format_notification() raises an exception, uses a fallback
        description to maintain fire-and-forget guarantee (NFR12).

    """
    # Priority determines color
    is_high = is_high_priority(event)
    color = COLOR_HIGH_PRIORITY if is_high else COLOR_NORMAL

    # Use formatter for description with exception handling
    try:
        description = format_notification(event, payload)
    except Exception as e:
        logger.warning("Formatter error for %s: %s", event.value, e)
        description = f"{event.value} - {payload.__class__.__name__}"

    # Embed without verbose title - the formatted description contains all info
    return {
        "description": description,
        "color": color,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _is_retryable_error(
    status_code: int | None,
    exception: Exception | None,
) -> bool:
    """Determine if error is retryable.

    Retryable: network errors, timeouts, 429 rate limit, 5xx server errors.
    Not retryable: 400, 401, 403 (client errors).

    Args:
        status_code: HTTP status code, or None if exception occurred.
        exception: Exception that occurred, or None if status code available.

    Returns:
        True if error is transient and should be retried.

    """
    if exception is not None:
        return isinstance(exception, (httpx.TimeoutException, httpx.RequestError))
    if status_code is not None:
        return status_code == 429 or status_code >= 500
    return False


class DiscordProvider(NotificationProvider):
    """Discord notification provider using webhook embeds.

    Sends notifications via Discord Execute Webhook API with rich embeds.
    Implements retry with exponential backoff for transient failures.

    Credentials can be passed via constructor or loaded from environment:
        - webhook_url: Full webhook URL from Discord server settings

    Example:
        >>> provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/...")
        >>> payload = StoryStartedPayload(
        ...     project="my-project", epic=1, story="1-1", phase="DEV_STORY"
        ... )
        >>> success = await provider.send(EventType.STORY_STARTED, payload)
        >>> print(success)
        True

    """

    TIMEOUT_SECONDS = 10.0
    MAX_RETRIES = 2
    BASE_RETRY_DELAY = 1.0  # seconds

    def __init__(self, webhook_url: str | None = None) -> None:
        """Initialize Discord provider with credentials.

        Args:
            webhook_url: Discord webhook URL (required, passed from config).

        Note:
            Credentials flow through NotificationConfig only (AC5).
            Environment variable substitution happens at config load time.

        """
        self._webhook_url = webhook_url or ""

        if not self._credentials_valid:
            logger.warning(
                "Discord webhook not configured. Pass webhook_url or set DISCORD_WEBHOOK_URL."
            )

    @property
    def provider_name(self) -> str:
        """Return provider identifier."""
        return "discord"

    @property
    def _credentials_valid(self) -> bool:
        """Check if required credentials are configured."""
        return bool(self._webhook_url)

    def __repr__(self) -> str:
        """Return string representation with fully masked webhook URL."""
        url = self._webhook_url
        # Fully mask webhook URL - it contains sensitive token
        masked = "***" if url else "(not configured)"
        return f"DiscordProvider(webhook_url={masked})"

    async def _send_with_retry(self, embed: dict[str, object]) -> bool:
        """Send embed with retry on transient failures.

        Args:
            embed: Discord embed dict to send.

        Returns:
            True if message sent successfully, False otherwise.

        """
        request_payload = {"embeds": [embed]}

        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
            for attempt in range(self.MAX_RETRIES + 1):
                try:
                    response = await client.post(self._webhook_url, json=request_payload)

                    # Discord returns 204 No Content on success
                    if 200 <= response.status_code < 300:
                        return True

                    # Non-retryable client error
                    if not _is_retryable_error(response.status_code, None):
                        logger.error(
                            "Discord API error: status=%s, response=%s",
                            response.status_code,
                            response.text,
                        )
                        return False

                    # Retryable server error - store for logging
                    last_error = httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )

                except (httpx.TimeoutException, httpx.RequestError) as e:
                    last_error = e

                # Exponential backoff before retry
                if attempt < self.MAX_RETRIES:
                    delay = self.BASE_RETRY_DELAY * (2**attempt)
                    logger.debug(
                        "Discord request failed, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        self.MAX_RETRIES + 1,
                    )
                    await asyncio.sleep(delay)

        # All retries exhausted
        logger.error(
            "Discord notification failed after %d attempts: %s",
            self.MAX_RETRIES + 1,
            str(last_error),
        )
        return False

    async def send(self, event: EventType, payload: EventPayload) -> bool:
        """Send notification via Discord webhook.

        MUST NOT raise exceptions - all errors logged internally.

        Args:
            event: The event type being sent.
            payload: Validated event payload.

        Returns:
            True if notification sent successfully, False otherwise.

        """
        if not self._credentials_valid:
            logger.debug("Discord webhook not configured, skipping notification")
            return False

        try:
            embed = _format_embed(event, payload)
            return await self._send_with_retry(embed)
        except Exception as e:
            logger.error(
                "Notification failed: event=%s, provider=%s, error=%s",
                event,
                self.provider_name,
                str(e),
            )
            return False
