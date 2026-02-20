"""Tests for provider settings loading functionality.

This module tests resolve_settings_file() and validate_settings_file()
functions from providers/base.py, covering AC1-AC10, AC2b, AC2c.

Test organization:
- TestResolveSettingsFile: Path resolution tests (AC1, AC6, AC7, AC8)
- TestValidateSettingsFile: File existence validation (AC2, AC2b, AC2c, AC3, AC4)
- TestClaudeSubprocessProviderSettingsIntegration: Integration with invoke() (AC5, AC9, AC10)

Note: Settings integration tests use ClaudeSubprocessProvider explicitly since
they test subprocess-specific behavior. The SDK provider (ClaudeSDKProvider) uses
different settings handling via ClaudeCodeOptions.
"""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.providers import (
    ClaudeSubprocessProvider,
    ProviderResult,
    resolve_settings_file,
    validate_settings_file,
)

from .conftest import create_mock_process


class TestResolveSettingsFile:
    """Tests for resolve_settings_file() function (AC1, AC6, AC7, AC8)."""

    def test_none_input_returns_none(self) -> None:
        """AC6: None settings_path returns None without processing."""
        result = resolve_settings_file(None, Path("/project"))
        assert result is None

    def test_relative_path_resolved_against_base_dir(self, tmp_path: Path) -> None:
        """AC1: Relative path is resolved against base_dir."""
        result = resolve_settings_file("./provider-configs/master.json", tmp_path)
        expected = tmp_path / "provider-configs" / "master.json"
        assert result == expected.resolve()

    def test_relative_path_without_dot_prefix(self, tmp_path: Path) -> None:
        """AC1: Relative path without ./ also resolves against base_dir."""
        result = resolve_settings_file("provider-configs/master.json", tmp_path)
        expected = tmp_path / "provider-configs" / "master.json"
        assert result == expected.resolve()

    def test_absolute_path_used_as_is(self, tmp_path: Path) -> None:
        """AC1: Absolute path is used directly, ignoring base_dir."""
        absolute_path = "/etc/provider-settings.json"
        result = resolve_settings_file(absolute_path, tmp_path)
        assert result == Path(absolute_path).resolve()

    def test_tilde_expansion(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC8: Tilde (~) is expanded to user home directory."""
        # Mock HOME environment variable for consistent testing
        monkeypatch.setenv("HOME", str(tmp_path))

        result = resolve_settings_file("~/provider-configs/custom.json", Path("/project"))
        expected = tmp_path / "provider-configs" / "custom.json"
        assert result == expected

    def test_tilde_expansion_results_in_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC8: Resolved path after tilde expansion is absolute."""
        monkeypatch.setenv("HOME", str(tmp_path))

        result = resolve_settings_file("~/config.json", Path("/project"))
        assert result is not None
        assert result.is_absolute()

    def test_result_is_always_resolved(self, tmp_path: Path) -> None:
        """All returned paths are fully resolved (no .. or symlinks)."""
        result = resolve_settings_file("./configs/../provider-configs/test.json", tmp_path)
        expected = tmp_path / "provider-configs" / "test.json"
        assert result == expected.resolve()
        # Verify there's no ".." in the path
        assert ".." not in str(result)


class TestValidateSettingsFile:
    """Tests for validate_settings_file() function (AC2, AC2b, AC2c, AC3, AC4)."""

    def test_none_input_returns_none(self) -> None:
        """None settings_file returns None without validation."""
        result = validate_settings_file(None, "claude", "opus")
        assert result is None

    def test_existing_file_returns_path(self, tmp_path: Path) -> None:
        """AC5: Existing file returns the Path unchanged."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('{"timeout": 600}')

        result = validate_settings_file(settings_file, "claude", "opus")
        assert result == settings_file

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """AC2b: Missing file returns None (not raised exception)."""
        missing_file = tmp_path / "nonexistent.json"

        result = validate_settings_file(missing_file, "claude", "opus")
        assert result is None

    def test_missing_file_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC3: Warning logged when settings file is missing."""
        missing_file = tmp_path / "missing-settings.json"

        with caplog.at_level(logging.WARNING):
            validate_settings_file(missing_file, "claude", "opus")

        # Verify warning was logged
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.WARNING
        assert "Settings file not found" in record.message
        assert "missing-settings.json" in record.message
        assert "claude" in record.message
        assert "opus" in record.message

    def test_directory_path_returns_none(self, tmp_path: Path) -> None:
        """AC2c: Directory (not file) returns None."""
        dir_path = tmp_path / "settings-dir"
        dir_path.mkdir()

        result = validate_settings_file(dir_path, "claude", "opus")
        assert result is None

    def test_directory_path_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC2c: Warning logged when settings path is directory."""
        dir_path = tmp_path / "settings-dir"
        dir_path.mkdir()

        with caplog.at_level(logging.WARNING):
            validate_settings_file(dir_path, "claude", "opus")

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.WARNING
        assert "Settings path is not a file" in record.message
        assert "claude" in record.message
        assert "opus" in record.message

    def test_warning_uses_structured_logging(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC3: Warning uses structured parameters (not f-string)."""
        missing_file = tmp_path / "structured-test.json"

        with caplog.at_level(logging.WARNING):
            validate_settings_file(missing_file, "test-provider", "test-model")

        record = caplog.records[0]
        # Structured logging uses % formatting, not f-strings
        # The message template contains %s placeholders
        assert record.args is not None
        assert len(record.args) == 3
        # Verify the arguments are passed separately (structured logging)
        assert str(missing_file) in str(record.args[0])
        assert record.args[1] == "test-provider"
        assert record.args[2] == "test-model"


class TestClaudeSubprocessProviderSettingsIntegration:
    """Integration tests for ClaudeSubprocessProvider with settings files (AC5, AC9, AC10)."""

    @pytest.fixture
    def provider(self) -> ClaudeSubprocessProvider:
        """Create ClaudeSubprocessProvider instance."""
        return ClaudeSubprocessProvider()

    def test_invoke_with_existing_settings_file(
        self, provider: ClaudeSubprocessProvider, tmp_path: Path
    ) -> None:
        """AC5: Settings file passed to CLI when it exists."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('{"timeout": 600}')

        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="Response text",
            )
            provider.invoke("Hello", model="sonnet", settings_file=settings_file)

            # Verify --settings flag is in command
            call_args = mock_popen.call_args
            command = call_args[0][0]
            assert "--settings" in command
            settings_idx = command.index("--settings")
            assert command[settings_idx + 1] == str(settings_file)

    def test_invoke_without_settings_file(self, provider: ClaudeSubprocessProvider) -> None:
        """AC6: CLI executed WITHOUT --settings flag when settings_file is None."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="Response text",
            )
            provider.invoke("Hello", model="sonnet", settings_file=None)

            # Verify --settings flag is NOT in command
            call_args = mock_popen.call_args
            command = call_args[0][0]
            assert "--settings" not in command

    def test_invoke_with_missing_settings_file_omits_flag(
        self,
        provider: ClaudeSubprocessProvider,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AC4: Provider runs WITHOUT --settings flag when file missing.

        When settings_file is provided but doesn't exist, ClaudeSubprocessProvider:
        1. Logs a warning with provider/model context (AC3)
        2. Omits --settings flag from CLI command (AC4)
        3. Returns ProviderResult normally (graceful degradation)
        """
        missing_file = tmp_path / "missing.json"

        with caplog.at_level(logging.WARNING):
            with patch("bmad_assist.providers.claude.Popen") as mock_popen:
                mock_popen.return_value = create_mock_process(
                    response_text="Response text",
                )
                result = provider.invoke("Hello", model="sonnet", settings_file=missing_file)

        # Verify result returned normally (graceful degradation)
        assert isinstance(result, ProviderResult)

        # Verify --settings flag is NOT in command (AC4)
        call_args = mock_popen.call_args
        command = call_args[0][0]
        assert "--settings" not in command

        # Verify warning was logged (AC3)
        assert len(caplog.records) >= 1
        warning_logged = any(
            "Settings file not found" in r.message
            for r in caplog.records
            if r.levelno == logging.WARNING
        )
        assert warning_logged, "Expected warning about missing settings file"

    def test_invoke_with_directory_settings_file_omits_flag(
        self,
        provider: ClaudeSubprocessProvider,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AC2c: Provider runs WITHOUT --settings flag when path is directory.

        When settings_file is a directory (not a regular file), ClaudeSubprocessProvider:
        1. Logs a warning about path not being a file (AC2c)
        2. Omits --settings flag from CLI command
        3. Returns ProviderResult normally (graceful degradation)
        """
        dir_path = tmp_path / "settings-dir"
        dir_path.mkdir()

        with caplog.at_level(logging.WARNING):
            with patch("bmad_assist.providers.claude.Popen") as mock_popen:
                mock_popen.return_value = create_mock_process(
                    response_text="Response text",
                )
                result = provider.invoke("Hello", model="sonnet", settings_file=dir_path)

        # Verify result returned normally (graceful degradation)
        assert isinstance(result, ProviderResult)

        # Verify --settings flag is NOT in command
        call_args = mock_popen.call_args
        command = call_args[0][0]
        assert "--settings" not in command

        # Verify warning was logged
        assert len(caplog.records) >= 1
        warning_logged = any(
            "Settings path is not a file" in r.message
            for r in caplog.records
            if r.levelno == logging.WARNING
        )
        assert warning_logged, "Expected warning about path not being a file"

    def test_settings_file_content_not_validated(
        self, provider: ClaudeSubprocessProvider, tmp_path: Path
    ) -> None:
        """AC9: Settings file content is NOT parsed/validated by bmad-assist.

        Invalid JSON, broken content, or non-JSON files are passed directly
        to CLI - CLI tool handles validation.
        """
        # Create file with invalid JSON
        invalid_json = tmp_path / "invalid.json"
        invalid_json.write_text("{broken")

        # Create file with non-JSON content
        non_json = tmp_path / "text.txt"
        non_json.write_text("hello world")

        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="Response text",
            )
            # Both should execute without bmad-assist raising errors
            result1 = provider.invoke("Hello", model="sonnet", settings_file=invalid_json)
            result2 = provider.invoke("Hello", model="sonnet", settings_file=non_json)

        assert isinstance(result1, ProviderResult)
        assert isinstance(result2, ProviderResult)

    def test_backward_compatibility_invoke_without_settings(
        self, provider: ClaudeSubprocessProvider
    ) -> None:
        """AC10: Existing invoke() calls without settings_file work unchanged."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="Response text",
            )
            # Call invoke WITHOUT settings_file parameter (existing pattern)
            result = provider.invoke("Hello", model="opus", timeout=60)

        assert isinstance(result, ProviderResult)
        assert result.exit_code == 0

    def test_backward_compatibility_all_params_optional(
        self, provider: ClaudeSubprocessProvider
    ) -> None:
        """AC10: invoke() with only prompt works (all other params optional)."""
        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="Response text",
            )
            result = provider.invoke("Hello")

        assert isinstance(result, ProviderResult)

    def test_settings_file_path_object(
        self, provider: ClaudeSubprocessProvider, tmp_path: Path
    ) -> None:
        """AC5: invoke() receives settings_file as Path object."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('{"key": "value"}')

        with patch("bmad_assist.providers.claude.Popen") as mock_popen:
            mock_popen.return_value = create_mock_process(
                response_text="Response text",
            )
            # Pass Path object (not string)
            provider.invoke("Hello", model="sonnet", settings_file=settings_file)

            # Verify path was converted to string for CLI
            call_args = mock_popen.call_args
            command = call_args[0][0]
            settings_idx = command.index("--settings")
            # Command contains string representation
            assert command[settings_idx + 1] == str(settings_file)


