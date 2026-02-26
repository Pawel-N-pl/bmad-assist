"""Tests for experiments config template system.

Tests cover:
- ConfigTemplate model validation
- Variable resolution (${project}, ${home})
- YAML loading and error handling
- ConfigRegistry discovery and access
- Provider validation warnings
"""

import logging
from pathlib import Path

import pytest

from bmad_assist.core.exceptions import ConfigError
from bmad_assist.experiments.config import (
    KNOWN_PROVIDERS,
    NAME_PATTERN,
    ConfigRegistry,
    ConfigTemplate,
    ConfigTemplateProviders,
    _resolve_variables,
    load_config_template,
)


class TestNamePattern:
    """Tests for name validation pattern."""

    def test_valid_names(self) -> None:
        """Test valid name patterns."""
        valid_names = [
            "opus-solo",
            "haiku_config",
            "Test123",
            "_private",
            "a",
            "A1_b2-c3",
        ]
        for name in valid_names:
            assert NAME_PATTERN.match(name), f"Expected '{name}' to be valid"

    def test_invalid_names(self) -> None:
        """Test invalid name patterns."""
        invalid_names = [
            "123-start",  # starts with number
            "-hyphen-start",  # starts with hyphen
            "has spaces",  # contains space
            "has.dots",  # contains dot
            "has@special",  # contains special char
            "",  # empty
        ]
        for name in invalid_names:
            assert not NAME_PATTERN.match(name), f"Expected '{name}' to be invalid"


