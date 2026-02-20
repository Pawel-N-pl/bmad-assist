"""Tests for project setup module.

Mocking strategy for Rich prompts:
- Use monkeypatch to replace rich.prompt.Prompt.ask
- Return predefined values for test scenarios
"""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from bmad_assist.core.project_setup import (
    SetupResult,
    _compare_files,
    _validate_path_safe,
    check_gitignore_warning,
    ensure_project_setup,
)


class TestPathValidation:
    """Tests for path traversal prevention."""

    def test_valid_path_within_project(self, tmp_path: Path) -> None:
        """AC11: Path within project is valid."""
        target = tmp_path / "_bmad" / "workflows" / "test"
        assert _validate_path_safe(tmp_path, target) is True

    def test_invalid_path_traversal(self, tmp_path: Path) -> None:
        """AC11: Path traversal attempt is rejected."""
        target = tmp_path / "_bmad" / ".." / ".." / "etc" / "passwd"
        assert _validate_path_safe(tmp_path, target) is False

    def test_valid_nested_path(self, tmp_path: Path) -> None:
        """Deep nested path within project is valid."""
        target = tmp_path / "a" / "b" / "c" / "d" / "file.txt"
        assert _validate_path_safe(tmp_path, target) is True

    def test_sibling_path_invalid(self, tmp_path: Path) -> None:
        """Path to sibling directory is invalid."""
        sibling = tmp_path.parent / "sibling_project"
        assert _validate_path_safe(tmp_path, sibling) is False


class TestFileComparison:
    """Tests for file comparison with normalization."""

    def test_identical_files(self, tmp_path: Path) -> None:
        """Identical files compare as equal."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("same content\n")
        file2.write_text("same content\n")
        assert _compare_files(file1, file2) is True

    def test_different_files(self, tmp_path: Path) -> None:
        """Different files compare as not equal."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content A\n")
        file2.write_text("content B\n")
        assert _compare_files(file1, file2) is False

    def test_crlf_treated_as_lf(self, tmp_path: Path) -> None:
        """AC10: CRLF and LF versions compare as equal."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("line1\r\nline2\r\n")
        file2.write_text("line1\nline2\n")
        assert _compare_files(file1, file2) is True

    def test_trailing_whitespace_normalized(self, tmp_path: Path) -> None:
        """Trailing whitespace is stripped before comparison."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content\n\n\n")
        file2.write_text("content")
        assert _compare_files(file1, file2) is True

    @pytest.mark.skipif(
        os.name == "nt", reason="Symlinks require admin on Windows"
    )
    def test_symlink_treated_as_different(self, tmp_path: Path) -> None:
        """AC12: Symlinks are always treated as different."""
        real = tmp_path / "real.txt"
        link = tmp_path / "link.txt"
        real.write_text("content")
        link.symlink_to(real)
        assert _compare_files(real, link) is False

    def test_binary_files_compared(self, tmp_path: Path) -> None:
        """Binary files use byte comparison."""
        file1 = tmp_path / "file1.bin"
        file2 = tmp_path / "file2.bin"
        file1.write_bytes(b"\x00\x01\x02")
        file2.write_bytes(b"\x00\x01\x02")
        assert _compare_files(file1, file2) is True

    def test_binary_files_different(self, tmp_path: Path) -> None:
        """Different binary files compare as not equal."""
        file1 = tmp_path / "file1.bin"
        file2 = tmp_path / "file2.bin"
        file1.write_bytes(b"\x00\x01\x02")
        file2.write_bytes(b"\x00\x01\x03")
        assert _compare_files(file1, file2) is False


class TestGitignoreWarning:
    """Tests for gitignore warning behavior."""

    def test_warning_suppressed_by_config(self, tmp_path: Path) -> None:
        """AC6: Config option suppresses warning."""
        config = MagicMock()
        config.warnings = MagicMock()
        config.warnings.suppress_gitignore = True
        console = MagicMock()

        check_gitignore_warning(tmp_path, config, console)
        console.print.assert_not_called()

    def test_warning_shown_when_no_config(self, tmp_path: Path) -> None:
        """Warning displayed when no config suppression."""
        console = MagicMock()
        check_gitignore_warning(tmp_path, None, console)
        # Should have called print at least once for warning
        assert console.print.called

    def test_warning_shown_when_warnings_none(self, tmp_path: Path) -> None:
        """Warning displayed when config.warnings is None."""
        config = MagicMock()
        config.warnings = None
        console = MagicMock()

        check_gitignore_warning(tmp_path, config, console)
        assert console.print.called

    def test_no_warning_when_gitignore_complete(self, tmp_path: Path) -> None:
        """No warning when gitignore has all patterns."""
        # Create complete gitignore
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(
            "# bmad-assist artifacts (auto-generated, never commit)\n"
            ".bmad-assist/cache/\n"
            "*.meta.yaml\n"
            "*.tpl.xml\n"
        )

        console = MagicMock()
        check_gitignore_warning(tmp_path, None, console)
        # Should not print anything when gitignore is complete
        console.print.assert_not_called()


