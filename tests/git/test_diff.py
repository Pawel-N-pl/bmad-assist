"""Tests for the git diff utilities module.

Tests the P0/P1 fixes for the 92% false positive rate in code reviews:
- P0: Path filtering (excludes cache, metadata, node_modules)
- P0: Merge-base detection (handles merge commits correctly)
- P1: Diff quality validation (warns if too much garbage)
"""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from bmad_assist.git.diff import (
    DEFAULT_EXCLUDE_PATTERNS,
    DiffQualityError,
    DiffValidationResult,
    _classify_file_priority,
    _prioritize_diff_sections,
    capture_filtered_diff,
    extract_files_from_diff,
    get_merge_base,
    get_validated_diff,
    validate_diff_quality,
)


class TestMergeBaseDetection:
    """Tests for merge-base detection (P0)."""

    def test_detects_merge_commit_uses_first_parent(self, tmp_path: Path) -> None:
        """For merge commits, uses first parent as base."""
        with patch("subprocess.run") as mock_run:
            # Mock git rev-parse HEAD^@ returning multiple parents
            mock_parents = Mock()
            mock_parents.returncode = 0
            mock_parents.stdout = "abc123\ndef456"

            mock_run.return_value = mock_parents

            result = get_merge_base(tmp_path)

        assert result == "abc123"

    def test_regular_commit_finds_merge_base_with_main(self, tmp_path: Path) -> None:
        """For regular commits, finds merge-base with main branch."""
        with patch("subprocess.run") as mock_run:
            # First call: rev-parse HEAD^@ returns single parent
            mock_parents = Mock()
            mock_parents.returncode = 0
            mock_parents.stdout = "single_parent"

            # Second call: rev-parse --verify refs/heads/main succeeds
            mock_verify = Mock()
            mock_verify.returncode = 0

            # Third call: merge-base main HEAD returns base
            mock_base = Mock()
            mock_base.returncode = 0
            mock_base.stdout = "merge_base_sha"

            mock_run.side_effect = [mock_parents, mock_verify, mock_base]

            result = get_merge_base(tmp_path)

        assert result == "merge_base_sha"

    def test_fallback_to_head_tilde_1_when_no_main(self, tmp_path: Path) -> None:
        """Falls back to HEAD~1 when main branch not found."""
        with patch("subprocess.run") as mock_run:
            # rev-parse HEAD^@ returns single parent
            mock_parents = Mock()
            mock_parents.returncode = 0
            mock_parents.stdout = "single_parent"

            # All branch verifications fail
            mock_fail = Mock()
            mock_fail.returncode = 128

            # symbolic-ref also fails
            mock_sym_fail = Mock()
            mock_sym_fail.returncode = 128

            mock_run.side_effect = [
                mock_parents,
                mock_fail,  # main
                mock_fail,  # master
                mock_fail,  # develop
                mock_sym_fail,  # symbolic-ref
            ]

            result = get_merge_base(tmp_path)

        assert result == "HEAD~1"


class TestPathFiltering:
    """Tests for path filtering in diff (P0)."""

    def test_default_exclude_patterns_include_cache_files(self) -> None:
        """Default exclude patterns include cache, metadata, and BMAD artifact files."""
        assert "*.cache" in DEFAULT_EXCLUDE_PATTERNS
        assert "*.meta.yaml" in DEFAULT_EXCLUDE_PATTERNS
        assert ".bmad-assist/*" in DEFAULT_EXCLUDE_PATTERNS
        assert "_bmad-output/*" in DEFAULT_EXCLUDE_PATTERNS
        assert "node_modules/*" in DEFAULT_EXCLUDE_PATTERNS
        assert "__pycache__/*" in DEFAULT_EXCLUDE_PATTERNS

    def test_capture_filtered_diff_excludes_garbage(self, tmp_path: Path) -> None:
        """capture_filtered_diff excludes cache and metadata files."""
        with (
            patch("subprocess.run") as mock_run,
            patch("bmad_assist.git.diff.get_merge_base") as mock_base,
        ):
            mock_base.return_value = "HEAD~1"

            mock_diff = Mock()
            mock_diff.returncode = 0
            mock_diff.stdout = "diff --git a/src/main.py b/src/main.py\n+code"

            mock_run.return_value = mock_diff

            result = capture_filtered_diff(tmp_path)

        # Verify pathspec exclusions are in the command
        call_args = mock_run.call_args[0][0]
        assert any(":(exclude)" in arg for arg in call_args)
        assert "--no-ext-diff" in call_args
        assert "<!-- GIT_DIFF_START -->" in result


