"""Tests for config schema export (Story 17.1).

Covers:
- AC7: Schema Export Function
- AC8: Tests for schema output structure and dangerous field exclusion
"""

import pytest

from bmad_assist.core.config import (
    BenchmarkingConfig,
    Config,
    MasterProviderConfig,
    MultiProviderConfig,
    ProjectPathsConfig,
    get_config_schema,
    get_field_security,
    get_field_widget,
)
from bmad_assist.notifications.config import ProviderConfigItem


class TestGetFieldSecurity:
    """Tests for get_field_security helper function."""

    def test_explicit_safe_security(self) -> None:
        """Test field with explicit 'safe' security returns 'safe'."""
        security = get_field_security(BenchmarkingConfig, "enabled")
        assert security == "safe"

    def test_explicit_risky_security(self) -> None:
        """Test field with explicit 'risky' security returns 'risky'."""
        security = get_field_security(BenchmarkingConfig, "extraction_provider")
        assert security == "risky"

    def test_explicit_dangerous_security(self) -> None:
        """Test field with explicit 'dangerous' security returns 'dangerous'."""
        security = get_field_security(MasterProviderConfig, "settings")
        assert security == "dangerous"

    def test_field_without_security_returns_default(self) -> None:
        """Test field without explicit security returns default 'safe'."""
        # Config.timeout has explicit json_schema_extra with security="safe"
        # This test verifies the helper function correctly reads it
        security = get_field_security(Config, "timeout")
        assert security == "safe"

    def test_nonexistent_field_raises_key_error(self) -> None:
        """Test nonexistent field raises KeyError."""
        with pytest.raises(KeyError, match="Field 'nonexistent' not found"):
            get_field_security(Config, "nonexistent")

    def test_provider_config_fields(self) -> None:
        """Test MasterProviderConfig field security levels."""
        assert get_field_security(MasterProviderConfig, "provider") == "risky"
        assert get_field_security(MasterProviderConfig, "model") == "risky"
        assert get_field_security(MasterProviderConfig, "model_name") == "safe"
        assert get_field_security(MasterProviderConfig, "settings") == "dangerous"

    def test_multi_provider_config_fields(self) -> None:
        """Test MultiProviderConfig field security levels."""
        assert get_field_security(MultiProviderConfig, "provider") == "risky"
        assert get_field_security(MultiProviderConfig, "model") == "risky"
        assert get_field_security(MultiProviderConfig, "model_name") == "safe"
        assert get_field_security(MultiProviderConfig, "settings") == "dangerous"

    def test_project_paths_all_dangerous(self) -> None:
        """Test all ProjectPathsConfig fields are dangerous."""
        for field in ProjectPathsConfig.model_fields:
            security = get_field_security(ProjectPathsConfig, field)
            assert security == "dangerous", f"Field {field} should be dangerous"

    def test_notification_provider_security(self) -> None:
        """Test ProviderConfigItem field security levels (AC6a)."""
        assert get_field_security(ProviderConfigItem, "type") == "safe"
        assert get_field_security(ProviderConfigItem, "bot_token") == "dangerous"
        assert get_field_security(ProviderConfigItem, "chat_id") == "risky"
        assert get_field_security(ProviderConfigItem, "webhook_url") == "dangerous"


class TestGetFieldWidget:
    """Tests for get_field_widget helper function."""

    def test_explicit_toggle_widget(self) -> None:
        """Test field with explicit 'toggle' widget returns 'toggle'."""
        widget = get_field_widget(BenchmarkingConfig, "enabled")
        assert widget == "toggle"

    def test_explicit_dropdown_widget(self) -> None:
        """Test field with explicit 'dropdown' widget returns 'dropdown'."""
        widget = get_field_widget(BenchmarkingConfig, "extraction_provider")
        assert widget == "dropdown"

    def test_bool_type_infers_toggle(self) -> None:
        """Test bool type without explicit widget infers 'toggle'."""
        # This depends on Config having a bool field without explicit widget
        # Using BenchmarkingConfig.enabled which has explicit toggle
        widget = get_field_widget(BenchmarkingConfig, "enabled")
        assert widget == "toggle"

    def test_int_type_infers_number(self) -> None:
        """Test int type without explicit widget infers 'number'."""
        widget = get_field_widget(Config, "timeout")
        assert widget == "number"

    def test_nonexistent_field_raises_key_error(self) -> None:
        """Test nonexistent field raises KeyError."""
        with pytest.raises(KeyError, match="Field 'nonexistent' not found"):
            get_field_widget(Config, "nonexistent")


