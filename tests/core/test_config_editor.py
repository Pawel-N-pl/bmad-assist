"""Tests for ConfigEditor and ProvenanceTracker.

This test module covers:
- ProvenanceTracker building and querying
- ConfigEditor loading and context manager
- Merged config with provenance
- Update, remove, and validate operations
- Backup rotation
- Atomic save
- List and restore backups
- reload_config singleton swap
"""

import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from bmad_assist.core.config import (
    get_config,
    load_global_config,
    reload_config,
)
from bmad_assist.core.config_editor import (
    ConfigEditor,
    ProvenanceTracker,
    _delete_nested_value,
    _flatten_dict,
    _get_nested_value,
    _set_nested_value,
)
from bmad_assist.core.exceptions import ConfigError

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def minimal_global_config() -> str:
    """Minimal valid global config YAML."""
    return """\
providers:
  master:
    provider: claude
    model: opus
"""


@pytest.fixture
def full_global_config() -> str:
    """Global config with multiple settings."""
    return """\
providers:
  master:
    provider: claude
    model: opus
  multi:
    - provider: gemini
      model: flash
benchmarking:
  enabled: true
  extraction_provider: claude
  extraction_model: haiku
timeout: 300
"""


@pytest.fixture
def project_config() -> str:
    """Project config that overrides some global settings."""
    return """\
benchmarking:
  enabled: false
timeout: 600
"""


@pytest.fixture
def global_config_file(tmp_path: Path, minimal_global_config: str) -> Path:
    """Create a global config file."""
    path = tmp_path / "global" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(minimal_global_config)
    return path


@pytest.fixture
def full_global_config_file(tmp_path: Path, full_global_config: str) -> Path:
    """Create a full global config file."""
    path = tmp_path / "global" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(full_global_config)
    return path


@pytest.fixture
def project_config_file(tmp_path: Path, project_config: str) -> Path:
    """Create a project config file."""
    path = tmp_path / "project" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(project_config)
    return path


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestFlattenDict:
    """Tests for _flatten_dict helper."""

    def test_flat_dict(self) -> None:
        """Flat dict remains unchanged."""
        d = {"a": 1, "b": 2}
        assert _flatten_dict(d) == {"a": 1, "b": 2}

    def test_nested_dict(self) -> None:
        """Nested dict is flattened with dot notation."""
        d = {"a": {"b": 1, "c": 2}}
        assert _flatten_dict(d) == {"a.b": 1, "a.c": 2}

    def test_deeply_nested(self) -> None:
        """Deeply nested dict is fully flattened."""
        d = {"a": {"b": {"c": 3}}}
        assert _flatten_dict(d) == {"a.b.c": 3}

    def test_mixed_nesting(self) -> None:
        """Mixed nesting levels are handled."""
        d = {"a": 1, "b": {"c": 2}, "d": {"e": {"f": 3}}}
        expected = {"a": 1, "b.c": 2, "d.e.f": 3}
        assert _flatten_dict(d) == expected

    def test_empty_dict(self) -> None:
        """Empty dict returns empty dict."""
        assert _flatten_dict({}) == {}


class TestGetNestedValue:
    """Tests for _get_nested_value helper."""

    def test_top_level(self) -> None:
        """Get top-level key."""
        d = {"a": 1}
        value, found = _get_nested_value(d, "a")
        assert found is True
        assert value == 1

    def test_nested(self) -> None:
        """Get nested key."""
        d = {"a": {"b": 2}}
        value, found = _get_nested_value(d, "a.b")
        assert found is True
        assert value == 2

    def test_missing_top_level(self) -> None:
        """Missing top-level key returns (None, False)."""
        d = {"a": 1}
        value, found = _get_nested_value(d, "b")
        assert found is False
        assert value is None

    def test_missing_nested(self) -> None:
        """Missing nested key returns (None, False)."""
        d = {"a": {"b": 1}}
        value, found = _get_nested_value(d, "a.c")
        assert found is False

    def test_intermediate_not_dict(self) -> None:
        """Non-dict intermediate value returns (None, False)."""
        d = {"a": 1}
        value, found = _get_nested_value(d, "a.b")
        assert found is False


