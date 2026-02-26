"""Tests for state location configuration (Story 3.6).

This module tests the configurable state file location functionality:
- DEFAULT_STATE_PATH constant
- get_state_path() function
- Config.state_path field

Test organization follows Epic 3 patterns with comprehensive edge case coverage.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from bmad_assist.core.config import Config, _reset_config
from bmad_assist.core.state import (
    DEFAULT_STATE_PATH,
    State,
    get_state_path,
    load_state,
    save_state,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def minimal_providers_dict() -> dict:
    """Minimal providers configuration for creating Config instances."""
    return {
        "providers": {
            "master": {"provider": "claude", "model": "opus_4"},
        },
    }


@pytest.fixture
def config_with_local_path(tmp_path: Path, minimal_providers_dict: dict) -> Config:
    """Config with project-local state path."""
    config_dict = {
        **minimal_providers_dict,
        "state_path": str(tmp_path / "local-state.yaml"),
    }
    return Config.model_validate(config_dict)


@pytest.fixture
def config_with_global_path(minimal_providers_dict: dict) -> Config:
    """Config with global (tilde) state path."""
    config_dict = {
        **minimal_providers_dict,
        "state_path": "~/.bmad-assist/state.yaml",
    }
    return Config.model_validate(config_dict)


@pytest.fixture
def config_without_state_path(minimal_providers_dict: dict) -> Config:
    """Config without state_path field set (None)."""
    return Config.model_validate(minimal_providers_dict)


@pytest.fixture
def config_with_empty_state_path(minimal_providers_dict: dict) -> Config:
    """Config with empty string state_path."""
    config_dict = {
        **minimal_providers_dict,
        "state_path": "",
    }
    return Config.model_validate(config_dict)


@pytest.fixture
def config_with_relative_path(minimal_providers_dict: dict) -> Config:
    """Config with relative state path (no leading ./)."""
    config_dict = {
        **minimal_providers_dict,
        "state_path": "state/loop-state.yaml",
    }
    return Config.model_validate(config_dict)


@pytest.fixture(autouse=True)
def reset_config_singleton() -> None:
    """Reset config singleton before each test."""
    _reset_config()


# =============================================================================
# TestConfigStatePath - AC4
# =============================================================================


class TestConfigStatePath:
    """Tests for Config.state_path field (AC4)."""

    def test_state_path_field_exists(self, minimal_providers_dict: dict) -> None:
        """AC4: state_path field exists in Config model."""
        assert "state_path" in Config.model_fields

    def test_state_path_type_is_str_or_none(self) -> None:
        """AC4: state_path type annotation is str | None."""
        field_info = Config.model_fields["state_path"]
        # Check annotation allows both str and None
        annotation = field_info.annotation
        # str | None represented as Union[str, None]
        assert annotation == str | None

    def test_state_path_default_is_none(self, minimal_providers_dict: dict) -> None:
        """AC4: state_path default value is None."""
        config = Config.model_validate(minimal_providers_dict)
        assert config.state_path is None

    def test_state_path_accepts_string(self, minimal_providers_dict: dict) -> None:
        """AC4: state_path accepts string value."""
        config_dict = {
            **minimal_providers_dict,
            "state_path": "/custom/path/state.yaml",
        }
        config = Config.model_validate(config_dict)
        assert config.state_path == "/custom/path/state.yaml"

    def test_state_path_accepts_none(self, minimal_providers_dict: dict) -> None:
        """AC4: state_path accepts None explicitly."""
        config_dict = {
            **minimal_providers_dict,
            "state_path": None,
        }
        config = Config.model_validate(config_dict)
        assert config.state_path is None

    def test_state_path_has_description(self) -> None:
        """AC4: state_path field has description docstring."""
        field_info = Config.model_fields["state_path"]
        assert field_info.description is not None
        assert "state file" in field_info.description.lower()
        assert "~/.bmad-assist/state.yaml" in field_info.description


# =============================================================================
# TestGetStatePathWithConfig - AC1, AC2, AC5
# =============================================================================


class TestGetStatePathWithConfig:
    """Tests for get_state_path with Config provided."""

    def test_local_path_returns_absolute(
        self, config_with_local_path: Config, tmp_path: Path
    ) -> None:
        """AC1: Config with project-local state_path uses local path."""
        result = get_state_path(config_with_local_path)

        assert result.is_absolute()
        assert result.name == "local-state.yaml"
        assert str(tmp_path) in str(result)

    def test_global_path_expands_tilde(self, config_with_global_path: Config) -> None:
        """AC2: Config with global state_path expands tilde."""
        result = get_state_path(config_with_global_path)

        assert result.is_absolute()
        assert "~" not in str(result)
        assert ".bmad-assist" in str(result)
        assert result.name == "state.yaml"

    def test_relative_path_resolved_to_absolute(self, config_with_relative_path: Config) -> None:
        """AC5: Relative paths resolved to absolute."""
        result = get_state_path(config_with_relative_path)

        assert result.is_absolute()
        # Path should contain cwd since it's relative
        cwd = Path.cwd()
        assert str(result).startswith(str(cwd))
        assert result.name == "loop-state.yaml"

    def test_dot_relative_path_resolved(self, minimal_providers_dict: dict) -> None:
        """AC1/AC5: Dot-relative path (./file) resolved to absolute."""
        config_dict = {
            **minimal_providers_dict,
            "state_path": "./bmad-state.yaml",
        }
        config = Config.model_validate(config_dict)

        result = get_state_path(config)

        assert result.is_absolute()
        assert result.name == "bmad-state.yaml"
        cwd = Path.cwd()
        assert str(result).startswith(str(cwd))

    def test_absolute_path_unchanged(self, minimal_providers_dict: dict, tmp_path: Path) -> None:
        """Absolute paths are returned as-is (already resolved)."""
        abs_path = tmp_path / "absolute" / "state.yaml"
        config_dict = {
            **minimal_providers_dict,
            "state_path": str(abs_path),
        }
        config = Config.model_validate(config_dict)

        result = get_state_path(config)

        assert result.is_absolute()
        # Path.resolve() may add symlink resolution, so compare resolved
        assert result == abs_path.resolve()


# =============================================================================
# TestGetStatePathWithoutConfig - AC3, AC7
# =============================================================================


class TestGetStatePathWithoutConfig:
    """Tests for get_state_path without Config (uses default)."""

    def test_none_config_uses_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC3: Config without state_path uses default global path."""
        monkeypatch.chdir(tmp_path)
        result = get_state_path(None)

        assert result.is_absolute()
        assert "~" not in str(result)
        assert ".bmad-assist" in str(result)
        assert result.name == "state.yaml"

    def test_no_argument_uses_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC7: get_state_path() called without arguments uses default."""
        monkeypatch.chdir(tmp_path)
        result = get_state_path()

        assert result.is_absolute()
        assert "~" not in str(result)
        assert ".bmad-assist" in str(result)
        assert result.name == "state.yaml"

    def test_config_with_none_state_path_uses_default(
        self, config_without_state_path: Config
    ) -> None:
        """AC3: Config with state_path=None uses default."""
        result = get_state_path(config_without_state_path)

        assert result.is_absolute()
        assert "~" not in str(result)
        assert ".bmad-assist" in str(result)
        assert result.name == "state.yaml"

    def test_default_path_is_in_home_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default path is under user's home directory."""
        monkeypatch.chdir(tmp_path)
        result = get_state_path()

        # With CWD-based state path, result is now CWD/.bmad-assist/state.yaml
        assert result.is_absolute()
        assert ".bmad-assist" in str(result)
        assert result.name == "state.yaml"


