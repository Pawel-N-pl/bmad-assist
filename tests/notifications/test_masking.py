"""Tests for notification masking utilities."""

import pytest

from bmad_assist.notifications.masking import mask_token, mask_url


class TestMaskUrl:
    """Tests for mask_url()."""

    def test_masks_discord_webhook_smart(self) -> None:
        """Discord webhook URL masked after /webhooks/ marker."""
        url = "https://discord.com/api/webhooks/123456789/abcdefghijklmnop"
        result = mask_url(url)
        # Smart masking: show up to "/webhooks/" then mask
        assert result == "https://discord.com/api/webhooks/***"
        assert "123456789" not in result  # ID hidden
        assert "abcdef" not in result  # Token hidden

    def test_masks_telegram_bot_smart(self) -> None:
        """Telegram bot URL masked after /bot marker."""
        url = "https://api.telegram.org/bot123456:ABCdef/sendMessage"
        result = mask_url(url)
        assert result == "https://api.telegram.org/bot***"
        assert "123456" not in result
        assert "ABCdef" not in result

    def test_masks_unknown_url_fallback(self) -> None:
        """Unknown URL uses prefix_length fallback."""
        url = "https://example.com/very/long/path/with/secret/token"
        result = mask_url(url)
        # No marker found, uses 40 char prefix
        assert result == "https://example.com/very/long/path/with/***"
        assert "secret" not in result
        assert "token" not in result

    def test_masks_short_url_shows_domain(self) -> None:
        """F7 FIX: Short URL shows scheme+domain, not just ***."""
        result = mask_url("http://x.co/secret")
        assert result == "http://x.co/***"
        assert "secret" not in result

    def test_masks_short_url_no_path(self) -> None:
        """Short URL without path appends ***."""
        result = mask_url("http://x.co")
        assert result == "http://x.co***"

    def test_bot_in_domain_not_matched(self) -> None:
        """F5 FIX: /bot marker in domain is NOT matched (only in path)."""
        url = "https://mybot.example.com/api/secret"
        result = mask_url(url)
        # Should NOT match /bot in "mybot" - that's in domain
        # Should use prefix_length fallback or show domain+path
        assert "secret" not in result
        assert "mybot.example.com" in result  # Domain should be visible

    def test_webhooks_in_domain_not_matched(self) -> None:
        """F5 FIX: /webhooks/ in domain-like path is handled correctly."""
        url = "https://webhooks.example.com/api/secret"
        result = mask_url(url)
        assert "secret" not in result

    def test_none_url(self) -> None:
        """None returns not configured."""
        assert mask_url(None) == "(not configured)"

    def test_empty_url(self) -> None:
        """Empty string returns not configured."""
        assert mask_url("") == "(not configured)"

    def test_custom_prefix_length(self) -> None:
        """Custom prefix length is respected for URLs without markers."""
        url = "https://example.com/very/long/path/without/markers/here"
        result = mask_url(url, prefix_length=25)
        assert result == "https://example.com/very/***"

    def test_malformed_webhook_no_token(self) -> None:
        """Edge case: webhook URL without token after /webhooks/."""
        url = "https://discord.com/api/webhooks/"  # Incomplete - no ID/token
        result = mask_url(url)
        assert result == "https://discord.com/api/webhooks/***"

    def test_url_with_encoded_chars(self) -> None:
        """URL with encoded characters handles correctly."""
        url = "https://discord.com/api/webhooks/123%2F456/token"
        result = mask_url(url)
        # %2F is encoded /, but marker detection works on literal string
        assert result == "https://discord.com/api/webhooks/***"
        assert "token" not in result


class TestMaskToken:
    """Tests for mask_token()."""

    def test_masks_long_token(self) -> None:
        """Long token shows prefix + ***."""
        token = "123456789:ABCdefGHIjklMNO"
        result = mask_token(token)
        assert result == "12345***"
        assert "6789" not in result
        assert "ABC" not in result

    def test_masks_short_token(self) -> None:
        """Token shorter than prefix shows ***."""
        result = mask_token("1234")
        assert result == "***"

    def test_none_token(self) -> None:
        """None returns not configured."""
        assert mask_token(None) == "(not configured)"

    def test_empty_token(self) -> None:
        """Empty string returns not configured."""
        assert mask_token("") == "(not configured)"

    def test_custom_prefix_length(self) -> None:
        """Custom prefix length is respected."""
        token = "abcdefghij"
        result = mask_token(token, prefix_length=3)
        assert result == "abc***"