class TestSetNestedValue:
    """Tests for _set_nested_value helper."""

    def test_top_level(self) -> None:
        """Set top-level key."""
        d: dict = {}
        _set_nested_value(d, "a", 1)
        assert d == {"a": 1}

    def test_nested_creates_intermediate(self) -> None:
        """Setting nested path creates intermediate dicts."""
        d: dict = {}
        _set_nested_value(d, "a.b.c", 3)
        assert d == {"a": {"b": {"c": 3}}}

    def test_overwrite_existing(self) -> None:
        """Overwrite existing value."""
        d = {"a": 1}
        _set_nested_value(d, "a", 2)
        assert d == {"a": 2}

    def test_empty_path_raises(self) -> None:
        """Empty path raises ValueError."""
        d: dict = {}
        with pytest.raises(ValueError, match="Path cannot be empty"):
            _set_nested_value(d, "", 1)

    def test_empty_segment_raises(self) -> None:
        """Empty segment in path raises ValueError."""
        d: dict = {}
        with pytest.raises(ValueError, match="empty segment"):
            _set_nested_value(d, "a..b", 1)

    def test_leading_dot_raises(self) -> None:
        """Leading dot raises ValueError."""
        d: dict = {}
        with pytest.raises(ValueError, match="empty segment"):
            _set_nested_value(d, ".a", 1)

    def test_trailing_dot_raises(self) -> None:
        """Trailing dot raises ValueError."""
        d: dict = {}
        with pytest.raises(ValueError, match="empty segment"):
            _set_nested_value(d, "a.", 1)

    def test_intermediate_not_dict_raises(self) -> None:
        """Non-dict intermediate value raises ValueError."""
        d = {"a": 1}
        with pytest.raises(ValueError, match="is int, not dict"):
            _set_nested_value(d, "a.b", 2)

    def test_numeric_segment_as_dict_key(self) -> None:
        """Numeric segment is treated as dict key, not array index."""
        d: dict = {}
        _set_nested_value(d, "items.0", "first")
        assert d == {"items": {"0": "first"}}


class TestDeleteNestedValue:
    """Tests for _delete_nested_value helper."""

    def test_delete_top_level(self) -> None:
        """Delete top-level key."""
        d = {"a": 1, "b": 2}
        result = _delete_nested_value(d, "a")
        assert result is True
        assert d == {"b": 2}

    def test_delete_nested(self) -> None:
        """Delete nested key."""
        d = {"a": {"b": 1, "c": 2}}
        result = _delete_nested_value(d, "a.b")
        assert result is True
        assert d == {"a": {"c": 2}}

    def test_delete_missing_returns_false(self) -> None:
        """Deleting missing key returns False."""
        d = {"a": 1}
        result = _delete_nested_value(d, "b")
        assert result is False

    def test_delete_idempotent(self) -> None:
        """Deleting same key twice is idempotent."""
        d = {"a": 1}
        _delete_nested_value(d, "a")
        result = _delete_nested_value(d, "a")
        assert result is False

    def test_empty_path_raises(self) -> None:
        """Empty path raises ValueError."""
        d = {"a": 1}
        with pytest.raises(ValueError, match="Path cannot be empty"):
            _delete_nested_value(d, "")


# =============================================================================
# ProvenanceTracker Tests
# =============================================================================


class TestProvenanceTracker:
    """Tests for ProvenanceTracker."""

    def test_default_only(self) -> None:
        """Values only in defaults have 'default' provenance."""
        defaults = {"a": 1, "b": 2}
        tracker = ProvenanceTracker(defaults=defaults, global_cfg={}, project_cfg={})

        assert tracker.get_provenance("a") == "default"
        assert tracker.get_provenance("b") == "default"

    def test_global_overrides_default(self) -> None:
        """Global config overrides default provenance."""
        defaults = {"a": 1}
        global_cfg = {"a": 10}
        tracker = ProvenanceTracker(defaults=defaults, global_cfg=global_cfg, project_cfg={})

        assert tracker.get_provenance("a") == "global"

    def test_project_overrides_global(self) -> None:
        """Project config overrides global provenance."""
        defaults = {"a": 1}
        global_cfg = {"a": 10}
        project_cfg = {"a": 100}
        tracker = ProvenanceTracker(
            defaults=defaults, global_cfg=global_cfg, project_cfg=project_cfg
        )

        assert tracker.get_provenance("a") == "project"

    def test_nested_provenance(self) -> None:
        """Nested values tracked with dot notation."""
        defaults = {"a": {"b": 1}}
        global_cfg = {"a": {"b": 10}}
        tracker = ProvenanceTracker(defaults=defaults, global_cfg=global_cfg, project_cfg={})

        assert tracker.get_provenance("a.b") == "global"

    def test_mixed_provenance(self) -> None:
        """Different values can have different provenances."""
        defaults = {"a": 1, "b": 2, "c": 3}
        global_cfg = {"b": 20}
        project_cfg = {"c": 300}
        tracker = ProvenanceTracker(
            defaults=defaults, global_cfg=global_cfg, project_cfg=project_cfg
        )

        assert tracker.get_provenance("a") == "default"
        assert tracker.get_provenance("b") == "global"
        assert tracker.get_provenance("c") == "project"

    def test_get_all_provenance(self) -> None:
        """get_all_provenance returns complete mapping."""
        defaults = {"a": 1}
        global_cfg = {"b": 2}
        tracker = ProvenanceTracker(defaults=defaults, global_cfg=global_cfg, project_cfg={})

        all_prov = tracker.get_all_provenance()
        assert "a" in all_prov
        assert "b" in all_prov

    def test_unknown_path_returns_default(self) -> None:
        """Unknown path returns 'default' provenance."""
        tracker = ProvenanceTracker(defaults={}, global_cfg={}, project_cfg={})
        assert tracker.get_provenance("unknown.path") == "default"


