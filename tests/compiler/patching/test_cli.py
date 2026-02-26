"""Tests for patch CLI integration."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from bmad_assist.cli import app

runner = CliRunner()


class TestPatchCompileCommand:
    """Tests for bmad-assist patch compile command."""

    def test_compile_requires_workflow(self) -> None:
        """Test that compile command requires --workflow option."""
        result = runner.invoke(app, ["patch", "compile"])
        assert result.exit_code != 0
        assert "workflow" in result.output.lower() or "missing" in result.output.lower()

    def test_compile_success(self, cli_isolated_env: Path) -> None:
        """Test successful patch compilation."""
        # Create minimal project structure
        tmp_path = cli_isolated_env
        project = tmp_path / "project"
        project.mkdir()

        # Create a patch file
        patch_dir = project / ".bmad-assist" / "patches"
        patch_dir.mkdir(parents=True)
        patch_file = patch_dir / "create-story.patch.yaml"
        patch_file.write_text("""
patch:
  name: test-patch
  version: "1.0"
compatibility:
  bmad_version: "0.1.0"
  workflow: create-story
transforms:
  - action: remove
    target: "//step[@n='1']"
""")

        # Mock the patch compilation
        with patch("bmad_assist.commands.patch.compile_patch") as mock_compile:
            mock_compile.return_value = (
                "<workflow>compiled</workflow>",
                Path(project / ".bmad-assist/cache/create-story.tpl.xml"),
                0,  # 0 warnings
            )

            result = runner.invoke(
                app,
                ["patch", "compile", "-w", "create-story", "-p", str(project)],
            )

            assert result.exit_code == 0
            assert "Compiled" in result.output

    def test_compile_with_warnings(self, cli_isolated_env: Path) -> None:
        """Test compilation with transform warnings."""
        tmp_path = cli_isolated_env
        project = tmp_path / "project"
        project.mkdir()

        with patch("bmad_assist.commands.patch.compile_patch") as mock_compile:
            mock_compile.return_value = (
                "<workflow>compiled</workflow>",
                Path(project / ".bmad-assist/cache/test.tpl.xml"),
                2,  # 2 warnings
            )

            result = runner.invoke(
                app,
                ["patch", "compile", "-w", "test", "-p", str(project)],
            )

            assert result.exit_code == 0
            assert "warnings" in result.output.lower()
            assert "2" in result.output

    def test_compile_patch_error(self, cli_isolated_env: Path) -> None:
        """Test compilation failure with PatchError."""
        from bmad_assist.core.exceptions import PatchError

        tmp_path = cli_isolated_env
        project = tmp_path / "project"
        project.mkdir()

        with patch("bmad_assist.commands.patch.compile_patch") as mock_compile:
            mock_compile.side_effect = PatchError("Test patch error")

            result = runner.invoke(
                app,
                ["patch", "compile", "-w", "test", "-p", str(project)],
            )

            assert result.exit_code == 16  # EXIT_PATCH_ERROR
            assert "error" in result.output.lower()

    def test_compile_validation_error(self, cli_isolated_env: Path) -> None:
        """Test compilation failure with validation error."""
        from bmad_assist.core.exceptions import PatchError

        tmp_path = cli_isolated_env
        project = tmp_path / "project"
        project.mkdir()

        with patch("bmad_assist.commands.patch.compile_patch") as mock_compile:
            # Simulate validation failure
            error = PatchError("Validation failed: must_contain 'step' not found")
            error.is_validation_error = True
            mock_compile.side_effect = error

            result = runner.invoke(
                app,
                ["patch", "compile", "-w", "test", "-p", str(project)],
            )

            assert result.exit_code == 17  # EXIT_PATCH_VALIDATION_ERROR

    def test_compile_debug_mode(self, cli_isolated_env: Path) -> None:
        """Test compilation with --debug flag."""
        tmp_path = cli_isolated_env
        project = tmp_path / "project"
        project.mkdir()

        # Create debug directory
        debug_dir = Path.home() / ".bmad-assist" / "debug"

        with patch("bmad_assist.commands.patch.compile_patch") as mock_compile:
            mock_compile.return_value = (
                "<workflow>compiled</workflow>",
                Path(project / ".bmad-assist/cache/test.tpl.xml"),
                0,
            )

            result = runner.invoke(
                app,
                ["patch", "compile", "-w", "test", "-p", str(project), "--debug"],
            )

            assert result.exit_code == 0
            # Debug mode should show more output
            # Actual debug log file creation tested in integration tests


class TestPatchListCommand:
    """Tests for bmad-assist patch list command."""

    def test_list_no_patches(self, tmp_path: Path) -> None:
        """Test list when no patches exist."""
        project = tmp_path / "project"
        project.mkdir()

        with patch("bmad_assist.commands.patch.list_patches") as mock_list:
            mock_list.return_value = []

            result = runner.invoke(
                app,
                ["patch", "list", "-p", str(project)],
            )

            assert result.exit_code == 0
            # Should show empty table or message

    def test_list_with_patches(self, tmp_path: Path) -> None:
        """Test list with multiple patches."""
        project = tmp_path / "project"
        project.mkdir()

        with patch("bmad_assist.commands.patch.list_patches") as mock_list:
            mock_list.return_value = [
                {
                    "workflow": "create-story",
                    "version": "1.0.0",
                    "status": "compiled",
                    "last_compiled": "2025-01-01T12:00:00Z",
                },
                {
                    "workflow": "dev-story",
                    "version": "2.0.0",
                    "status": "stale",
                    "last_compiled": "2025-01-01T10:00:00Z",
                },
                {
                    "workflow": "code-review",
                    "version": "1.5.0",
                    "status": "missing",
                    "last_compiled": None,
                },
            ]

            result = runner.invoke(
                app,
                ["patch", "list", "-p", str(project)],
            )

            assert result.exit_code == 0
            # Check for workflow names in output
            assert "create-story" in result.output
            assert "dev-story" in result.output
            assert "code-review" in result.output
            # Check for status values
            assert "compiled" in result.output.lower() or "stale" in result.output.lower()

    def test_list_table_columns(self, tmp_path: Path) -> None:
        """Test that list shows expected table columns."""
        project = tmp_path / "project"
        project.mkdir()

        with patch("bmad_assist.commands.patch.list_patches") as mock_list:
            mock_list.return_value = [
                {
                    "workflow": "test-workflow",
                    "version": "1.0.0",
                    "status": "compiled",
                    "last_compiled": "2025-01-01T12:00:00Z",
                },
            ]

            result = runner.invoke(
                app,
                ["patch", "list", "-p", str(project)],
            )

            assert result.exit_code == 0
            # Table should have columns (may be rendered with Rich)
            output_lower = result.output.lower()
            assert "workflow" in output_lower or "test-workflow" in output_lower


class TestPatchExitCodes:
    """Tests for patch command exit codes."""

    def test_exit_code_constants_defined(self) -> None:
        """Test that patch exit codes are defined in cli_utils module."""
        from bmad_assist import cli_utils

        assert hasattr(cli_utils, "EXIT_PATCH_ERROR")
        assert cli_utils.EXIT_PATCH_ERROR == 16

        assert hasattr(cli_utils, "EXIT_PATCH_VALIDATION_ERROR")
        assert cli_utils.EXIT_PATCH_VALIDATION_ERROR == 17

    def test_exit_codes_unique(self) -> None:
        """Test that patch exit codes don't conflict with existing codes."""
        from bmad_assist import cli_utils

        existing_codes = {
            cli_utils.EXIT_SUCCESS,
            cli_utils.EXIT_ERROR,
            cli_utils.EXIT_CONFIG_ERROR,
            cli_utils.EXIT_SIGINT,
            cli_utils.EXIT_SIGTERM,
            cli_utils.EXIT_PARSER_ERROR,
            cli_utils.EXIT_VARIABLE_ERROR,
            cli_utils.EXIT_AMBIGUOUS_ERROR,
            cli_utils.EXIT_COMPILER_ERROR,
            cli_utils.EXIT_FRAMEWORK_ERROR,
            cli_utils.EXIT_TOKEN_BUDGET_ERROR,
        }

        # Patch exit codes should be unique
        assert cli_utils.EXIT_PATCH_ERROR not in existing_codes
        assert cli_utils.EXIT_PATCH_VALIDATION_ERROR not in existing_codes
        assert cli_utils.EXIT_PATCH_ERROR != cli_utils.EXIT_PATCH_VALIDATION_ERROR
