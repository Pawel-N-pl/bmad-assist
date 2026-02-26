"""Tests for state restoration (Story 3.3).

Story 3.3 Tests cover:
- AC1: State file loaded and deserialized
- AC2: StateError raised for corrupted file
- AC3: StateError raised for schema mismatch
- AC4: Fresh state returned when file missing
- AC5: Orphaned temp files cleaned before load
- AC6: Path accepts str or Path with tilde expansion
- AC7: Function signature and exports
- AC8: Empty file returns fresh state
- AC9: Partial state file loads with defaults
- AC10: StateError raised for IO/permission errors
"""

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from bmad_assist.core.exceptions import StateError
from bmad_assist.core.state import Phase, State, load_state, save_state

# =============================================================================
# AC1: State file loaded and deserialized
# =============================================================================


class TestLoadStateSuccess:
    """Test successful state loading (AC1)."""

    def test_load_state_returns_state_object(self, saved_state_file: tuple[Path, State]) -> None:
        """load_state returns State instance."""
        path, _ = saved_state_file
        result = load_state(path)
        assert isinstance(result, State)

    def test_load_state_restores_all_fields(self, saved_state_file: tuple[Path, State]) -> None:
        """load_state restores all field values correctly."""
        path, original = saved_state_file
        restored = load_state(path)
        assert restored.current_epic == original.current_epic
        assert restored.current_story == original.current_story
        assert restored.current_phase == original.current_phase
        assert restored.completed_stories == original.completed_stories
        assert restored.started_at == original.started_at
        assert restored.updated_at == original.updated_at

    def test_load_state_restores_phase_enum(self, saved_state_file: tuple[Path, State]) -> None:
        """AC1: Phase enum is restored from string value."""
        path, _ = saved_state_file
        restored = load_state(path)
        assert restored.current_phase == Phase.DEV_STORY
        assert isinstance(restored.current_phase, Phase)

    def test_load_state_parses_datetime_from_iso(
        self, saved_state_file: tuple[Path, State]
    ) -> None:
        """AC1: Datetime is parsed from ISO string."""
        path, _ = saved_state_file
        restored = load_state(path)
        assert restored.started_at == datetime(2025, 12, 10, 8, 0, 0)
        assert isinstance(restored.started_at, datetime)


# =============================================================================
# AC2: StateError raised for corrupted file
# =============================================================================


class TestLoadStateCorruptedYaml:
    """Test StateError on corrupted YAML (AC2)."""

    def test_load_state_raises_state_error_for_invalid_yaml(
        self, corrupted_yaml_file: Path
    ) -> None:
        """AC2: StateError raised for invalid YAML syntax."""
        with pytest.raises(StateError) as exc_info:
            load_state(corrupted_yaml_file)
        assert "corrupted" in str(exc_info.value).lower()
        assert str(corrupted_yaml_file) in str(exc_info.value)

    def test_load_state_preserves_yaml_error_cause(self, corrupted_yaml_file: Path) -> None:
        """AC2: Original yaml.YAMLError is preserved as __cause__."""
        with pytest.raises(StateError) as exc_info:
            load_state(corrupted_yaml_file)
        assert exc_info.value.__cause__ is not None
        assert "yaml" in type(exc_info.value.__cause__).__module__.lower()


# =============================================================================
# AC3: StateError raised for schema mismatch
# =============================================================================


class TestLoadStateSchemaErrors:
    """Test StateError on schema mismatch (AC3)."""

    def test_load_state_raises_state_error_for_invalid_type(
        self, invalid_schema_file: Path
    ) -> None:
        """AC3: StateError raised for invalid field types."""
        with pytest.raises(StateError) as exc_info:
            load_state(invalid_schema_file)
        assert "validation failed" in str(exc_info.value).lower()
        assert str(invalid_schema_file) in str(exc_info.value)

    def test_load_state_preserves_validation_error_cause(self, invalid_schema_file: Path) -> None:
        """AC3: Original ValidationError is preserved as __cause__."""
        with pytest.raises(StateError) as exc_info:
            load_state(invalid_schema_file)
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, ValidationError)

    def test_load_state_raises_for_invalid_phase_value(self, tmp_path: Path) -> None:
        """AC3: StateError raised for invalid Phase enum value."""
        path = tmp_path / "bad_phase.yaml"
        path.write_text(yaml.dump({"current_phase": "not_a_valid_phase"}), encoding="utf-8")
        with pytest.raises(StateError) as exc_info:
            load_state(path)
        assert "validation failed" in str(exc_info.value).lower()

    def test_load_state_raises_for_non_dict_yaml(self, tmp_path: Path) -> None:
        """AC3: StateError raised when YAML parses to non-dict."""
        path = tmp_path / "string.yaml"
        path.write_text("just a string", encoding="utf-8")
        with pytest.raises(StateError) as exc_info:
            load_state(path)
        assert "corrupted" in str(exc_info.value).lower()
        assert "expected dict" in str(exc_info.value).lower()