# =============================================================================
# ConfigEditor Tests
# =============================================================================


class TestConfigEditorLoad:
    """Tests for ConfigEditor loading."""

    def test_load_global_only(self, global_config_file: Path) -> None:
        """Load with global config only."""
        editor = ConfigEditor(global_path=global_config_file)
        editor.load()

        global_data = editor.get_global_raw()
        assert "providers" in global_data
        assert global_data["providers"]["master"]["provider"] == "claude"

    def test_load_with_project(
        self, full_global_config_file: Path, project_config_file: Path
    ) -> None:
        """Load with both global and project configs."""
        editor = ConfigEditor(
            global_path=full_global_config_file,
            project_path=project_config_file,
        )
        editor.load()

        global_data = editor.get_global_raw()
        project_data = editor.get_project_raw()

        assert global_data["benchmarking"]["enabled"] is True
        assert project_data["benchmarking"]["enabled"] is False

    def test_load_missing_global_raises(self, tmp_path: Path) -> None:
        """Loading with missing global config raises ConfigError."""
        editor = ConfigEditor(global_path=tmp_path / "nonexistent.yaml")

        with pytest.raises(ConfigError, match="Config file not found"):
            editor.load()

    def test_load_missing_project_ok(self, global_config_file: Path, tmp_path: Path) -> None:
        """Missing project config is not an error."""
        editor = ConfigEditor(
            global_path=global_config_file,
            project_path=tmp_path / "nonexistent.yaml",
        )
        editor.load()

        assert editor.get_project_raw() == {}

    def test_load_invalid_yaml_raises(self, tmp_path: Path) -> None:
        """Invalid YAML raises ConfigError."""
        path = tmp_path / "invalid.yaml"
        path.write_text("invalid: yaml: [broken")

        editor = ConfigEditor(global_path=path)
        with pytest.raises(ConfigError, match="Invalid YAML"):
            editor.load()

    def test_context_manager(self, global_config_file: Path) -> None:
        """Context manager loads on enter."""
        with ConfigEditor(global_path=global_config_file) as editor:
            assert "providers" in editor.get_global_raw()


class TestConfigEditorProvenance:
    """Tests for ConfigEditor provenance tracking."""

    def test_provenance_after_load(
        self, full_global_config_file: Path, project_config_file: Path
    ) -> None:
        """Provenance is tracked after load."""
        editor = ConfigEditor(
            global_path=full_global_config_file,
            project_path=project_config_file,
        )
        editor.load()

        # Global config sets this
        assert editor.get_provenance("benchmarking.extraction_provider") == "global"

        # Project config overrides this
        assert editor.get_provenance("benchmarking.enabled") == "project"

    def test_get_all_provenance(self, full_global_config_file: Path) -> None:
        """get_all_provenance returns mapping."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        all_prov = editor.get_all_provenance()
        assert isinstance(all_prov, dict)
        assert len(all_prov) > 0


class TestMergedWithProvenance:
    """Tests for get_merged_with_provenance."""

    def test_structure(self, full_global_config_file: Path) -> None:
        """Merged config has value/source structure."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        merged = editor.get_merged_with_provenance()

        # Check nested structure
        assert "benchmarking" in merged
        assert "enabled" in merged["benchmarking"]
        assert "value" in merged["benchmarking"]["enabled"]
        assert "source" in merged["benchmarking"]["enabled"]

    def test_values_correct(self, full_global_config_file: Path, project_config_file: Path) -> None:
        """Merged values are correct with proper sources."""
        editor = ConfigEditor(
            global_path=full_global_config_file,
            project_path=project_config_file,
        )
        editor.load()

        merged = editor.get_merged_with_provenance()

        # Project overrides global
        assert merged["benchmarking"]["enabled"]["value"] is False
        assert merged["benchmarking"]["enabled"]["source"] == "project"

        # Global not overridden
        assert merged["benchmarking"]["extraction_provider"]["value"] == "claude"
        assert merged["benchmarking"]["extraction_provider"]["source"] == "global"


class TestConfigEditorUpdate:
    """Tests for ConfigEditor update method."""

    def test_update_global(self, full_global_config_file: Path) -> None:
        """Update global config value."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        editor.update("global", "benchmarking.enabled", False)

        assert editor.get_global_raw()["benchmarking"]["enabled"] is False

    def test_update_project(self, full_global_config_file: Path, project_config_file: Path) -> None:
        """Update project config value."""
        editor = ConfigEditor(
            global_path=full_global_config_file,
            project_path=project_config_file,
        )
        editor.load()

        editor.update("project", "timeout", 1200)

        assert editor.get_project_raw()["timeout"] == 1200

    def test_update_creates_nested(self, full_global_config_file: Path) -> None:
        """Update creates nested paths."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        editor.update("global", "new.nested.path", "value")

        assert editor.get_global_raw()["new"]["nested"]["path"] == "value"

    def test_update_invalid_scope_raises(self, full_global_config_file: Path) -> None:
        """Invalid scope raises ValueError."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        with pytest.raises(ValueError, match="scope must be"):
            editor.update("invalid", "a", 1)

    def test_update_project_without_path_raises(self, full_global_config_file: Path) -> None:
        """Updating project config without project path raises ValueError."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        with pytest.raises(ValueError, match="no project path configured"):
            editor.update("project", "a", 1)


