"""Tests for platform_command module.

Tests cross-platform command building for large prompts to avoid ARG_MAX limits.
"""

import os
import sys
from unittest.mock import patch

import pytest

from bmad_assist.core.platform_command import (
    IS_POSIX,
    IS_WINDOWS,
    TEMP_FILE_THRESHOLD,
    build_cross_platform_command,
    cleanup_temp_file,
)


class TestPlatformDetection:
    """Tests for platform detection constants."""

    def test_is_windows_or_posix(self):
        """One of IS_WINDOWS or IS_POSIX must be True."""
        assert IS_WINDOWS or IS_POSIX
        assert not (IS_WINDOWS and IS_POSIX)

    def test_matches_sys_platform(self):
        """IS_WINDOWS should match sys.platform == win32."""
        assert (sys.platform == "win32") == IS_WINDOWS
        assert (sys.platform != "win32") == IS_POSIX


class TestTempFileThreshold:
    """Tests for threshold constant."""

    def test_threshold_is_100kb(self):
        """Threshold should be 100KB (100,000 bytes)."""
        assert TEMP_FILE_THRESHOLD == 100_000


class TestBuildCrossPlatformCommand:
    """Tests for build_cross_platform_command function."""

    def test_small_prompt_returns_direct_command(self):
        """Small prompts should return direct command with no temp file."""
        prompt = "Hello, world!"
        cmd, temp_file = build_cross_platform_command("copilot", ["-p"], prompt)

        assert temp_file is None
        assert cmd == ["copilot", "-p", "Hello, world!"]

    def test_empty_args_list(self):
        """Should work with empty args list."""
        cmd, temp_file = build_cross_platform_command("test-cli", [], "prompt")

        assert temp_file is None
        assert cmd == ["test-cli", "prompt"]

    def test_multiple_args(self):
        """Should handle multiple args before prompt."""
        cmd, temp_file = build_cross_platform_command(
            "cursor-agent",
            ["--print", "--model", "claude-sonnet-4", "--force"],
            "short prompt",
        )

        assert temp_file is None
        assert cmd == [
            "cursor-agent",
            "--print",
            "--model",
            "claude-sonnet-4",
            "--force",
            "short prompt",
        ]

    @pytest.mark.skipif(IS_WINDOWS, reason="Temp file only on POSIX")
    def test_large_prompt_creates_temp_file_on_posix(self):
        """Large prompts on POSIX should create temp file."""
        # Create prompt just over threshold (100KB)
        large_prompt = "x" * (TEMP_FILE_THRESHOLD + 1)
        cmd, temp_file = build_cross_platform_command("copilot", ["-p"], large_prompt)

        try:
            assert temp_file is not None
            assert os.path.exists(temp_file)

            # Command should be shell wrapper
            assert cmd[0] == "/bin/sh"
            assert cmd[1] == "-c"
            assert "$(cat " in cmd[2]
            assert temp_file in cmd[2]

            # Verify temp file contains prompt
            with open(temp_file, encoding="utf-8") as f:
                content = f.read()
            assert content == large_prompt
        finally:
            cleanup_temp_file(temp_file)

    @pytest.mark.skipif(IS_WINDOWS, reason="Temp file only on POSIX")
    def test_prompt_at_threshold_uses_direct_command(self):
        """Prompt exactly at threshold should use direct command (< not <=)."""
        prompt = "x" * (TEMP_FILE_THRESHOLD - 1)  # Just under threshold
        cmd, temp_file = build_cross_platform_command("test", ["-p"], prompt)

        assert temp_file is None
        assert cmd == ["test", "-p", prompt]

    @pytest.mark.skipif(IS_WINDOWS, reason="Temp file only on POSIX")
    def test_unicode_prompt_measures_bytes(self):
        """Unicode prompts should measure size in bytes, not chars."""
        # Each emoji is 4 bytes in UTF-8
        emoji = "\U0001F600"  # 😀 = 4 bytes
        assert len(emoji) == 1  # 1 character
        assert len(emoji.encode("utf-8")) == 4  # 4 bytes

        # Create prompt that's under threshold in chars but over in bytes
        # Need 100,000 bytes / 4 bytes per emoji = 25,000 emojis
        chars_needed = TEMP_FILE_THRESHOLD // 4 + 1
        large_prompt = emoji * chars_needed

        # Verify our math
        assert len(large_prompt) < TEMP_FILE_THRESHOLD  # chars
        assert len(large_prompt.encode("utf-8")) >= TEMP_FILE_THRESHOLD  # bytes

        cmd, temp_file = build_cross_platform_command("test", ["-p"], large_prompt)

        try:
            assert temp_file is not None
        finally:
            cleanup_temp_file(temp_file)

    @pytest.mark.skipif(not IS_WINDOWS, reason="Windows-specific test")
    def test_windows_always_uses_direct_command(self):
        """Windows should always use direct command regardless of size."""
        large_prompt = "x" * (TEMP_FILE_THRESHOLD + 1000)
        cmd, temp_file = build_cross_platform_command("copilot", ["-p"], large_prompt)

        assert temp_file is None
        assert cmd == ["copilot", "-p", large_prompt]

    def test_simulated_windows_uses_direct_command(self):
        """Simulated Windows should use direct command for large prompts."""
        with patch("bmad_assist.core.platform_command.IS_WINDOWS", True):
            with patch("bmad_assist.core.platform_command.IS_POSIX", False):
                large_prompt = "x" * (TEMP_FILE_THRESHOLD + 1000)
                cmd, temp_file = build_cross_platform_command(
                    "copilot", ["-p"], large_prompt
                )

                assert temp_file is None
                assert cmd == ["copilot", "-p", large_prompt]