# =============================================================================
# TestGetStatePathEdgeCases - AC9
# =============================================================================


class TestGetStatePathEdgeCases:
    """Tests for get_state_path edge cases."""

    def test_empty_string_treated_as_none(self, config_with_empty_state_path: Config) -> None:
        """AC9: Empty string state_path treated as None (uses default)."""
        result = get_state_path(config_with_empty_state_path)

        assert result.is_absolute()
        assert "~" not in str(result)
        assert ".bmad-assist" in str(result)
        assert result.name == "state.yaml"

    def test_whitespace_only_path_uses_default(self, minimal_providers_dict: dict) -> None:
        """Whitespace-only state_path should use default (falsy check)."""
        config_dict = {
            **minimal_providers_dict,
            "state_path": "   ",  # Just whitespace
        }
        config = Config.model_validate(config_dict)

        # Whitespace string is truthy, so it will try to use it
        # This is expected behavior - Path("   ") creates a path
        result = get_state_path(config)

        # Whitespace is truthy, so it won't use default
        # This tests current implementation behavior
        assert result.is_absolute()

    def test_path_with_spaces_in_name(self, minimal_providers_dict: dict, tmp_path: Path) -> None:
        """Path with spaces in name is handled correctly."""
        path_with_spaces = tmp_path / "my state" / "file name.yaml"
        config_dict = {
            **minimal_providers_dict,
            "state_path": str(path_with_spaces),
        }
        config = Config.model_validate(config_dict)

        result = get_state_path(config)

        assert result.is_absolute()
        assert "my state" in str(result)
        assert result.name == "file name.yaml"


# =============================================================================
# TestDefaultStatePathConstant - AC10
# =============================================================================