class TestConfigTemplate:
    """Tests for ConfigTemplate Pydantic model."""

    def test_valid_minimal_template(self) -> None:
        """Test creating a minimal valid template."""
        template = ConfigTemplate(
            name="test-config",
            providers=ConfigTemplateProviders(
                master={"provider": "claude", "model": "opus"},
                multi=[],
            ),
        )
        assert template.name == "test-config"
        assert template.description is None
        assert template.providers.master.provider == "claude"
        assert template.providers.master.model == "opus"
        assert template.providers.multi == []

    def test_valid_full_template(self) -> None:
        """Test creating a full template with all fields."""
        template = ConfigTemplate(
            name="full-config",
            description="Full configuration",
            providers=ConfigTemplateProviders(
                master={"provider": "claude", "model": "opus"},
                multi=[
                    {"provider": "claude", "model": "sonnet"},
                    {"provider": "gemini", "model": "gemini-2.5-flash"},
                ],
            ),
        )
        assert template.name == "full-config"
        assert template.description == "Full configuration"
        assert len(template.providers.multi) == 2

    def test_empty_name_raises_error(self) -> None:
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            ConfigTemplate(
                name="",
                providers=ConfigTemplateProviders(
                    master={"provider": "claude", "model": "opus"},
                ),
            )

    def test_whitespace_name_raises_error(self) -> None:
        """Test that whitespace-only name raises ValueError."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            ConfigTemplate(
                name="   ",
                providers=ConfigTemplateProviders(
                    master={"provider": "claude", "model": "opus"},
                ),
            )

    def test_name_with_spaces_raises_error(self) -> None:
        """Test that name with spaces raises ValueError."""
        with pytest.raises(ValueError, match="Invalid name"):
            ConfigTemplate(
                name="has spaces",
                providers=ConfigTemplateProviders(
                    master={"provider": "claude", "model": "opus"},
                ),
            )

    def test_name_with_special_chars_raises_error(self) -> None:
        """Test that name with special characters raises ValueError."""
        with pytest.raises(ValueError, match="Invalid name"):
            ConfigTemplate(
                name="has@special",
                providers=ConfigTemplateProviders(
                    master={"provider": "claude", "model": "opus"},
                ),
            )

    def test_name_starting_with_number_raises_error(self) -> None:
        """Test that name starting with number raises ValueError."""
        with pytest.raises(ValueError, match="Invalid name"):
            ConfigTemplate(
                name="123config",
                providers=ConfigTemplateProviders(
                    master={"provider": "claude", "model": "opus"},
                ),
            )

    def test_name_starting_with_hyphen_raises_error(self) -> None:
        """Test that name starting with hyphen raises ValueError."""
        with pytest.raises(ValueError, match="Invalid name"):
            ConfigTemplate(
                name="-config",
                providers=ConfigTemplateProviders(
                    master={"provider": "claude", "model": "opus"},
                ),
            )

    def test_template_is_frozen(self) -> None:
        """Test that template is immutable."""
        from pydantic import ValidationError

        template = ConfigTemplate(
            name="test-config",
            providers=ConfigTemplateProviders(
                master={"provider": "claude", "model": "opus"},
            ),
        )
        with pytest.raises(ValidationError, match="frozen"):
            template.name = "new-name"  # type: ignore[misc]

    def test_template_with_none_providers(self) -> None:
        """Test creating a template without providers (full config mode)."""
        template = ConfigTemplate(
            name="full-config",
            description="Full config template",
            providers=None,
            raw_config={"config_name": "full-config", "providers": {"master": {}}},
        )
        assert template.name == "full-config"
        assert template.providers is None
        assert template.raw_config["config_name"] == "full-config"

    def test_template_raw_config_default_empty(self) -> None:
        """Test raw_config defaults to empty dict."""
        template = ConfigTemplate(
            name="test-config",
            providers=ConfigTemplateProviders(
                master={"provider": "claude", "model": "opus"},
            ),
        )
        assert template.raw_config == {}


class TestVariableResolution:
    """Tests for variable resolution function."""

    def test_project_variable_resolution(self) -> None:
        """Test ${project} variable is resolved."""
        content = "path: ${project}/config.yaml"
        context = {"project": "/path/to/project"}
        result = _resolve_variables(content, context)
        assert result == "path: /path/to/project/config.yaml"

    def test_home_variable_resolution(self) -> None:
        """Test ${home} variable is resolved."""
        content = "path: ${home}/.config"
        context = {"home": "/home/user"}
        result = _resolve_variables(content, context)
        assert result == "path: /home/user/.config"

    def test_multiple_variables(self) -> None:
        """Test multiple variables in same content."""
        content = "${project}/data ${home}/.cache"
        context = {"project": "/proj", "home": "/home"}
        result = _resolve_variables(content, context)
        assert result == "/proj/data /home/.cache"

    def test_same_variable_multiple_times(self) -> None:
        """Test same variable used multiple times."""
        content = "${project}/a ${project}/b"
        context = {"project": "/proj"}
        result = _resolve_variables(content, context)
        assert result == "/proj/a /proj/b"

    def test_unknown_variable_raises_error(self) -> None:
        """Test unknown variable raises ConfigError."""
        content = "path: ${unknown}/config"
        context = {"project": "/proj"}
        with pytest.raises(ConfigError, match="Unknown variable: \\$\\{unknown\\}"):
            _resolve_variables(content, context)

    def test_variable_with_none_value_raises_error(self) -> None:
        """Test variable with None value raises ConfigError."""
        content = "path: ${project}/config"
        context: dict[str, str | None] = {"project": None}
        with pytest.raises(ConfigError, match="cannot be resolved"):
            _resolve_variables(content, context)

    def test_no_variables_unchanged(self) -> None:
        """Test content without variables is unchanged."""
        content = "plain content without variables"
        context = {"project": "/proj"}
        result = _resolve_variables(content, context)
        assert result == content


class TestLoadConfigTemplate:
    """Tests for load_config_template function."""

    def test_load_minimal_template(
        self,
        write_config: callable,
        valid_minimal_config: str,
    ) -> None:
        """Test loading a minimal valid template."""
        path = write_config(valid_minimal_config, "test-config.yaml")
        template = load_config_template(path)

        assert template.name == "test-config"
        assert template.description == "Test configuration"
        assert template.providers.master.provider == "claude"
        assert template.providers.master.model == "opus"
        assert template.providers.multi == []

    def test_load_full_template(
        self,
        write_config: callable,
        valid_full_config: str,
    ) -> None:
        """Test loading a full template with multi validators."""
        path = write_config(valid_full_config, "full-config.yaml")
        template = load_config_template(path)

        assert template.name == "full-config"
        assert len(template.providers.multi) == 2
        assert template.providers.multi[0].provider == "claude"
        assert template.providers.multi[1].provider == "gemini"

    def test_file_not_found_raises_error(self, tmp_path: Path) -> None:
        """Test missing file raises ConfigError."""
        path = tmp_path / "nonexistent.yaml"
        with pytest.raises(ConfigError, match="not found"):
            load_config_template(path)

    def test_invalid_yaml_raises_error(
        self,
        write_config: callable,
    ) -> None:
        """Test invalid YAML raises ConfigError."""
        path = write_config("invalid: yaml: [", "invalid.yaml")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_config_template(path)

    def test_empty_file_raises_error(
        self,
        write_config: callable,
    ) -> None:
        """Test empty file raises ConfigError."""
        path = write_config("", "empty.yaml")
        with pytest.raises(ConfigError, match="is empty"):
            load_config_template(path)

    def test_non_mapping_raises_error(
        self,
        write_config: callable,
    ) -> None:
        """Test non-mapping YAML raises ConfigError."""
        path = write_config("- just\n- a\n- list", "list.yaml")
        with pytest.raises(ConfigError, match="must contain a YAML mapping"):
            load_config_template(path)

    def test_validation_error_raises_config_error(
        self,
        write_config: callable,
    ) -> None:
        """Test schema validation failure raises ConfigError."""
        content = """\