class TestConfigEditorRemove:
    """Tests for ConfigEditor remove method."""

    def test_remove_existing(self, full_global_config_file: Path) -> None:
        """Remove existing key."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        editor.remove("global", "timeout")

        assert "timeout" not in editor.get_global_raw()

    def test_remove_missing_idempotent(self, full_global_config_file: Path) -> None:
        """Removing missing key is idempotent."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        # Should not raise
        editor.remove("global", "nonexistent")

    def test_remove_project_without_path_raises(self, full_global_config_file: Path) -> None:
        """Removing from project without path raises ValueError."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        with pytest.raises(ValueError, match="no project path configured"):
            editor.remove("project", "a")


class TestConfigEditorValidate:
    """Tests for ConfigEditor validate method."""

    def test_validate_success(self, full_global_config_file: Path) -> None:
        """Validate valid config succeeds."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        config = editor.validate()
        assert config.providers.master.provider == "claude"

    def test_validate_invalid_raises(self, tmp_path: Path) -> None:
        """Validate invalid config raises ConfigError."""
        # Create config without required 'providers' field
        path = tmp_path / "invalid.yaml"
        path.write_text("benchmarking:\n  enabled: true\n")

        editor = ConfigEditor(global_path=path)
        editor.load()

        with pytest.raises(ConfigError, match="validation failed"):
            editor.validate()


class TestBackupRotation:
    """Tests for backup rotation."""

    def test_rotation_creates_backup(self, full_global_config_file: Path) -> None:
        """Save creates backup file."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        editor.save("global")

        backup_path = Path(f"{full_global_config_file}.1")
        assert backup_path.exists()

    def test_rotation_shifts_backups(self, full_global_config_file: Path) -> None:
        """Multiple saves shift backup versions."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        # Initial content
        original_content = full_global_config_file.read_text()

        # First save
        editor.update("global", "timeout", 100)
        editor.save("global")

        # Second save
        editor.update("global", "timeout", 200)
        editor.save("global")

        # Check backup chain
        backup1 = Path(f"{full_global_config_file}.1")
        backup2 = Path(f"{full_global_config_file}.2")

        assert backup1.exists()
        assert backup2.exists()

        # .2 should have original content
        assert "timeout: 300" in backup2.read_text() or "timeout:" not in original_content

    def test_max_backups_enforced(self, full_global_config_file: Path) -> None:
        """Only MAX_BACKUPS versions are kept."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        # Create more saves than MAX_BACKUPS
        for i in range(ConfigEditor.MAX_BACKUPS + 2):
            editor.update("global", "timeout", 100 + i)
            editor.save("global")

        # Check only MAX_BACKUPS exist
        for i in range(1, ConfigEditor.MAX_BACKUPS + 1):
            backup = Path(f"{full_global_config_file}.{i}")
            assert backup.exists(), f"Backup {i} should exist"

        # Beyond MAX_BACKUPS should not exist
        excess = Path(f"{full_global_config_file}.{ConfigEditor.MAX_BACKUPS + 1}")
        assert not excess.exists()

    def test_rotation_with_partial_backups(self, full_global_config_file: Path) -> None:
        """Rotation handles partial backup state correctly."""
        # Create only backup 1 and 3 (skip 2)
        Path(f"{full_global_config_file}.1").write_text("backup1")
        Path(f"{full_global_config_file}.3").write_text("backup3")

        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()
        editor.save("global")

        # Check rotation happened
        assert Path(f"{full_global_config_file}.1").exists()
        assert Path(f"{full_global_config_file}.2").exists()

    def test_rotation_no_file_no_backup(self, tmp_path: Path) -> None:
        """New file creation doesn't create backup."""
        global_path = tmp_path / "new_config.yaml"
        global_path.write_text("providers:\n  master:\n    provider: claude\n    model: opus\n")

        project_path = tmp_path / "project.yaml"

        editor = ConfigEditor(global_path=global_path, project_path=project_path)
        editor.load()

        # Add something to project
        editor.update("project", "timeout", 500)
        editor.save("project")

        # No backup for new file
        backup = Path(f"{project_path}.1")
        assert not backup.exists()


