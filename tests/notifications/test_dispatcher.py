"""Tests for EventDispatcher and global accessor functions.

Story 15.4: Test concurrent dispatch, event filtering, and global accessors.
"""

from unittest.mock import AsyncMock

import pytest


class TestEventDispatcher:
    """Tests for EventDispatcher class."""

    def test_dispatcher_init_with_enabled_config(self) -> None:
        """Test dispatcher initializes with enabled config and providers."""
        from bmad_assist.notifications.config import NotificationConfig, ProviderConfigItem
        from bmad_assist.notifications.dispatcher import EventDispatcher

        config = NotificationConfig(
            enabled=True,
            providers=[
                ProviderConfigItem(type="telegram", bot_token="tok", chat_id="123"),
            ],
            events=["story_started"],
        )

        dispatcher = EventDispatcher(config)

        assert dispatcher._config == config
        assert len(dispatcher._providers) == 1

    def test_dispatcher_no_providers_when_disabled(self) -> None:
        """Test no providers instantiated when disabled."""
        from bmad_assist.notifications.config import NotificationConfig, ProviderConfigItem
        from bmad_assist.notifications.dispatcher import EventDispatcher

        config = NotificationConfig(
            enabled=False,
            providers=[
                ProviderConfigItem(type="telegram", bot_token="tok", chat_id="123"),
            ],
            events=["story_started"],
        )

        dispatcher = EventDispatcher(config)

        assert dispatcher._providers == []

    def test_dispatcher_unknown_provider_type_skipped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test unknown provider types are logged and skipped."""
        import logging

        from bmad_assist.notifications.config import NotificationConfig, ProviderConfigItem
        from bmad_assist.notifications.dispatcher import EventDispatcher

        caplog.set_level(logging.WARNING)

        config = NotificationConfig(
            enabled=True,
            providers=[
                ProviderConfigItem(type="unknown_provider"),
            ],
            events=["story_started"],
        )

        dispatcher = EventDispatcher(config)

        assert len(dispatcher._providers) == 0
        assert "Unknown provider type" in caplog.text

    @pytest.mark.asyncio
    async def test_dispatch_concurrent_to_multiple_providers(self) -> None:
        """Test dispatch sends to all providers concurrently."""
        from bmad_assist.notifications.config import NotificationConfig, ProviderConfigItem
        from bmad_assist.notifications.dispatcher import EventDispatcher
        from bmad_assist.notifications.events import EventType, StoryStartedPayload

        config = NotificationConfig(
            enabled=True,
            providers=[
                ProviderConfigItem(type="telegram", bot_token="tok", chat_id="123"),
                ProviderConfigItem(type="discord", webhook_url="https://example.com"),
            ],
            events=["story_started"],
        )

        dispatcher = EventDispatcher(config)

        # Mock providers
        mock_provider1 = AsyncMock()
        mock_provider1.send = AsyncMock(return_value=True)
        mock_provider1.provider_name = "telegram"

        mock_provider2 = AsyncMock()
        mock_provider2.send = AsyncMock(return_value=True)
        mock_provider2.provider_name = "discord"

        dispatcher._providers = [mock_provider1, mock_provider2]

        payload = StoryStartedPayload(project="test", epic=1, story="1-1", phase="CREATE_STORY")

        await dispatcher.dispatch(EventType.STORY_STARTED, payload)

        # Both providers should be called
        mock_provider1.send.assert_called_once_with(EventType.STORY_STARTED, payload)
        mock_provider2.send.assert_called_once_with(EventType.STORY_STARTED, payload)

    @pytest.mark.asyncio
    async def test_dispatch_filters_unconfigured_events(self) -> None:
        """Test dispatch filters out events not in config."""
        from bmad_assist.notifications.config import NotificationConfig, ProviderConfigItem
        from bmad_assist.notifications.dispatcher import EventDispatcher
        from bmad_assist.notifications.events import EventType, StoryCompletedPayload

        config = NotificationConfig(
            enabled=True,
            providers=[
                ProviderConfigItem(type="telegram", bot_token="tok", chat_id="123"),
            ],
            events=["story_started"],  # story_completed NOT included
        )

        dispatcher = EventDispatcher(config)

        mock_provider = AsyncMock()
        mock_provider.send = AsyncMock(return_value=True)
        mock_provider.provider_name = "telegram"
        dispatcher._providers = [mock_provider]

        payload = StoryCompletedPayload(
            project="test", epic=1, story="1-1", duration_ms=1000, outcome="success"
        )

        # story_completed should be filtered out
        await dispatcher.dispatch(EventType.STORY_COMPLETED, payload)

        # Provider should NOT be called
        mock_provider.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_noop_when_disabled(self) -> None:
        """Test dispatch is no-op when notifications disabled."""
        from bmad_assist.notifications.config import NotificationConfig
        from bmad_assist.notifications.dispatcher import EventDispatcher
        from bmad_assist.notifications.events import EventType, StoryStartedPayload

        config = NotificationConfig(enabled=False)

        dispatcher = EventDispatcher(config)

        payload = StoryStartedPayload(project="test", epic=1, story="1-1", phase="CREATE_STORY")

        # Should not raise, just return
        await dispatcher.dispatch(EventType.STORY_STARTED, payload)

    @pytest.mark.asyncio
    async def test_dispatch_noop_when_no_providers(self) -> None:
        """Test dispatch is no-op when no providers configured."""
        from bmad_assist.notifications.config import NotificationConfig
        from bmad_assist.notifications.dispatcher import EventDispatcher
        from bmad_assist.notifications.events import EventType, StoryStartedPayload

        config = NotificationConfig(
            enabled=True,
            providers=[],  # No providers
            events=["story_started"],
        )

        dispatcher = EventDispatcher(config)

        payload = StoryStartedPayload(project="test", epic=1, story="1-1", phase="CREATE_STORY")

        # Should not raise, just return
        await dispatcher.dispatch(EventType.STORY_STARTED, payload)

    @pytest.mark.asyncio
    async def test_dispatch_one_provider_failure_doesnt_block_others(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test one provider failure doesn't block other providers."""
        import logging

        from bmad_assist.notifications.config import NotificationConfig, ProviderConfigItem
        from bmad_assist.notifications.dispatcher import EventDispatcher
        from bmad_assist.notifications.events import EventType, StoryStartedPayload

        caplog.set_level(logging.ERROR)

        config = NotificationConfig(
            enabled=True,
            providers=[
                ProviderConfigItem(type="telegram", bot_token="tok", chat_id="123"),
                ProviderConfigItem(type="discord", webhook_url="https://example.com"),
            ],
            events=["story_started"],
        )

        dispatcher = EventDispatcher(config)

        # Mock providers - first fails with exception
        mock_provider1 = AsyncMock()
        mock_provider1.send = AsyncMock(side_effect=RuntimeError("Provider 1 failed"))
        mock_provider1.provider_name = "telegram"

        mock_provider2 = AsyncMock()
        mock_provider2.send = AsyncMock(return_value=True)
        mock_provider2.provider_name = "discord"

        dispatcher._providers = [mock_provider1, mock_provider2]

        payload = StoryStartedPayload(project="test", epic=1, story="1-1", phase="CREATE_STORY")

        # Should not raise despite first provider failing
        await dispatcher.dispatch(EventType.STORY_STARTED, payload)

        # Both providers should be called
        mock_provider1.send.assert_called_once()
        mock_provider2.send.assert_called_once()

        # Error should be logged
        assert "Provider 1 failed" in caplog.text or "raised exception" in caplog.text

    @pytest.mark.asyncio
    async def test_dispatch_provider_returns_false_logged_as_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test provider returning False is logged as warning."""
        import logging

        from bmad_assist.notifications.config import NotificationConfig, ProviderConfigItem
        from bmad_assist.notifications.dispatcher import EventDispatcher
        from bmad_assist.notifications.events import EventType, StoryStartedPayload

        caplog.set_level(logging.WARNING)

        config = NotificationConfig(
            enabled=True,
            providers=[
                ProviderConfigItem(type="telegram", bot_token="tok", chat_id="123"),
            ],
            events=["story_started"],
        )

        dispatcher = EventDispatcher(config)

        mock_provider = AsyncMock()
        mock_provider.send = AsyncMock(return_value=False)
        mock_provider.provider_name = "telegram"
        dispatcher._providers = [mock_provider]

        payload = StoryStartedPayload(project="test", epic=1, story="1-1", phase="CREATE_STORY")

        await dispatcher.dispatch(EventType.STORY_STARTED, payload)

        assert "failed to send" in caplog.text


class TestGlobalAccessor:
    """Tests for global accessor functions."""

    def test_get_dispatcher_returns_none_when_not_initialized(self) -> None:
        """Test get_dispatcher returns None when not initialized."""
        from bmad_assist.notifications.dispatcher import get_dispatcher, reset_dispatcher

        reset_dispatcher()

        result = get_dispatcher()

        assert result is None

    def test_init_dispatcher_creates_instance(self) -> None:
        """Test init_dispatcher creates EventDispatcher instance."""
        from bmad_assist.notifications.config import NotificationConfig
        from bmad_assist.notifications.dispatcher import (
            EventDispatcher,
            get_dispatcher,
            init_dispatcher,
            reset_dispatcher,
        )

        reset_dispatcher()

        config = NotificationConfig(enabled=True, events=["story_started"])
        init_dispatcher(config)

        result = get_dispatcher()

        assert result is not None
        assert isinstance(result, EventDispatcher)

        reset_dispatcher()

    def test_init_dispatcher_with_none_disables(self) -> None:
        """Test init_dispatcher with None disables dispatcher."""
        from bmad_assist.notifications.dispatcher import (
            get_dispatcher,
            init_dispatcher,
            reset_dispatcher,
        )

        reset_dispatcher()

        init_dispatcher(None)

        assert get_dispatcher() is None

    def test_init_dispatcher_with_disabled_config(self) -> None:
        """Test init_dispatcher with disabled config."""
        from bmad_assist.notifications.config import NotificationConfig
        from bmad_assist.notifications.dispatcher import (
            get_dispatcher,
            init_dispatcher,
            reset_dispatcher,
        )

        reset_dispatcher()

        config = NotificationConfig(enabled=False)
        init_dispatcher(config)

        assert get_dispatcher() is None

        reset_dispatcher()

    def test_init_dispatcher_double_init_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test double init logs warning."""
        import logging

        from bmad_assist.notifications.config import NotificationConfig
        from bmad_assist.notifications.dispatcher import init_dispatcher, reset_dispatcher

        caplog.set_level(logging.WARNING)
        reset_dispatcher()

        config = NotificationConfig(enabled=True, events=["story_started"])
        init_dispatcher(config)
        init_dispatcher(config)  # Double init

        assert "already initialized" in caplog.text

        reset_dispatcher()

    def test_reset_dispatcher_clears_instance(self) -> None:
        """Test reset_dispatcher clears cached instance."""
        from bmad_assist.notifications.config import NotificationConfig
        from bmad_assist.notifications.dispatcher import (
            get_dispatcher,
            init_dispatcher,
            reset_dispatcher,
        )

        config = NotificationConfig(enabled=True, events=["story_started"])
        init_dispatcher(config)

        assert get_dispatcher() is not None

        reset_dispatcher()

        assert get_dispatcher() is None
