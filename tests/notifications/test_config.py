"""Tests for notification configuration models.

Story 15.4: Test NotificationConfig and ProviderConfigItem with env var substitution.
"""

import os

import pytest


class TestProviderConfigItem:
    """Tests for ProviderConfigItem Pydantic model."""

    def test_telegram_provider_config(self) -> None:
        """Test valid telegram provider configuration."""
        from bmad_assist.notifications.config import ProviderConfigItem

        config = ProviderConfigItem(
            type="telegram",
            bot_token="test-token",
            chat_id="123456",
        )

        assert config.type == "telegram"
        assert config.bot_token == "test-token"
        assert config.chat_id == "123456"
        assert config.webhook_url is None

    def test_discord_provider_config(self) -> None:
        """Test valid discord provider configuration."""
        from bmad_assist.notifications.config import ProviderConfigItem

        config = ProviderConfigItem(
            type="discord",
            webhook_url="https://discord.com/api/webhooks/123/abc",
        )

        assert config.type == "discord"
        assert config.webhook_url == "https://discord.com/api/webhooks/123/abc"
        assert config.bot_token is None
        assert config.chat_id is None

    def test_env_var_substitution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ${VAR} patterns are substituted with env values."""
        from bmad_assist.notifications.config import ProviderConfigItem

        monkeypatch.setenv("MY_BOT_TOKEN", "secret-token-123")
        monkeypatch.setenv("MY_CHAT_ID", "999888")

        config = ProviderConfigItem(
            type="telegram",
            bot_token="${MY_BOT_TOKEN}",
            chat_id="${MY_CHAT_ID}",
        )

        assert config.bot_token == "secret-token-123"
        assert config.chat_id == "999888"

    def test_env_var_missing_logs_debug_uses_empty(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test missing env vars log debug message and substitute empty string."""
        from bmad_assist.notifications.config import ProviderConfigItem

        # Ensure env var doesn't exist
        monkeypatch.delenv("NONEXISTENT_TOKEN", raising=False)

        import logging

        caplog.set_level(logging.DEBUG)

        config = ProviderConfigItem(
            type="telegram",
            bot_token="${NONEXISTENT_TOKEN}",
            chat_id="123",
        )

        assert config.bot_token == ""
        assert "NONEXISTENT_TOKEN" in caplog.text

    def test_frozen_model(self) -> None:
        """Test config is immutable (frozen=True)."""
        from bmad_assist.notifications.config import ProviderConfigItem

        config = ProviderConfigItem(type="telegram", bot_token="abc", chat_id="123")

        with pytest.raises(Exception):  # Pydantic frozen model raises error
            config.bot_token = "new"  # type: ignore[misc]


class TestNotificationConfig:
    """Tests for NotificationConfig Pydantic model."""

    def test_valid_config_with_providers(self) -> None:
        """Test valid notification config with multiple providers."""
        from bmad_assist.notifications.config import NotificationConfig, ProviderConfigItem

        config = NotificationConfig(
            enabled=True,
            providers=[
                ProviderConfigItem(type="telegram", bot_token="tok", chat_id="123"),
                ProviderConfigItem(type="discord", webhook_url="https://example.com/webhook"),
            ],
            events=["story_started", "story_completed"],
        )

        assert config.enabled is True
        assert len(config.providers) == 2
        assert config.providers[0].type == "telegram"
        assert config.providers[1].type == "discord"
        assert config.events == ["story_started", "story_completed"]

    def test_default_values(self) -> None:
        """Test default values when minimal config provided."""
        from bmad_assist.notifications.config import NotificationConfig

        config = NotificationConfig()

        assert config.enabled is True  # Default enabled
        assert config.providers == []
        assert config.events == []

    def test_enabled_events_property_valid(self) -> None:
        """Test enabled_events returns valid EventType frozenset."""
        from bmad_assist.notifications.config import NotificationConfig
        from bmad_assist.notifications.events import EventType

        config = NotificationConfig(events=["story_started", "error_occurred", "phase_completed"])

        enabled = config.enabled_events

        assert EventType.STORY_STARTED in enabled
        assert EventType.ERROR_OCCURRED in enabled
        assert EventType.PHASE_COMPLETED in enabled
        assert len(enabled) == 3

    def test_enabled_events_unknown_type_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test unknown event types log warning and are skipped."""
        from bmad_assist.notifications.config import NotificationConfig
        from bmad_assist.notifications.events import EventType

        import logging

        caplog.set_level(logging.WARNING)

        config = NotificationConfig(events=["story_started", "unknown_event", "also_invalid"])

        enabled = config.enabled_events

        # Only valid event should be in set
        assert EventType.STORY_STARTED in enabled
        assert len(enabled) == 1

        # Warnings logged for unknown events
        assert "unknown_event" in caplog.text
        assert "also_invalid" in caplog.text

    def test_empty_events_returns_empty_set(self) -> None:
        """Test empty events list returns empty frozenset."""
        from bmad_assist.notifications.config import NotificationConfig

        config = NotificationConfig(events=[])

        assert config.enabled_events == frozenset()

    def test_frozen_model(self) -> None:
        """Test config is immutable (frozen=True)."""
        from bmad_assist.notifications.config import NotificationConfig

        config = NotificationConfig(enabled=True)

        with pytest.raises(Exception):  # Pydantic frozen model raises error
            config.enabled = False  # type: ignore[misc]


class TestEnvVarSubstitution:
    """Tests for _substitute_env_vars helper function."""

    def test_single_var_substitution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test single ${VAR} substitution."""
        from bmad_assist.notifications.config import _substitute_env_vars

        monkeypatch.setenv("MY_VAR", "my_value")

        result = _substitute_env_vars("prefix_${MY_VAR}_suffix")

        assert result == "prefix_my_value_suffix"

    def test_multiple_var_substitution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test multiple ${VAR} substitutions in same string."""
        from bmad_assist.notifications.config import _substitute_env_vars

        monkeypatch.setenv("VAR1", "first")
        monkeypatch.setenv("VAR2", "second")

        result = _substitute_env_vars("${VAR1}-${VAR2}")

        assert result == "first-second"

    def test_no_var_returns_unchanged(self) -> None:
        """Test string without ${VAR} returns unchanged."""
        from bmad_assist.notifications.config import _substitute_env_vars

        result = _substitute_env_vars("plain string")

        assert result == "plain string"

    def test_partial_pattern_unchanged(self) -> None:
        """Test partial patterns like $VAR (without braces) are unchanged."""
        from bmad_assist.notifications.config import _substitute_env_vars

        result = _substitute_env_vars("$VAR is not ${VAR} format")

        # $VAR should remain, ${VAR} without matching env returns empty
        assert "$VAR" in result