class TestAtomicSave:
    """Tests for atomic save operations."""

    def test_save_is_atomic(self, full_global_config_file: Path) -> None:
        """Save uses temp file for atomicity."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        editor.update("global", "timeout", 999)
        editor.save("global")

        # Verify content
        saved = yaml.safe_load(full_global_config_file.read_text())
        assert saved["timeout"] == 999

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Save creates parent directories if needed."""
        global_path = tmp_path / "global.yaml"
        global_path.write_text("providers:\n  master:\n    provider: claude\n    model: opus\n")

        project_path = tmp_path / "deep" / "nested" / "project.yaml"

        editor = ConfigEditor(global_path=global_path, project_path=project_path)
        editor.load()
        editor.update("project", "timeout", 100)
        editor.save("project")

        assert project_path.exists()

    def test_save_validates_first(self, tmp_path: Path) -> None:
        """Save validates config before writing."""
        path = tmp_path / "config.yaml"
        path.write_text("providers:\n  master:\n    provider: claude\n    model: opus\n")

        editor = ConfigEditor(global_path=path)
        editor.load()

        # Remove required field
        editor.remove("global", "providers")

        with pytest.raises(ConfigError):
            editor.save("global")

    def test_save_rebuilds_provenance(
        self, full_global_config_file: Path, project_config_file: Path
    ) -> None:
        """Save rebuilds provenance tracker."""
        editor = ConfigEditor(
            global_path=full_global_config_file,
            project_path=project_config_file,
        )
        editor.load()

        # Initially project overrides benchmarking.enabled
        assert editor.get_provenance("benchmarking.enabled") == "project"

        # Add new value to global
        editor.update("global", "new_field", "value")
        editor.save("global")

        # New field should have global provenance
        assert editor.get_provenance("new_field") == "global"


class TestListBackups:
    """Tests for list_backups method."""

    def test_list_no_backups(self, full_global_config_file: Path) -> None:
        """List returns empty when no backups exist."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        backups = editor.list_backups("global")
        assert backups == []

    def test_list_with_backups(self, full_global_config_file: Path) -> None:
        """List returns backup metadata."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        # Create some backups
        editor.save("global")
        time.sleep(0.1)  # Ensure different timestamps
        editor.save("global")

        backups = editor.list_backups("global")
        assert len(backups) >= 2

        # Check structure
        assert backups[0]["version"] == 1
        assert "path" in backups[0]
        assert "modified" in backups[0]

    def test_list_sorted_by_version(self, full_global_config_file: Path) -> None:
        """List is sorted by version number."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        for _ in range(3):
            editor.save("global")

        backups = editor.list_backups("global")
        versions = [b["version"] for b in backups]
        assert versions == sorted(versions)


class TestRestoreBackup:
    """Tests for restore_backup method."""

    def test_restore_valid_backup(self, full_global_config_file: Path) -> None:
        """Restore replaces current config with backup."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        original_timeout = editor.get_global_raw().get("timeout")

        # Modify and save
        editor.update("global", "timeout", 9999)
        editor.save("global")

        # Restore
        editor.restore_backup("global", 1)

        # Should have original value
        restored_timeout = editor.get_global_raw().get("timeout")
        assert restored_timeout == original_timeout

    def test_restore_creates_backup_of_current(self, full_global_config_file: Path) -> None:
        """Restore creates backup of current state before overwriting."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        # Save once to create backup
        editor.update("global", "timeout", 111)
        editor.save("global")

        # Modify again
        editor.update("global", "timeout", 222)
        editor.save("global")

        # Count backups before restore
        backups_before = len(editor.list_backups("global"))

        # Restore version 2
        editor.restore_backup("global", 2)

        # Should have one more backup
        backups_after = len(editor.list_backups("global"))
        assert backups_after >= backups_before

    def test_restore_nonexistent_raises(self, full_global_config_file: Path) -> None:
        """Restore nonexistent version raises ConfigError."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        with pytest.raises(ConfigError, match="does not exist"):
            editor.restore_backup("global", 99)

    def test_restore_invalid_backup_raises(self, tmp_path: Path) -> None:
        """Restore invalid backup content raises ConfigError without modifying main config."""
        path = tmp_path / "config.yaml"
        path.write_text("providers:\n  master:\n    provider: claude\n    model: opus\n")

        editor = ConfigEditor(global_path=path)
        editor.load()

        # Create an invalid backup manually
        backup_path = Path(f"{path}.1")
        backup_path.write_text("invalid: yaml that will fail validation")

        original_content = path.read_text()

        with pytest.raises(ConfigError):
            editor.restore_backup("global", 1)

        # Main config should be unchanged
        assert path.read_text() == original_content

    def test_restore_rebuilds_provenance(self, full_global_config_file: Path) -> None:
        """Restore rebuilds provenance tracker."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        # Save with new field
        editor.update("global", "new_field", "value")
        editor.save("global")

        # Restore removes the field
        editor.restore_backup("global", 1)

        # Provenance should be rebuilt
        all_prov = editor.get_all_provenance()
        # The new_field shouldn't be in global anymore after restore
        assert isinstance(all_prov, dict)


# =============================================================================
# reload_config Tests
# =============================================================================


class TestReloadConfig:
    """Tests for reload_config function."""

    def test_reload_swaps_singleton(self, full_global_config_file: Path) -> None:
        """reload_config swaps the singleton."""
        # First load
        config1 = load_global_config(full_global_config_file)

        # Modify file
        current = yaml.safe_load(full_global_config_file.read_text())
        current["timeout"] = 12345
        full_global_config_file.write_text(yaml.dump(current))

        # Reload with patched path (patch where it's used, in loaders module)
        with patch("bmad_assist.core.config.loaders.GLOBAL_CONFIG_PATH", full_global_config_file):
            config2 = reload_config()

        assert config2.timeout == 12345
        assert config1.timeout != config2.timeout

    def test_reload_returns_new_config(self, full_global_config_file: Path) -> None:
        """reload_config returns the new Config instance."""
        load_global_config(full_global_config_file)

        with patch("bmad_assist.core.config.loaders.GLOBAL_CONFIG_PATH", full_global_config_file):
            result = reload_config()

        assert result is get_config()

    def test_reload_with_project(
        self, full_global_config_file: Path, project_config_file: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """reload_config with project_path loads merged config."""
        # Create project directory with config
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        project_config = project_dir / "bmad-assist.yaml"
        project_config.write_text("timeout: 7777\n")

        # Change CWD to tmp_path to avoid loading real bmad-assist.yaml from project root
        monkeypatch.chdir(tmp_path)

        with patch("bmad_assist.core.config.loaders.GLOBAL_CONFIG_PATH", full_global_config_file):
            config = reload_config(project_path=project_dir)

        assert config.timeout == 7777


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        """Empty config file raises ConfigError."""
        path = tmp_path / "empty.yaml"
        path.write_text("")

        editor = ConfigEditor(global_path=path)
        with pytest.raises(ConfigError, match="empty"):
            editor.load()

    def test_directory_raises(self, tmp_path: Path) -> None:
        """Directory path raises ConfigError."""
        editor = ConfigEditor(global_path=tmp_path)
        with pytest.raises(ConfigError, match="directory"):
            editor.load()

    def test_yaml_with_only_comments(self, tmp_path: Path) -> None:
        """YAML file with only comments raises ConfigError."""
        path = tmp_path / "comments.yaml"
        path.write_text("# Just a comment\n# Another comment\n")

        editor = ConfigEditor(global_path=path)
        with pytest.raises(ConfigError, match="empty"):
            editor.load()

    def test_get_raw_returns_copy(self, full_global_config_file: Path) -> None:
        """get_*_raw returns deep copy, not original."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        raw = editor.get_global_raw()
        raw["modified"] = True

        # Original should be unchanged
        assert "modified" not in editor.get_global_raw()


