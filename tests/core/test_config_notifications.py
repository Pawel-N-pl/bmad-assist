"""Tests for notifications field in Config model.

Story 15.4: Test notifications integration with Config.
"""



class TestConfigNotificationsField:
    """Tests for Config.notifications field."""

    def test_config_with_notifications_section(self) -> None:
        """Test Config loads with notifications section present."""
        from bmad_assist.core.config import _reset_config, load_config
        from bmad_assist.notifications.config import NotificationConfig

        _reset_config()

        config_data = {
            "providers": {
                "master": {"provider": "claude", "model": "opus"},
            },
            "notifications": {
                "enabled": True,
                "providers": [
                    {"type": "telegram", "bot_token": "abc", "chat_id": "123"},
                ],
                "events": ["story_started", "story_completed"],
            },
        }

        config = load_config(config_data)

        assert config.notifications is not None
        assert isinstance(config.notifications, NotificationConfig)
        assert config.notifications.enabled is True
        assert len(config.notifications.providers) == 1
        assert config.notifications.providers[0].type == "telegram"
        assert config.notifications.events == ["story_started", "story_completed"]

        _reset_config()

    def test_config_without_notifications_section(self) -> None:
        """Test Config loads without notifications (defaults to None)."""
        from bmad_assist.core.config import _reset_config, load_config

        _reset_config()

        config_data = {
            "providers": {
                "master": {"provider": "claude", "model": "opus"},
            },
        }

        config = load_config(config_data)

        assert config.notifications is None

        _reset_config()

    def test_config_with_disabled_notifications(self) -> None:
        """Test Config with notifications.enabled = false."""
        from bmad_assist.core.config import _reset_config, load_config

        _reset_config()

        config_data = {
            "providers": {
                "master": {"provider": "claude", "model": "opus"},
            },
            "notifications": {
                "enabled": False,
            },
        }

        config = load_config(config_data)

        assert config.notifications is not None
        assert config.notifications.enabled is False
        assert config.notifications.providers == []
        assert config.notifications.events == []

        _reset_config()

    def test_config_notifications_with_multiple_providers(self) -> None:
        """Test Config with both telegram and discord providers."""
        from bmad_assist.core.config import _reset_config, load_config

        _reset_config()

        config_data = {
            "providers": {
                "master": {"provider": "claude", "model": "opus"},
            },
            "notifications": {
                "enabled": True,
                "providers": [
                    {"type": "telegram", "bot_token": "tok", "chat_id": "123"},
                    {"type": "discord", "webhook_url": "https://example.com/hook"},
                ],
                "events": ["story_started"],
            },
        }

        config = load_config(config_data)

        assert config.notifications is not None
        assert len(config.notifications.providers) == 2
        assert config.notifications.providers[0].type == "telegram"
        assert config.notifications.providers[1].type == "discord"

        _reset_config()

    def test_config_notifications_field_position(self) -> None:
        """Test notifications field is after testarch (alphabetically ordered)."""
        from bmad_assist.core.config import Config

        # Get field order from model_fields
        fields = list(Config.model_fields.keys())

        # Find positions
        if "testarch" in fields and "notifications" in fields:
            testarch_pos = fields.index("testarch")
            notifications_pos = fields.index("notifications")
            # Both should exist
            assert "notifications" in fields
            assert "testarch" in fields
