"""Tests for debug JSON logger module.

Tests the DebugJsonLogger class that provides resilient append-only logging
of raw JSON messages from provider communication.
"""

import json
import logging
from pathlib import Path

import pytest

from bmad_assist.core.debug_logger import DebugJsonLogger, save_prompt

# Use real DebugJsonLogger in this module (not the global mock)
pytestmark = pytest.mark.real_debug_logger


class TestDebugJsonLoggerBasic:
    """Basic functionality tests."""

    def test_disabled_logger_does_not_write(self, tmp_path: Path) -> None:
        """Disabled logger should not create files or write."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=False)

        init_msg = json.dumps({"type": "system", "subtype": "init", "session_id": "test-123"})
        logger.append(init_msg)
        logger.close()

        # No files should be created
        assert list(tmp_path.glob("*.jsonl")) == []

    def test_enabled_logger_creates_file_on_init_message(self, tmp_path: Path) -> None:
        """Logger should create file when init message is received."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        init_msg = json.dumps(
            {"type": "system", "subtype": "init", "session_id": "test-session-123"}
        )
        logger.append(init_msg)

        # File should be created
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        assert "test-session-123" in files[0].name

        logger.close()

    def test_file_contains_all_appended_lines(self, tmp_path: Path) -> None:
        """All appended lines should be written to file."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        messages = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "abc123"}),
            json.dumps({"type": "assistant", "message": {"content": []}}),
            json.dumps({"type": "result", "total_cost_usd": 0.001}),
        ]

        for msg in messages:
            logger.append(msg)

        logger.close()

        # Read file and verify contents
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1

        content = files[0].read_text()
        lines = content.strip().split("\n")

        assert len(lines) == 3
        for i, line in enumerate(lines):
            assert json.loads(line) == json.loads(messages[i])

    def test_session_id_extracted_from_init(self, tmp_path: Path) -> None:
        """Session ID should be extracted from init message."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        init_msg = json.dumps(
            {"type": "system", "subtype": "init", "session_id": "my-unique-session"}
        )
        logger.append(init_msg)

        assert logger.session_id == "my-unique-session"
        logger.close()


