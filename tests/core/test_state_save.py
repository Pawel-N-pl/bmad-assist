"""Tests for atomic state persistence (Story 3.2).

Story 3.2 Tests cover:
- AC1: Atomic write via temporary file + rename
- AC2: YAML format is human-readable
- AC3: Crash during write preserves previous state
- AC4: Temporary file cleanup on startup
- AC5: Path accepts str or Path with tilde expansion
- AC6: Directory is created if missing
- AC7: StateError raised on write failure
- AC8: Function signature and types
- AC9: Empty State serializes correctly
"""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from bmad_assist.core.exceptions import StateError
from bmad_assist.core.state import State, _cleanup_temp_files, save_state

# =============================================================================
# AC1: Atomic write via temporary file + rename
# =============================================================================


class TestSaveStateAtomicWrite:
    """Test atomic write behavior (AC1, AC3)."""

    def test_save_state_creates_file(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """save_state creates file at target path."""
        save_state(state_for_persistence, temp_state_file)
        assert temp_state_file.exists()

    def test_save_state_no_temp_file_after_success(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """Temp file is removed after successful save."""
        save_state(state_for_persistence, temp_state_file)
        temp_path = temp_state_file.with_suffix(".yaml.tmp")
        assert not temp_path.exists()

    def test_save_state_uses_os_replace(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """save_state uses os.replace for cross-platform atomic operation."""
        import os as real_os

        with patch("bmad_assist.core.state.os.replace", wraps=real_os.replace) as mock_replace:
            save_state(state_for_persistence, temp_state_file)
            mock_replace.assert_called_once()
            # Verify temp file pattern
            call_args = mock_replace.call_args[0]
            assert str(call_args[0]).endswith(".yaml.tmp")
            assert str(call_args[1]).endswith(".yaml")

    def test_save_state_crash_simulation_preserves_original(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """AC3: Crash during write preserves previous state."""
        # First, create a valid state file
        original_state = State(current_epic=1, current_story="1.1")
        save_state(original_state, temp_state_file)
        original_content = temp_state_file.read_text()

        # Now simulate crash during second write (after temp created, before replace)
        with patch("bmad_assist.core.state.os.replace") as mock_replace:
            mock_replace.side_effect = OSError("Simulated crash")
            with pytest.raises(StateError):
                save_state(state_for_persistence, temp_state_file)

        # Original file should be intact
        assert temp_state_file.read_text() == original_content
        # Verify original state can be loaded
        loaded = yaml.safe_load(temp_state_file.read_text())
        assert loaded["current_epic"] == 1


# =============================================================================
# AC2: YAML format is human-readable
# =============================================================================


class TestSaveStateYamlFormat:
    """Test YAML output format (AC2)."""

    def test_yaml_uses_block_style(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """YAML output uses block style (not flow style)."""
        save_state(state_for_persistence, temp_state_file)
        content = temp_state_file.read_text()
        # Block style has key on separate line, not {...}
        assert "current_epic: 3" in content
        assert "{" not in content  # Not flow style

    def test_yaml_datetime_is_iso_string(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """Datetime values are ISO format strings."""
        save_state(state_for_persistence, temp_state_file)
        content = temp_state_file.read_text()
        assert "'2025-12-10T08:00:00'" in content or "2025-12-10T08:00:00" in content

    def test_yaml_phase_is_string_value(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """Phase enum is serialized as string value."""
        save_state(state_for_persistence, temp_state_file)
        content = temp_state_file.read_text()
        assert "current_phase: dev_story" in content

    def test_yaml_no_excessive_line_length(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """No line exceeds 200 characters."""
        save_state(state_for_persistence, temp_state_file)
        content = temp_state_file.read_text()
        for line in content.splitlines():
            assert len(line) <= 200

    def test_yaml_keys_not_sorted(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """Keys preserve logical field order (not alphabetically sorted)."""
        save_state(state_for_persistence, temp_state_file)
        content = temp_state_file.read_text()
        lines = content.splitlines()
        # current_epic should come before current_story
        epic_idx = next(i for i, l in enumerate(lines) if "current_epic" in l)
        story_idx = next(i for i, l in enumerate(lines) if "current_story" in l)
        assert epic_idx < story_idx


# =============================================================================
# AC4: Temporary file cleanup on startup
# =============================================================================


class TestCleanupTempFiles:
    """Test orphaned temp file cleanup (AC4)."""

    def test_cleanup_removes_orphaned_temp_file(self, temp_state_file: Path) -> None:
        """_cleanup_temp_files removes orphaned temp file."""
        temp_path = temp_state_file.with_suffix(".yaml.tmp")
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text("orphaned content")

        _cleanup_temp_files(temp_state_file)

        assert not temp_path.exists()

    def test_cleanup_logs_warning(
        self, temp_state_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_cleanup_temp_files logs warning about cleanup."""
        temp_path = temp_state_file.with_suffix(".yaml.tmp")
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text("orphaned content")

        with caplog.at_level("WARNING"):
            _cleanup_temp_files(temp_state_file)

        assert "orphaned temp file" in caplog.text.lower()

    def test_cleanup_no_error_if_no_temp_file(self, temp_state_file: Path) -> None:
        """_cleanup_temp_files succeeds when no temp file exists."""
        # Should not raise
        _cleanup_temp_files(temp_state_file)

    def test_cleanup_with_string_path(self, tmp_path: Path) -> None:
        """_cleanup_temp_files accepts string path."""
        state_file = tmp_path / "state.yaml"
        temp_path = state_file.with_suffix(".yaml.tmp")
        temp_path.write_text("orphaned")

        _cleanup_temp_files(str(state_file))  # String path

        assert not temp_path.exists()

    def test_cleanup_raises_state_error_on_permission_denied(self, tmp_path: Path) -> None:
        """_cleanup_temp_files raises StateError when unlink fails."""
        state_file = tmp_path / "state.yaml"
        temp_path = state_file.with_suffix(".yaml.tmp")
        temp_path.write_text("orphaned")

        with patch.object(Path, "unlink") as mock_unlink:
            mock_unlink.side_effect = PermissionError("Cannot delete")
            with pytest.raises(StateError) as exc_info:
                _cleanup_temp_files(state_file)

            assert "cannot remove" in str(exc_info.value).lower()
            assert str(temp_path) in str(exc_info.value)
            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, PermissionError)


# =============================================================================
# AC5: Path accepts str or Path with tilde expansion
# =============================================================================


class TestSaveStatePathHandling:
    """Test path handling (AC5)."""

    def test_save_state_with_string_path(
        self, state_for_persistence: State, tmp_path: Path
    ) -> None:
        """save_state works with string path."""
        path_str = str(tmp_path / "state.yaml")
        save_state(state_for_persistence, path_str)
        assert Path(path_str).exists()

    def test_save_state_with_path_object(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """save_state works with Path object."""
        save_state(state_for_persistence, temp_state_file)
        assert temp_state_file.exists()

    def test_save_state_expands_tilde(
        self, state_for_persistence: State, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """save_state expands tilde to user home directory."""
        # Mock expanduser to use tmp_path as home
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        def mock_expanduser(path: Path) -> Path:
            path_str = str(path)
            if path_str.startswith("~"):
                return Path(str(fake_home) + path_str[1:])
            return path

        monkeypatch.setattr(Path, "expanduser", mock_expanduser)

        save_state(state_for_persistence, "~/.bmad-assist/state.yaml")

        expected = fake_home / ".bmad-assist" / "state.yaml"
        assert expected.exists()

    def test_string_and_path_produce_identical_results(
        self, state_for_persistence: State, tmp_path: Path
    ) -> None:
        """String and Path paths produce identical file content."""
        path_str = str(tmp_path / "state_str.yaml")
        path_obj = tmp_path / "state_path.yaml"

        save_state(state_for_persistence, path_str)
        save_state(state_for_persistence, path_obj)

        content_str = Path(path_str).read_text()
        content_path = path_obj.read_text()
        assert content_str == content_path


# =============================================================================
# AC6: Directory is created if missing
# =============================================================================


class TestSaveStateDirCreation:
    """Test directory creation (AC6)."""

    def test_save_state_creates_missing_directory(
        self, state_for_persistence: State, tmp_path: Path
    ) -> None:
        """save_state creates parent directory if missing."""
        nested_path = tmp_path / "new" / "nested" / "dir" / "state.yaml"
        assert not nested_path.parent.exists()

        save_state(state_for_persistence, nested_path)

        assert nested_path.exists()
        assert nested_path.parent.exists()

    def test_save_state_succeeds_with_existing_directory(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """save_state succeeds when directory already exists."""
        temp_state_file.parent.mkdir(parents=True, exist_ok=True)
        save_state(state_for_persistence, temp_state_file)
        assert temp_state_file.exists()


# =============================================================================
# AC7: StateError raised on write failure
# =============================================================================


class TestSaveStateErrors:
    """Test error handling (AC7)."""

    def test_save_state_raises_state_error_on_oserror(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """StateError is raised on OSError."""
        with patch("bmad_assist.core.state.os.replace") as mock_replace:
            mock_replace.side_effect = OSError("Disk full")

            with pytest.raises(StateError) as exc_info:
                save_state(state_for_persistence, temp_state_file)

            assert "Failed to save state" in str(exc_info.value)
            assert str(temp_state_file) in str(exc_info.value)

    def test_save_state_error_cleans_up_temp_file(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """Temp file is cleaned up on error."""
        temp_path = temp_state_file.with_suffix(".yaml.tmp")

        with patch("bmad_assist.core.state.os.replace") as mock_replace:
            mock_replace.side_effect = OSError("Disk full")

            with pytest.raises(StateError):
                save_state(state_for_persistence, temp_state_file)

            # Temp file should be cleaned up
            assert not temp_path.exists()

    def test_save_state_error_preserves_exception_chain(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """StateError preserves original OSError in chain."""
        with patch("bmad_assist.core.state.os.replace") as mock_replace:
            mock_replace.side_effect = OSError("Original error")

            with pytest.raises(StateError) as exc_info:
                save_state(state_for_persistence, temp_state_file)

            # __cause__ should be the original OSError
            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, OSError)


# =============================================================================
# AC8: Function signature and types
# =============================================================================


class TestSaveStateFunctionSignature:
    """Test function signature and types (AC8)."""

    def test_save_state_returns_none(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """save_state returns None."""
        result = save_state(state_for_persistence, temp_state_file)
        assert result is None

    def test_save_state_has_docstring(self) -> None:
        """save_state has Google-style docstring."""
        assert save_state.__doc__ is not None
        assert "Args:" in save_state.__doc__
        assert "Raises:" in save_state.__doc__

    def test_save_state_docstring_has_example(self) -> None:
        """save_state docstring includes example."""
        assert save_state.__doc__ is not None
        assert "Example:" in save_state.__doc__

    def test_cleanup_temp_files_has_docstring(self) -> None:
        """_cleanup_temp_files has docstring."""
        assert _cleanup_temp_files.__doc__ is not None
        assert "Args:" in _cleanup_temp_files.__doc__


# =============================================================================
# AC9: Empty State serializes correctly
# =============================================================================


class TestSaveStateEmptyState:
    """Test empty state serialization (AC9)."""

    def test_empty_state_serializes_correctly(self, temp_state_file: Path) -> None:
        """AC9: Empty state serializes correctly."""
        empty_state = State()

        save_state(empty_state, temp_state_file)

        assert temp_state_file.exists()
        content = temp_state_file.read_text()
        # All fields present with default values
        assert "current_epic:" in content
        assert "current_story:" in content
        assert "current_phase:" in content
        assert "completed_stories:" in content

    def test_empty_state_round_trip(self, temp_state_file: Path) -> None:
        """Empty state survives save and reload."""
        empty_state = State()
        save_state(empty_state, temp_state_file)

        # Load and validate
        loaded_data = yaml.safe_load(temp_state_file.read_text())
        restored = State.model_validate(loaded_data)

        assert restored.current_epic is None
        assert restored.current_story is None
        assert restored.current_phase is None
        assert restored.completed_stories == []


# =============================================================================
# Full round-trip test with save_state
# =============================================================================


class TestSaveStateRoundTrip:
    """Test complete save/load round-trip with save_state function."""

    def test_full_state_round_trip(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """Full state survives save_state -> yaml.safe_load -> State round-trip."""
        save_state(state_for_persistence, temp_state_file)

        loaded_data = yaml.safe_load(temp_state_file.read_text())
        restored = State.model_validate(loaded_data)

        assert restored.current_epic == state_for_persistence.current_epic
        assert restored.current_story == state_for_persistence.current_story
        assert restored.current_phase == state_for_persistence.current_phase
        assert restored.completed_stories == state_for_persistence.completed_stories
        assert restored.started_at == state_for_persistence.started_at
        assert restored.updated_at == state_for_persistence.updated_at

    def test_overwrite_existing_file(
        self, state_for_persistence: State, temp_state_file: Path
    ) -> None:
        """save_state overwrites existing file atomically."""
        # Save initial state
        initial_state = State(current_epic=1)
        save_state(initial_state, temp_state_file)

        # Save new state
        save_state(state_for_persistence, temp_state_file)

        # Should have new state
        loaded = yaml.safe_load(temp_state_file.read_text())
        assert loaded["current_epic"] == 3

    def test_unicode_round_trip(self, temp_state_file: Path) -> None:
        """State with Unicode characters survives round-trip (cross-platform)."""
        state = State(
            current_epic=1,
            current_story="Paweł's Story ąęłóżźć",
            completed_stories=["1.1-тест", "1.2-日本語"],
        )
        save_state(state, temp_state_file)

        # Verify file is UTF-8 encoded with actual Unicode (not escaped)
        content = temp_state_file.read_text(encoding="utf-8")
        assert "Paweł" in content  # Not escaped as \\u0142
        assert "ąęłóżźć" in content

        # Round-trip
        loaded = yaml.safe_load(content)
        restored = State.model_validate(loaded)
        assert restored.current_story == "Paweł's Story ąęłóżźć"
        assert "1.1-тест" in restored.completed_stories
        assert "1.2-日本語" in restored.completed_stories


# =============================================================================
# Module exports test for save_state
# =============================================================================


class TestSaveStateModuleExports:
    """Test module exports for save_state (AC8)."""

    def test_save_state_in_module_all(self) -> None:
        """save_state is in __all__."""
        from bmad_assist.core import state as state_module

        assert "save_state" in state_module.__all__

    def test_save_state_importable(self) -> None:
        """save_state is importable from module."""
        from bmad_assist.core.state import save_state as imported_save_state

        assert imported_save_state is save_state