class TestDiffQualityValidation:
    """Tests for diff quality validation (P1)."""

    def test_validate_empty_diff_is_valid(self) -> None:
        """Empty diff is valid (nothing to review)."""
        result = validate_diff_quality("")
        assert result.is_valid is True
        assert result.total_files == 0

    def test_validate_source_only_diff_is_valid(self) -> None:
        """Diff with only source files is valid."""
        diff_content = """
 src/main.py | 42 +++
 tests/test_main.py | 10 +
 2 files changed
"""
        result = validate_diff_quality(diff_content)
        assert result.is_valid is True
        assert result.source_files == 2
        assert result.garbage_files == 0
        assert result.garbage_ratio == 0.0

    def test_validate_high_garbage_ratio_is_invalid(self) -> None:
        """Diff with >30% garbage files is invalid."""
        diff_content = """
 src/main.py | 10 +
 file.cache | 100 +++
 data.meta.yaml | 50 ++
 node_modules/pkg/index.js | 200 ++++
 4 files changed
"""
        result = validate_diff_quality(diff_content, max_garbage_ratio=0.3)
        assert result.is_valid is False
        assert result.garbage_ratio > 0.3
        assert len(result.issues) > 0

    def test_validate_only_garbage_files_is_invalid(self) -> None:
        """Diff with only garbage files (0 source files) is invalid."""
        diff_content = """
 .bmad-assist/cache/template.cache | 100 +++
 __pycache__/module.pyc | 50 ++
 2 files changed
"""
        result = validate_diff_quality(diff_content)
        assert result.is_valid is False
        assert result.source_files == 0
        assert "No source files in diff" in str(result.issues)


class TestFileExtraction:
    """Tests for file extraction from diff content."""

    def test_extract_files_from_stat_line(self) -> None:
        """Extracts files from git diff --stat output."""
        diff_content = """
 src/compiler.py     | 42 +++
 tests/test_comp.py | 25 ++++
 2 files changed
"""
        files = extract_files_from_diff(diff_content)
        assert "src/compiler.py" in files
        assert "tests/test_comp.py" in files

    def test_extract_files_from_diff_header(self) -> None:
        """Extracts files from diff --git header."""
        diff_content = """
diff --git a/src/main.py b/src/main.py
index abc123..def456 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,5 +1,6 @@
+new line
"""
        files = extract_files_from_diff(diff_content)
        assert "src/main.py" in files

    def test_extract_handles_rename(self) -> None:
        """Handles renamed files (old.py => new.py)."""
        diff_content = """
 old.py => new.py | 5 +++--
 1 file changed
"""
        files = extract_files_from_diff(diff_content)
        assert "new.py" in files


class TestValidatedDiff:
    """Tests for the combined validated diff function."""

    def test_get_validated_diff_returns_diff_and_validation(self, tmp_path: Path) -> None:
        """get_validated_diff returns both diff content and validation result."""
        with patch("bmad_assist.git.diff.capture_filtered_diff") as mock_capture:
            mock_capture.return_value = (
                "<!-- GIT_DIFF_START -->\nsrc/main.py | 10 +\n<!-- GIT_DIFF_END -->"
            )

            diff, validation = get_validated_diff(tmp_path)

        assert "GIT_DIFF_START" in diff
        assert isinstance(validation, DiffValidationResult)
        assert validation.is_valid is True

    def test_get_validated_diff_raises_on_invalid_when_requested(self, tmp_path: Path) -> None:
        """get_validated_diff raises DiffQualityError when raise_on_invalid=True."""
        with patch("bmad_assist.git.diff.capture_filtered_diff") as mock_capture:
            # Return garbage-heavy diff
            mock_capture.return_value = """<!-- GIT_DIFF_START -->
 file.cache | 100 +++
 data.meta.yaml | 50 ++
 node_modules/pkg/index.js | 200 ++++
<!-- GIT_DIFF_END -->"""

            with pytest.raises(DiffQualityError) as exc_info:
                get_validated_diff(tmp_path, raise_on_invalid=True)

            assert exc_info.value.validation.is_valid is False

    def test_get_validated_diff_warns_but_continues_by_default(self, tmp_path: Path) -> None:
        """get_validated_diff warns but doesn't raise by default."""
        with patch("bmad_assist.git.diff.capture_filtered_diff") as mock_capture:
            # Return garbage-heavy diff
            mock_capture.return_value = """<!-- GIT_DIFF_START -->
 file.cache | 100 +++
 data.meta.yaml | 50 ++
 node_modules/pkg/index.js | 200 ++++
<!-- GIT_DIFF_END -->"""

            # Should not raise
            diff, validation = get_validated_diff(tmp_path, raise_on_invalid=False)

        assert validation.is_valid is False
        assert diff != ""  # Still returns the diff