class TestDebugJsonLoggerFilename:
    """Tests for filename generation."""

    def test_filename_contains_session_id(self, tmp_path: Path) -> None:
        """Filename should include session_id."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        init_msg = json.dumps({"type": "system", "subtype": "init", "session_id": "unique-id-42"})
        logger.append(init_msg)

        assert logger.file_path is not None
        assert "unique-id-42" in logger.file_path.name
        logger.close()

    def test_filename_contains_timestamp(self, tmp_path: Path) -> None:
        """Filename should include compact timestamp."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        init_msg = json.dumps({"type": "system", "subtype": "init", "session_id": "session"})
        logger.append(init_msg)

        assert logger.file_path is not None
        # Should have format like: 25.12.14-17.30-session.jsonl
        name = logger.file_path.name
        # Timestamp comes first (YY.MM.DD-HH.MM)
        assert name[2] == "."  # YY.MM
        assert name[5] == "."  # MM.DD
        assert "-" in name  # Separators
        assert name.endswith(".jsonl")
        logger.close()

    def test_filename_is_filesystem_safe(self, tmp_path: Path) -> None:
        """Filename should not contain problematic characters."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        init_msg = json.dumps({"type": "system", "subtype": "init", "session_id": "session"})
        logger.append(init_msg)

        assert logger.file_path is not None
        name = logger.file_path.name
        # No colons (problematic on Windows)
        assert ":" not in name
        logger.close()


class TestDebugJsonLoggerResilience:
    """Tests for crash resilience."""

    def test_data_written_immediately(self, tmp_path: Path) -> None:
        """Data should be on disk immediately after append."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        init_msg = json.dumps({"type": "system", "subtype": "init", "session_id": "test"})
        logger.append(init_msg)

        # Without calling close(), data should still be on disk
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1

        content = files[0].read_text()
        assert "test" in content

    def test_multiple_appends_accumulate(self, tmp_path: Path) -> None:
        """Multiple appends should accumulate in file."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        # First message creates file
        logger.append(json.dumps({"type": "system", "subtype": "init", "session_id": "test"}))

        # Add more messages
        for i in range(5):
            logger.append(json.dumps({"type": "data", "index": i}))

        # Verify all lines present
        files = list(tmp_path.glob("*.jsonl"))
        content = files[0].read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 6  # init + 5 data messages


class TestDebugJsonLoggerBuffering:
    """Tests for pre-init buffering."""

    def test_non_init_messages_buffered(self, tmp_path: Path) -> None:
        """Messages before init should be buffered and written later."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        # Send non-init message first (unusual but should handle)
        logger.append(json.dumps({"type": "other", "data": "test"}))

        # No file created yet
        assert logger.file_path is None

        # Now send init
        logger.append(json.dumps({"type": "system", "subtype": "init", "session_id": "test"}))

        # File should be created with both messages
        assert logger.file_path is not None
        content = logger.file_path.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2

        logger.close()

    def test_close_writes_buffered_to_fallback(self, tmp_path: Path) -> None:
        """Close should write buffered messages to fallback file."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        # Only non-init messages
        logger.append(json.dumps({"type": "other", "data": "test"}))

        # Call close without init
        logger.close()

        # Fallback file should be created with format: {timestamp}-unknown-{unique}.jsonl
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        assert "-unknown-" in files[0].name


class TestDebugJsonLoggerIntegration:
    """Integration tests with logging module."""

    def test_enabled_follows_debug_level(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Logger should auto-enable based on DEBUG level."""
        # Set DEBUG level
        with caplog.at_level(logging.DEBUG, logger="bmad_assist.core.debug_logger"):
            logger = DebugJsonLogger(debug_dir=tmp_path)
            assert logger.enabled is True

    def test_disabled_at_info_level(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Logger should be disabled at INFO level."""
        with caplog.at_level(logging.INFO, logger="bmad_assist.core.debug_logger"):
            logger = DebugJsonLogger(debug_dir=tmp_path)
            assert logger.enabled is False

    def test_path_property_returns_none_when_disabled(self, tmp_path: Path) -> None:
        """Path property should return None when disabled."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=False)
        assert logger.path is None

    def test_path_property_returns_path_when_enabled(self, tmp_path: Path) -> None:
        """Path property should return Path when enabled and file created."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        logger.append(json.dumps({"type": "system", "subtype": "init", "session_id": "test"}))

        assert logger.path is not None
        assert logger.path.exists()
        logger.close()


class TestDebugJsonLoggerEdgeCases:
    """Edge case tests."""

    def test_empty_line_ignored(self, tmp_path: Path) -> None:
        """Empty lines should be ignored."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        logger.append(json.dumps({"type": "system", "subtype": "init", "session_id": "test"}))
        logger.append("")  # Empty
        logger.append("  ")  # Whitespace only
        logger.append(json.dumps({"type": "data"}))

        content = logger.file_path.read_text()
        lines = content.strip().split("\n")
        # Should only have init and data, not empty lines
        assert len(lines) == 2
        logger.close()

    def test_invalid_json_still_logged(self, tmp_path: Path) -> None:
        """Invalid JSON should still be logged as-is."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        logger.append(json.dumps({"type": "system", "subtype": "init", "session_id": "test"}))
        logger.append("not valid json")
        logger.append("{broken")

        content = logger.file_path.read_text()
        assert "not valid json" in content
        assert "{broken" in content
        logger.close()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if they don't exist."""
        deep_path = tmp_path / "a" / "b" / "c"
        logger = DebugJsonLogger(debug_dir=deep_path, enabled=True)

        logger.append(json.dumps({"type": "system", "subtype": "init", "session_id": "test"}))

        assert deep_path.exists()
        assert logger.file_path is not None
        assert logger.file_path.exists()
        logger.close()

    def test_unicode_content_preserved(self, tmp_path: Path) -> None:
        """Unicode content should be preserved."""
        logger = DebugJsonLogger(debug_dir=tmp_path, enabled=True)

        logger.append(json.dumps({"type": "system", "subtype": "init", "session_id": "test"}))
        # Use ensure_ascii=False to preserve unicode in JSON
        logger.append(
            json.dumps({"type": "text", "content": "日本語 Cześć 🚀"}, ensure_ascii=False)
        )

        content = logger.file_path.read_text(encoding="utf-8")
        assert "日本語" in content
        assert "Cześć" in content
        assert "🚀" in content
        logger.close()


class TestSavePrompt:
    """Tests for save_prompt function."""

    def test_disabled_does_not_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When disabled, should not create any files."""
        monkeypatch.setattr("bmad_assist.core.debug_logger.PROMPTS_DIR", tmp_path)

        result = save_prompt("test prompt", "create_story", enabled=False)

        assert result is None
        assert list(tmp_path.glob("*.txt")) == []

    def test_enabled_creates_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When enabled, should create file with prompt content."""
        monkeypatch.setattr("bmad_assist.core.debug_logger.PROMPTS_DIR", tmp_path)

        result = save_prompt("test prompt content", "create_story", enabled=True)

        assert result is not None
        assert result.exists()
        assert result.read_text() == "test prompt content"

    def test_filename_contains_phase_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Filename should include phase name."""
        monkeypatch.setattr("bmad_assist.core.debug_logger.PROMPTS_DIR", tmp_path)

        result = save_prompt("prompt", "my_phase", enabled=True)

        assert result is not None
        assert "my_phase" in result.name
        assert result.name.endswith(".xml")

    def test_filename_contains_timestamp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Filename should include timestamp in YY.MM.DD-HH.MM.SS format."""
        monkeypatch.setattr("bmad_assist.core.debug_logger.PROMPTS_DIR", tmp_path)

        result = save_prompt("prompt", "test", enabled=True)

        assert result is not None
        name = result.name
        # Format: 25.12.14-17.30.45-test.txt
        assert name[2] == "."  # YY.MM
        assert name[5] == "."  # MM.DD
        assert name[8] == "-"  # DD-HH
        assert name[11] == "."  # HH.MM
        assert name[14] == "."  # MM.SS

    def test_creates_parent_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should create parent directories if they don't exist."""
        deep_path = tmp_path / "a" / "b" / "prompts"
        monkeypatch.setattr("bmad_assist.core.debug_logger.PROMPTS_DIR", deep_path)

        result = save_prompt("prompt", "test", enabled=True)

        assert result is not None
        assert deep_path.exists()
        assert result.exists()

    def test_unicode_content_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unicode content should be preserved."""
        monkeypatch.setattr("bmad_assist.core.debug_logger.PROMPTS_DIR", tmp_path)

        prompt = "日本語 Cześć 🚀 émoji"
        result = save_prompt(prompt, "test", enabled=True)

        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "日本語" in content
        assert "Cześć" in content
        assert "🚀" in content

    def test_follows_debug_level_when_enabled_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When enabled=None, should follow logger DEBUG level."""
        monkeypatch.setattr("bmad_assist.core.debug_logger.PROMPTS_DIR", tmp_path)

        # At DEBUG level, should save
        with caplog.at_level(logging.DEBUG, logger="bmad_assist.core.debug_logger"):
            result = save_prompt("prompt", "test")
            assert result is not None

    def test_disabled_at_info_level(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When enabled=None at INFO level, should not save."""
        monkeypatch.setattr("bmad_assist.core.debug_logger.PROMPTS_DIR", tmp_path)

        with caplog.at_level(logging.INFO, logger="bmad_assist.core.debug_logger"):
            result = save_prompt("prompt", "test")
            assert result is None