class TestEndToEndSettingsLoading:
    """End-to-end tests combining resolve and validate functions."""

    def test_full_resolution_and_validation_flow(self, tmp_path: Path) -> None:
        """Test complete flow: resolve path → validate → use."""
        # Create settings file
        settings_dir = tmp_path / "provider-configs"
        settings_dir.mkdir()
        settings_file = settings_dir / "master-claude-opus_4.json"
        settings_file.write_text('{"timeout": 600}')

        # Step 1: Resolve relative path
        resolved = resolve_settings_file("./provider-configs/master-claude-opus_4.json", tmp_path)
        assert resolved is not None
        assert resolved.is_absolute()

        # Step 2: Validate file exists
        validated = validate_settings_file(resolved, "claude", "opus_4")
        assert validated == resolved

    def test_flow_with_missing_file(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Test flow when settings file doesn't exist."""
        # Step 1: Resolve path (succeeds even if file doesn't exist)
        resolved = resolve_settings_file("./missing/settings.json", tmp_path)
        assert resolved is not None

        # Step 2: Validate detects missing file
        with caplog.at_level(logging.WARNING):
            validated = validate_settings_file(resolved, "claude", "opus")

        assert validated is None
        assert len(caplog.records) == 1

    def test_flow_with_none_path(self) -> None:
        """Test flow when no settings configured (None throughout)."""
        resolved = resolve_settings_file(None, Path("/project"))
        assert resolved is None

        validated = validate_settings_file(resolved, "claude", "opus")
        assert validated is None

    def test_tilde_path_end_to_end(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test tilde expansion in full flow."""
        # Mock HOME environment variable to tmp_path for testing
        monkeypatch.setenv("HOME", str(tmp_path))

        # Create file in "home" directory
        config_dir = tmp_path / "provider-configs"
        config_dir.mkdir()
        settings_file = config_dir / "custom.json"
        settings_file.write_text("{}")

        # Resolve with tilde
        resolved = resolve_settings_file("~/provider-configs/custom.json", Path("/other/project"))
        assert resolved == settings_file

        # Validate file exists
        validated = validate_settings_file(resolved, "claude", "opus")
        assert validated == settings_file
