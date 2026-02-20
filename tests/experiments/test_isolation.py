"""Tests for fixture isolation engine.

Tests for IsolationResult dataclass, FixtureIsolator class,
and IsolationError exception handling.
"""

import stat
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.core.exceptions import ConfigError, IsolationError
from bmad_assist.experiments.isolation import (
    DEFAULT_TIMEOUT_SECONDS,
    PROGRESS_BYTES_INTERVAL,
    PROGRESS_FILES_INTERVAL,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
    FixtureIsolator,
    IsolationResult,
)


class TestIsolationResult:
    """Tests for IsolationResult dataclass."""

    def test_create_isolation_result(self, tmp_path: Path) -> None:
        """Test IsolationResult creation with all fields."""
        source = tmp_path / "source"
        snapshot = tmp_path / "snapshot"

        result = IsolationResult(
            source_path=source,
            snapshot_path=snapshot,
            file_count=42,
            total_bytes=1_500_000,
            duration_seconds=2.5,
            verified=True,
        )

        assert result.source_path == source
        assert result.snapshot_path == snapshot
        assert result.file_count == 42
        assert result.total_bytes == 1_500_000
        assert result.duration_seconds == 2.5
        assert result.verified is True

    def test_isolation_result_frozen(self, tmp_path: Path) -> None:
        """Test IsolationResult is immutable."""
        result = IsolationResult(
            source_path=tmp_path / "source",
            snapshot_path=tmp_path / "snapshot",
            file_count=10,
            total_bytes=1000,
            duration_seconds=0.5,
            verified=True,
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            result.file_count = 20  # type: ignore[misc]

    def test_isolation_result_repr(self, tmp_path: Path) -> None:
        """Test IsolationResult __repr__ is human-readable."""
        result = IsolationResult(
            source_path=tmp_path / "source",
            snapshot_path=tmp_path / "snapshot",
            file_count=42,
            total_bytes=1_500_000,  # 1.43 MB
            duration_seconds=2.5,
            verified=True,
        )

        repr_str = repr(result)
        assert "files=42" in repr_str
        assert "1.4MB" in repr_str  # Approximate
        assert "2.5s" in repr_str
        assert "verified=True" in repr_str

    def test_isolation_result_repr_zero_bytes(self, tmp_path: Path) -> None:
        """Test IsolationResult __repr__ with zero bytes."""
        result = IsolationResult(
            source_path=tmp_path / "source",
            snapshot_path=tmp_path / "snapshot",
            file_count=0,
            total_bytes=0,
            duration_seconds=0.1,
            verified=False,
        )

        repr_str = repr(result)
        assert "files=0" in repr_str
        assert "0.0MB" in repr_str
        assert "verified=False" in repr_str


class TestFixtureIsolatorBasics:
    """Basic tests for FixtureIsolator class."""

    def test_isolator_creation(self, runs_dir: Path) -> None:
        """Test FixtureIsolator can be created."""
        isolator = FixtureIsolator(runs_dir)
        assert isolator._runs_dir == runs_dir

    def test_isolate_minimal_fixture(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test isolation of minimal fixture."""
        isolator = FixtureIsolator(runs_dir)

        result = isolator.isolate(minimal_fixture, "run-001")

        assert result.verified is True
        assert result.file_count == 2  # prd.md and architecture.md
        assert result.total_bytes > 0
        assert result.duration_seconds > 0
        assert result.snapshot_path == runs_dir / "run-001" / "fixture-snapshot"
        assert result.snapshot_path.exists()

        # Verify files were copied
        assert (result.snapshot_path / "docs" / "prd.md").exists()
        assert (result.snapshot_path / "docs" / "architecture.md").exists()

    def test_isolate_preserves_directory_structure(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test isolation preserves directory structure."""
        # Add nested directories
        nested = minimal_fixture / "deep" / "nested" / "path"
        nested.mkdir(parents=True)
        (nested / "file.md").write_text("# Deep file")

        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(minimal_fixture, "run-001")

        # Verify nested structure
        assert (result.snapshot_path / "deep" / "nested" / "path" / "file.md").exists()


class TestSkipPatterns:
    """Tests for skip pattern handling."""

    def test_skip_git_directory(
        self,
        runs_dir: Path,
        fixture_with_git: Path,
    ) -> None:
        """Test .git directory is skipped."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_with_git, "run-001")

        # .git should not exist in snapshot
        assert not (result.snapshot_path / ".git").exists()
        # But docs should be there
        assert (result.snapshot_path / "docs").exists()

    def test_skip_pycache_directory(
        self,
        runs_dir: Path,
        fixture_with_pycache: Path,
    ) -> None:
        """Test __pycache__ directory and .pyc files are skipped."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_with_pycache, "run-001")

        # __pycache__ should not exist
        assert not (result.snapshot_path / "src" / "__pycache__").exists()
        # But .py files should be there
        assert (result.snapshot_path / "src" / "module.py").exists()

    def test_skip_venv_directory(
        self,
        runs_dir: Path,
        fixture_with_venv: Path,
    ) -> None:
        """Test .venv directory is skipped."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_with_venv, "run-001")

        # .venv should not exist
        assert not (result.snapshot_path / ".venv").exists()

    def test_skip_node_modules_directory(
        self,
        runs_dir: Path,
        fixture_with_node_modules: Path,
    ) -> None:
        """Test node_modules directory is skipped."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_with_node_modules, "run-001")

        # node_modules should not exist
        assert not (result.snapshot_path / "node_modules").exists()

    def test_skip_pytest_cache_directory(
        self,
        runs_dir: Path,
        fixture_with_pytest_cache: Path,
    ) -> None:
        """Test .pytest_cache directory is skipped."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_with_pytest_cache, "run-001")

        # .pytest_cache should not exist
        assert not (result.snapshot_path / ".pytest_cache").exists()

    def test_dotfiles_are_copied(
        self,
        runs_dir: Path,
        fixture_with_dotfiles: Path,
    ) -> None:
        """Test dotfiles like .gitignore ARE copied."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_with_dotfiles, "run-001")

        # Dotfiles should be copied
        assert (result.snapshot_path / ".gitignore").exists()
        assert (result.snapshot_path / ".env.example").exists()
        assert (result.snapshot_path / ".editorconfig").exists()

    def test_skip_dirs_constant(self) -> None:
        """Test SKIP_DIRS contains expected patterns."""
        assert ".git" in SKIP_DIRS
        assert "__pycache__" in SKIP_DIRS
        assert ".venv" in SKIP_DIRS
        assert "node_modules" in SKIP_DIRS
        assert ".pytest_cache" in SKIP_DIRS

    def test_skip_extensions_constant(self) -> None:
        """Test SKIP_EXTENSIONS contains expected patterns."""
        assert ".pyc" in SKIP_EXTENSIONS
        assert ".pyo" in SKIP_EXTENSIONS


class TestEmptyDirectories:
    """Tests for empty directory handling."""

    def test_empty_directories_preserved(
        self,
        runs_dir: Path,
        fixture_with_empty_dirs: Path,
    ) -> None:
        """Test empty directories are preserved in snapshot."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_with_empty_dirs, "run-001")

        # Empty directories should exist
        assert (result.snapshot_path / "src").exists()
        assert (result.snapshot_path / "src").is_dir()
        assert (result.snapshot_path / "tests").exists()
        assert (result.snapshot_path / "tests" / "unit").exists()


class TestFilePreservation:
    """Tests for file metadata preservation."""

    def test_file_permissions_preserved(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test file permissions are preserved."""
        # Create file with specific permissions
        script = minimal_fixture / "script.sh"
        script.write_text("#!/bin/bash\necho hello")
        script.chmod(0o755)

        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(minimal_fixture, "run-001")

        copied_script = result.snapshot_path / "script.sh"
        assert copied_script.exists()
        mode = stat.S_IMODE(copied_script.stat().st_mode)
        # Check executable bit is preserved (at least for owner)
        assert mode & stat.S_IXUSR

    def test_file_timestamps_preserved(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test file timestamps are preserved (copy2 behavior)."""
        prd_file = minimal_fixture / "docs" / "prd.md"
        original_mtime = prd_file.stat().st_mtime

        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(minimal_fixture, "run-001")

        copied_file = result.snapshot_path / "docs" / "prd.md"
        copied_mtime = copied_file.stat().st_mtime

        # Timestamps should be preserved (within small epsilon for filesystem precision)
        assert abs(original_mtime - copied_mtime) < 1.0


class TestSymlinkHandling:
    """Tests for symlink handling."""

    def test_internal_symlink_dereferenced(
        self,
        runs_dir: Path,
        fixture_with_symlinks: Path,
    ) -> None:
        """Test internal symlink is dereferenced and content copied."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_with_symlinks, "run-001")

        # Internal symlink should become a regular file with dereferenced content
        link_path = result.snapshot_path / "docs" / "link_to_prd.md"
        assert link_path.exists()
        assert not link_path.is_symlink()  # Should NOT be a symlink
        assert link_path.is_file()  # Should be a regular file
        content = link_path.read_text()
        assert "Minimal PRD" in content

    def test_external_symlink_skipped(
        self,
        runs_dir: Path,
        fixture_with_symlinks: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test external symlink is skipped with warning."""
        isolator = FixtureIsolator(runs_dir)

        with caplog.at_level("WARNING"):
            result = isolator.isolate(fixture_with_symlinks, "run-001")

        # External symlink should be skipped
        assert not (result.snapshot_path / "external_link.txt").exists()
        assert "Skipping symlink pointing outside fixture" in caplog.text

    def test_broken_symlink_skipped(
        self,
        runs_dir: Path,
        fixture_with_symlinks: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test broken symlink is skipped with warning."""
        isolator = FixtureIsolator(runs_dir)

        with caplog.at_level("WARNING"):
            result = isolator.isolate(fixture_with_symlinks, "run-001")

        # Broken symlink should be skipped
        assert not (result.snapshot_path / "broken_link.txt").exists()
        assert "Skipping symlink" in caplog.text

    def test_no_symlinks_in_snapshot(
        self,
        runs_dir: Path,
        fixture_with_symlinks: Path,
    ) -> None:
        """Test no symlinks exist in snapshot after isolation."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_with_symlinks, "run-001")

        # Walk snapshot and verify no symlinks
        for path in result.snapshot_path.rglob("*"):
            assert not path.is_symlink(), f"Found symlink in snapshot: {path}"

    def test_internal_dir_symlink_dereferenced(
        self,
        runs_dir: Path,
        fixture_with_dir_symlink: Path,
    ) -> None:
        """Test internal directory symlink is dereferenced with contents copied."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_with_dir_symlink, "run-001")

        # The linked_src directory should exist and contain the dereferenced files
        linked_dir = result.snapshot_path / "linked_src"
        assert linked_dir.exists()
        assert linked_dir.is_dir()
        assert not linked_dir.is_symlink()

        # Files from the target directory should be present
        assert (linked_dir / "main.py").exists()
        assert (linked_dir / "utils.py").exists()

        # Original src directory should also exist
        src_dir = result.snapshot_path / "src"
        assert src_dir.exists()
        assert (src_dir / "main.py").exists()


class TestVerification:
    """Tests for copy verification."""

    def test_verification_passes_for_valid_copy(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test verification passes for valid copy."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(minimal_fixture, "run-001")

        assert result.verified is True

    def test_verification_checks_file_count(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test verification fails on file count mismatch."""
        isolator = FixtureIsolator(runs_dir)

        # Manually test the verification method
        source = minimal_fixture.resolve()
        snapshot = runs_dir / "run-001" / "fixture-snapshot"
        snapshot.mkdir(parents=True)

        # Copy only one file
        (snapshot / "docs").mkdir()
        (snapshot / "docs" / "prd.md").write_text("# PRD")

        # Verification should fail
        verified, reason = isolator._verify_copy(source, snapshot)
        assert verified is False
        assert "File count mismatch" in reason

    def test_verification_checks_total_size(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test verification fails on size mismatch."""
        isolator = FixtureIsolator(runs_dir)

        source = minimal_fixture.resolve()
        snapshot = runs_dir / "run-001" / "fixture-snapshot"
        snapshot.mkdir(parents=True)

        # Copy both files but with wrong content
        (snapshot / "docs").mkdir()
        (snapshot / "docs" / "prd.md").write_text("X")  # Wrong size
        (snapshot / "docs" / "architecture.md").write_text("Y")  # Wrong size

        verified, reason = isolator._verify_copy(source, snapshot)
        assert verified is False
        assert "Size mismatch" in reason

    def test_verification_requires_md_or_yaml_content(
        self,
        runs_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test verification fails if no .md or .yaml files."""
        fixture = tmp_path / "fixture"
        fixture.mkdir()
        (fixture / "file.txt").write_text("plain text")

        isolator = FixtureIsolator(runs_dir)

        # Copy
        snapshot = runs_dir / "run-001" / "fixture-snapshot"
        snapshot.mkdir(parents=True)
        (snapshot / "file.txt").write_text("plain text")

        verified, reason = isolator._verify_copy(fixture, snapshot)
        assert verified is False
        assert "No .md or .yaml files found" in reason


class TestErrorHandling:
    """Tests for error handling scenarios."""

    def test_error_source_not_exists(self, runs_dir: Path, tmp_path: Path) -> None:
        """Test ConfigError when source doesn't exist."""
        isolator = FixtureIsolator(runs_dir)
        nonexistent = tmp_path / "nonexistent"

        with pytest.raises(ConfigError) as exc_info:
            isolator.isolate(nonexistent, "run-001")

        assert "does not exist" in str(exc_info.value)

    def test_error_source_not_directory(
        self,
        runs_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test ConfigError when source is not a directory."""
        isolator = FixtureIsolator(runs_dir)
        file_path = tmp_path / "file.txt"
        file_path.write_text("not a directory")

        with pytest.raises(ConfigError) as exc_info:
            isolator.isolate(file_path, "run-001")

        assert "is not a directory" in str(exc_info.value)

    def test_error_target_already_exists(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test ConfigError when target directory already exists."""
        isolator = FixtureIsolator(runs_dir)

        # Create target first
        snapshot = runs_dir / "run-001" / "fixture-snapshot"
        snapshot.mkdir(parents=True)

        with pytest.raises(ConfigError) as exc_info:
            isolator.isolate(minimal_fixture, "run-001")

        assert "already exists" in str(exc_info.value)

    def test_error_only_skipped_content(
        self,
        runs_dir: Path,
        fixture_only_skipped: Path,
    ) -> None:
        """Test IsolationError when fixture has only skippable content."""
        isolator = FixtureIsolator(runs_dir)

        with pytest.raises(IsolationError) as exc_info:
            isolator.isolate(fixture_only_skipped, "run-001")

        assert "no copyable files" in str(exc_info.value)

    def test_error_run_id_with_path_traversal(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test ConfigError when run_id contains path traversal characters."""
        isolator = FixtureIsolator(runs_dir)

        # Test forward slash
        with pytest.raises(ConfigError) as exc_info:
            isolator.isolate(minimal_fixture, "run/../escape")
        assert "must not contain" in str(exc_info.value)

        # Test backslash
        with pytest.raises(ConfigError) as exc_info:
            isolator.isolate(minimal_fixture, "run\\escape")
        assert "must not contain" in str(exc_info.value)

        # Test double dot
        with pytest.raises(ConfigError) as exc_info:
            isolator.isolate(minimal_fixture, "..run")
        assert "must not contain" in str(exc_info.value)

    def test_cleanup_on_failure(
        self,
        runs_dir: Path,
        fixture_only_skipped: Path,
    ) -> None:
        """Test partial snapshot is cleaned up on failure."""
        isolator = FixtureIsolator(runs_dir)
        snapshot = runs_dir / "run-001" / "fixture-snapshot"

        with pytest.raises(IsolationError):
            isolator.isolate(fixture_only_skipped, "run-001")

        # Snapshot directory should be cleaned up
        assert not snapshot.exists()

    def test_isolation_error_has_context(
        self,
        runs_dir: Path,
        fixture_only_skipped: Path,
    ) -> None:
        """Test IsolationError includes source and snapshot paths."""
        isolator = FixtureIsolator(runs_dir)

        with pytest.raises(IsolationError) as exc_info:
            isolator.isolate(fixture_only_skipped, "run-001")

        error = exc_info.value
        assert error.source_path is not None
        assert error.snapshot_path is not None


class TestTimeoutHandling:
    """Tests for timeout handling."""

    def test_timeout_parameter_default(self) -> None:
        """Test default timeout constant."""
        assert DEFAULT_TIMEOUT_SECONDS == 300  # 5 minutes

    def test_timeout_raises_isolation_error(
        self,
        runs_dir: Path,
        large_fixture: Path,
    ) -> None:
        """Test timeout raises IsolationError."""
        isolator = FixtureIsolator(runs_dir)

        # Mock time.monotonic to simulate timeout
        start_time = time.monotonic()
        call_count = 0

        def mock_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            # First call is start time, subsequent calls exceed timeout
            if call_count <= 1:
                return start_time
            return start_time + 10  # 10 seconds elapsed

        with patch("bmad_assist.experiments.isolation.time.monotonic", mock_monotonic):
            with pytest.raises(IsolationError) as exc_info:
                isolator.isolate(large_fixture, "run-001", timeout_seconds=5)

        assert "Timeout" in str(exc_info.value)


class TestProgressLogging:
    """Tests for progress logging."""

    def test_progress_intervals_defined(self) -> None:
        """Test progress interval constants are defined."""
        assert PROGRESS_FILES_INTERVAL == 100
        assert PROGRESS_BYTES_INTERVAL == 10 * 1024 * 1024  # 10MB

    def test_large_fixture_logs_progress(
        self,
        runs_dir: Path,
        large_fixture: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test large fixture isolation logs progress."""
        isolator = FixtureIsolator(runs_dir)

        with caplog.at_level("DEBUG"):
            result = isolator.isolate(large_fixture, "run-001")

        # Should have logged progress
        assert "Copy progress:" in caplog.text
        assert result.file_count > 1000


class TestIntegration:
    """Integration tests with real fixture scenarios."""

    def test_isolate_fixture_twice_different_runs(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test same fixture can be isolated to different runs."""
        isolator = FixtureIsolator(runs_dir)

        result1 = isolator.isolate(minimal_fixture, "run-001")
        result2 = isolator.isolate(minimal_fixture, "run-002")

        assert result1.snapshot_path != result2.snapshot_path
        assert result1.snapshot_path.exists()
        assert result2.snapshot_path.exists()

    def test_source_fixture_unchanged_after_isolation(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test source fixture is not modified by isolation."""
        # Record original state
        original_files = list(minimal_fixture.rglob("*"))
        original_content = {}
        for f in original_files:
            if f.is_file():
                original_content[f] = f.read_bytes()

        isolator = FixtureIsolator(runs_dir)
        isolator.isolate(minimal_fixture, "run-001")

        # Verify source unchanged
        current_files = list(minimal_fixture.rglob("*"))
        assert len(original_files) == len(current_files)

        for f in current_files:
            if f.is_file():
                assert f.read_bytes() == original_content[f]

    def test_complex_fixture_with_multiple_skip_patterns(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test fixture with multiple skip patterns."""
        # Add various skipped content
        (minimal_fixture / ".git").mkdir()
        (minimal_fixture / ".git" / "config").write_text("[core]")

        (minimal_fixture / "src").mkdir()
        (minimal_fixture / "src" / "__pycache__").mkdir()
        (minimal_fixture / "src" / "__pycache__" / "test.pyc").write_bytes(b"code")
        (minimal_fixture / "src" / "main.py").write_text("print('hello')")

        (minimal_fixture / ".venv").mkdir()
        (minimal_fixture / ".venv" / "bin").mkdir()
        (minimal_fixture / ".venv" / "bin" / "python").write_bytes(b"bin")

        (minimal_fixture / "node_modules").mkdir()
        (minimal_fixture / "node_modules" / "pkg").mkdir()
        (minimal_fixture / "node_modules" / "pkg" / "index.js").write_text("js")

        # Add dotfiles that should be copied
        (minimal_fixture / ".gitignore").write_text("*.pyc")

        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(minimal_fixture, "run-001")

        # Verify skip patterns applied
        assert not (result.snapshot_path / ".git").exists()
        assert not (result.snapshot_path / "src" / "__pycache__").exists()
        assert not (result.snapshot_path / ".venv").exists()
        assert not (result.snapshot_path / "node_modules").exists()

        # Verify kept content
        assert (result.snapshot_path / "docs" / "prd.md").exists()
        assert (result.snapshot_path / "src" / "main.py").exists()
        assert (result.snapshot_path / ".gitignore").exists()


class TestIsolationErrorException:
    """Tests for IsolationError exception class."""

    def test_isolation_error_creation(self) -> None:
        """Test IsolationError can be created with message."""
        error = IsolationError("Test error")
        assert str(error) == "Test error"
        assert error.source_path is None
        assert error.snapshot_path is None

    def test_isolation_error_with_paths(self, tmp_path: Path) -> None:
        """Test IsolationError with source and snapshot paths."""
        source = tmp_path / "source"
        snapshot = tmp_path / "snapshot"

        error = IsolationError(
            "Copy failed",
            source_path=source,
            snapshot_path=snapshot,
        )

        assert error.source_path == source
        assert error.snapshot_path == snapshot
        assert "Copy failed" in str(error)

    def test_isolation_error_inherits_from_bmad_error(self) -> None:
        """Test IsolationError is a BmadAssistError."""
        from bmad_assist.core.exceptions import BmadAssistError

        error = IsolationError("test")
        assert isinstance(error, BmadAssistError)


class TestTarExtraction:
    """Tests for tar archive extraction."""

    @pytest.fixture
    def fixture_with_tar(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create a fixture directory and corresponding tar archive."""
        import tarfile

        fixtures_dir = tmp_path / "fixtures"
        fixtures_dir.mkdir()

        # Create fixture content
        fixture_dir = fixtures_dir / "test-fixture"
        fixture_dir.mkdir()
        (fixture_dir / "docs").mkdir()
        (fixture_dir / "docs" / "prd.md").write_text("# Test PRD")
        (fixture_dir / "config.yaml").write_text("name: test")

        # Create tar archive
        tar_path = fixtures_dir / "test-fixture.tar"
        with tarfile.open(tar_path, "w") as tar:
            for item in fixture_dir.rglob("*"):
                arcname = item.relative_to(fixture_dir)
                tar.add(item, arcname=str(arcname))

        return fixture_dir, tar_path

    def test_isolate_prefers_tar_over_directory(
        self,
        runs_dir: Path,
        fixture_with_tar: tuple[Path, Path],
    ) -> None:
        """Test that tar archive is preferred over directory when both exist."""
        fixture_dir, tar_path = fixture_with_tar

        # Modify directory content (to verify tar is used, not directory)
        (fixture_dir / "docs" / "prd.md").write_text("# Modified PRD")

        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_dir, "run-001")

        # Verify tar was used (original content, not modified)
        prd_content = (result.snapshot_path / "docs" / "prd.md").read_text()
        assert prd_content == "# Test PRD"
        assert result.source_path == tar_path

    def test_isolate_from_tar_only(
        self,
        runs_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test isolation when only tar exists (no directory)."""
        import tarfile

        fixtures_dir = tmp_path / "fixtures"
        fixtures_dir.mkdir()

        # Create tar without directory
        tar_path = fixtures_dir / "tar-only.tar"
        with tarfile.open(tar_path, "w") as tar:
            # Add content directly to tar
            import io

            prd_content = b"# TAR Only PRD"
            prd_info = tarfile.TarInfo(name="docs/prd.md")
            prd_info.size = len(prd_content)
            tar.addfile(prd_info, io.BytesIO(prd_content))

        # Try to isolate from non-existent directory path
        fixture_dir = fixtures_dir / "tar-only"  # Doesn't exist

        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_dir, "run-001")

        assert result.source_path == tar_path
        assert (result.snapshot_path / "docs" / "prd.md").exists()
        assert (result.snapshot_path / "docs" / "prd.md").read_text() == "# TAR Only PRD"

    def test_isolate_from_tar_gz(
        self,
        runs_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test isolation from gzip-compressed tar archive."""
        import tarfile

        fixtures_dir = tmp_path / "fixtures"
        fixtures_dir.mkdir()

        # Create tar.gz
        tar_path = fixtures_dir / "compressed.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            import io

            content = b"# Compressed PRD"
            info = tarfile.TarInfo(name="docs/prd.md")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        fixture_dir = fixtures_dir / "compressed"

        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_dir, "run-001")

        assert result.source_path == tar_path
        assert (result.snapshot_path / "docs" / "prd.md").read_text() == "# Compressed PRD"

    def test_isolate_from_tgz(
        self,
        runs_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test isolation from .tgz archive (alias for tar.gz)."""
        import tarfile

        fixtures_dir = tmp_path / "fixtures"
        fixtures_dir.mkdir()

        # Create .tgz
        tar_path = fixtures_dir / "alias.tgz"
        with tarfile.open(tar_path, "w:gz") as tar:
            import io

            content = b"# TGZ PRD"
            info = tarfile.TarInfo(name="docs/prd.md")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        fixture_dir = fixtures_dir / "alias"

        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_dir, "run-001")

        assert result.source_path == tar_path

    def test_tar_format_priority(
        self,
        runs_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that .tar is preferred over .tar.gz when both exist."""
        import tarfile

        fixtures_dir = tmp_path / "fixtures"
        fixtures_dir.mkdir()

        # Create both .tar and .tar.gz with different content
        tar_path = fixtures_dir / "multi.tar"
        with tarfile.open(tar_path, "w") as tar:
            import io

            content = b"# From .tar"
            info = tarfile.TarInfo(name="docs/prd.md")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        tar_gz_path = fixtures_dir / "multi.tar.gz"
        with tarfile.open(tar_gz_path, "w:gz") as tar:
            import io

            content = b"# From .tar.gz"
            info = tarfile.TarInfo(name="docs/prd.md")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        fixture_dir = fixtures_dir / "multi"

        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(fixture_dir, "run-001")

        # .tar should be preferred (faster, no decompression)
        assert result.source_path == tar_path
        assert (result.snapshot_path / "docs" / "prd.md").read_text() == "# From .tar"

    def test_tar_path_traversal_attack_blocked(
        self,
        runs_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test that tar archives with path traversal attacks are rejected."""
        import tarfile

        fixtures_dir = tmp_path / "fixtures"
        fixtures_dir.mkdir()

        # Create malicious tar with path traversal
        tar_path = fixtures_dir / "malicious.tar"
        with tarfile.open(tar_path, "w") as tar:
            import io

            content = b"malicious"
            info = tarfile.TarInfo(name="../../../etc/passwd")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        fixture_dir = fixtures_dir / "malicious"

        isolator = FixtureIsolator(runs_dir)

        with pytest.raises(IsolationError) as exc_info:
            isolator.isolate(fixture_dir, "run-001")

        assert "unsafe path" in str(exc_info.value)

    def test_fallback_to_directory_when_no_tar(
        self,
        runs_dir: Path,
        minimal_fixture: Path,
    ) -> None:
        """Test fallback to directory copy when no tar archive exists."""
        isolator = FixtureIsolator(runs_dir)
        result = isolator.isolate(minimal_fixture, "run-001")

        # Source should be the directory, not a tar file
        assert result.source_path == minimal_fixture
        assert result.verified is True