class TestClassifyFilePriority:
    """Tests for _classify_file_priority()."""

    def test_source_file_gets_priority_0(self) -> None:
        """Source code files should get highest priority (0)."""
        assert _classify_file_priority("src/lib/store.ts") == 0
        assert _classify_file_priority("app/main.py") == 0
        assert _classify_file_priority("lib/handler.go") == 0
        assert _classify_file_priority("src/Component.svelte") == 0
        assert _classify_file_priority("src/App.vue") == 0

    def test_test_file_gets_priority_1(self) -> None:
        """Test files should get medium priority (1)."""
        assert _classify_file_priority("tests/test_main.py") == 1
        assert _classify_file_priority("src/lib/store.test.ts") == 1
        assert _classify_file_priority("tests/e2e/flow.spec.ts") == 1
        assert _classify_file_priority("__tests__/app.js") == 1

    def test_config_file_gets_priority_2(self) -> None:
        """Config files should get low priority (2)."""
        assert _classify_file_priority("package.json") == 2
        assert _classify_file_priority("tsconfig.json") == 2
        assert _classify_file_priority("config.yaml") == 2

    def test_unknown_file_gets_priority_3(self) -> None:
        """Unknown file types should get lowest priority (3)."""
        assert _classify_file_priority("Dockerfile") == 3
        assert _classify_file_priority("LICENSE") == 3


class TestPrioritizeDiffSections:
    """Tests for _prioritize_diff_sections()."""

    def test_source_files_sorted_before_config(self) -> None:
        """Source code diff sections should appear before config sections."""
        patch_content = (
            "diff --git a/config.yaml b/config.yaml\n"
            "--- a/config.yaml\n"
            "+++ b/config.yaml\n"
            "+setting: value\n"
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "+import os\n"
        )

        result = _prioritize_diff_sections(patch_content)

        # src/main.py (priority 0) should appear before config.yaml (priority 2)
        main_pos = result.find("src/main.py")
        config_pos = result.find("config.yaml")
        assert main_pos < config_pos

    def test_source_before_test_before_config(self) -> None:
        """Full priority ordering: source > test > config."""
        patch_content = (
            "diff --git a/setup.yaml b/setup.yaml\n"
            "+config\n"
            "diff --git a/tests/test_app.py b/tests/test_app.py\n"
            "+test code\n"
            "diff --git a/src/app.py b/src/app.py\n"
            "+source code\n"
        )

        result = _prioritize_diff_sections(patch_content)

        src_pos = result.find("src/app.py")
        test_pos = result.find("tests/test_app.py")
        cfg_pos = result.find("setup.yaml")
        assert src_pos < test_pos < cfg_pos

    def test_empty_input_returns_empty(self) -> None:
        """Empty patch content should return empty."""
        assert _prioritize_diff_sections("") == ""
        assert _prioritize_diff_sections("   \n  ") == "   \n  "

    def test_single_section_unchanged(self) -> None:
        """A single diff section should be returned unchanged."""
        patch = (
            "diff --git a/src/main.py b/src/main.py\n"
            "+import os\n"
        )
        assert _prioritize_diff_sections(patch) == patch


class TestGarbagePatternsIncludeBmadPaths:
    """Tests that garbage detection catches .bmad-assist and _bmad-output."""

    def test_bmad_assist_state_is_garbage(self) -> None:
        """Files in .bmad-assist/ should be detected as garbage."""
        diff_content = " .bmad-assist/state.yaml | 6 +-\n 1 file changed\n"
        result = validate_diff_quality(diff_content)
        assert result.garbage_files == 1
        assert result.source_files == 0

    def test_bmad_output_benchmarks_are_garbage(self) -> None:
        """Files in _bmad-output/ should be detected as garbage."""
        diff_content = (
            " _bmad-output/implementation-artifacts/benchmarks/eval.yaml | 130 +++\n"
            " src/main.py | 10 +\n"
            " 2 files changed\n"
        )
        result = validate_diff_quality(diff_content)
        assert result.garbage_files == 1
        assert result.source_files == 1


# =============================================================================
# Configurable Garbage Patterns (Fix #4)
# =============================================================================
#
# validate_diff_quality() must accept user-configurable extra patterns and
# whitelist exclusions so users can control which files count as garbage.