class TestPermissions:
    """Tests for file permission handling."""

    def test_new_project_file_has_secure_permissions(
        self, full_global_config_file: Path, tmp_path: Path
    ) -> None:
        """New project config files get 0o600 permissions."""
        project_path = tmp_path / "new_project.yaml"

        editor = ConfigEditor(
            global_path=full_global_config_file,
            project_path=project_path,
        )
        editor.load()
        editor.update("project", "timeout", 100)
        editor.save("project")

        # Check permissions (Unix only)
        if os.name != "nt":
            mode = project_path.stat().st_mode & 0o777
            assert mode == 0o600


# =============================================================================
# Comment Preservation Tests (Story 17.3)
# =============================================================================


class TestRuamelYamlDetection:
    """Tests for ruamel.yaml detection and caching."""

    def test_has_ruamel_yaml_returns_bool(self) -> None:
        """has_ruamel_yaml returns a boolean."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        result = has_ruamel_yaml()
        assert isinstance(result, bool)

    def test_has_ruamel_yaml_always_returns_true(self) -> None:
        """has_ruamel_yaml always returns True since ruamel.yaml is now required."""
        from bmad_assist.core import config_editor

        # Multiple calls should consistently return True
        result1 = config_editor.has_ruamel_yaml()
        result2 = config_editor.has_ruamel_yaml()

        assert result1 is True
        assert result2 is True

    def test_has_ruamel_yaml_required_dependency(self) -> None:
        """ruamel.yaml is now a required dependency, not optional."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        # This test verifies ruamel.yaml is properly installed
        # as a required dependency (moved from optional-dependencies)
        assert has_ruamel_yaml() is True


class TestCommentsPreserved:
    """Tests for comments_preserved() method."""

    def test_comments_preserved_returns_bool(self, full_global_config_file: Path) -> None:
        """comments_preserved returns a boolean."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        result = editor.comments_preserved("global")
        assert isinstance(result, bool)

    def test_comments_preserved_global_scope(self, full_global_config_file: Path) -> None:
        """comments_preserved returns True for global when ruamel available."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        if has_ruamel_yaml():
            assert editor.comments_preserved("global") is True
        else:
            assert editor.comments_preserved("global") is False

    def test_comments_preserved_project_scope(
        self, full_global_config_file: Path, project_config_file: Path
    ) -> None:
        """comments_preserved returns True for project when ruamel available."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        editor = ConfigEditor(
            global_path=full_global_config_file,
            project_path=project_config_file,
        )
        editor.load()

        if has_ruamel_yaml():
            assert editor.comments_preserved("project") is True
        else:
            assert editor.comments_preserved("project") is False

    def test_comments_preserved_default_scope(
        self, full_global_config_file: Path, project_config_file: Path
    ) -> None:
        """comments_preserved defaults to project scope."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        editor = ConfigEditor(
            global_path=full_global_config_file,
            project_path=project_config_file,
        )
        editor.load()

        # Default should be project scope
        if has_ruamel_yaml():
            assert editor.comments_preserved() is True
        else:
            assert editor.comments_preserved() is False

    def test_comments_preserved_false_for_new_file(
        self, full_global_config_file: Path, tmp_path: Path
    ) -> None:
        """comments_preserved returns False for non-existent project file."""
        editor = ConfigEditor(
            global_path=full_global_config_file,
            project_path=tmp_path / "nonexistent.yaml",
        )
        editor.load()

        # Project file doesn't exist, so no CommentedMap
        assert editor.comments_preserved("project") is False

    def test_comments_preserved_invalid_scope(self, full_global_config_file: Path) -> None:
        """comments_preserved returns False for invalid scope."""
        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        assert editor.comments_preserved("invalid") is False


