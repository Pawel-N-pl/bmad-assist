"""Telegram notification provider using Bot API.

This module implements the TelegramProvider class for sending notifications
via Telegram's sendMessage API with MarkdownV2 formatting.

Credentials are passed via NotificationConfig (with env var substitution at load time):
    - bot_token: Bot authentication token from BotFather
    - chat_id: Target chat/channel ID for notifications

Example:
    >>> import asyncio
    >>> from bmad_assist.notifications.telegram import TelegramProvider
    >>> from bmad_assist.notifications.events import EventType, StoryStartedPayload
    >>> provider = TelegramProvider(bot_token="123:ABC", chat_id="999")
    >>> payload = StoryStartedPayload(
    ...     project="my-project", epic=1, story="1-1", phase="DEV_STORY"
    ... )
    >>> asyncio.run(provider.send(EventType.STORY_STARTED, payload))
    True

"""

import asyncio
import logging

import httpx

from .base import NotificationProvider
from .events import EventPayload, EventType
from .formatter import format_notification
from .masking import mask_token

logger = logging.getLogger(__name__)

# Characters that need escaping in Telegram MarkdownV2 (including backslash itself)
_MARKDOWN_ESCAPE_CHARS: str = r"\_*[]()~`>#+-=|{}.!"


def _escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2.

    Args:
        text: Raw text to escape.

    Returns:
        Text with MarkdownV2 special characters escaped.

    """
    result = []
    for char in text:
        if char in _MARKDOWN_ESCAPE_CHARS:
            result.append(f"\\{char}")
        else:
            result.append(char)
    return "".join(result)


def _format_message(event: EventType, payload: EventPayload) -> str:
    """Format notification message using Epic 21 format with MarkdownV2 escaping.

    Uses the centralized format_notification() for message content,
    then applies MarkdownV2 escaping for Telegram compatibility.

    Args:
        event: Event type being sent.
        payload: Event payload with details.

    Returns:
        Formatted and escaped message string for Telegram.

    Note:
        If format_notification() raises an exception, returns a fallback
        format to maintain fire-and-forget guarantee (NFR12).

    """
    try:
        raw_message = format_notification(event, payload)
    except Exception as e:
        logger.warning("Formatter error for %s: %s", event.value, e)
        raw_message = f"{event.value} - {payload.__class__.__name__}"
    return _escape_markdown(raw_message)


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


class TelegramProvider(NotificationProvider):
    """Telegram notification provider using Bot API.

    Sends notifications via Telegram sendMessage API with MarkdownV2 formatting.
    Implements retry with exponential backoff for transient failures.

    Credentials can be passed via constructor or loaded from environment:
        - bot_token: Bot authentication token from BotFather
        - chat_id: Target chat/channel ID for notifications

    Example:
        >>> provider = TelegramProvider(bot_token="123:ABC", chat_id="999")
        >>> payload = StoryStartedPayload(
        ...     project="my-project", epic=1, story="1-1", phase="DEV_STORY"
        ... )
        >>> success = await provider.send(EventType.STORY_STARTED, payload)
        >>> print(success)
        True

    """

    TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
    TIMEOUT_SECONDS = 10.0
    MAX_RETRIES = 2
    BASE_RETRY_DELAY = 1.0  # seconds

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        """Initialize Telegram provider with credentials.

        Args:
            bot_token: Telegram bot token (required, passed from config).
            chat_id: Telegram chat ID (required, passed from config).

        Note:
            Credentials flow through NotificationConfig only (AC5).
            Environment variable substitution happens at config load time.

        """
        self._bot_token = bot_token or ""
        self._chat_id = chat_id or ""

        if not self._credentials_valid:
            logger.warning(
                "Telegram credentials not configured. "
                "Pass bot_token/chat_id or set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID."
            )

    @property
    def provider_name(self) -> str:
        """Return provider identifier."""
        return "telegram"

    @property
    def _credentials_valid(self) -> bool:
        """Check if required credentials are configured."""
        return bool(self._bot_token and self._chat_id)

    def __repr__(self) -> str:
        """Return string representation with masked credentials.

        Per project_context.md: Providers with credentials MUST implement
        __repr__ with masked values to prevent credential leakage in logs.
        """
        return (
            f"TelegramProvider("
            f"bot_token={mask_token(self._bot_token)}, "
            f"chat_id={mask_token(self._chat_id, prefix_length=3)}"
            f")"
        )

    async def _send_with_retry(self, message: str) -> bool:
        """Send message with retry on transient failures.

        Args:
            message: Formatted message to send.

        Returns:
            True if message sent successfully, False otherwise.

        """
        url = self.TELEGRAM_API_URL.format(token=self._bot_token)
        request_payload = {
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": "MarkdownV2",
        }

        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
            for attempt in range(self.MAX_RETRIES + 1):
                try:
                    response = await client.post(url, json=request_payload)

                    if response.status_code == 200:
                        return True

                    # Non-retryable client error
                    if not _is_retryable_error(response.status_code, None):
                        logger.error(
                            "Telegram API error: status=%s",
                            response.status_code,
                        )
                        logger.debug(
                            "Telegram API response body: %s",
                            response.text[:200] if response.text else "(empty)",
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
                        "Telegram request failed, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        self.MAX_RETRIES + 1,
                    )
                    await asyncio.sleep(delay)

        # All retries exhausted
        logger.error(
            "Telegram notification failed after %d attempts",
            self.MAX_RETRIES + 1,
        )
        logger.debug("Last error type: %s", type(last_error).__name__)
        return False

    async def send(self, event: EventType, payload: EventPayload) -> bool:
        """Send notification via Telegram.

        MUST NOT raise exceptions - all errors logged internally.

        Args:
            event: The event type being sent.
            payload: Validated event payload.

        Returns:
            True if notification sent successfully, False otherwise.

        """
        if not self._credentials_valid:
            logger.debug("Telegram credentials not configured, skipping notification")
            return False

        try:
            message = _format_message(event, payload)
            return await self._send_with_retry(message)
        except Exception as e:
            logger.error(
                "Telegram notification failed: event=%s, error_type=%s",
                event.value,
                type(e).__name__,  # F1 FIX: Only log type, not str(e)
            )
            return False