class TestCleanupTempFile:
    """Tests for cleanup_temp_file function."""

    def test_cleanup_none_is_noop(self):
        """Cleanup with None should not raise."""
        cleanup_temp_file(None)  # Should not raise

    def test_cleanup_nonexistent_file_is_silent(self):
        """Cleanup of nonexistent file should not raise."""
        cleanup_temp_file("/nonexistent/path/that/does/not/exist")  # Should not raise

    @pytest.mark.skipif(IS_WINDOWS, reason="Temp file only on POSIX")
    def test_cleanup_removes_file(self):
        """Cleanup should delete the temp file."""
        # Create temp file via build_cross_platform_command
        large_prompt = "x" * (TEMP_FILE_THRESHOLD + 1)
        _, temp_file = build_cross_platform_command("test", ["-p"], large_prompt)

        assert temp_file is not None
        assert os.path.exists(temp_file)

        cleanup_temp_file(temp_file)

        assert not os.path.exists(temp_file)

    def test_cleanup_suppresses_permission_error(self):
        """Cleanup should suppress permission errors."""
        with patch("os.unlink", side_effect=PermissionError("denied")):
            cleanup_temp_file("/some/path")  # Should not raise


class TestLargePromptEdgeCases:
    """Tests for edge cases with large prompts."""

    @pytest.mark.skipif(IS_WINDOWS, reason="Temp file only on POSIX")
    def test_special_characters_in_prompt(self):
        """Prompts with special shell characters should be handled safely."""
        # Prompt with shell-dangerous characters
        dangerous_prompt = 'x" ; rm -rf / ; echo "' * 10000

        if len(dangerous_prompt.encode("utf-8")) < TEMP_FILE_THRESHOLD:
            # If under threshold, make it larger
            dangerous_prompt = dangerous_prompt * 20

        cmd, temp_file = build_cross_platform_command("test", ["-p"], dangerous_prompt)

        try:
            assert temp_file is not None
            # The prompt should be stored in file, not in command
            # Command should use shlex.quote for safety
            assert '"$(cat ' in cmd[2] or "'$(cat " in cmd[2]
        finally:
            cleanup_temp_file(temp_file)

    @pytest.mark.skipif(IS_WINDOWS, reason="Temp file only on POSIX")
    def test_newlines_in_prompt(self):
        """Prompts with newlines should be handled correctly."""
        prompt_with_newlines = "line1\nline2\nline3\n" * 30000

        cmd, temp_file = build_cross_platform_command("test", ["-p"], prompt_with_newlines)

        try:
            assert temp_file is not None

            # Verify file content preserves newlines
            with open(temp_file, encoding="utf-8") as f:
                content = f.read()
            assert content == prompt_with_newlines
        finally:
            cleanup_temp_file(temp_file)

    @pytest.mark.skipif(IS_WINDOWS, reason="Temp file only on POSIX")
    def test_temp_file_prefix_and_suffix(self):
        """Temp file should have recognizable prefix and suffix."""
        large_prompt = "x" * (TEMP_FILE_THRESHOLD + 1)
        _, temp_file = build_cross_platform_command("test", ["-p"], large_prompt)

        try:
            assert temp_file is not None
            assert "bmad_prompt_" in os.path.basename(temp_file)
            assert temp_file.endswith(".txt")
        finally:
            cleanup_temp_file(temp_file)