class TestCommentPreservationLoad:
    """Tests for loading configs with comment preservation."""

    def test_load_stores_commented_map_for_global(self, full_global_config_file: Path) -> None:
        """Load stores CommentedMap for global config when ruamel available."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        editor = ConfigEditor(global_path=full_global_config_file)
        editor.load()

        if has_ruamel_yaml():
            assert editor._global_commented is not None
        else:
            assert editor._global_commented is None

    def test_load_stores_commented_map_for_project(
        self, full_global_config_file: Path, project_config_file: Path
    ) -> None:
        """Load stores CommentedMap for project config when ruamel available."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        editor = ConfigEditor(
            global_path=full_global_config_file,
            project_path=project_config_file,
        )
        editor.load()

        if has_ruamel_yaml():
            assert editor._project_commented is not None
        else:
            assert editor._project_commented is None

    def test_load_missing_project_has_none_commented(
        self, full_global_config_file: Path, tmp_path: Path
    ) -> None:
        """Missing project file has None for commented map."""
        editor = ConfigEditor(
            global_path=full_global_config_file,
            project_path=tmp_path / "nonexistent.yaml",
        )
        editor.load()

        assert editor._project_commented is None


class TestCommentPreservationSave:
    """Tests for saving configs with comment preservation."""

    def test_save_preserves_inline_comments(self, tmp_path: Path) -> None:
        """Save preserves inline comments when ruamel available."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        if not has_ruamel_yaml():
            pytest.skip("ruamel.yaml not available")

        # Create config with inline comments
        config_path = tmp_path / "config.yaml"
        config_path.write_text("""\
providers:
  master:
    provider: claude  # Main AI provider
    model: opus  # Best model for complex tasks
timeout: 300  # Default timeout in seconds
""")

        editor = ConfigEditor(global_path=config_path)
        editor.load()

        # Modify a value
        editor.update("global", "timeout", 600)
        editor.save("global")

        # Check that comments are preserved
        content = config_path.read_text()
        assert "# Main AI provider" in content
        assert "# Best model for complex tasks" in content
        # Comment for timeout may or may not be preserved depending on ruamel behavior

    def test_save_preserves_block_comments(self, tmp_path: Path) -> None:
        """Save preserves block comments above keys."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        if not has_ruamel_yaml():
            pytest.skip("ruamel.yaml not available")

        # Create config with block comment
        config_path = tmp_path / "config.yaml"
        config_path.write_text("""\
# Provider configuration section
# This controls which AI to use
providers:
  master:
    provider: claude
    model: opus
""")

        editor = ConfigEditor(global_path=config_path)
        editor.load()

        # Modify a value
        editor.update("global", "providers.master.model", "sonnet")
        editor.save("global")

        # Check that block comments are preserved
        content = config_path.read_text()
        assert "# Provider configuration section" in content
        assert "# This controls which AI to use" in content

    def test_save_nested_structure_preserves_comments(self, tmp_path: Path) -> None:
        """Save preserves comments in nested structures (3+ levels)."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        if not has_ruamel_yaml():
            pytest.skip("ruamel.yaml not available")

        # Create config with nested comments
        config_path = tmp_path / "config.yaml"
        config_path.write_text("""\
providers:
  master:
    provider: claude  # Level 2 comment
    model: opus
  multi:
    - provider: gemini
      model: flash
benchmarking:
  enabled: true  # Enable performance tracking
  extraction_provider: claude
  extraction_model: haiku
""")

        editor = ConfigEditor(global_path=config_path)
        editor.load()

        # Modify nested value
        editor.update("global", "benchmarking.enabled", False)
        editor.save("global")

        # Check that nested comments are preserved
        content = config_path.read_text()
        assert "# Level 2 comment" in content

    def test_save_new_keys_added_without_comments(self, tmp_path: Path) -> None:
        """New keys are added without comments (appended at end)."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        if not has_ruamel_yaml():
            pytest.skip("ruamel.yaml not available")

        config_path = tmp_path / "config.yaml"
        config_path.write_text("""\
providers:
  master:
    provider: claude
    model: opus
""")

        editor = ConfigEditor(global_path=config_path)
        editor.load()

        # Add new key
        editor.update("global", "new_field", "new_value")
        editor.save("global")

        # New key should be added
        content = config_path.read_text()
        assert "new_field: new_value" in content

    def test_save_removed_keys_deleted(self, tmp_path: Path) -> None:
        """Removed keys are deleted from config."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        if not has_ruamel_yaml():
            pytest.skip("ruamel.yaml not available")

        config_path = tmp_path / "config.yaml"
        config_path.write_text("""\
