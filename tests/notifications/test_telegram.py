"""Tests for TelegramProvider.

Tests AC1 (configuration), AC2 (API integration), AC3 (message formatting),
AC4 (error handling), and AC5 (retry with backoff).
"""

import httpx
import pytest
from pytest_httpx import HTTPXMock

from bmad_assist.notifications.events import (
    AnomalyDetectedPayload,
    ErrorOccurredPayload,
    EventType,
    PhaseCompletedPayload,
    QueueBlockedPayload,
    StoryCompletedPayload,
    StoryStartedPayload,
)
from bmad_assist.notifications.telegram import (
    TelegramProvider,
    _escape_markdown,
    _format_message,
    _is_retryable_error,
)


class TestTelegramProviderClass:
    """Test AC1: TelegramProvider class structure."""

    def test_provider_name_returns_telegram(self) -> None:
        """Test provider_name property returns 'telegram'."""
        provider = TelegramProvider(bot_token="test-token", chat_id="12345")
        assert provider.provider_name == "telegram"

    def test_inherits_from_notification_provider(self) -> None:
        """Test TelegramProvider inherits from NotificationProvider."""
        from bmad_assist.notifications.base import NotificationProvider

        provider = TelegramProvider(bot_token="test-token", chat_id="12345")
        assert isinstance(provider, NotificationProvider)

    def test_credentials_from_constructor(self) -> None:
        """Test credentials loaded from constructor parameters."""
        provider = TelegramProvider(bot_token="my-secret-token", chat_id="987654321")
        # Access private attributes for testing
        assert provider._bot_token == "my-secret-token"
        assert provider._chat_id == "987654321"

    def test_credentials_valid_when_both_set(self) -> None:
        """Test _credentials_valid is True when both params set."""
        provider = TelegramProvider(bot_token="token", chat_id="123")
        assert provider._credentials_valid is True

    def test_credentials_invalid_when_token_missing(self) -> None:
        """Test _credentials_valid is False when token missing."""
        provider = TelegramProvider(bot_token=None, chat_id="123")
        assert provider._credentials_valid is False

    def test_credentials_invalid_when_chat_id_missing(self) -> None:
        """Test _credentials_valid is False when chat_id missing."""
        provider = TelegramProvider(bot_token="token", chat_id=None)
        assert provider._credentials_valid is False

    def test_credentials_invalid_when_both_missing(self) -> None:
        """Test _credentials_valid is False when both missing."""
        provider = TelegramProvider()
        assert provider._credentials_valid is False

    def test_logs_warning_when_credentials_missing(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test warning logged when credentials not configured."""
        with caplog.at_level("WARNING"):
            TelegramProvider()
        assert "credentials not configured" in caplog.text.lower()

    def test_repr_masks_bot_token(self) -> None:
        """Test __repr__ masks credentials to prevent leakage."""
        provider = TelegramProvider(
            bot_token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            chat_id="999888777",
        )
        result = repr(provider)
        assert "TelegramProvider" in result
        # Token should show only first 5 chars then ***
        assert "12345***" in result
        # Full token should NOT be visible
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in result
        # Chat ID should be masked - only last 3 digits visible
        assert "***777" in result
        assert "999888777" not in result

    def test_repr_when_token_short(self) -> None:
        """Test __repr__ fully masks short tokens."""
        provider = TelegramProvider(bot_token="short", chat_id="123")
        result = repr(provider)
        assert "***" in result
        assert "short" not in result

    def test_repr_when_not_configured(self) -> None:
        """Test __repr__ shows 'not configured' when token not set."""
        provider = TelegramProvider()
        result = repr(provider)
        assert "(not configured)" in result


class TestEscapeMarkdown:
    """Test AC3: MarkdownV2 escaping function."""

    def test_escapes_asterisk(self) -> None:
        """Test asterisk is escaped."""
        assert _escape_markdown("*bold*") == "\\*bold\\*"

    def test_escapes_underscore(self) -> None:
        """Test underscore is escaped."""
        assert _escape_markdown("_italic_") == "\\_italic\\_"

    def test_escapes_brackets(self) -> None:
        """Test square brackets are escaped."""
        assert _escape_markdown("[link]") == "\\[link\\]"

    def test_escapes_parentheses(self) -> None:
        """Test parentheses are escaped."""
        assert _escape_markdown("(text)") == "\\(text\\)"

    def test_escapes_tilde(self) -> None:
        """Test tilde is escaped."""
        assert _escape_markdown("~strikethrough~") == "\\~strikethrough\\~"

    def test_escapes_backtick(self) -> None:
        """Test backtick is escaped."""
        assert _escape_markdown("`code`") == "\\`code\\`"

    def test_escapes_greater_than(self) -> None:
        """Test greater-than is escaped."""
        assert _escape_markdown(">quote") == "\\>quote"

    def test_escapes_hash(self) -> None:
        """Test hash is escaped."""
        assert _escape_markdown("#header") == "\\#header"

    def test_escapes_plus_minus_equals(self) -> None:
        """Test +, -, = are escaped."""
        assert _escape_markdown("+-=") == "\\+\\-\\="

    def test_escapes_pipe(self) -> None:
        """Test pipe is escaped."""
        assert _escape_markdown("|table|") == "\\|table\\|"

    def test_escapes_braces(self) -> None:
        """Test braces are escaped."""
        assert _escape_markdown("{var}") == "\\{var\\}"

    def test_escapes_dot(self) -> None:
        """Test dot is escaped."""
        assert _escape_markdown("file.txt") == "file\\.txt"

    def test_escapes_exclamation(self) -> None:
        """Test exclamation is escaped."""
        assert _escape_markdown("Hello!") == "Hello\\!"

    def test_plain_text_unchanged(self) -> None:
        """Test plain alphanumeric text is not modified."""
        assert _escape_markdown("hello world 123") == "hello world 123"

    def test_multiple_special_chars(self) -> None:
        """Test multiple special characters in one string."""
        assert _escape_markdown("Hello *world*!") == "Hello \\*world\\*\\!"

    def test_escapes_backslash(self) -> None:
        """Test backslash is escaped (MarkdownV2 escape character itself)."""
        assert _escape_markdown(r"C:\Windows\System32") == r"C:\\Windows\\System32"

    def test_empty_string(self) -> None:
        """Test empty string returns empty string."""
        assert _escape_markdown("") == ""


class TestFormatMessage:
    """Test Epic 21 format integration with MarkdownV2 escaping."""

    def test_format_uses_formatter(self) -> None:
        """Test _format_message() uses format_notification() from formatter."""
        payload = StoryStartedPayload(
            project="test-project", epic=15, story="15-1", phase="DEV_STORY"
        )
        message = _format_message(EventType.STORY_STARTED, payload)
        # Epic 21 format: "{icon} {label} {status} {story}" - not old verbose format
        # Should NOT contain old format markers like "Project:" or "Epic:"
        assert "Project:" not in message
        assert "Epic:" not in message

    def test_format_success_with_checkmark(self) -> None:
        """Test success format includes ✓ checkmark (escaped for Telegram)."""
        payload = StoryCompletedPayload(
            project="test-project",
            epic=12,
            story="Status codes",
            duration_ms=180000,
            outcome="success",
        )
        message = _format_message(EventType.STORY_COMPLETED, payload)
        # Success format: "{icon} {label} ✓ {story} {time}"
        assert "✓" in message  # Checkmark present
        assert "3m" in message  # Duration formatted as 3m

    def test_format_failure_has_two_lines(self) -> None:
        """Test failure format has header + error line."""
        payload = StoryCompletedPayload(
            project="test-project",
            epic=12,
            story="Status codes",
            duration_ms=180000,
            outcome="Missing tests",
        )
        message = _format_message(EventType.STORY_COMPLETED, payload)
        # Failure format: two lines with "→" on second line
        assert "\n" in message
        assert "→" in message
        assert "Missing tests" in message

    def test_format_escapes_markdown_special_chars(self) -> None:
        """Test special characters are escaped for MarkdownV2."""
        payload = StoryStartedPayload(
            project="test-project", epic=15, story="15-1", phase="DEV_STORY"
        )
        message = _format_message(EventType.STORY_STARTED, payload)
        # Dots in story ID should be escaped (no epic duplication: "15.1" not "15.15-1")
        assert "15\\.1" in message

    def test_format_preserves_newlines(self) -> None:
        """Test multi-line notifications preserve newlines through escaping."""
        payload = StoryCompletedPayload(
            project="test-project",
            epic=12,
            story="Test",
            duration_ms=60000,
            outcome="Error occurred",
        )
        message = _format_message(EventType.STORY_COMPLETED, payload)
        # Should have newline preserved
        lines = message.split("\n")
        assert len(lines) >= 2
        # Second line starts with escaped arrow
        assert lines[1].startswith("→")

    def test_format_preserves_unicode_emojis(self) -> None:
        """Test Unicode emojis (✓, ❌, →) pass through escaping unchanged."""
        # Success case
        success_payload = StoryCompletedPayload(
            project="test", epic=1, story="s", duration_ms=1000, outcome="success"
        )
        success_msg = _format_message(EventType.STORY_COMPLETED, success_payload)
        assert "✓" in success_msg  # Checkmark not escaped

        # Failure case
        fail_payload = StoryCompletedPayload(
            project="test", epic=1, story="s", duration_ms=1000, outcome="fail"
        )
        fail_msg = _format_message(EventType.STORY_COMPLETED, fail_payload)
        assert "❌" in fail_msg  # Cross mark not escaped
        assert "→" in fail_msg  # Arrow not escaped

    def test_formatter_exception_triggers_fallback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test formatter exception triggers fallback format."""
        import bmad_assist.notifications.telegram as telegram_module

        # Mock format_notification to raise
        def mock_format(*args: object, **kwargs: object) -> str:
            raise ValueError("Test exception")

        monkeypatch.setattr(telegram_module, "format_notification", mock_format)

        payload = StoryStartedPayload(project="test", epic=1, story="1", phase="DEV")
        with caplog.at_level("WARNING"):
            message = _format_message(EventType.STORY_STARTED, payload)

        # Should return fallback format (escaped for MarkdownV2)
        # "story_started" becomes "story\\_started" after escaping
        assert "story\\_started" in message
        assert "StoryStartedPayload" in message
        # Should log warning
        assert "Formatter error" in caplog.text

    def test_all_existing_event_types_format_correctly(self) -> None:
        """Test all 6 existing event types format without error."""
        # STORY_STARTED
        msg1 = _format_message(
            EventType.STORY_STARTED,
            StoryStartedPayload(project="p", epic=1, story="s", phase="DEV"),
        )
        assert msg1  # Not empty

        # STORY_COMPLETED
        msg2 = _format_message(
            EventType.STORY_COMPLETED,
            StoryCompletedPayload(
                project="p", epic=1, story="s", duration_ms=1000, outcome="success"
            ),
        )
        assert msg2

        # PHASE_COMPLETED
        msg3 = _format_message(
            EventType.PHASE_COMPLETED,
            PhaseCompletedPayload(project="p", epic=1, story="s", phase="DEV", next_phase="REVIEW"),
        )
        assert msg3

        # ANOMALY_DETECTED
        msg4 = _format_message(
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
        assert msg4

        # QUEUE_BLOCKED
        msg5 = _format_message(
            EventType.QUEUE_BLOCKED,
            QueueBlockedPayload(project="p", epic=1, story="s", reason="blocked", waiting_tasks=5),
        )
        assert msg5

        # ERROR_OCCURRED
        msg6 = _format_message(
            EventType.ERROR_OCCURRED,
            ErrorOccurredPayload(
                project="p", epic=1, story="s", error_type="E", message="m", stack_trace=None
            ),
        )
        assert msg6

    def test_infrastructure_event_types_format_correctly(self) -> None:
        """Test 4 new infrastructure event types format correctly."""
        from bmad_assist.notifications.events import (
            CLICrashedPayload,
            FatalErrorPayload,
            TimeoutWarningPayload,
        )

        # TIMEOUT_WARNING
        msg1 = _format_message(
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
        assert msg1
        assert "10m" in msg1  # remaining time formatted

        # CLI_CRASHED (not recovered)
        msg2 = _format_message(
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
        assert msg2
        assert "3/3" in msg2

        # CLI_RECOVERED
        msg3 = _format_message(
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
        assert msg3
        assert "2/3" in msg3

        # FATAL_ERROR
        msg4 = _format_message(
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
        assert msg4
        assert "KeyError" in msg4


class TestIsRetryableError:
    """Test AC5: _is_retryable_error helper function."""

    def test_timeout_exception_is_retryable(self) -> None:
        """Test httpx.TimeoutException is retryable."""
        exc = httpx.TimeoutException("Connection timed out")
        assert _is_retryable_error(None, exc) is True

    def test_request_error_is_retryable(self) -> None:
        """Test httpx.RequestError is retryable."""
        request = httpx.Request("POST", "https://api.telegram.org/test")
        exc = httpx.RequestError("Network error", request=request)
        assert _is_retryable_error(None, exc) is True

    def test_connect_error_is_retryable(self) -> None:
        """Test httpx.ConnectError (subclass of RequestError) is retryable."""
        request = httpx.Request("POST", "https://api.telegram.org/test")
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
    """Test AC2, AC4, AC5: send() method behavior."""

    @pytest.fixture
    def telegram_provider(self) -> TelegramProvider:
        """Create TelegramProvider with test credentials."""
        return TelegramProvider(bot_token="test-token", chat_id="12345")

    @pytest.fixture
    def story_started_payload(self) -> StoryStartedPayload:
        """Sample StoryStartedPayload."""
        return StoryStartedPayload(project="test-project", epic=15, story="15-1", phase="DEV_STORY")

    @pytest.mark.asyncio
    async def test_send_returns_false_when_credentials_missing(self) -> None:
        """Test send() returns False when credentials are missing."""
        provider = TelegramProvider()
        payload = StoryStartedPayload(
            project="test-project", epic=15, story="15-1", phase="DEV_STORY"
        )
        result = await provider.send(EventType.STORY_STARTED, payload)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success_http_200(
        self,
        telegram_provider: TelegramProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test send() returns True on HTTP 200."""
        httpx_mock.add_response(
            url="https://api.telegram.org/bottest-token/sendMessage",
            method="POST",
            status_code=200,
            json={"ok": True, "result": {"message_id": 123}},
        )
        result = await telegram_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_failure_http_400(
        self,
        telegram_provider: TelegramProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test send() returns False on HTTP 400 (no retry)."""
        httpx_mock.add_response(
            url="https://api.telegram.org/bottest-token/sendMessage",
            method="POST",
            status_code=400,
            json={"ok": False, "error_code": 400, "description": "Bad Request"},
        )
        with caplog.at_level("ERROR"):
            result = await telegram_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is False
        assert "400" in caplog.text

    @pytest.mark.asyncio
    async def test_send_no_retry_on_401(
        self,
        telegram_provider: TelegramProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test send() does NOT retry on HTTP 401."""
        httpx_mock.add_response(
            url="https://api.telegram.org/bottest-token/sendMessage",
            method="POST",
            status_code=401,
            json={"ok": False, "error_code": 401, "description": "Unauthorized"},
        )
        with caplog.at_level("ERROR"):
            result = await telegram_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is False
        # Should only be 1 request (no retry)
        assert len(httpx_mock.get_requests()) == 1

    @pytest.mark.asyncio
    async def test_send_no_retry_on_403(
        self,
        telegram_provider: TelegramProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test send() does NOT retry on HTTP 403."""
        httpx_mock.add_response(
            url="https://api.telegram.org/bottest-token/sendMessage",
            method="POST",
            status_code=403,
            json={"ok": False, "error_code": 403, "description": "Forbidden"},
        )
        result = await telegram_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is False
        # Should only be 1 request (no retry)
        assert len(httpx_mock.get_requests()) == 1

    @pytest.mark.asyncio
    async def test_send_retry_on_429(
        self,
        telegram_provider: TelegramProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test send() retries on HTTP 429 rate limit."""
        # Mock asyncio.sleep to speed up test
        sleep_calls: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        import bmad_assist.notifications.telegram as telegram_module

        monkeypatch.setattr(telegram_module.asyncio, "sleep", mock_sleep)

        # Return 429 twice, then 200
        httpx_mock.add_response(status_code=429)
        httpx_mock.add_response(status_code=429)
        httpx_mock.add_response(status_code=200, json={"ok": True})

        result = await telegram_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is True
        # Should be 3 requests (initial + 2 retries)
        assert len(httpx_mock.get_requests()) == 3
        # Check exponential backoff delays: 1s, 2s
        assert sleep_calls == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_send_retry_on_timeout(
        self,
        telegram_provider: TelegramProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test send() retries on timeout and returns False after max retries."""

        # Mock asyncio.sleep to speed up test
        async def mock_sleep(delay: float) -> None:
            pass

        import bmad_assist.notifications.telegram as telegram_module

        monkeypatch.setattr(telegram_module.asyncio, "sleep", mock_sleep)

        # Always timeout (3 times)
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))
        httpx_mock.add_exception(httpx.TimeoutException("Timeout"))

        with caplog.at_level("ERROR"):
            result = await telegram_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is False
        # Should be 3 requests (initial + 2 retries)
        assert len(httpx_mock.get_requests()) == 3
        assert "failed after 3 attempts" in caplog.text

    @pytest.mark.asyncio
    async def test_send_logs_error_on_failure(
        self,
        telegram_provider: TelegramProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test send() logs at ERROR level on failure."""
        httpx_mock.add_response(status_code=400, json={"ok": False})
        with caplog.at_level("ERROR"):
            await telegram_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert "Telegram API error" in caplog.text

    @pytest.mark.asyncio
    async def test_send_posts_correct_json(
        self,
        telegram_provider: TelegramProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test send() posts correct JSON with MarkdownV2 and Epic 21 format."""
        httpx_mock.add_response(status_code=200, json={"ok": True})
        await telegram_provider.send(EventType.STORY_STARTED, story_started_payload)

        requests = httpx_mock.get_requests()
        assert len(requests) == 1
        request = requests[0]
        import json

        body = json.loads(request.content)
        assert body["chat_id"] == "12345"
        assert body["parse_mode"] == "MarkdownV2"
        # Epic 21 format: compact with story ID, not verbose with "STORY STARTED"
        text = body["text"]
        assert "15\\.1" in text  # Story ID escaped for MarkdownV2 (no epic duplication)
        # STORY_STARTED has no checkmark (checkmark only on STORY_COMPLETED success)
        assert "💻" in text  # Develop icon for DEV_STORY phase

    @pytest.mark.asyncio
    async def test_send_never_raises_exception(
        self,
        telegram_provider: TelegramProvider,
        story_started_payload: StoryStartedPayload,
        httpx_mock: HTTPXMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test send() never raises exceptions - catches all errors."""

        # Mock asyncio.sleep to speed up test
        async def mock_sleep(delay: float) -> None:
            pass

        import bmad_assist.notifications.telegram as telegram_module

        monkeypatch.setattr(telegram_module.asyncio, "sleep", mock_sleep)

        # Simulate network error
        request = httpx.Request("POST", "https://api.telegram.org/test")
        httpx_mock.add_exception(httpx.ConnectError("Connection refused", request=request))
        httpx_mock.add_exception(httpx.ConnectError("Connection refused", request=request))
        httpx_mock.add_exception(httpx.ConnectError("Connection refused", request=request))

        # Should not raise, just return False
        result = await telegram_provider.send(EventType.STORY_STARTED, story_started_payload)
        assert result is False