# =============================================================================
# AC4: Fresh state returned when file missing
# =============================================================================


class TestLoadStateMissingFile:
    """Test fresh state for missing file (AC4)."""

    def test_load_state_returns_fresh_state_when_missing(self, tmp_path: Path) -> None:
        """AC4: Missing file returns fresh State()."""
        path = tmp_path / "nonexistent.yaml"
        state = load_state(path)
        assert isinstance(state, State)
        assert state == State()

    def test_load_state_logs_info_for_missing_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC4: Info log indicates fresh start for missing file."""
        import logging

        path = tmp_path / "nonexistent.yaml"
        with caplog.at_level(logging.INFO):
            load_state(path)
        assert "starting fresh" in caplog.text.lower()

    def test_load_state_no_error_for_missing_file(self, tmp_path: Path) -> None:
        """AC4: No error raised for missing file."""
        path = tmp_path / "does_not_exist.yaml"
        # Should not raise
        state = load_state(path)
        assert state.current_epic is None


# =============================================================================
# AC5: Orphaned temp files cleaned before load
# =============================================================================


class TestLoadStateTempCleanup:
    """Test orphaned temp file cleanup (AC5)."""

    def test_load_state_calls_cleanup_first(self, saved_state_file: tuple[Path, State]) -> None:
        """AC5: _cleanup_temp_files is called before loading."""
        path, _ = saved_state_file
        with patch("bmad_assist.core.state._cleanup_temp_files") as mock_cleanup:
            load_state(path)
            mock_cleanup.assert_called_once()
            # Verify it was called with the path (expanded)
            call_arg = mock_cleanup.call_args[0][0]
            assert Path(call_arg) == path.expanduser()

    def test_load_state_removes_orphaned_temp_file(
        self, saved_state_file: tuple[Path, State]
    ) -> None:
        """AC5: Orphaned temp file is deleted before load."""
        path, _ = saved_state_file
        temp_path = path.with_suffix(".yaml.tmp")
        temp_path.write_text("orphaned content", encoding="utf-8")

        load_state(path)

        assert not temp_path.exists()

    def test_load_state_logs_warning_for_cleanup(
        self, saved_state_file: tuple[Path, State], caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC5: WARNING logged when cleaning orphaned temp file."""
        import logging

        path, _ = saved_state_file
        temp_path = path.with_suffix(".yaml.tmp")
        temp_path.write_text("orphaned", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            load_state(path)

        assert "orphaned" in caplog.text.lower()


# =============================================================================
# AC6: Path accepts str or Path with tilde expansion
# =============================================================================


class TestLoadStatePathHandling:
    """Test path handling (AC6)."""

    def test_load_state_with_string_path(self, saved_state_file: tuple[Path, State]) -> None:
        """AC6: load_state works with string path."""
        path, original = saved_state_file
        restored = load_state(str(path))
        assert restored.current_epic == original.current_epic

    def test_load_state_with_path_object(self, saved_state_file: tuple[Path, State]) -> None:
        """AC6: load_state works with Path object."""
        path, original = saved_state_file
        restored = load_state(path)
        assert restored.current_epic == original.current_epic

    def test_load_state_expands_tilde(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC6: Tilde is expanded to user home directory."""
        # Set up fake home with state file
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        bmad_dir = fake_home / ".bmad-assist"
        bmad_dir.mkdir()
        state_file = bmad_dir / "state.yaml"
        save_state(State(current_epic=42), state_file)

        def mock_expanduser(self: Path) -> Path:
            path_str = str(self)
            if path_str.startswith("~"):
                return Path(str(fake_home) + path_str[1:])
            return self

        monkeypatch.setattr(Path, "expanduser", mock_expanduser)

        restored = load_state("~/.bmad-assist/state.yaml")
        assert restored.current_epic == 42


# =============================================================================
# AC7: Function signature and exports
# =============================================================================


class TestLoadStateFunctionSignature:
    """Test function signature and exports (AC7)."""

    def test_load_state_in_module_all(self) -> None:
        """AC7: load_state is in __all__."""
        from bmad_assist.core import state as state_module

        assert "load_state" in state_module.__all__

    def test_load_state_importable(self) -> None:
        """AC7: load_state is importable from module."""
        from bmad_assist.core.state import load_state as imported_load_state

        assert imported_load_state is load_state

    def test_load_state_has_docstring(self) -> None:
        """AC7: load_state has Google-style docstring."""
        assert load_state.__doc__ is not None
        assert "Args:" in load_state.__doc__
        assert "Returns:" in load_state.__doc__
        assert "Raises:" in load_state.__doc__

    def test_load_state_docstring_has_example(self) -> None:
        """AC7: load_state docstring includes Example section."""
        assert load_state.__doc__ is not None
        assert "Example:" in load_state.__doc__


# =============================================================================
# AC8: Empty file returns fresh state
# =============================================================================


class TestLoadStateEmptyFile:
    """Test empty file handling (AC8)."""

    def test_load_state_returns_fresh_state_for_empty_file(self, tmp_path: Path) -> None:
        """AC8: Empty file returns fresh State()."""
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        state = load_state(path)
        assert state == State()

    def test_load_state_returns_fresh_state_for_whitespace_only(self, tmp_path: Path) -> None:
        """AC8: File with only whitespace returns fresh State()."""
        path = tmp_path / "whitespace.yaml"
        path.write_text("   \n\n  \t  ", encoding="utf-8")
        state = load_state(path)
        assert state == State()

    def test_load_state_logs_info_for_empty_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC8: Info log indicates fresh start for empty file."""
        import logging

        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        with caplog.at_level(logging.INFO):
            load_state(path)
        assert "empty" in caplog.text.lower()
        assert "fresh" in caplog.text.lower()


# =============================================================================
# AC9: Partial state file loads with defaults
# =============================================================================


class TestLoadStatePartialFile:
    """Test partial state file handling (AC9)."""

    def test_load_state_with_partial_fields(self, tmp_path: Path) -> None:
        """AC9: Partial state file loads with defaults for missing fields."""
        path = tmp_path / "partial.yaml"
        data = {"current_epic": 2, "current_story": "2.1"}
        path.write_text(yaml.dump(data), encoding="utf-8")

        state = load_state(path)

        # Provided fields
        assert state.current_epic == 2
        assert state.current_story == "2.1"
        # Default fields
        assert state.current_phase is None
        assert state.completed_stories == []
        assert state.started_at is None
        assert state.updated_at is None

    def test_load_state_with_only_phase(self, tmp_path: Path) -> None:
        """AC9: State with only phase loads correctly."""
        path = tmp_path / "phase_only.yaml"
        path.write_text(yaml.dump({"current_phase": "code_review"}), encoding="utf-8")

        state = load_state(path)

        assert state.current_phase == Phase.CODE_REVIEW
        assert state.current_epic is None

    def test_load_state_with_empty_dict(self, tmp_path: Path) -> None:
        """AC9: Empty dict produces default State."""
        path = tmp_path / "empty_dict.yaml"
        path.write_text("{}", encoding="utf-8")

        state = load_state(path)

        assert state == State()


# =============================================================================
# AC10: StateError raised for IO/permission errors
# =============================================================================


class TestLoadStateIOErrors:
    """Test IO/permission error handling (AC10)."""

    @pytest.mark.skipif(os.geteuid() == 0, reason="Root ignores permissions")
    def test_load_state_raises_state_error_for_permission_error(
        self, saved_state_file: tuple[Path, State]
    ) -> None:
        """AC10: PermissionError raises StateError."""
        path, _ = saved_state_file
        # Remove read permission
        path.chmod(0o000)

        try:
            with pytest.raises(StateError) as exc_info:
                load_state(path)

            assert "cannot read" in str(exc_info.value).lower()
            assert str(path) in str(exc_info.value)
        finally:
            # Restore permissions for cleanup
            path.chmod(0o644)

    @pytest.mark.skipif(os.geteuid() == 0, reason="Root ignores permissions")
    def test_load_state_preserves_permission_error_cause(
        self, saved_state_file: tuple[Path, State]
    ) -> None:
        """AC10: Original PermissionError is preserved as __cause__."""
        path, _ = saved_state_file
        path.chmod(0o000)

        try:
            with pytest.raises(StateError) as exc_info:
                load_state(path)

            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, PermissionError)
        finally:
            path.chmod(0o644)

    def test_load_state_raises_state_error_for_oserror(self, tmp_path: Path) -> None:
        """AC10: General OSError raises StateError with chained cause."""
        path = tmp_path / "state.yaml"
        # Create file first
        path.write_text("current_epic: 1", encoding="utf-8")

        # Mock read_text to raise OSError
        with patch.object(Path, "read_text") as mock_read:
            mock_read.side_effect = OSError("Network filesystem timeout")
            with pytest.raises(StateError) as exc_info:
                load_state(path)

            assert "cannot read" in str(exc_info.value).lower()
            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, OSError)

    def test_load_state_raises_state_error_for_unicode_decode_error(self, tmp_path: Path) -> None:
        """AC10: UnicodeDecodeError raises StateError (corrupted/binary file)."""
        path = tmp_path / "binary.yaml"
        # Write invalid UTF-8 bytes (Latin-1 encoded ñ without proper UTF-8)
        path.write_bytes(b"\xff\xfe invalid utf-8 content")

        with pytest.raises(StateError) as exc_info:
            load_state(path)

        assert "not valid utf-8" in str(exc_info.value).lower()
        assert str(path) in str(exc_info.value)
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, UnicodeDecodeError)