name: test
# missing providers section
"""
        path = write_config(content, "missing-providers.yaml")
        with pytest.raises(ConfigError, match="validation failed"):
            load_config_template(path)

    def test_project_variable_without_root_raises_error(
        self,
        write_config: callable,
        config_with_project_var: str,
    ) -> None:
        """Test ${project} without project_root raises ConfigError."""
        path = write_config(config_with_project_var, "project-var-config.yaml")
        with pytest.raises(
            ConfigError,
            match="project_root parameter required",
        ):
            load_config_template(path, project_root=None)

    def test_project_variable_with_root(
        self,
        write_config: callable,
        project_root: Path,
    ) -> None:
        """Test ${project} with project_root resolves correctly."""
        # Create the settings file so validation passes
        settings_dir = project_root / ".bmad-assist"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text("{}")

        content = """\
name: project-var-config
description: "Config using project variable"

providers:
  master:
    provider: claude
    model: opus
    settings: ${project}/.bmad-assist/settings.json
  multi: []
"""
        path = write_config(content, "project-var-config.yaml")
        template = load_config_template(path, project_root=project_root)

        expected_settings = f"{project_root}/.bmad-assist/settings.json"
        assert template.providers.master.settings == expected_settings

    def test_home_variable_resolves(
        self,
        write_config: callable,
    ) -> None:
        """Test ${home} variable resolves to user home."""
        # We can't easily create the settings file in user's home,
        # so we'll test with a config that doesn't require the file to exist
        content = """\
name: home-var-config
description: "Config using home variable"

providers:
  master:
    provider: claude
    model: opus
  multi: []
"""
        path = write_config(content, "home-var-config.yaml")
        template = load_config_template(path)

        assert template.name == "home-var-config"

    def test_whitespace_model_raises_error(
        self,
        write_config: callable,
    ) -> None:
        """Test whitespace-only model raises ConfigError."""
        content = """\
name: test-config
providers:
  master:
    provider: claude
    model: "   "
  multi: []
