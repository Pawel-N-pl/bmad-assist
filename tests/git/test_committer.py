"""Tests for git auto-commit scoping (Task #21).

Covers:
- stage_all_changes accepts an explicit path list and uses
  ``git add -- <paths>`` instead of ``git add -A``.
- BMAD_GIT_STAGE_ALL escape hatch preserves legacy ``git add -A``.
- Empty path list is a no-op (returns True without running git).
- Large-commit warning fires above the configured threshold.
- Threshold env var parsing (default, explicit, disabled, invalid).
- auto_commit_phase passes the filtered list to stage_all_changes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from bmad_assist.core.state import Phase
from bmad_assist.git.committer import (
    _DEFAULT_LARGE_COMMIT_THRESHOLD,
    _get_large_commit_threshold,
    _should_force_stage_all,
    auto_commit_phase,
    stage_all_changes,
)

# =============================================================================
# stage_all_changes — path-scoped staging
# =============================================================================


class TestStageAllChangesScoped:
    """stage_all_changes scopes to explicit paths when provided."""

    def test_explicit_paths_uses_add_dash_dash(self, tmp_path: Path) -> None:
        """When paths given, uses ``git add -- <paths>`` not ``git add -A``."""
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (0, "", "")
            ok = stage_all_changes(tmp_path, paths=["src/a.py", "src/b.py"])

        assert ok is True
        assert mock_run.call_count == 1
        args, _kwargs = mock_run.call_args
        git_args = args[0]
        # Must use explicit paths with the -- separator.
        assert git_args == ["add", "--", "src/a.py", "src/b.py"]

    def test_paths_none_falls_back_to_add_all(self, tmp_path: Path) -> None:
        """paths=None → legacy ``git add -A`` behavior."""
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (0, "", "")
            ok = stage_all_changes(tmp_path, paths=None)

        assert ok is True
        args, _ = mock_run.call_args
        assert args[0] == ["add", "-A"]

    def test_no_paths_arg_defaults_to_add_all(self, tmp_path: Path) -> None:
        """No paths kwarg → legacy behavior (backward compat for callers)."""
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (0, "", "")
            ok = stage_all_changes(tmp_path)

        assert ok is True
        args, _ = mock_run.call_args
        assert args[0] == ["add", "-A"]

    def test_empty_path_list_is_noop(self, tmp_path: Path) -> None:
        """Empty list → don't invoke git at all; return True."""
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            ok = stage_all_changes(tmp_path, paths=[])

        assert ok is True
        mock_run.assert_not_called()

    def test_escape_hatch_forces_add_all(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """BMAD_GIT_STAGE_ALL=1 → legacy ``git add -A`` even when paths given."""
        monkeypatch.setenv("BMAD_GIT_STAGE_ALL", "1")
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (0, "", "")
            ok = stage_all_changes(tmp_path, paths=["only/a.py"])

        assert ok is True
        args, _ = mock_run.call_args
        # Escape hatch takes precedence — ignores the supplied paths.
        assert args[0] == ["add", "-A"]

    def test_escape_hatch_non_unity_value_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Only ``"1"`` activates the escape hatch; other values ignored."""
        monkeypatch.setenv("BMAD_GIT_STAGE_ALL", "true")
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (0, "", "")
            stage_all_changes(tmp_path, paths=["a.py"])

        args, _ = mock_run.call_args
        assert args[0] == ["add", "--", "a.py"]  # scoped (not forced all)

    def test_git_failure_returns_false(self, tmp_path: Path) -> None:
        """Non-zero git exit code → return False, no exception."""
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (128, "", "fatal: pathspec 'bad' did not match")
            ok = stage_all_changes(tmp_path, paths=["bad.py"])

        assert ok is False

    def test_paths_with_dash_prefix_safe_via_separator(
        self, tmp_path: Path
    ) -> None:
        """``--`` separator protects against paths that start with ``-``.

        Without the ``--``, a path like ``-rf`` would be parsed as a
        git flag. Regression guard for that concern.
        """
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (0, "", "")
            stage_all_changes(tmp_path, paths=["-rf", "weird-file.py"])

        args, _ = mock_run.call_args
        # ``--`` appears immediately after ``add`` so git treats
        # everything after as paths.
        assert args[0][0:2] == ["add", "--"]
        assert "-rf" in args[0]


# =============================================================================
# Threshold helpers
# =============================================================================


class TestLargeCommitThreshold:
    """_get_large_commit_threshold parses env var with safe fallbacks."""

    def test_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unset env var → module default threshold."""
        monkeypatch.delenv("BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD", raising=False)
        assert _get_large_commit_threshold() == _DEFAULT_LARGE_COMMIT_THRESHOLD

    def test_explicit_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Numeric env var → used verbatim."""
        monkeypatch.setenv("BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD", "25")
        assert _get_large_commit_threshold() == 25

    def test_zero_disables_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """0 is a valid value and disables the warning."""
        monkeypatch.setenv("BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD", "0")
        assert _get_large_commit_threshold() == 0

    def test_negative_clamped_to_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative values are treated as 'disabled' (clamped to 0)."""
        monkeypatch.setenv("BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD", "-5")
        assert _get_large_commit_threshold() == 0

    def test_invalid_value_falls_back_to_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Non-integer env var → log a warning and fall back to default."""
        monkeypatch.setenv("BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD", "not-a-number")
        with caplog.at_level(logging.WARNING, logger="bmad_assist.git.committer"):
            result = _get_large_commit_threshold()
        assert result == _DEFAULT_LARGE_COMMIT_THRESHOLD
        assert "Invalid BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD" in caplog.text


class TestShouldForceStageAll:
    """Escape-hatch env var helper."""

    def test_unset_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unset BMAD_GIT_STAGE_ALL → escape hatch inactive."""
        monkeypatch.delenv("BMAD_GIT_STAGE_ALL", raising=False)
        assert _should_force_stage_all() is False

    def test_value_one_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``BMAD_GIT_STAGE_ALL=1`` → escape hatch active."""
        monkeypatch.setenv("BMAD_GIT_STAGE_ALL", "1")
        assert _should_force_stage_all() is True

    def test_other_values_return_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the literal ``"1"`` counts; ``true`` / ``yes`` / ``""`` don't."""
        monkeypatch.setenv("BMAD_GIT_STAGE_ALL", "true")
        assert _should_force_stage_all() is False
        monkeypatch.setenv("BMAD_GIT_STAGE_ALL", "yes")
        assert _should_force_stage_all() is False
        monkeypatch.setenv("BMAD_GIT_STAGE_ALL", "")
        assert _should_force_stage_all() is False


# =============================================================================
# auto_commit_phase integration
# =============================================================================


class TestAutoCommitPhaseScoping:
    """auto_commit_phase routes the filtered list into stage_all_changes."""

    @pytest.fixture(autouse=True)
    def enable_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Simulate ``--git`` being on for all tests in this class."""
        monkeypatch.setenv("BMAD_GIT_COMMIT", "1")
        # Disable the real pre-commit fix layer; not under test here.
        monkeypatch.setattr(
            "bmad_assist.git.committer._run_precommit_fix",
            lambda _p: None,
        )

    def test_stages_only_filtered_paths(self, tmp_path: Path) -> None:
        """auto_commit_phase calls stage_all_changes with the filter output."""
        filtered = ["src/main.py", "stories/11-1-foo.md"]

        with (
            patch(
                "bmad_assist.git.committer.get_modified_files",
                return_value=filtered,
            ),
            patch(
                "bmad_assist.git.committer.check_for_deleted_story_files",
                return_value=[],
            ),
            patch("bmad_assist.git.committer.stage_all_changes") as mock_stage,
            patch(
                "bmad_assist.git.committer.commit_changes",
                return_value=True,
            ),
        ):
            mock_stage.return_value = True
            ok = auto_commit_phase(Phase.CREATE_STORY, "11.1", tmp_path)

        assert ok is True
        # stage_all_changes invoked twice: initial + post-lint-refresh.
        assert mock_stage.call_count == 2
        # Both calls pass paths= kwarg (not None).
        for call in mock_stage.call_args_list:
            assert "paths" in call.kwargs
            assert call.kwargs["paths"] == filtered

    def test_large_commit_warning_fires(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When filtered file count > threshold, emit a clear WARNING."""
        monkeypatch.setenv("BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD", "5")
        # 10 files > threshold 5
        many_files = [f"src/f{i}.py" for i in range(10)]

        with (
            patch(
                "bmad_assist.git.committer.get_modified_files",
                return_value=many_files,
            ),
            patch(
                "bmad_assist.git.committer.check_for_deleted_story_files",
                return_value=[],
            ),
            patch(
                "bmad_assist.git.committer.stage_all_changes",
                return_value=True,
            ),
            patch(
                "bmad_assist.git.committer.commit_changes",
                return_value=True,
            ),
            caplog.at_level(logging.WARNING, logger="bmad_assist.git.committer"),
        ):
            auto_commit_phase(Phase.CREATE_STORY, "11.1", tmp_path)

        warnings = [
            r for r in caplog.records if r.levelname == "WARNING"
        ]
        assert any("Large auto-commit detected" in r.getMessage() for r in warnings)
        # Warning includes file count and threshold.
        msg = [
            r.getMessage() for r in warnings
            if "Large auto-commit" in r.getMessage()
        ][0]
        assert "10 files" in msg
        assert "threshold 5" in msg
        assert "BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD" in msg  # tells user how to tune

    def test_large_commit_warning_suppressed_when_threshold_zero(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Threshold=0 disables the warning entirely, even for 1000 files."""
        monkeypatch.setenv("BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD", "0")
        many_files = [f"src/f{i}.py" for i in range(1000)]

        with (
            patch(
                "bmad_assist.git.committer.get_modified_files",
                return_value=many_files,
            ),
            patch(
                "bmad_assist.git.committer.check_for_deleted_story_files",
                return_value=[],
            ),
            patch(
                "bmad_assist.git.committer.stage_all_changes",
                return_value=True,
            ),
            patch(
                "bmad_assist.git.committer.commit_changes",
                return_value=True,
            ),
            caplog.at_level(logging.WARNING, logger="bmad_assist.git.committer"),
        ):
            auto_commit_phase(Phase.CREATE_STORY, "11.1", tmp_path)

        assert not any(
            "Large auto-commit" in r.getMessage() for r in caplog.records
        )

    def test_warning_skipped_when_below_threshold(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Typical small commits (< threshold) don't trigger the warning."""
        monkeypatch.delenv(
            "BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD", raising=False
        )
        few_files = ["stories/11-1-foo.md"]

        with (
            patch(
                "bmad_assist.git.committer.get_modified_files",
                return_value=few_files,
            ),
            patch(
                "bmad_assist.git.committer.check_for_deleted_story_files",
                return_value=[],
            ),
            patch(
                "bmad_assist.git.committer.stage_all_changes",
                return_value=True,
            ),
            patch(
                "bmad_assist.git.committer.commit_changes",
                return_value=True,
            ),
            caplog.at_level(logging.WARNING, logger="bmad_assist.git.committer"),
        ):
            auto_commit_phase(Phase.CREATE_STORY, "11.1", tmp_path)

        assert not any(
            "Large auto-commit" in r.getMessage() for r in caplog.records
        )

    def test_refreshed_file_list_used_on_restage(
        self, tmp_path: Path
    ) -> None:
        """After lint fixes, re-query get_modified_files and stage refreshed list.

        Lint may modify files outside the original filter (e.g. auto-
        generated caches). The refreshed list keeps staging aligned
        with the current working tree state post-lint.
        """
        initial = ["src/a.py"]
        refreshed = ["src/a.py", "src/b.py"]  # lint touched an extra file

        with (
            patch(
                "bmad_assist.git.committer.get_modified_files",
                side_effect=[initial, refreshed],
            ),
            patch(
                "bmad_assist.git.committer.check_for_deleted_story_files",
                return_value=[],
            ),
            patch("bmad_assist.git.committer.stage_all_changes") as mock_stage,
            patch(
                "bmad_assist.git.committer.commit_changes",
                return_value=True,
            ),
        ):
            mock_stage.return_value = True
            auto_commit_phase(Phase.CREATE_STORY, "11.1", tmp_path)

        # Two stage calls: first with initial, second with refreshed.
        assert mock_stage.call_count == 2
        assert mock_stage.call_args_list[0].kwargs["paths"] == initial
        assert mock_stage.call_args_list[1].kwargs["paths"] == refreshed


# =============================================================================
# Porcelain -z parsing (Task #22: running.lock fix)
# =============================================================================
#
# get_modified_files used line[3:] which assumed the documented
# "XY filename" format (3-char prefix). But git porcelain v1 without -z
# emits 2-char prefix "M filename" in some staged states, which made
# line[3:] eat the first char of the filename. Resulting in:
#   ".bmad-assist/running.lock" → "bmad-assist/running.lock"
# which then caused "git add -- <path>" to fail with "pathspec did not
# match any files". Fix: use --porcelain=v1 -z which guarantees a
# stable 2-char XY + space + path + NUL layout.


from bmad_assist.git.committer import (  # noqa: E402
    _parse_porcelain_z,
    get_modified_files,
)


class TestParsePorcelainZ:
    """_parse_porcelain_z handles the stable -z format across git quirks."""

    def test_standard_modified_records(self) -> None:
        """Plain space-M (unstaged modified) records parse cleanly."""
        stdout = " M .bmad-assist/state.yaml\x00 M packages/y3a-client\x00"
        records = _parse_porcelain_z(stdout)
        assert records == [
            (" M", ".bmad-assist/state.yaml"),
            (" M", "packages/y3a-client"),
        ]

    def test_staged_only_record(self) -> None:
        """Staged modified with worktree unchanged: X='M', Y=' '.

        Regression guard for the original bug: text porcelain could
        emit "M filename" (collapsed trailing-space Y) but -z is
        always "M  filename" (2-char XY + separator space).
        """
        stdout = "M  .bmad-assist/running.lock\x00"
        records = _parse_porcelain_z(stdout)
        assert records == [("M ", ".bmad-assist/running.lock")]

    def test_untracked_record(self) -> None:
        """Untracked files use ``??`` status."""
        stdout = "?? .bmad-assist/prompts/new.md\x00"
        records = _parse_porcelain_z(stdout)
        assert records == [("??", ".bmad-assist/prompts/new.md")]

    def test_rename_consumes_two_records(self) -> None:
        """Rename/copy emit TWO NUL-separated entries: new then old."""
        # Rename: R  new.md\x00old.md\x00
        stdout = "R  packages/new.md\x00packages/old.md\x00"
        records = _parse_porcelain_z(stdout)
        # We keep the NEW path only (post-rename name).
        assert records == [("R ", "packages/new.md")]

    def test_copy_consumes_two_records(self) -> None:
        """Copy (C status) follows the same rename format."""
        stdout = "C  packages/copy.md\x00packages/orig.md\x00"
        records = _parse_porcelain_z(stdout)
        assert records == [("C ", "packages/copy.md")]

    def test_multiple_mixed_records(self) -> None:
        """Modified + untracked + rename in one call."""
        stdout = (
            " M src/a.py\x00"
            "?? src/b.py\x00"
            "R  src/new.py\x00src/old.py\x00"
            " D src/gone.py\x00"
        )
        records = _parse_porcelain_z(stdout)
        assert records == [
            (" M", "src/a.py"),
            ("??", "src/b.py"),
            ("R ", "src/new.py"),
            (" D", "src/gone.py"),
        ]

    def test_empty_stdout_returns_empty_list(self) -> None:
        """No output → no records."""
        assert _parse_porcelain_z("") == []

    def test_path_with_dot_prefix_preserved(self) -> None:
        """Dotfile paths keep their leading dot (THE original bug)."""
        stdout = "M  .bmad-assist/running.lock\x00 M .bmad-assist/state.yaml\x00"
        records = _parse_porcelain_z(stdout)
        paths = [p for _, p in records]
        assert ".bmad-assist/running.lock" in paths
        assert ".bmad-assist/state.yaml" in paths
        # Neither entry should have lost its dot.
        assert "bmad-assist/running.lock" not in paths


class TestGetModifiedFilesExclusions:
    """get_modified_files filters out bmad-assist runtime state files."""

    def test_excludes_running_lock(self) -> None:
        """``.bmad-assist/running.lock`` is bmad-assist's own lock; exclude it."""
        stdout = (
            "M  .bmad-assist/running.lock\x00"
            " M src/real_change.py\x00"
        )
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (0, stdout, "")
            files = get_modified_files(Path("/fake"))
        assert ".bmad-assist/running.lock" not in files
        assert "src/real_change.py" in files

    def test_excludes_runs_directory(self) -> None:
        """``.bmad-assist/runs/*`` are per-run logs; never auto-commit."""
        stdout = (
            " M .bmad-assist/runs/run-20260417T142447Z-09a886bd.yaml\x00"
            " M src/real.py\x00"
        )
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (0, stdout, "")
            files = get_modified_files(Path("/fake"))
        assert all(not f.startswith(".bmad-assist/runs/") for f in files)
        assert "src/real.py" in files

    def test_excludes_prompts_cache_debug_output(self) -> None:
        """Existing exclusions still work with the -z parser."""
        stdout = (
            "?? .bmad-assist/prompts/x.md\x00"
            "?? .bmad-assist/cache/y.json\x00"
            "?? .bmad-assist/debug/z.log\x00"
            "?? _bmad-output/w.md\x00"
            " M src/real.py\x00"
        )
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (0, stdout, "")
            files = get_modified_files(Path("/fake"))
        assert files == ["src/real.py"]

    def test_legitimate_state_yaml_kept(self) -> None:
        """``.bmad-assist/state.yaml`` stays in the commit (resume-after-crash)."""
        stdout = " M .bmad-assist/state.yaml\x00"
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (0, stdout, "")
            files = get_modified_files(Path("/fake"))
        assert files == [".bmad-assist/state.yaml"]

    def test_regression_path_integrity(self) -> None:
        """Leading dots survive parsing (the original failure mode)."""
        # Reproduces the exact broken input:
        # previously this got parsed as "bmad-assist/running.lock" (no dot).
        stdout = "M  .bmad-assist/state.yaml\x00"
        with patch("bmad_assist.git.committer._run_git") as mock_run:
            mock_run.return_value = (0, stdout, "")
            files = get_modified_files(Path("/fake"))
        assert files == [".bmad-assist/state.yaml"]