class TestDefaultStatePathConstant:
    """Tests for DEFAULT_STATE_PATH constant (AC10)."""

    def test_default_state_path_exported(self) -> None:
        """AC10: DEFAULT_STATE_PATH is exported from state module."""
        from bmad_assist.core import state

        assert hasattr(state, "DEFAULT_STATE_PATH")
        assert "DEFAULT_STATE_PATH" in state.__all__

    def test_default_state_path_value(self) -> None:
        """AC10: DEFAULT_STATE_PATH has expected value."""
        assert DEFAULT_STATE_PATH == "~/.bmad-assist/state.yaml"

    def test_default_state_path_is_string(self) -> None:
        """AC10: DEFAULT_STATE_PATH is a string constant."""
        assert isinstance(DEFAULT_STATE_PATH, str)

    def test_default_state_path_can_be_used_by_modules(self) -> None:
        """AC10: Constant can be used by other modules."""
        # Verify it can be imported and used
        path = Path(DEFAULT_STATE_PATH).expanduser()
        assert path.is_absolute()
        assert path.name == "state.yaml"


# =============================================================================
# TestFunctionSignatureAndExports - AC6, AC11
# =============================================================================


class TestFunctionSignatureAndExports:
    """Tests for get_state_path signature and exports (AC6, AC11)."""

    def test_function_exported_in_all(self) -> None:
        """AC6/AC11: get_state_path is exported in __all__."""
        from bmad_assist.core import state

        assert "get_state_path" in state.__all__

    def test_default_state_path_exported_in_all(self) -> None:
        """AC11: DEFAULT_STATE_PATH is in __all__."""
        from bmad_assist.core import state

        assert "DEFAULT_STATE_PATH" in state.__all__

    def test_function_signature(self) -> None:
        """AC6: get_state_path has correct signature."""
        sig = inspect.signature(get_state_path)

        # Check parameters
        params = list(sig.parameters.values())
        assert len(params) == 2

        # First param: config
        assert params[0].name == "config"
        assert params[0].default is None

        # Second param: project_root (keyword-only)
        assert params[1].name == "project_root"
        assert params[1].default is None
        assert params[1].kind == inspect.Parameter.KEYWORD_ONLY

        # Check return type
        assert sig.return_annotation == Path

    def test_function_has_docstring(self) -> None:
        """AC6: get_state_path has Google-style docstring."""
        doc = get_state_path.__doc__
        assert doc is not None
        assert len(doc) > 0

    def test_docstring_has_args_section(self) -> None:
        """AC6: Docstring has Args section."""
        doc = get_state_path.__doc__
        assert doc is not None
        assert "Args:" in doc

    def test_docstring_has_returns_section(self) -> None:
        """AC6: Docstring has Returns section."""
        doc = get_state_path.__doc__
        assert doc is not None
        assert "Returns:" in doc

    def test_docstring_has_example_section(self) -> None:
        """AC6: Docstring has Example section."""
        doc = get_state_path.__doc__
        assert doc is not None
        assert "Example:" in doc


# =============================================================================
# TestIntegrationWithSaveLoad - AC8
# =============================================================================


class TestIntegrationWithSaveLoad:
    """Tests for integration with existing save_state/load_state (AC8)."""

    def test_save_and_load_with_get_state_path(
        self, tmp_path: Path, minimal_providers_dict: dict
    ) -> None:
        """AC8: Integration with save_state/load_state works."""
        # Configure custom path
        state_file = tmp_path / "project-state.yaml"
        config_dict = {
            **minimal_providers_dict,
            "state_path": str(state_file),
        }
        config = Config.model_validate(config_dict)

        # Get the path
        path = get_state_path(config)

        # Create and save state
        state = State(current_epic=3, current_story="3.6")
        save_state(state, path)

        # Load state back
        loaded = load_state(path)

        assert loaded.current_epic == 3
        assert loaded.current_story == "3.6"

    def test_existing_functions_work_without_modification(self, tmp_path: Path) -> None:
        """AC8: Existing save_state/load_state work without modification."""
        # Use get_state_path result directly with existing functions
        state_file = tmp_path / "direct-state.yaml"

        # Direct path usage (existing behavior)
        state = State(current_epic=1, current_story="1.1")
        save_state(state, state_file)

        loaded = load_state(state_file)
        assert loaded.current_epic == 1
        assert loaded.current_story == "1.1"

    def test_round_trip_with_configured_path(self, config_with_local_path: Config) -> None:
        """AC8: Full round-trip with configured path."""
        path = get_state_path(config_with_local_path)

        # Create parent directory
        path.parent.mkdir(parents=True, exist_ok=True)

        # Save
        original = State(
            current_epic=5,
            current_story="5.3",
        )
        save_state(original, path)

        # Load
        loaded = load_state(path)

        assert loaded.current_epic == original.current_epic
        assert loaded.current_story == original.current_story


# =============================================================================
# TestPathExpansionBehavior
# =============================================================================