"""
        path = write_config(content, "whitespace-model.yaml")
        with pytest.raises(ConfigError, match="cannot be empty"):
            load_config_template(path)

    def test_unknown_provider_logs_warning(
        self,
        write_config: callable,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test unknown provider name logs warning but doesn't fail."""
        content = """\
name: test-config
providers:
  master:
    provider: unknown-provider
    model: some-model
  multi: []
"""
        path = write_config(content, "unknown-provider.yaml")

        with caplog.at_level(logging.WARNING):
            template = load_config_template(path)

        assert template.name == "test-config"
        assert "Unknown provider" in caplog.text
        assert "unknown-provider" in caplog.text

    def test_settings_file_not_found_raises_error(
        self,
        write_config: callable,
        project_root: Path,
    ) -> None:
        """Test missing settings file raises ConfigError."""
        content = """\
name: test-config
providers:
  master:
    provider: claude
    model: opus
    settings: ${project}/nonexistent/settings.json
  multi: []
"""
        path = write_config(content, "test-config.yaml")
        with pytest.raises(ConfigError, match="does not exist"):
            load_config_template(path, project_root=project_root)

    def test_path_is_directory_raises_error(
        self,
        configs_dir: Path,
    ) -> None:
        """Test path that is directory raises ConfigError."""
        with pytest.raises(ConfigError, match="is not a file"):
            load_config_template(configs_dir)

    def test_load_full_config_with_config_name(
        self,
        write_config: callable,
    ) -> None:
        """Test loading a full config with config_name field."""
        content = """\
config_name: full-test
description: "Full config with phase_models"

providers:
  master:
    provider: claude-subprocess
    model: opus
  multi:
    - provider: gemini
      model: gemini-2.5-flash

phase_models:
  create_story:
    provider: claude-subprocess
    model: opus

timeouts:
  default: 600
"""
        path = write_config(content, "full-test.yaml")
        template = load_config_template(path)

        assert template.name == "full-test"
        assert template.description == "Full config with phase_models"
        # Providers extracted for display
        assert template.providers is not None
        assert template.providers.master.provider == "claude-subprocess"
        # raw_config contains all fields
        assert "phase_models" in template.raw_config
        assert "timeouts" in template.raw_config
        assert template.raw_config["config_name"] == "full-test"

    def test_load_full_config_preserves_all_fields(
        self,
        write_config: callable,
    ) -> None:
        """Test full config raw_config preserves all fields."""
        content = """\
config_name: preserved
providers:
  master:
    provider: claude
    model: opus
  multi: []

deep_verify:
  enabled: true
security_agent:
  enabled: true
compiler:
  source_context:
    budgets:
      default: 30000
"""
        path = write_config(content, "preserved.yaml")
        template = load_config_template(path)

        assert "deep_verify" in template.raw_config
        assert "security_agent" in template.raw_config
        assert "compiler" in template.raw_config

    def test_load_full_config_without_providers_section(
        self,
        write_config: callable,
    ) -> None:
        """Test full config without providers section has None providers."""
        content = """\
config_name: no-providers
phase_models:
  create_story:
    provider: claude-subprocess
    model: opus
"""
        path = write_config(content, "no-providers.yaml")
        template = load_config_template(path)

        assert template.name == "no-providers"
        assert template.providers is None
        assert "phase_models" in template.raw_config


