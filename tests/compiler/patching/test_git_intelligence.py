"""Tests for git intelligence extraction."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from bmad_assist.compiler.patching.git_intelligence import (
    _substitute_variables,
    extract_git_intelligence,
    is_git_repo,
    run_git_command,
)
from bmad_assist.compiler.patching.types import GitCommand, GitIntelligence


class TestIsGitRepo:
    """Tests for is_git_repo function."""

    def test_is_git_repo_returns_true_for_git_root(self, tmp_path: Path) -> None:
        """Returns True when directory is a git repo ROOT."""
        # Mock git returning the same path as the target
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=str(tmp_path) + "\n",
            )
            result = is_git_repo(tmp_path)

        assert result is True
        mock_run.assert_called_once()

    def test_is_git_repo_returns_false_for_subdirectory_of_git_repo(self, tmp_path: Path) -> None:
        """Returns False for subdirectory inside a parent git repo.

        This is the critical bug fix - when tests/fixtures/portfolio-project
        is inside bmad-assist (a git repo), we must NOT detect it as a git repo.
        """
        # Create a subdirectory that is NOT a git root
        subdir = tmp_path / "tests" / "fixtures" / "portfolio-project"
        subdir.mkdir(parents=True)

        # Mock git returning the PARENT path (not the subdirectory)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=str(tmp_path) + "\n",  # Parent git root, not subdir
            )
            result = is_git_repo(subdir)

        assert result is False

    def test_is_git_repo_returns_false_for_non_git_directory(self, tmp_path: Path) -> None:
        """Returns False when directory is not a git repo."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="")
            result = is_git_repo(tmp_path)

        assert result is False

    def test_is_git_repo_returns_false_on_timeout(self, tmp_path: Path) -> None:
        """Returns False when git command times out."""
        import subprocess

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("git", 10)
            result = is_git_repo(tmp_path)

        assert result is False

    def test_is_git_repo_returns_false_on_file_not_found(self, tmp_path: Path) -> None:
        """Returns False when git is not installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = is_git_repo(tmp_path)

        assert result is False


class TestSubstituteVariables:
    """Tests for _substitute_variables function."""

    def test_substitutes_simple_variable(self) -> None:
        """Substitutes {{variable}} with value."""
        result = _substitute_variables("git log --grep='{{epic_num}}'", {"epic_num": 6})
        assert result == "git log --grep='6'"

    def test_substitutes_multiple_variables(self) -> None:
        """Substitutes multiple variables."""
        result = _substitute_variables("{{a}}-{{b}}-{{a}}", {"a": "X", "b": "Y"})
        assert result == "X-Y-X"

    def test_handles_variable_with_spaces(self) -> None:
        """Handles {{ variable }} with spaces."""
        result = _substitute_variables("{{ epic_num }}", {"epic_num": 6})
        assert result == "6"

    def test_leaves_unknown_variables_unchanged(self) -> None:
        """Leaves unknown variables unchanged."""
        result = _substitute_variables("{{unknown}}", {"known": "value"})
        assert result == "{{unknown}}"

    def test_handles_empty_variables_dict(self) -> None:
        """Handles empty variables dict."""
        result = _substitute_variables("no variables here", {})
        assert result == "no variables here"


class TestRunGitCommand:
    """Tests for run_git_command function."""

    def test_runs_command_and_returns_output(self, tmp_path: Path) -> None:
        """Runs command and returns stdout."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="abc123 commit message\n", stderr=""
            )
            result = run_git_command("git log --oneline -1", tmp_path)

        assert "abc123 commit message" in result

    def test_substitutes_variables_in_command(self, tmp_path: Path) -> None:
        """Substitutes variables before running."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
            run_git_command("git log --grep='{{epic}}'", tmp_path, {"epic": 6})

        call_args = mock_run.call_args
        assert "git log --grep='6'" in call_args[0][0]

    def test_truncates_long_output(self, tmp_path: Path) -> None:
        """Truncates output exceeding MAX_OUTPUT_LENGTH."""
        with patch("subprocess.run") as mock_run:
            long_output = "x" * 3000
            mock_run.return_value = MagicMock(returncode=0, stdout=long_output, stderr="")
            result = run_git_command("git log", tmp_path)

        assert "truncated" in result
        assert len(result) < 3000

    def test_returns_error_message_on_failure(self, tmp_path: Path) -> None:
        """Returns error message when command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="fatal: not a git repo"
            )
            result = run_git_command("git log", tmp_path)

        assert "command failed" in result

    def test_returns_no_output_message(self, tmp_path: Path) -> None:
        """Returns (no output) when stdout is empty."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = run_git_command("git log", tmp_path)

        assert result == "(no output)"

    def test_handles_timeout(self, tmp_path: Path) -> None:
        """Handles timeout gracefully."""
        import subprocess

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("git", 10)
            result = run_git_command("git log", tmp_path)

        assert "timed out" in result


class TestExtractGitIntelligence:
    """Tests for extract_git_intelligence function."""

    def test_returns_empty_when_disabled(self, tmp_path: Path) -> None:
        """Returns empty string when git_intelligence is disabled."""
        config = GitIntelligence(enabled=False)
        result = extract_git_intelligence(config, tmp_path)
        assert result == ""

    def test_returns_no_git_message_when_not_git_repo(self, tmp_path: Path) -> None:
        """Returns no_git_message when directory is not a git repo."""
        config = GitIntelligence(
            enabled=True,
            no_git_message="No git here!",
            commands=[GitCommand(name="test", command="git log")],
        )

        with patch("bmad_assist.compiler.patching.git_intelligence.is_git_repo") as mock_is_git:
            mock_is_git.return_value = False
            result = extract_git_intelligence(config, tmp_path)

        assert "No git here!" in result
        assert "<git-intelligence>" in result
        assert "</git-intelligence>" in result

    def test_runs_commands_and_formats_output(self, tmp_path: Path) -> None:
        """Runs configured commands and formats output."""
        config = GitIntelligence(
            enabled=True,
            commands=[
                GitCommand(name="Recent Commits", command="git log --oneline -5"),
                GitCommand(name="Status", command="git status"),
            ],
        )

        with patch("bmad_assist.compiler.patching.git_intelligence.is_git_repo") as mock_is_git:
            mock_is_git.return_value = True

            with patch(
                "bmad_assist.compiler.patching.git_intelligence.run_git_command"
            ) as mock_run:
                mock_run.side_effect = ["commit1\ncommit2", "On branch main"]
                result = extract_git_intelligence(config, tmp_path)

        assert "<git-intelligence>" in result
        assert "</git-intelligence>" in result
        assert "### Recent Commits" in result
        assert "### Status" in result
        assert "commit1" in result
        assert "On branch main" in result
        assert "Do NOT run additional git commands" in result

    def test_uses_custom_embed_marker(self, tmp_path: Path) -> None:
        """Uses custom embed_marker for XML tags."""
        config = GitIntelligence(
            enabled=True,
            embed_marker="custom-git",
            commands=[GitCommand(name="test", command="git log")],
        )

        with patch("bmad_assist.compiler.patching.git_intelligence.is_git_repo") as mock_is_git:
            mock_is_git.return_value = True

            with patch(
                "bmad_assist.compiler.patching.git_intelligence.run_git_command"
            ) as mock_run:
                mock_run.return_value = "output"
                result = extract_git_intelligence(config, tmp_path)

        assert "<custom-git>" in result
        assert "</custom-git>" in result

    def test_passes_variables_to_commands(self, tmp_path: Path) -> None:
        """Passes variables to run_git_command."""
        config = GitIntelligence(
            enabled=True,
            commands=[GitCommand(name="test", command="git log --grep='{{epic}}'")],
        )
        variables = {"epic": 6}

        with patch("bmad_assist.compiler.patching.git_intelligence.is_git_repo") as mock_is_git:
            mock_is_git.return_value = True

            with patch(
                "bmad_assist.compiler.patching.git_intelligence.run_git_command"
            ) as mock_run:
                mock_run.return_value = "output"
                extract_git_intelligence(config, tmp_path, variables)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        # Check positional args: (command, cwd, variables)
        assert call_args[0][0] == "git log --grep='{{epic}}'"
        assert call_args[0][1] == tmp_path
        assert call_args[0][2] == {"epic": 6}