# =============================================================================
# Full round-trip test with load_state
# =============================================================================


class TestLoadStateRoundTrip:
    """Test complete save/load round-trip with load_state function."""

    def test_full_state_round_trip(self, saved_state_file: tuple[Path, State]) -> None:
        """Full state survives save_state -> load_state round-trip."""
        path, original = saved_state_file
        restored = load_state(path)

        assert restored.current_epic == original.current_epic
        assert restored.current_story == original.current_story
        assert restored.current_phase == original.current_phase
        assert restored.completed_stories == original.completed_stories
        assert restored.started_at == original.started_at
        assert restored.updated_at == original.updated_at

    def test_empty_state_round_trip(self, tmp_path: Path) -> None:
        """Empty state survives save_state -> load_state round-trip."""
        path = tmp_path / "empty_state.yaml"
        original = State()
        save_state(original, path)

        restored = load_state(path)

        assert restored == original
        assert restored.current_epic is None
        assert restored.completed_stories == []

    def test_unicode_round_trip_with_load_state(self, tmp_path: Path) -> None:
        """State with Unicode survives round-trip via load_state."""
        path = tmp_path / "unicode.yaml"
        original = State(
            current_epic=1,
            current_story="Paweł's Story ąęłóżźć",
            completed_stories=["1.1-тест", "1.2-日本語"],
        )
        save_state(original, path)

        restored = load_state(path)

        assert restored.current_story == "Paweł's Story ąęłóżźć"
        assert "1.1-тест" in restored.completed_stories
        assert "1.2-日本語" in restored.completed_stories

    def test_overwrite_and_reload(self, tmp_path: Path) -> None:
        """Multiple save/load cycles work correctly."""
        path = tmp_path / "multi.yaml"

        # First save/load
        state1 = State(current_epic=1)
        save_state(state1, path)
        assert load_state(path).current_epic == 1

        # Second save/load (overwrite)
        state2 = State(current_epic=2, current_story="2.1")
        save_state(state2, path)
        restored = load_state(path)
        assert restored.current_epic == 2
        assert restored.current_story == "2.1"