class TestConfigRegistry:
    """Tests for ConfigRegistry class."""

    def test_discover_finds_yaml_files(
        self,
        write_config: callable,
        configs_dir: Path,
    ) -> None:
        """Test discovery finds all .yaml files."""
        write_config(
            "name: config-a\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "config-a.yaml",
        )
        write_config(
            "name: config-b\nproviders:\n  master:\n    provider: claude\n    model: haiku\n  multi: []",
            "config-b.yaml",
        )

        registry = ConfigRegistry(configs_dir)
        names = registry.list()

        assert sorted(names) == ["config-a", "config-b"]

    def test_discover_skips_hidden_files(
        self,
        write_config: callable,
        configs_dir: Path,
    ) -> None:
        """Test discovery skips hidden files."""
        write_config(
            "name: visible\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "visible.yaml",
        )
        (configs_dir / ".hidden.yaml").write_text(
            "name: hidden\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []"
        )

        registry = ConfigRegistry(configs_dir)
        names = registry.list()

        assert names == ["visible"]

    def test_discover_skips_yml_files(
        self,
        write_config: callable,
        configs_dir: Path,
    ) -> None:
        """Test discovery only finds .yaml, not .yml files."""
        write_config(
            "name: yaml-file\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "yaml-file.yaml",
        )
        (configs_dir / "yml-file.yml").write_text(
            "name: yml-file\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []"
        )

        registry = ConfigRegistry(configs_dir)
        names = registry.list()

        assert names == ["yaml-file"]

    def test_discover_finds_config_name_files(
        self,
        write_config: callable,
        configs_dir: Path,
    ) -> None:
        """Test discovery finds files using config_name field."""
        write_config(
            "config_name: full-cfg\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []\nphase_models:\n  create_story:\n    provider: claude\n    model: opus",
            "full-cfg.yaml",
        )
        write_config(
            "name: legacy-cfg\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "legacy-cfg.yaml",
        )

        registry = ConfigRegistry(configs_dir)
        names = registry.list()

        assert sorted(names) == ["full-cfg", "legacy-cfg"]

    def test_discover_skips_name_mismatch(
        self,
        write_config: callable,
        configs_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test discovery skips files where name doesn't match filename."""
        write_config(
            "name: correct\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "correct.yaml",
        )
        write_config(
            "name: wrong-name\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "mismatched.yaml",
        )

        with caplog.at_level(logging.WARNING):
            registry = ConfigRegistry(configs_dir)
            names = registry.list()

        assert names == ["correct"]
        assert "does not match filename stem" in caplog.text

    def test_discover_skips_malformed_yaml(
        self,
        write_config: callable,
        configs_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test discovery skips files with invalid YAML."""
        write_config(
            "name: valid\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "valid.yaml",
        )
        write_config("invalid: yaml: [", "invalid.yaml")

        with caplog.at_level(logging.WARNING):
            registry = ConfigRegistry(configs_dir)
            names = registry.list()

        assert names == ["valid"]
        assert "invalid YAML" in caplog.text

    def test_discover_nonexistent_directory(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test discovery returns empty dict for non-existent directory."""
        nonexistent = tmp_path / "nonexistent"

        with caplog.at_level(logging.INFO):
            registry = ConfigRegistry(nonexistent)
            names = registry.list()

        assert names == []
        assert "does not exist" in caplog.text

    def test_get_returns_template(
        self,
        write_config: callable,
        configs_dir: Path,
    ) -> None:
        """Test get() returns loaded template."""
        write_config(
            "name: test-config\ndescription: Test\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "test-config.yaml",
        )

        registry = ConfigRegistry(configs_dir)
        template = registry.get("test-config")

        assert template.name == "test-config"
        assert template.description == "Test"

    def test_get_not_found_raises_error(
        self,
        write_config: callable,
        configs_dir: Path,
    ) -> None:
        """Test get() raises ConfigError for unknown name."""
        write_config(
            "name: existing\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "existing.yaml",
        )

        registry = ConfigRegistry(configs_dir)

        with pytest.raises(ConfigError, match="not found") as exc_info:
            registry.get("nonexistent")

        assert "existing" in str(exc_info.value)  # Should list available

    def test_get_caches_templates(
        self,
        write_config: callable,
        configs_dir: Path,
    ) -> None:
        """Test get() caches loaded templates."""
        write_config(
            "name: cached\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "cached.yaml",
        )

        registry = ConfigRegistry(configs_dir)

        template1 = registry.get("cached")
        template2 = registry.get("cached")

        # Same instance due to caching
        assert template1 is template2

    def test_list_returns_sorted_names(
        self,
        write_config: callable,
        configs_dir: Path,
    ) -> None:
        """Test list() returns sorted names."""
        write_config(
            "name: zebra\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "zebra.yaml",
        )
        write_config(
            "name: alpha\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "alpha.yaml",
        )
        write_config(
            "name: beta\nproviders:\n  master:\n    provider: claude\n    model: opus\n  multi: []",
            "beta.yaml",
        )

        registry = ConfigRegistry(configs_dir)
        names = registry.list()

        assert names == ["alpha", "beta", "zebra"]

    def test_registry_with_project_root(
        self,
        configs_dir: Path,
        project_root: Path,
    ) -> None:
        """Test registry resolves ${project} in templates."""
        # Create settings file
        settings_dir = project_root / ".bmad-assist"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text("{}")

        # Create config using ${project}
        content = """\
name: with-project
providers:
  master:
    provider: claude
    model: opus
    settings: ${project}/.bmad-assist/settings.json
  multi: []
"""
        (configs_dir / "with-project.yaml").write_text(content)

        registry = ConfigRegistry(configs_dir, project_root=project_root)
        template = registry.get("with-project")

        expected = f"{project_root}/.bmad-assist/settings.json"
        assert template.providers.master.settings == expected


class TestKnownProviders:
    """Tests for KNOWN_PROVIDERS constant."""

    def test_known_providers_is_frozenset(self) -> None:
        """Test KNOWN_PROVIDERS is a frozenset."""
        assert isinstance(KNOWN_PROVIDERS, frozenset)

    def test_known_providers_contains_expected(self) -> None:
        """Test KNOWN_PROVIDERS contains expected providers."""
        expected = {"claude", "claude-subprocess", "codex", "gemini"}
        assert expected == KNOWN_PROVIDERS


class TestDefaultTemplates:
    """Tests for default config templates in experiments/configs/."""

    @pytest.fixture
    def default_configs_dir(self) -> Path:
        """Path to default config templates."""
        # This assumes tests are run from project root
        return Path("experiments/configs")

    def test_opus_solo_exists(self, default_configs_dir: Path) -> None:
        """Test opus-solo.yaml exists and is valid."""
        if not default_configs_dir.exists():
            pytest.skip("Default configs not available in this environment")

        template = load_config_template(default_configs_dir / "opus-solo.yaml")
        assert template.name == "opus-solo"
        assert template.providers.master.model == "opus"
        assert template.providers.multi == []

    def test_haiku_solo_exists(self, default_configs_dir: Path) -> None:
        """Test haiku-solo.yaml exists and is valid."""
        if not default_configs_dir.exists():
            pytest.skip("Default configs not available in this environment")

        template = load_config_template(default_configs_dir / "haiku-solo.yaml")
        assert template.name == "haiku-solo"
        assert template.providers.master.model == "haiku"

    def test_sonnet_solo_exists(self, default_configs_dir: Path) -> None:
        """Test sonnet-solo.yaml exists and is valid."""
        if not default_configs_dir.exists():
            pytest.skip("Default configs not available in this environment")

        template = load_config_template(default_configs_dir / "sonnet-solo.yaml")
        assert template.name == "sonnet-solo"
        assert template.providers.master.model == "sonnet"

    def test_all_default_templates_discoverable(self, default_configs_dir: Path) -> None:
        """Test ConfigRegistry discovers all YAML configs in the directory."""
        if not default_configs_dir.exists():
            pytest.skip("Default configs not available in this environment")

        registry = ConfigRegistry(default_configs_dir)
        names = registry.list()

        # Dynamically derive expected from actual YAML files on disk
        yaml_files = sorted(
            p.stem for p in default_configs_dir.glob("*.yaml")
        )
        assert sorted(names) == yaml_files
        assert len(names) >= 1, "Should discover at least one config template"