class TestEnsureProjectSetup:
    """Tests for ensure_project_setup orchestration."""

    def test_creates_bmad_assist_dir(self, tmp_path: Path) -> None:
        """Creates .bmad-assist directory on fresh project."""
        result = ensure_project_setup(tmp_path, console=Console(quiet=True))
        assert (tmp_path / ".bmad-assist").exists()
        assert (tmp_path / ".bmad-assist" / "cache").exists()

    def test_creates_bmad_config(self, tmp_path: Path) -> None:
        """Creates BMAD config if missing."""
        result = ensure_project_setup(tmp_path, console=Console(quiet=True))
        config_file = tmp_path / "_bmad" / "bmm" / "config.yaml"
        assert config_file.exists()
        assert result.config_created is True

    def test_skips_existing_bmad_config(self, tmp_path: Path) -> None:
        """Does not overwrite existing BMAD config."""
        config_dir = tmp_path / "_bmad" / "bmm"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.yaml"
        config_file.write_text("existing: true\n")

        result = ensure_project_setup(tmp_path, console=Console(quiet=True))
        assert result.config_created is False
        assert config_file.read_text() == "existing: true\n"

    def test_gitignore_not_updated_by_default(self, tmp_path: Path) -> None:
        """Gitignore not modified unless include_gitignore=True."""
        result = ensure_project_setup(tmp_path, include_gitignore=False, console=Console(quiet=True))
        assert result.gitignore_updated is False

    def test_gitignore_updated_when_requested(self, tmp_path: Path) -> None:
        """Gitignore updated when include_gitignore=True."""
        result = ensure_project_setup(tmp_path, include_gitignore=True, console=Console(quiet=True))
        assert (tmp_path / ".gitignore").exists()
        assert result.gitignore_updated is True

    def test_idempotent_second_run(self, tmp_path: Path) -> None:
        """Second run on same project creates no new artifacts."""
        # First run
        ensure_project_setup(tmp_path, include_gitignore=True, console=Console(quiet=True))

        # Second run
        result = ensure_project_setup(tmp_path, include_gitignore=True, console=Console(quiet=True))
        assert result.config_created is False
        assert result.gitignore_updated is False
        assert len(result.dirs_created) == 0


class TestSetupResult:
    """Tests for SetupResult dataclass."""

    def test_has_skipped_false_when_empty(self) -> None:
        """has_skipped is False when no skipped workflows."""
        result = SetupResult()
        assert result.has_skipped is False

    def test_has_skipped_true_when_skipped(self) -> None:
        """has_skipped is True when workflows skipped."""
        result = SetupResult(workflows_skipped=["dev-story"])
        assert result.has_skipped is True

    def test_has_skipped_false_when_only_copied(self) -> None:
        """has_skipped is False when only copied workflows."""
        result = SetupResult(workflows_copied=["dev-story", "create-story"])
        assert result.has_skipped is False


class TestAtomicCopyFile:
    """Tests for _atomic_copy_file error handling."""

    def test_temp_file_cleaned_on_write_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC9: Temp file cleaned up when write fails."""
        from bmad_assist.core.project_setup import SetupError, _atomic_copy_file

        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"
        src.write_text("content")

        # Mock os.write to fail
        def failing_write(fd: int, data: bytes) -> int:
            raise OSError("Disk full")

        monkeypatch.setattr("os.write", failing_write)

        with pytest.raises(SetupError, match="Failed to copy"):
            _atomic_copy_file(src, dst)

        # Verify no temp file left behind
        temp_path = dst.with_suffix(".txt.tmp")
        assert not temp_path.exists()

    def test_file_permissions_are_644(self, tmp_path: Path) -> None:
        """Copied files have 0o644 permissions (readable by all)."""
        from bmad_assist.core.project_setup import _atomic_copy_file

        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"
        src.write_text("content")

        _atomic_copy_file(src, dst)

        # Check permissions (masking with 0o777 to ignore setuid/setgid bits)
        mode = dst.stat().st_mode & 0o777
        assert mode == 0o644


class TestNonTTYBehavior:
    """Tests for non-interactive (CI) mode behavior."""

    def test_non_tty_returns_skip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC4: Non-TTY mode skips differing files without prompting."""
        from bmad_assist.core.project_setup import OverwriteDecision, _prompt_overwrite_batch

        # Mock stdin.isatty() to return False
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        differing = [(tmp_path / "a.txt", tmp_path / "b.txt")]
        console = MagicMock()

        result = _prompt_overwrite_batch(differing, console)

        assert result == OverwriteDecision.SKIP
        # Should print non-interactive message
        console.print.assert_called()
