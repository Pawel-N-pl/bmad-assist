"""Tests for bmad_assist.core.platform_command module.

This module tests cross-platform command building utilities including:
- Platform detection (IS_WINDOWS, IS_POSIX, get_platform)
- Command building (build_cross_platform_command, _build_direct_command)
- Shell command building with temp files (_build_shell_command)
- Shell quoting (_shell_quote)
- Cleanup utilities (cleanup_temp_file)
- Shell command retrieval (get_shell_command)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch


class TestPlatformDetection:
    """Tests for platform detection constants and functions."""

    def test_is_windows_on_windows(self) -> None:
        """IS_WINDOWS should be True when sys.platform is win32."""
        with patch.object(sys, "platform", "win32"):
            # Need to reimport to get new values
            import importlib

            import bmad_assist.core.platform_command as pc

            importlib.reload(pc)
            assert pc.IS_WINDOWS is True
            assert pc.IS_POSIX is False

    def test_is_posix_on_linux(self) -> None:
        """IS_POSIX should be True when sys.platform is linux."""
        with patch.object(sys, "platform", "linux"):
            import importlib

            import bmad_assist.core.platform_command as pc

            importlib.reload(pc)
            assert pc.IS_WINDOWS is False
            assert pc.IS_POSIX is True

    def test_is_posix_on_darwin(self) -> None:
        """IS_POSIX should be True when sys.platform is darwin (macOS)."""
        with patch.object(sys, "platform", "darwin"):
            import importlib

            import bmad_assist.core.platform_command as pc

            importlib.reload(pc)
            assert pc.IS_WINDOWS is False
            assert pc.IS_POSIX is True

    def test_get_platform_windows(self) -> None:
        """get_platform() should return 'windows' on Windows."""
        from bmad_assist.core import platform_command as pc

        with patch.object(pc, "IS_WINDOWS", True), patch.object(pc, "IS_POSIX", False):
            assert pc.get_platform() == "windows"

    def test_get_platform_posix(self) -> None:
        """get_platform() should return 'posix' on POSIX systems."""
        from bmad_assist.core import platform_command as pc

        with patch.object(pc, "IS_WINDOWS", False), patch.object(pc, "IS_POSIX", True):
            assert pc.get_platform() == "posix"

    def test_get_platform_unknown(self) -> None:
        """get_platform() should return 'unknown' on unknown platforms."""
        from bmad_assist.core import platform_command as pc

        with patch.object(pc, "IS_WINDOWS", False), patch.object(pc, "IS_POSIX", False):
            assert pc.get_platform() == "unknown"


class TestTempFileThreshold:
    """Tests for TEMP_FILE_THRESHOLD constant."""

    def test_threshold_value(self) -> None:
        """TEMP_FILE_THRESHOLD should be 100,000 characters."""
        from bmad_assist.core.platform_command import TEMP_FILE_THRESHOLD

        assert TEMP_FILE_THRESHOLD == 100_000

    def test_threshold_is_integer(self) -> None:
        """TEMP_FILE_THRESHOLD should be an integer."""
        from bmad_assist.core.platform_command import TEMP_FILE_THRESHOLD

        assert isinstance(TEMP_FILE_THRESHOLD, int)


class TestBuildDirectCommand:
    """Tests for _build_direct_command function."""

    def test_simple_command(self) -> None:
        """Build command with simple executable, args, and prompt."""
        from bmad_assist.core.platform_command import _build_direct_command

        result = _build_direct_command("codex", ["--json"], "Hello")
        assert result == ["codex", "--json", "Hello"]

    def test_empty_args(self) -> None:
        """Build command with no additional args."""
        from bmad_assist.core.platform_command import _build_direct_command

        result = _build_direct_command("codex", [], "Hello world")
        assert result == ["codex", "Hello world"]

    def test_multiple_args(self) -> None:
        """Build command with multiple args."""
        from bmad_assist.core.platform_command import _build_direct_command

        result = _build_direct_command(
            "codex", ["--json", "--full-auto", "-m", "o3-mini"], "Test prompt"
        )
        assert result == [
            "codex",
            "--json",
            "--full-auto",
            "-m",
            "o3-mini",
            "Test prompt",
        ]

    def test_empty_prompt(self) -> None:
        """Build command with empty prompt."""
        from bmad_assist.core.platform_command import _build_direct_command

        result = _build_direct_command("codex", ["--help"], "")
        assert result == ["codex", "--help", ""]

    def test_prompt_with_special_characters(self) -> None:
        """Build command with special characters in prompt."""
        from bmad_assist.core.platform_command import _build_direct_command

        prompt = 'Fix the bug in "main.py" & test it'
        result = _build_direct_command("codex", [], prompt)
        assert result == ["codex", prompt]

    def test_multiline_prompt(self) -> None:
        """Build command with multiline prompt."""
        from bmad_assist.core.platform_command import _build_direct_command

        prompt = "Line 1\nLine 2\nLine 3"
        result = _build_direct_command("codex", ["--json"], prompt)
        assert result == ["codex", "--json", prompt]


class TestShellQuote:
    """Tests for _shell_quote function."""

    def test_alphanumeric_no_quoting(self) -> None:
        """Alphanumeric strings should not be quoted."""
        from bmad_assist.core.platform_command import _shell_quote

        assert _shell_quote("hello123") == "hello123"
        assert _shell_quote("ABC") == "ABC"
        assert _shell_quote("test") == "test"

    def test_safe_single_chars(self) -> None:
        """Single safe characters should not be quoted."""
        from bmad_assist.core.platform_command import _shell_quote

        assert _shell_quote("_") == "_"
        assert _shell_quote("-") == "-"
        assert _shell_quote(".") == "."
        assert _shell_quote("/") == "/"

    def test_unsafe_characters_quoted(self) -> None:
        """Strings with unsafe characters should be quoted."""
        from bmad_assist.core.platform_command import _shell_quote

        assert _shell_quote("hello world") == "'hello world'"
        assert _shell_quote("test$var") == "'test$var'"
        assert _shell_quote("cmd;ls") == "'cmd;ls'"
        assert _shell_quote("file*") == "'file*'"
        assert _shell_quote("a&b") == "'a&b'"

    def test_single_quote_escaping(self) -> None:
        """Single quotes in strings should be properly escaped."""
        from bmad_assist.core.platform_command import _shell_quote

        # ' becomes '\''
        assert _shell_quote("it's") == "'it'\\''s'"
        assert _shell_quote("don't") == "'don'\\''t'"

    def test_multiple_single_quotes(self) -> None:
        """Multiple single quotes should each be escaped."""
        from bmad_assist.core.platform_command import _shell_quote

        # Input: 'a'b'
        # Each ' becomes '\'' so: '\'' a '\'' b '\''
        # Wrapped in quotes: ' + '\'' + a + '\'' + b + '\'' + '
        result = _shell_quote("'a'b'")
        assert result == "''\\''a'\\''b'\\'''"

    def test_empty_string(self) -> None:
        """Empty string should be quoted."""
        from bmad_assist.core.platform_command import _shell_quote

        assert _shell_quote("") == "''"

    def test_path_like_string(self) -> None:
        """Path-like strings with spaces should be quoted."""
        from bmad_assist.core.platform_command import _shell_quote

        assert _shell_quote("/path/to/file with space") == "'/path/to/file with space'"

    def test_option_with_value(self) -> None:
        """Options with special chars should be quoted."""
        from bmad_assist.core.platform_command import _shell_quote

        assert _shell_quote("--name=value with space") == "'--name=value with space'"


class TestBuildShellCommand:
    """Tests for _build_shell_command function."""

    def test_creates_temp_file(self, tmp_path: Path) -> None:
        """_build_shell_command should create a temp file with the prompt."""
        from bmad_assist.core.platform_command import (
            _build_shell_command,
            cleanup_temp_file,
        )

        cmd, temp_file = _build_shell_command("codex", ["--json"], "Test prompt")

        try:
            assert temp_file is not None
            assert os.path.exists(temp_file)

            # Read content of temp file
            with open(temp_file, "rb") as f:
                content = f.read().decode("utf-8")
            assert content == "Test prompt"
        finally:
            cleanup_temp_file(temp_file)

    def test_temp_file_prefix(self) -> None:
        """Temp file should have executable name as prefix."""
        from bmad_assist.core.platform_command import (
            _build_shell_command,
            cleanup_temp_file,
        )

        cmd, temp_file = _build_shell_command("myexec", [], "prompt")

        try:
            assert temp_file is not None
            basename = os.path.basename(temp_file)
            assert basename.startswith("myexec_prompt_")
            assert basename.endswith(".txt")
        finally:
            cleanup_temp_file(temp_file)

    def test_shell_command_structure(self) -> None:
        """Shell command should use /bin/sh -c with command substitution."""
        from bmad_assist.core.platform_command import (
            _build_shell_command,
            cleanup_temp_file,
        )

        cmd, temp_file = _build_shell_command("codex", ["--json"], "Test")

        try:
            assert cmd[0] == "/bin/sh"
            assert cmd[1] == "-c"
            assert "codex" in cmd[2]
            assert "$(cat" in cmd[2]
            assert temp_file in cmd[2]
            assert "--json" in cmd[2]
        finally:
            cleanup_temp_file(temp_file)

    def test_args_in_shell_command(self) -> None:
        """All args should be included in shell command."""
        from bmad_assist.core.platform_command import (
            _build_shell_command,
            cleanup_temp_file,
        )

        cmd, temp_file = _build_shell_command(
            "codex", ["--json", "--full-auto", "-m", "o3-mini"], "Prompt"
        )

        try:
            shell_cmd = cmd[2]
            assert "--json" in shell_cmd
            assert "--full-auto" in shell_cmd
            assert "-m" in shell_cmd
            assert "o3-mini" in shell_cmd
        finally:
            cleanup_temp_file(temp_file)

    def test_empty_args(self) -> None:
        """Shell command should work with no args."""
        from bmad_assist.core.platform_command import (
            _build_shell_command,
            cleanup_temp_file,
        )

        cmd, temp_file = _build_shell_command("codex", [], "Prompt")

        try:
            shell_cmd = cmd[2]
            assert "codex" in shell_cmd
            assert "$(cat" in shell_cmd
        finally:
            cleanup_temp_file(temp_file)

    def test_unicode_prompt(self) -> None:
        """Unicode prompts should be handled correctly."""
        from bmad_assist.core.platform_command import (
            _build_shell_command,
            cleanup_temp_file,
        )

        prompt = "Test with émojis 🎉 and ñ"
        cmd, temp_file = _build_shell_command("codex", [], prompt)

        try:
            with open(temp_file, "rb") as f:
                content = f.read().decode("utf-8")
            assert content == prompt
        finally:
            cleanup_temp_file(temp_file)


class TestBuildCrossPlatformCommand:
    """Tests for build_cross_platform_command function."""

    def test_short_prompt_posix_uses_direct(self) -> None:
        """Short prompts on POSIX should use direct command."""
        from bmad_assist.core import platform_command as pc

        with patch.object(pc, "IS_POSIX", True), patch.object(pc, "IS_WINDOWS", False):
            cmd, temp_file = pc.build_cross_platform_command(
                "codex", ["--json"], "Short prompt"
            )

            assert temp_file is None
            assert cmd == ["codex", "--json", "Short prompt"]

    def test_short_prompt_windows_uses_direct(self) -> None:
        """Short prompts on Windows should use direct command."""
        from bmad_assist.core import platform_command as pc

        with patch.object(pc, "IS_POSIX", False), patch.object(pc, "IS_WINDOWS", True):
            cmd, temp_file = pc.build_cross_platform_command(
                "codex", ["--json"], "Short prompt"
            )

            assert temp_file is None
            assert cmd == ["codex", "--json", "Short prompt"]

    def test_large_prompt_posix_uses_shell(self) -> None:
        """Large prompts on POSIX should use shell command with temp file."""
        from bmad_assist.core import platform_command as pc

        large_prompt = "x" * (pc.TEMP_FILE_THRESHOLD + 1)

        with patch.object(pc, "IS_POSIX", True), patch.object(pc, "IS_WINDOWS", False):
            cmd, temp_file = pc.build_cross_platform_command(
                "codex", ["--json"], large_prompt
            )

            try:
                assert temp_file is not None
                assert os.path.exists(temp_file)
                assert cmd[0] == "/bin/sh"
                assert cmd[1] == "-c"
            finally:
                pc.cleanup_temp_file(temp_file)

    def test_large_prompt_windows_uses_direct(self) -> None:
        """Large prompts on Windows should still use direct command."""
        from bmad_assist.core import platform_command as pc

        large_prompt = "x" * (pc.TEMP_FILE_THRESHOLD + 1)

        with patch.object(pc, "IS_POSIX", False), patch.object(pc, "IS_WINDOWS", True):
            cmd, temp_file = pc.build_cross_platform_command(
                "codex", ["--json"], large_prompt
            )

            assert temp_file is None
            assert cmd == ["codex", "--json", large_prompt]

    def test_use_shell_forces_shell_on_posix(self) -> None:
        """use_shell=True should force shell command on POSIX even for short prompts."""
        from bmad_assist.core import platform_command as pc

        with patch.object(pc, "IS_POSIX", True), patch.object(pc, "IS_WINDOWS", False):
            cmd, temp_file = pc.build_cross_platform_command(
                "codex", ["--json"], "Short", use_shell=True
            )

            try:
                assert temp_file is not None
                assert cmd[0] == "/bin/sh"
            finally:
                pc.cleanup_temp_file(temp_file)

    def test_use_shell_ignored_on_windows(self) -> None:
        """use_shell=True should be ignored on Windows."""
        from bmad_assist.core import platform_command as pc

        with patch.object(pc, "IS_POSIX", False), patch.object(pc, "IS_WINDOWS", True):
            cmd, temp_file = pc.build_cross_platform_command(
                "codex", ["--json"], "Short", use_shell=True
            )

            assert temp_file is None
            assert cmd == ["codex", "--json", "Short"]

    def test_prompt_at_exact_threshold_uses_direct(self) -> None:
        """Prompt at exactly threshold length should use direct command."""
        from bmad_assist.core import platform_command as pc

        exact_prompt = "x" * pc.TEMP_FILE_THRESHOLD

        with patch.object(pc, "IS_POSIX", True), patch.object(pc, "IS_WINDOWS", False):
            cmd, temp_file = pc.build_cross_platform_command(
                "codex", [], exact_prompt
            )

            assert temp_file is None
            assert cmd == ["codex", exact_prompt]

    def test_prompt_one_over_threshold_uses_shell(self) -> None:
        """Prompt one char over threshold should use shell command."""
        from bmad_assist.core import platform_command as pc

        over_prompt = "x" * (pc.TEMP_FILE_THRESHOLD + 1)

        with patch.object(pc, "IS_POSIX", True), patch.object(pc, "IS_WINDOWS", False):
            cmd, temp_file = pc.build_cross_platform_command(
                "codex", [], over_prompt
            )

            try:
                assert temp_file is not None
            finally:
                pc.cleanup_temp_file(temp_file)


class TestCleanupTempFile:
    """Tests for cleanup_temp_file function."""

    def test_cleanup_none(self) -> None:
        """cleanup_temp_file should handle None gracefully."""
        from bmad_assist.core.platform_command import cleanup_temp_file

        # Should not raise
        cleanup_temp_file(None)

    def test_cleanup_existing_file(self, tmp_path: Path) -> None:
        """cleanup_temp_file should delete existing file."""
        from bmad_assist.core.platform_command import cleanup_temp_file

        temp_file = tmp_path / "test_temp.txt"
        temp_file.write_text("test content")

        assert temp_file.exists()
        cleanup_temp_file(str(temp_file))
        assert not temp_file.exists()

    def test_cleanup_nonexistent_file(self, tmp_path: Path) -> None:
        """cleanup_temp_file should handle non-existent file gracefully."""
        from bmad_assist.core.platform_command import cleanup_temp_file

        nonexistent = str(tmp_path / "nonexistent.txt")

        # Should not raise
        cleanup_temp_file(nonexistent)

    def test_cleanup_after_shell_command(self) -> None:
        """cleanup_temp_file should clean up files from _build_shell_command."""
        from bmad_assist.core.platform_command import (
            _build_shell_command,
            cleanup_temp_file,
        )

        cmd, temp_file = _build_shell_command("codex", [], "Test")

        assert temp_file is not None
        assert os.path.exists(temp_file)

        cleanup_temp_file(temp_file)
        assert not os.path.exists(temp_file)


class TestGetShellCommand:
    """Tests for get_shell_command function."""

    def test_get_shell_command_posix(self) -> None:
        """get_shell_command should return ['/bin/sh', '-c'] on POSIX."""
        from bmad_assist.core import platform_command as pc

        with patch.object(pc, "IS_POSIX", True), patch.object(pc, "IS_WINDOWS", False):
            result = pc.get_shell_command()
            assert result == ["/bin/sh", "-c"]

    def test_get_shell_command_windows(self) -> None:
        """get_shell_command should return None on Windows."""
        from bmad_assist.core import platform_command as pc

        with patch.object(pc, "IS_POSIX", False), patch.object(pc, "IS_WINDOWS", True):
            result = pc.get_shell_command()
            assert result is None

    def test_get_shell_command_returns_list(self) -> None:
        """get_shell_command should return a list on POSIX."""
        from bmad_assist.core import platform_command as pc

        with patch.object(pc, "IS_POSIX", True):
            result = pc.get_shell_command()
            assert isinstance(result, list)
            assert len(result) == 2


class TestIntegration:
    """Integration tests for the platform_command module."""

    def test_full_workflow_short_prompt(self) -> None:
        """Test full workflow with short prompt."""
        from bmad_assist.core import platform_command as pc

        cmd, temp_file = pc.build_cross_platform_command(
            "codex", ["--json", "--full-auto"], "Fix the bug"
        )

        try:
            if pc.IS_POSIX:
                # Short prompt should use direct
                assert temp_file is None
                assert cmd == ["codex", "--json", "--full-auto", "Fix the bug"]
            else:
                # Windows always uses direct
                assert temp_file is None
        finally:
            pc.cleanup_temp_file(temp_file)

    def test_full_workflow_large_prompt_posix(self) -> None:
        """Test full workflow with large prompt on POSIX."""
        from bmad_assist.core import platform_command as pc

        large_prompt = "Please fix this: " + "x" * (pc.TEMP_FILE_THRESHOLD + 100)

        with patch.object(pc, "IS_POSIX", True), patch.object(pc, "IS_WINDOWS", False):
            cmd, temp_file = pc.build_cross_platform_command(
                "codex", ["--json"], large_prompt
            )

            try:
                # Should use shell approach
                assert temp_file is not None
                assert os.path.exists(temp_file)

                # Verify temp file content
                with open(temp_file) as f:
                    content = f.read()
                assert content == large_prompt

                # Verify command structure
                assert cmd[0] == "/bin/sh"
                assert cmd[1] == "-c"
                assert "codex" in cmd[2]
            finally:
                pc.cleanup_temp_file(temp_file)
                # Verify cleanup worked
                assert not os.path.exists(temp_file)

    def test_args_with_special_chars_preserved(self) -> None:
        """Args with special characters should be preserved in direct mode."""
        from bmad_assist.core.platform_command import _build_direct_command

        args = ["--name=test value", "-m", "gpt-4", "--flag"]
        cmd = _build_direct_command("codex", args, "prompt")

        assert cmd == ["codex", "--name=test value", "-m", "gpt-4", "--flag", "prompt"]
