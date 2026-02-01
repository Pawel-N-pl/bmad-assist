"""Tests for DiscordProvider.

Tests configuration, API integration, embed formatting (Epic 21 format),
error handling, and retry with backoff.
"""

import httpx
import pytest
from pytest_httpx import HTTPXMock

from bmad_assist.notifications.discord import (
    COLOR_HIGH_PRIORITY,
    COLOR_NORMAL,
    DiscordProvider,
    _format_embed,
    _is_retryable_error,
)
from bmad_assist.notifications.events import (
    AnomalyDetectedPayload,
    ErrorOccurredPayload,
    EventType,
    PhaseCompletedPayload,
    QueueBlockedPayload,
    StoryCompletedPayload,
    StoryStartedPayload,
)


class TestDiscordProviderClass:
    """Test DiscordProvider class structure."""

    def test_provider_name_returns_discord(self) -> None:
        """Test provider_name property returns 'discord'."""
        provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/123/abc")
        assert provider.provider_name == "discord"

    def test_inherits_from_notification_provider(self) -> None:
        """Test DiscordProvider inherits from NotificationProvider."""
        from bmad_assist.notifications.base import NotificationProvider

        provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/123/abc")
        assert isinstance(provider, NotificationProvider)

    def test_credentials_from_constructor(self) -> None:
        """Test webhook URL loaded from constructor parameter."""
        provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/123/secret-token")
        assert provider._webhook_url == "https://discord.com/api/webhooks/123/secret-token"

    def test_credentials_valid_when_set(self) -> None:
        """Test _credentials_valid is True when webhook_url set."""
        provider = DiscordProvider(webhook_url="https://discord.com/api/webhooks/123/abc")
        assert provider._credentials_valid is True

    def test_credentials_invalid_when_unset(self) -> None:
        """Test _credentials_valid is False when webhook_url not set."""
        provider = DiscordProvider()
        assert provider._credentials_valid is False

    def test_credentials_invalid_when_empty_string(self) -> None:
        """Test _credentials_valid is False when webhook_url is empty string."""
        provider = DiscordProvider(webhook_url="")
        assert provider._credentials_valid is False

    def test_logs_warning_when_credentials_missing(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test warning logged when webhook URL not configured."""
        with caplog.at_level("WARNING"):
            DiscordProvider()
        assert "webhook not configured" in caplog.text.lower()

    def test_repr_masks_webhook_url(self) -> None:
        """Test __repr__ masks the webhook URL to prevent credential leakage."""
        provider = DiscordProvider(
            webhook_url="https://discord.com/api/webhooks/123456789/secret-token-here"
        )
        result = repr(provider)
        assert "DiscordProvider" in result
        assert "***" in result
        # Smart masking: shows service identifier but masks secrets
        assert "discord.com/api/webhooks/***" in result
        # Webhook ID and token should NOT be visible
        assert "123456789" not in result
        assert "secret-token-here" not in result

    def test_repr_when_not_configured(self) -> None:
        """Test __repr__ shows 'not configured' when webhook URL not set."""
        provider = DiscordProvider()
        result = repr(provider)
        assert "(not configured)" in result


class TestFormatEmbed:
    """Test Epic 21 embed formatting - uses description instead of fields."""

    def test_embed_uses_formatter_for_description(self) -> None:
        """Test embed description uses format_notification() output."""
        payload = StoryStartedPayload(
            project="test-project", epic=15, story="15-1", phase="DEV_STORY"
        )
        embed = _format_embed(EventType.STORY_STARTED, payload)

        # Embed should have description instead of fields
        assert "description" in embed
        # Description should contain Epic 21 format (story ID without epic duplication)
        desc = embed["description"]
        assert "15.1" in desc  # Story ID format (no epic duplication)
        # Should NOT contain old verbose format markers
        assert "Project:" not in desc
        assert "Epic:" not in desc

    def test_embed_has_no_fields_array(self) -> None:
        """Test embed has NO fields array per AC2."""
        payload = StoryStartedPayload(
            project="test-project", epic=15, story="15-1", phase="DEV_STORY"
        )
        embed = _format_embed(EventType.STORY_STARTED, payload)

        # Per AC2: remove embed fields array entirely
        assert "fields" not in embed

    def test_embed_has_correct_color_normal(self) -> None:
        """Test embed color is blue for normal priority events."""
        payload = StoryStartedPayload(
            project="test-project", epic=15, story="15-1", phase="DEV_STORY"
        )
        embed = _format_embed(EventType.STORY_STARTED, payload)

        assert embed["color"] == COLOR_NORMAL  # Blue

    def test_embed_has_correct_color_high_priority(self) -> None:
        """Test embed color is red for high priority events."""
        payload = ErrorOccurredPayload(
            project="test-project",
            epic=15,
            story="15-1",
            error_type="ProviderError",
            message="API timeout",
            stack_trace=None,
        )
        embed = _format_embed(EventType.ERROR_OCCURRED, payload)

        assert embed["color"] == COLOR_HIGH_PRIORITY  # Red

    def test_embed_has_timestamp(self) -> None:
        """Test embed includes ISO8601 timestamp."""
        payload = StoryStartedPayload(
            project="test-project", epic=15, story="15-1", phase="DEV_STORY"
        )
        embed = _format_embed(EventType.STORY_STARTED, payload)

        assert "timestamp" in embed
        # ISO8601 format check
        assert "T" in embed["timestamp"]

    def test_embed_has_no_title(self) -> None:
        """Test embed has NO title - all info is in compact description."""
        payload = StoryStartedPayload(
            project="test-project", epic=15, story="15-1", phase="DEV_STORY"
        )
        embed = _format_embed(EventType.STORY_STARTED, payload)

        # Per Epic 21 format changes: title removed, all info in description
        assert "title" not in embed

    def test_embed_multiline_description(self) -> None:
        """Test multi-line notifications in description."""
        payload = StoryCompletedPayload(
            project="test-project",
            epic=12,
            story="Status codes",
            duration_ms=180000,
            outcome="Missing tests",
        )
        embed = _format_embed(EventType.STORY_COMPLETED, payload)

        # Failure format: two lines with "→" on second line
        desc = embed["description"]
        assert "\n" in desc
        assert "→" in desc
        assert "Missing tests" in desc

    def test_embed_success_format(self) -> None:
        """Test success format in embed description."""
        payload = StoryCompletedPayload(
            project="test-project",
            epic=12,
            story="Status codes",
            duration_ms=180000,
            outcome="success",
        )
        embed = _format_embed(EventType.STORY_COMPLETED, payload)

        desc = embed["description"]
        assert "✓" in desc  # Success checkmark
        assert "3m" in desc  # Duration formatted

    def test_formatter_exception_triggers_fallback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test formatter exception triggers fallback format."""
        import bmad_assist.notifications.discord as discord_module

        # Mock format_notification to raise
        def mock_format(*args: object, **kwargs: object) -> str:
            raise ValueError("Test exception")

        monkeypatch.setattr(discord_module, "format_notification", mock_format)

        payload = StoryStartedPayload(project="test", epic=1, story="1", phase="DEV")
        with caplog.at_level("WARNING"):
            embed = _format_embed(EventType.STORY_STARTED, payload)

        # Should return fallback format in description
        assert "story_started" in embed["description"]
        assert "StoryStartedPayload" in embed["description"]
        # Should log warning
        assert "Formatter error" in caplog.text

    def test_all_existing_event_types_format_correctly(self) -> None:
        """Test all 6 existing event types format without error."""
        # STORY_STARTED
        embed1 = _format_embed(
            EventType.STORY_STARTED,
            StoryStartedPayload(project="p", epic=1, story="s", phase="DEV"),
        )
        assert embed1["description"]  # Not empty

        # STORY_COMPLETED
        embed2 = _format_embed(
            EventType.STORY_COMPLETED,
            StoryCompletedPayload(
                project="p", epic=1, story="s", duration_ms=1000, outcome="success"
            ),
        )
        assert embed2["description"]

        # PHASE_COMPLETED
        embed3 = _format_embed(
            EventType.PHASE_COMPLETED,
            PhaseCompletedPayload(project="p", epic=1, story="s", phase="DEV", next_phase="REVIEW"),
        )
        assert embed3["description"]

        # ANOMALY_DETECTED
        embed4 = _format_embed(
            EventType.ANOMALY_DETECTED,
            AnomalyDetectedPayload(
                project="p",
                epic=1,
                story="s",
                anomaly_type="test",
                context="ctx",
                suggested_actions=[],
            ),
        )
        assert embed4["description"]

        # QUEUE_BLOCKED
        embed5 = _format_embed(
            EventType.QUEUE_BLOCKED,
            QueueBlockedPayload(project="p", epic=1, story="s", reason="blocked", waiting_tasks=5),
        )
        assert embed5["description"]

        # ERROR_OCCURRED
        embed6 = _format_embed(
            EventType.ERROR_OCCURRED,
            ErrorOccurredPayload(
                project="p", epic=1, story="s", error_type="E", message="m", stack_trace=None
            ),
        )
        assert embed6["description"]

    def test_infrastructure_event_types_format_correctly(self) -> None:
        """Test 4 new infrastructure event types format correctly."""
        from bmad_assist.notifications.events import (
            CLICrashedPayload,
            FatalErrorPayload,
            TimeoutWarningPayload,
        )

        # TIMEOUT_WARNING
        embed1 = _format_embed(
            EventType.TIMEOUT_WARNING,
            TimeoutWarningPayload(
                project="p",
                epic=1,
                story="s",
                tool_name="claude-code",
                elapsed_ms=3000000,
                limit_ms=3600000,
                remaining_ms=600000,
            ),
        )
        assert embed1["description"]
        assert "10m" in embed1["description"]  # remaining time formatted

        # CLI_CRASHED (not recovered)
        embed2 = _format_embed(
            EventType.CLI_CRASHED,
            CLICrashedPayload(
                project="p",
                epic=1,
                story="s",
                tool_name="claude-code",
                exit_code=1,
                signal=None,
                attempt=3,
                max_attempts=3,
                recovered=False,
            ),
        )
        assert embed2["description"]
        assert "3/3" in embed2["description"]

        # CLI_RECOVERED
        embed3 = _format_embed(
            EventType.CLI_RECOVERED,
            CLICrashedPayload(
                project="p",
                epic=1,
                story="s",
                tool_name="claude-code",
                exit_code=None,
                signal=9,
                attempt=2,
                max_attempts=3,
                recovered=True,
            ),
        )
        assert embed3["description"]
        assert "2/3" in embed3["description"]

        # FATAL_ERROR
        embed4 = _format_embed(
            EventType.FATAL_ERROR,
            FatalErrorPayload(
                project="p",
                epic=1,
                story="s",
                exception_type="KeyError",
                message="key not found",
                location="state.py:142",
            ),
        )
        assert embed4["description"]
        assert "KeyError" in embed4["description"]


class TestIsRetryableError:
    """Test _is_retryable_error helper function."""

    def test_timeout_exception_is_retryable(self) -> None:
        """Test httpx.TimeoutException is retryable."""
        exc = httpx.TimeoutException("Connection timed out")
        assert _is_retryable_error(None, exc) is True

    def test_request_error_is_retryable(self) -> None:
        """Test httpx.RequestError is retryable."""
        request = httpx.Request("POST", "https://discord.com/api/webhooks/test")
        exc = httpx.RequestError("Network error", request=request)
        assert _is_retryable_error(None, exc) is True

    def test_connect_error_is_retryable(self) -> None:
        """Test httpx.ConnectError (subclass of RequestError) is retryable."""
        request = httpx.Request("POST", "https://discord.com/api/webhooks/test")
        exc = httpx.ConnectError("Connection refused", request=request)
        assert _is_retryable_error(None, exc) is True

    def test_status_429_is_retryable(self) -> None:
        """Test HTTP 429 rate limit is retryable."""
        assert _is_retryable_error(429, None) is True

    def test_status_500_is_retryable(self) -> None:
        """Test HTTP 500 server error is retryable."""
        assert _is_retryable_error(500, None) is True

    def test_status_502_is_retryable(self) -> None:
        """Test HTTP 502 bad gateway is retryable."""
        assert _is_retryable_error(502, None) is True

    def test_status_503_is_retryable(self) -> None:
        """Test HTTP 503 service unavailable is retryable."""
        assert _is_retryable_error(503, None) is True

    def test_status_400_not_retryable(self) -> None:
        """Test HTTP 400 bad request is NOT retryable."""
        assert _is_retryable_error(400, None) is False

    def test_status_401_not_retryable(self) -> None:
        """Test HTTP 401 unauthorized is NOT retryable."""
        assert _is_retryable_error(401, None) is False

    def test_status_403_not_retryable(self) -> None:
        """Test HTTP 403 forbidden is NOT retryable."""
        assert _is_retryable_error(403, None) is False

    def test_status_404_not_retryable(self) -> None:
        """Test HTTP 404 not found is NOT retryable."""
        assert _is_retryable_error(404, None) is False

    def test_generic_exception_not_retryable(self) -> None:
        """Test generic Exception is NOT retryable."""
        exc = ValueError("Some error")
        assert _is_retryable_error(None, exc) is False

    def test_both_none_not_retryable(self) -> None:
        """Test when both status_code and exception are None."""
        assert _is_retryable_error(None, None) is False


class TestSendMethod:
    """Test send() method behavior."""

    @pytest.fixture
    def discord_provider(self) -> DiscordProvider:
        """Create DiscordProvider with test credentials."""
        return DiscordProvider(webhook_url="https://discord.com/api/webhooks/123/test-token")

    @pytest.fixture
    def story_started_payload(self) -> StoryStartedPayload:
        """Sample StoryStartedPayload."""
        return StoryStartedPayload(project="test-project", epic=15, story="15-1", phase="DEV_STORY")

    @pytest.mark.asyncio
    async def test_send_returns_false_when_credentials_unset(self) -> None:
        """Test send() returns False when webhook URL not set."""
        provider = DiscordProvider()
        payload = StoryStartedPayload(
            project="test-project", epic=15, story="15-1", phase="DEV_STORY"
        )
        result = await provider.send(EventType.STORY_STARTED, payload)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_returns_false_when_credentials_empty(self) -> None:
        """Test send() returns False when webhook URL is empty string."""
        provider = DiscordProvider(webhook_url="")
        payload = StoryStartedPayload(
            project="test-project", epic=15, story="15-1", phase="DEV_STORY"
        )
        result = await provider.send(EventType.STORY_STARTED, payload)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success_http_204(
        self,
        discord_provider: DiscordProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test send() returns True on HTTP 204 No Content (Discord success)."""
        httpx_mock.add_response(
            url="https://discord.com/api/webhooks/123/test-token",
            method="POST",
            status_code=204,
        )
        result = await discord_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_success_http_200(
        self,
        discord_provider: DiscordProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test send() returns True on HTTP 200 (also valid success)."""
        httpx_mock.add_response(
            url="https://discord.com/api/webhooks/123/test-token",
            method="POST",
            status_code=200,
            json={},
        )
        result = await discord_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_failure_http_400(
        self,
        discord_provider: DiscordProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test send() returns False on HTTP 400 (no retry)."""
        httpx_mock.add_response(
            url="https://discord.com/api/webhooks/123/test-token",
            method="POST",
            status_code=400,
            json={"message": "Bad Request", "code": 50006},
        )
        with caplog.at_level("ERROR"):
            result = await discord_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is False
        assert "400" in caplog.text

    @pytest.mark.asyncio
    async def test_send_no_retry_on_401(
        self,
        discord_provider: DiscordProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test send() does NOT retry on HTTP 401."""
        httpx_mock.add_response(
            url="https://discord.com/api/webhooks/123/test-token",
            method="POST",
            status_code=401,
            json={"message": "Unauthorized", "code": 0},
        )
        with caplog.at_level("ERROR"):
            result = await discord_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is False
        # Should only be 1 request (no retry)
        assert len(httpx_mock.get_requests()) == 1

    @pytest.mark.asyncio
    async def test_send_no_retry_on_403(
        self,
        discord_provider: DiscordProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test send() does NOT retry on HTTP 403."""
        httpx_mock.add_response(
            url="https://discord.com/api/webhooks/123/test-token",
            method="POST",
            status_code=403,
            json={"message": "Forbidden", "code": 0},
        )
        result = await discord_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is False
        # Should only be 1 request (no retry)
        assert len(httpx_mock.get_requests()) == 1

    @pytest.mark.asyncio
    async def test_send_retry_on_429(
        self,
        discord_provider: DiscordProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test send() retries on HTTP 429 rate limit."""
        # Mock asyncio.sleep to speed up test
        sleep_calls: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        import bmad_assist.notifications.discord as discord_module

        monkeypatch.setattr(discord_module.asyncio, "sleep", mock_sleep)

        # Return 429 twice, then 204
        httpx_mock.add_response(status_code=429)
        httpx_mock.add_response(status_code=429)
        httpx_mock.add_response(status_code=204)

        result = await discord_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is True
        # Should be 3 requests (initial + 2 retries)
        assert len(httpx_mock.get_requests()) == 3
        # Check exponential backoff delays: 1s, 2s
        assert sleep_calls == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_send_retry_on_timeout(
        self,
        discord_provider: DiscordProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test send() retries on timeout and returns False after max retries."""

        # Mock asyncio.sleep to speed up test
        async def mock_sleep(delay: float) -> None:
            pass

        import bmad_assist.notifications.discord as discord_module

        monkeypatch.setattr(discord_module.asyncio, "sleep", mock_sleep)

        # Always timeout (3 times)
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))

        with caplog.at_level("ERROR"):
            result = await discord_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is False
        # Should be 3 requests (initial + 2 retries)
        assert len(httpx_mock.get_requests()) == 3
        assert "failed after 3 attempts" in caplog.text

    @pytest.mark.asyncio
    async def test_send_logs_error_on_failure(
        self,
        discord_provider: DiscordProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test send() logs at ERROR level on failure."""
        httpx_mock.add_response(status_code=400, json={"message": "Bad Request"})
        with caplog.at_level("ERROR"):
            await discord_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert "Discord API error" in caplog.text

    @pytest.mark.asyncio
    async def test_send_posts_correct_json_epic21_format(
        self,
        discord_provider: DiscordProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test send() posts correct JSON with Epic 21 format embeds."""
        httpx_mock.add_response(status_code=204)
        await discord_provider.send(EventType.STORY_STARTED, story_started_payload)

        requests = httpx_mock.get_requests()
        assert len(requests) == 1
        request = requests[0]
        import json

        body = json.loads(request.content)
        assert "embeds" in body
        assert len(body["embeds"]) == 1
        embed = body["embeds"][0]

        # Verify Epic 21 format: description instead of fields
        assert "description" in embed
        assert "15.1" in embed["description"]  # Story ID format (no epic duplication)
        assert "fields" not in embed  # No fields per AC2

        # Title removed per Epic 21, all info in description
        assert "title" not in embed
        assert embed["color"] == COLOR_NORMAL

    @pytest.mark.asyncio
    async def test_send_never_raises_exception(
        self,
        discord_provider: DiscordProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test send() never raises exceptions - catches all errors."""

        # Mock asyncio.sleep to speed up test
        async def mock_sleep(delay: float) -> None:
            pass

        import bmad_assist.notifications.discord as discord_module

        monkeypatch.setattr(discord_module.asyncio, "sleep", mock_sleep)

        # Simulate network error
        request = httpx.Request("POST", "https://discord.com/api/webhooks/test")
        httpx_mock.add_exception(httpx.ConnectError("Connection refused", request=request))
        httpx_mock.add_exception(httpx.ConnectError("Connection refused", request=request))
        httpx_mock.add_exception(httpx.ConnectError("Connection refused", request=request))

        # Should not raise, just return False
        result = await discord_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_catches_unexpected_exception_during_format(
        self,
        discord_provider: DiscordProvider,
        story_started_payload: StoryStartedPayload,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test send() catches unexpected exceptions during embed formatting."""
        import bmad_assist.notifications.discord as discord_module

        # Mock _format_embed to raise unexpected error
        def mock_format_embed(*args: object, **kwargs: object) -> dict[str, object]:
            raise ValueError("Unexpected formatting error")

        monkeypatch.setattr(discord_module, "_format_embed", mock_format_embed)

        with caplog.at_level("ERROR"):
            result = await discord_provider.send(EventType.STORY_STARTED, story_started_payload)

        assert result is False
        assert "Notification failed" in caplog.text
        assert "discord" in caplog.text.lower()
        # F1 FIX: Only error type is logged, not the message (prevents secret leakage)
        assert "ValueError" in caplog.text