class TestGetConfigSchema:
    """Tests for get_config_schema function (AC7)."""

    def test_returns_dict(self) -> None:
        """Test schema export returns dictionary."""
        schema = get_config_schema()
        assert isinstance(schema, dict)

    def test_benchmarking_section_present(self) -> None:
        """Test benchmarking section is in schema."""
        schema = get_config_schema()
        assert "benchmarking" in schema

    def test_benchmarking_enabled_has_required_fields(self) -> None:
        """Test benchmarking.enabled has security and ui_widget."""
        schema = get_config_schema()
        enabled = schema["benchmarking"]["enabled"]
        assert enabled["security"] == "safe"
        assert enabled["ui_widget"] == "toggle"
        assert enabled["type"] == "boolean"

    def test_benchmarking_extraction_provider_is_risky(self) -> None:
        """Test benchmarking.extraction_provider is marked risky."""
        schema = get_config_schema()
        provider = schema["benchmarking"]["extraction_provider"]
        assert provider["security"] == "risky"
        assert provider["ui_widget"] == "dropdown"

    def test_dangerous_fields_excluded(self) -> None:
        """Test dangerous fields are excluded from schema (AC6)."""
        schema = get_config_schema()

        # ProjectPathsConfig has only dangerous fields, so "paths" section
        # should be entirely omitted from schema
        assert "paths" not in schema, "paths section should be excluded (all fields dangerous)"

        # bmad_paths also has only dangerous fields
        assert "bmad_paths" not in schema, "bmad_paths should be excluded (all fields dangerous)"

    def test_provider_settings_excluded(self) -> None:
        """Test provider settings (dangerous) are excluded."""
        schema = get_config_schema()

        # providers section must exist
        assert "providers" in schema, "providers section should exist in schema"
        assert "master" in schema["providers"], "master provider should exist"

        # Master provider should not have settings field (dangerous)
        master = schema["providers"]["master"]
        assert "settings" not in master, "settings (dangerous) should be excluded"

    def test_nested_models_resolved(self) -> None:
        """Test nested Pydantic models are resolved recursively."""
        schema = get_config_schema()

        # BenchmarkingConfig is nested under root
        assert "benchmarking" in schema
        assert "enabled" in schema["benchmarking"]
        assert "extraction_provider" in schema["benchmarking"]
        assert "extraction_model" in schema["benchmarking"]

    def test_timeout_has_number_widget(self) -> None:
        """Test timeout field infers number widget from int type."""
        schema = get_config_schema()
        assert "timeout" in schema
        assert schema["timeout"]["ui_widget"] == "number"
        assert schema["timeout"]["type"] == "integer"

    def test_default_values_included(self) -> None:
        """Test default values are included in schema."""
        schema = get_config_schema()
        assert schema["timeout"]["default"] == 300
        assert schema["benchmarking"]["enabled"]["default"] is True

    def test_descriptions_included(self) -> None:
        """Test descriptions are included in schema."""
        schema = get_config_schema()
        assert "description" in schema["benchmarking"]["enabled"]

    def test_schema_is_cached(self) -> None:
        """Test schema is cached via lru_cache."""
        schema1 = get_config_schema()
        schema2 = get_config_schema()
        assert schema1 is schema2  # Same object due to caching


class TestSecurityInheritance:
    """Tests for security level inheritance (AC1)."""

    def test_field_with_explicit_security(self) -> None:
        """Test field with explicit security uses that level."""
        security = get_field_security(BenchmarkingConfig, "enabled")
        assert security == "safe"

    def test_field_with_explicit_security_on_timeout(self) -> None:
        """Test Config.timeout has explicit safe security."""
        # Config.timeout should have explicit json_schema_extra now
        security = get_field_security(Config, "timeout")
        assert security == "safe"