class TestNoSecretsInLogs:
    """Regression test: ensure no secrets appear in log output."""

    def test_discord_repr_no_webhook_token(self) -> None:
        """Discord __repr__ must not contain webhook token."""
        from bmad_assist.notifications.discord import DiscordProvider

        webhook = "https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyz1234567890ABCDEFGHIJKLMNOP"
        provider = DiscordProvider(webhook_url=webhook)
        repr_str = repr(provider)

        # Token part should not appear
        assert "abcdefghijklmnop" not in repr_str
        assert "ABCDEFGHIJKLMNOP" not in repr_str
        # But service identifier should be visible
        assert "discord.com" in repr_str

    def test_telegram_repr_no_bot_token(self) -> None:
        """Telegram __repr__ must not contain full bot token."""
        from bmad_assist.notifications.telegram import TelegramProvider

        token = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
        provider = TelegramProvider(bot_token=token, chat_id="999888777")
        repr_str = repr(provider)

        # Full token should not appear
        assert "ABCdefGHI" not in repr_str
        assert "jklMNOpqr" not in repr_str
        # First 5 chars may appear (masked prefix)
        assert "12345" in repr_str or "***" in repr_str


class TestExceptionLoggingNoSecrets:
    """F8 FIX: Verify exception messages (which may contain secrets) are NOT logged."""

    @pytest.mark.asyncio
    async def test_discord_exception_logs_type_not_message(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Discord send() must log exception TYPE, not str(e) which may contain URL."""
        import logging

        from bmad_assist.notifications.discord import DiscordProvider
        from bmad_assist.notifications.events import EventType, StoryStartedPayload

        webhook = "https://discord.com/api/webhooks/SECRET_ID/SECRET_TOKEN"
        provider = DiscordProvider(webhook_url=webhook)
        payload = StoryStartedPayload(
            project="test", epic=1, story="1-1", phase="DEV_STORY"
        )

        # Patch _format_embed to raise exception with secret in message
        import bmad_assist.notifications.discord as discord_module

        original_format = discord_module._format_embed

        def bad_format(*args, **kwargs):
            raise ValueError(f"Error processing {webhook}")  # Secret in exception!

        discord_module._format_embed = bad_format

        try:
            with caplog.at_level(logging.ERROR):
                result = await provider.send(EventType.STORY_STARTED, payload)

            assert result is False
            # Secret must NOT appear in any log
            assert "SECRET_ID" not in caplog.text
            assert "SECRET_TOKEN" not in caplog.text
            # But error type SHOULD appear
            assert "ValueError" in caplog.text
        finally:
            discord_module._format_embed = original_format

    @pytest.mark.asyncio
    async def test_telegram_exception_logs_type_not_message(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Telegram send() must log exception TYPE, not str(e) which may contain token."""
        import logging

        from bmad_assist.notifications.events import EventType, StoryStartedPayload
        from bmad_assist.notifications.telegram import TelegramProvider

        token = "SECRET_BOT_TOKEN_12345"
        provider = TelegramProvider(bot_token=token, chat_id="123")
        payload = StoryStartedPayload(
            project="test", epic=1, story="1-1", phase="DEV_STORY"
        )

        # Patch _format_message to raise exception with secret in message
        import bmad_assist.notifications.telegram as telegram_module

        original_format = telegram_module._format_message

        def bad_format(*args, **kwargs):
            raise ValueError(f"Error with token {token}")  # Secret in exception!

        telegram_module._format_message = bad_format

        try:
            with caplog.at_level(logging.ERROR):
                result = await provider.send(EventType.STORY_STARTED, payload)

            assert result is False
            # Secret must NOT appear in any log
            assert "SECRET_BOT_TOKEN" not in caplog.text
            # But error type SHOULD appear
            assert "ValueError" in caplog.text
        finally:
            telegram_module._format_message = original_format


class TestCircularImport:
    """F9 FIX: Verify lazy import in BaseHandler doesn't cause circular import."""

    def test_no_circular_import_basehandler_and_notifications(self) -> None:
        """BaseHandler and notifications can be imported without cycle."""
        # This import order might fail if lazy import in execute() doesn't work
        # Import both modules in sequence - should not raise ImportError
        from bmad_assist.notifications import dispatcher
        from bmad_assist.core.loop.handlers.base import BaseHandler

        assert BaseHandler is not None
        assert dispatcher is not None

    def test_no_circular_import_reverse_order(self) -> None:
        """Reverse import order also works."""
        from bmad_assist.core.loop.handlers.base import BaseHandler
        from bmad_assist.notifications import dispatcher

        assert BaseHandler is not None
        assert dispatcher is not None