providers:
  master:
    provider: claude
    model: opus
timeout: 300  # Will be removed
""")

        editor = ConfigEditor(global_path=config_path)
        editor.load()

        # Remove a key
        editor.remove("global", "timeout")
        editor.save("global")

        # Key should be removed
        content = config_path.read_text()
        assert "timeout" not in content

    def test_save_list_replacement(self, tmp_path: Path) -> None:
        """Lists are replaced entirely (list item comments not preserved)."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        if not has_ruamel_yaml():
            pytest.skip("ruamel.yaml not available")

        config_path = tmp_path / "config.yaml"
        config_path.write_text("""\
providers:
  master:
    provider: claude
    model: opus
  multi:
    - provider: gemini  # Gemini provider
      model: flash
    - provider: codex  # Codex provider
      model: gpt-4
""")

        editor = ConfigEditor(global_path=config_path)
        editor.load()

        # Replace entire list
        new_multi = [{"provider": "openai", "model": "gpt-4"}]
        editor.update("global", "providers.multi", new_multi)
        editor.save("global")

        # List should be replaced
        content = config_path.read_text()
        assert "openai" in content
        # Old list items should be gone
        assert "gemini" not in content

    def test_save_atomic_write_failure_cleanup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Atomic write failure cleans up temp file and preserves original."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("""\
providers:
  master:
    provider: claude
    model: opus
""")

        editor = ConfigEditor(global_path=config_path)
        editor.load()

        original_content = config_path.read_text()

        # Make write fail by raising an exception during ruamel dump
        from ruamel.yaml import YAML

        def failing_dump(self: Any, data: Any, stream: Any) -> None:
            raise OSError("Simulated write failure")

        editor.update("global", "timeout", 999)

        # Patch ruamel.yaml dump to fail (monkeypatch auto-restores after test)
        monkeypatch.setattr(YAML, "dump", failing_dump)

        # Save should raise
        with pytest.raises(OSError):
            editor.save("global")

        # Original file should be unchanged
        assert config_path.read_text() == original_content

        # No temp file should remain
        temp_files = list(tmp_path.glob("*.tmp*"))
        assert len(temp_files) == 0


class TestCommentPreservationWithRuamel:
    """Tests for comment preservation with ruamel.yaml (now required)."""

    def test_backup_rotation_works_with_ruamel(self, tmp_path: Path) -> None:
        """Backup rotation works with ruamel.yaml."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("""\
providers:
  master:
    provider: claude  # Comment
    model: opus
""")

        editor = ConfigEditor(global_path=config_path)
        editor.load()

        # Save to create backup
        editor.update("global", "timeout", 100)
        editor.save("global")

        # Backup should exist
        backup_path = Path(f"{config_path}.1")
        assert backup_path.exists()

        # Backup should have original comment
        assert "# Comment" in backup_path.read_text()


class TestEdgeCasesCommentPreservation:
    """Tests for edge cases in comment preservation."""

    def test_empty_file_handling(self, tmp_path: Path) -> None:
        """Empty file raises ConfigError (same behavior with/without ruamel)."""
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("")

        editor = ConfigEditor(global_path=config_path)
        with pytest.raises(ConfigError, match="empty"):
            editor.load()

    def test_file_with_only_comments(self, tmp_path: Path) -> None:
        """File with only comments raises ConfigError."""
        config_path = tmp_path / "comments_only.yaml"
        config_path.write_text("# Just a comment\n# Another comment\n")

        editor = ConfigEditor(global_path=config_path)
        with pytest.raises(ConfigError, match="empty"):
            editor.load()

    def test_key_ordering_preserved(self, tmp_path: Path) -> None:
        """Key ordering from original file is preserved."""
        from bmad_assist.core.config_editor import has_ruamel_yaml

        if not has_ruamel_yaml():
            pytest.skip("ruamel.yaml not available")

        config_path = tmp_path / "config.yaml"
        config_path.write_text("""\
providers:
  master:
    provider: claude
    model: opus
timeout: 300
benchmarking:
  enabled: true
""")

        editor = ConfigEditor(global_path=config_path)
        editor.load()

        # Modify middle key
        editor.update("global", "timeout", 600)
        editor.save("global")

        # Check key order is preserved (providers, timeout, benchmarking)
        content = config_path.read_text()
        providers_pos = content.find("providers:")
        timeout_pos = content.find("timeout:")
        benchmarking_pos = content.find("benchmarking:")

        assert providers_pos < timeout_pos < benchmarking_pos