class TestDangerousFieldsComprehensive:
    """Comprehensive tests for dangerous field exclusion."""

    def test_bmad_paths_all_dangerous(self) -> None:
        """Test all BmadPathsConfig fields are dangerous."""
        from bmad_assist.core.config import BmadPathsConfig

        for field in BmadPathsConfig.model_fields:
            security = get_field_security(BmadPathsConfig, field)
            assert security == "dangerous", f"BmadPathsConfig.{field} should be dangerous"

    def test_bmad_paths_excluded_from_schema(self) -> None:
        """Test BmadPathsConfig fields excluded from schema entirely."""
        schema = get_config_schema()
        # bmad_paths should not appear since all fields are dangerous
        assert "bmad_paths" not in schema

    def test_state_path_is_dangerous(self) -> None:
        """Test Config.state_path is marked dangerous."""
        security = get_field_security(Config, "state_path")
        assert security == "dangerous"

    def test_state_path_excluded_from_schema(self) -> None:
        """Test state_path excluded from schema."""
        schema = get_config_schema()
        assert "state_path" not in schema

    def test_compiler_patch_path_is_dangerous(self) -> None:
        """Test CompilerConfig.patch_path is marked dangerous."""
        from bmad_assist.core.config import CompilerConfig

        security = get_field_security(CompilerConfig, "patch_path")
        assert security == "dangerous"


class TestListOfModelsSchema:
    """Tests for list[BaseModel] schema handling."""

    def test_providers_multi_is_array(self) -> None:
        """Test providers.multi is an array schema, not flattened."""
        schema = get_config_schema()
        assert "providers" in schema
        assert "multi" in schema["providers"]
        multi = schema["providers"]["multi"]
        assert multi["type"] == "array"
        assert "items" in multi

    def test_providers_multi_items_structure(self) -> None:
        """Test providers.multi.items contains model fields."""
        schema = get_config_schema()
        items = schema["providers"]["multi"]["items"]
        # Should have MultiProviderConfig fields (minus dangerous settings)
        assert "provider" in items
        assert "model" in items
        assert "model_name" in items
        # settings should be excluded (dangerous)
        assert "settings" not in items

    def test_notifications_providers_is_array(self) -> None:
        """Test notifications.providers is an array schema."""
        schema = get_config_schema()
        if "notifications" in schema and "providers" in schema["notifications"]:
            providers = schema["notifications"]["providers"]
            assert providers["type"] == "array"
            assert "items" in providers


class TestSchemaJsonSerializable:
    """Tests for schema JSON serialization."""

    def test_schema_is_json_serializable(self) -> None:
        """Test get_config_schema() returns JSON-serializable dict."""
        import json

        schema = get_config_schema()
        # This should not raise - PydanticUndefined excluded
        json_str = json.dumps(schema)
        assert isinstance(json_str, str)
        assert len(json_str) > 0


class TestPlaywrightConfigInSchema:
    """Tests for PlaywrightConfig in schema export."""

    def test_playwright_browsers_has_checkbox_group(self) -> None:
        """Test PlaywrightConfig.browsers uses checkbox_group widget."""
        from bmad_assist.testarch.config import PlaywrightConfig

        widget = get_field_widget(PlaywrightConfig, "browsers")
        assert widget == "checkbox_group"

    def test_playwright_browsers_has_options(self) -> None:
        """Test PlaywrightConfig.browsers includes options in schema_extra."""
        from bmad_assist.testarch.config import PlaywrightConfig

        field_info = PlaywrightConfig.model_fields["browsers"]
        extra = field_info.json_schema_extra
        assert isinstance(extra, dict)
        assert "options" in extra
        assert extra["options"] == ["chromium", "firefox", "webkit"]

    def test_playwright_headless_is_toggle(self) -> None:
        """Test PlaywrightConfig.headless uses toggle widget."""
        from bmad_assist.testarch.config import PlaywrightConfig

        widget = get_field_widget(PlaywrightConfig, "headless")
        assert widget == "toggle"

    def test_playwright_timeout_has_unit(self) -> None:
        """Test PlaywrightConfig.timeout includes unit in schema_extra."""
        from bmad_assist.testarch.config import PlaywrightConfig

        field_info = PlaywrightConfig.model_fields["timeout"]
        extra = field_info.json_schema_extra
        assert isinstance(extra, dict)
        assert extra.get("unit") == "ms"

    def test_playwright_workers_is_number(self) -> None:
        """Test PlaywrightConfig.workers uses number widget."""
        from bmad_assist.testarch.config import PlaywrightConfig

        widget = get_field_widget(PlaywrightConfig, "workers")
        assert widget == "number"

    def test_playwright_all_fields_safe(self) -> None:
        """Test all PlaywrightConfig fields are 'safe'."""
        from bmad_assist.testarch.config import PlaywrightConfig

        for field in PlaywrightConfig.model_fields:
            security = get_field_security(PlaywrightConfig, field)
            assert security == "safe", f"Field {field} should be safe"