class TestConfigurableGarbagePatterns:
    """User-supplied garbage patterns and exclude paths."""

    def test_exclude_paths_whitelist_default_garbage(self) -> None:
        """An exclude_paths entry must override default garbage classification.

        The original report: ``.opencode/package-lock.json`` is a tracked
        file in the user's repo but matches the default ``package-lock.json$``
        pattern. With it whitelisted, it should count as a source file.
        """
        diff_content = (
            " .opencode/package-lock.json | 200 +++++++++++++++++\n"
            " src/main.py | 5 +-\n"
            " 2 files changed\n"
        )
        result = validate_diff_quality(
            diff_content,
            exclude_paths=[".opencode/package-lock.json"],
        )
        assert result.garbage_files == 0
        assert result.source_files == 2
        assert result.is_valid is True

    def test_exclude_paths_glob_pattern(self) -> None:
        """exclude_paths supports fnmatch glob patterns."""
        diff_content = (
            " vendor/foo.lock | 10 +\n"
            " vendor/bar.lock | 5 +\n"
            " src/main.py | 1 +\n"
        )
        result = validate_diff_quality(
            diff_content,
            exclude_paths=["vendor/*.lock"],
        )
        assert result.garbage_files == 0
        assert result.source_files == 3

    def test_exclude_paths_basename_match(self) -> None:
        """Bare basenames in exclude_paths should match by suffix."""
        diff_content = (
            " a/b/c/special.lock | 3 +\n"
            " src/main.py | 1 +\n"
        )
        # Bare "special.lock" without glob metachars should match by
        # path.endswith("/special.lock").
        result = validate_diff_quality(
            diff_content,
            exclude_paths=["special.lock"],
        )
        assert result.garbage_files == 0

    def test_extra_garbage_patterns_appended(self) -> None:
        """extra_garbage_patterns must be appended to the default list."""
        diff_content = (
            " src/generated/api.ts | 500 +++++\n"
            " src/main.py | 5 +-\n"
        )
        # Without extra: api.ts is a source file
        baseline = validate_diff_quality(diff_content)
        assert baseline.garbage_files == 0
        # With extra pattern: api.ts becomes garbage
        with_extra = validate_diff_quality(
            diff_content,
            extra_garbage_patterns=[r"src/generated/"],
        )
        assert with_extra.garbage_files == 1
        assert with_extra.source_files == 1

    def test_exclude_takes_priority_over_extra_patterns(self) -> None:
        """exclude_paths is a whitelist override over extra_garbage_patterns."""
        diff_content = " src/generated/api.ts | 1 +\n src/main.py | 1 +\n"
        result = validate_diff_quality(
            diff_content,
            extra_garbage_patterns=[r"src/generated/"],
            exclude_paths=["src/generated/api.ts"],
        )
        # Exclude wins → counted as source.
        assert result.garbage_files == 0
        assert result.source_files == 2

    def test_default_behavior_unchanged_without_overrides(self) -> None:
        """No new params → behavior matches the legacy hardcoded list."""
        diff_content = (
            " .bmad-assist/state.yaml | 6 +-\n"
            " package-lock.json | 100 +\n"
            " src/main.py | 5 +-\n"
        )
        result = validate_diff_quality(diff_content)
        assert result.garbage_files == 2
        assert result.source_files == 1


class TestGitConfigModel:
    """GitConfig is wired through to the main Config and validates."""

    def test_default_git_config_has_zero_overrides(self) -> None:
        """Default GitConfig has empty exclude/extra lists and 0.3 ratio."""
        from bmad_assist.core.config.models.features import GitConfig

        cfg = GitConfig()
        assert cfg.garbage_exclude_paths == ()
        assert cfg.garbage_extra_patterns == ()
        assert cfg.max_garbage_ratio == 0.3

    def test_git_config_round_trip(self) -> None:
        """Building from dict preserves provided values."""
        from bmad_assist.core.config.models.features import GitConfig

        cfg = GitConfig(
            garbage_exclude_paths=(".opencode/package-lock.json",),
            garbage_extra_patterns=(r"^vendor/",),
            max_garbage_ratio=0.5,
        )
        assert ".opencode/package-lock.json" in cfg.garbage_exclude_paths
        assert r"^vendor/" in cfg.garbage_extra_patterns
        assert cfg.max_garbage_ratio == 0.5

    def test_main_config_exposes_git_section(self) -> None:
        """main.Config aggregates GitConfig under .git."""
        from bmad_assist.core.config.models.features import GitConfig
        from bmad_assist.core.config.models.main import Config
        from bmad_assist.core.config.models.providers import (
            MasterProviderConfig,
            ProviderConfig,
        )

        config = Config(
            providers=ProviderConfig(
                master=MasterProviderConfig(provider="claude", model="opus")
            )
        )
        assert isinstance(config.git, GitConfig)
        assert config.git.max_garbage_ratio == 0.3