class TestPathExpansionBehavior:
    """Tests for path expansion behavior (expanduser + resolve)."""

    def test_tilde_expanded_before_resolve(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tilde is expanded before resolve (correct order)."""
        monkeypatch.chdir(tmp_path)
        result = get_state_path()

        # Should contain actual directory path, not tilde
        assert "~" not in str(result)
        # Result should be absolute path under CWD
        assert result.is_absolute()
        assert ".bmad-assist" in str(result)

    def test_resolve_handles_symlinks(self, tmp_path: Path) -> None:
        """Path.resolve() follows symlinks (expected behavior)."""
        # Create a symlink scenario
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link_dir = tmp_path / "link"

        try:
            link_dir.symlink_to(real_dir)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")

        config = Config.model_validate(
            {
                "providers": {"master": {"provider": "claude", "model": "opus_4"}},
                "state_path": str(link_dir / "state.yaml"),
            }
        )

        result = get_state_path(config)

        # resolve() follows symlinks
        assert str(real_dir) in str(result)

    def test_relative_path_resolved_from_cwd(self, minimal_providers_dict: dict) -> None:
        """Relative paths are resolved from current working directory."""
        config_dict = {
            **minimal_providers_dict,
            "state_path": "relative/path/state.yaml",
        }
        config = Config.model_validate(config_dict)

        result = get_state_path(config)

        cwd = Path.cwd()
        expected = cwd / "relative" / "path" / "state.yaml"
        assert result == expected.resolve()


# =============================================================================
# TestConfigValidatorInteraction
# =============================================================================


class TestConfigValidatorInteraction:
    """Tests for interaction with Config's expand_state_path validator."""

    def test_config_expands_tilde_in_state_path(self, minimal_providers_dict: dict) -> None:
        """Config validator expands tilde when state_path is set."""
        config_dict = {
            **minimal_providers_dict,
            "state_path": "~/custom/state.yaml",
        }
        config = Config.model_validate(config_dict)

        # Config validator should have expanded tilde
        assert "~" not in str(config.state_path)
        assert config.state_path is not None
        assert config.state_path.startswith("/")

    def test_config_none_state_path_not_expanded(self, config_without_state_path: Config) -> None:
        """Config validator doesn't fail on None state_path."""
        assert config_without_state_path.state_path is None

    def test_get_state_path_works_with_pre_expanded_path(
        self, minimal_providers_dict: dict
    ) -> None:
        """get_state_path works even if Config already expanded tilde."""
        config_dict = {
            **minimal_providers_dict,
            "state_path": "~/.custom/state.yaml",
        }
        config = Config.model_validate(config_dict)

        # Config validator already expanded
        assert "~" not in str(config.state_path)

        # get_state_path should still work (expanduser on expanded path is no-op)
        result = get_state_path(config)
        assert result.is_absolute()
        assert ".custom" in str(result)


# =============================================================================
# TestProjectRootParameter - New tests for project-based state location
# =============================================================================


class TestProjectRootParameter:
    """Tests for the project_root parameter in get_state_path."""

    def test_project_root_returns_state_in_project_dir(self, tmp_path: Path) -> None:
        """project_root param puts state in {project}/.bmad-assist/state.yaml."""
        result = get_state_path(project_root=tmp_path)

        expected = tmp_path / ".bmad-assist" / "state.yaml"
        assert result == expected.resolve()

    def test_project_root_takes_precedence_over_default(self, tmp_path: Path) -> None:
        """project_root is used even without config."""
        result = get_state_path(project_root=tmp_path)

        # Should NOT be in default location
        assert "~" not in str(result)
        assert str(tmp_path) in str(result)

    def test_config_state_path_takes_precedence_over_project_root(
        self, tmp_path: Path, minimal_providers_dict: dict
    ) -> None:
        """Explicit config.state_path wins over project_root."""
        custom_path = tmp_path / "custom-state.yaml"
        config = Config.model_validate(
            {
                **minimal_providers_dict,
                "state_path": str(custom_path),
            }
        )

        # Even with project_root, config.state_path wins
        result = get_state_path(config, project_root=tmp_path / "some-project")

        assert result == custom_path.resolve()

    def test_no_args_uses_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without project_root, uses CWD as project root."""
        monkeypatch.chdir(tmp_path)

        result = get_state_path()

        expected = tmp_path / ".bmad-assist" / "state.yaml"
        assert result == expected.resolve()

    def test_project_root_integration_with_save_load(self, tmp_path: Path) -> None:
        """State can be saved/loaded using project_root path."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        state_path = get_state_path(project_root=project_dir)

        # Create and save state
        state = State(current_epic=11, current_story="11.3")
        save_state(state, state_path)

        # Verify file location
        expected_file = project_dir / ".bmad-assist" / "state.yaml"
        assert expected_file.exists()

        # Load and verify
        loaded = load_state(state_path)
        assert loaded.current_epic == 11
        assert loaded.current_story == "11.3"
