"""Tests for CLI entry point - Story 1.6: Typer CLI Entry Point.

Comprehensive tests covering:
- Rich console output (AC4)
- Verbose/quiet flags (AC10, AC11)
- Project path validation (AC1, AC8, AC9)
- Config loading integration (AC2, AC6)
- Exit codes (AC7)
- Help text (AC3)
- Main loop delegation (AC5)
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from bmad_assist import __version__
from bmad_assist.cli import (
    _config_exists,
    app,
)
from bmad_assist.cli_utils import (
    EXIT_CONFIG_ERROR,
    EXIT_ERROR,
    EXIT_SUCCESS,
    _error,
    _setup_logging,
    _success,
    _validate_project_path,
    _warning,
    console,
)

runner = CliRunner()


# =============================================================================
# Test: Exit Code Constants
# =============================================================================


class TestExitCodes:
    """Tests for exit code constants (AC7)."""

    def test_exit_success_is_zero(self) -> None:
        """AC7: Success exit code is 0."""
        assert EXIT_SUCCESS == 0

    def test_exit_error_is_one(self) -> None:
        """AC7: General error exit code is 1."""
        assert EXIT_ERROR == 1

    def test_exit_config_error_is_two(self) -> None:
        """AC7: Config error exit code is 2."""
        assert EXIT_CONFIG_ERROR == 2


# =============================================================================
# Test: Rich Console Output
# =============================================================================


class TestRichOutput:
    """Tests for Rich console integration (AC4)."""

    def test_console_is_rich_console(self) -> None:
        """AC4: Console is Rich Console instance."""
        from rich.console import Console

        assert isinstance(console, Console)

    def test_error_function_calls_console_print(self) -> None:
        """AC4: _error() uses Rich console with red styling."""
        with patch.object(console, "print") as mock_print:
            _error("test error message")
            mock_print.assert_called_once()
            call_args = mock_print.call_args[0][0]
            assert "[red]" in call_args
            assert "test error message" in call_args

    def test_success_function_calls_console_print(self) -> None:
        """AC4: _success() uses Rich console with green styling."""
        with patch.object(console, "print") as mock_print:
            _success("test success message")
            mock_print.assert_called_once()
            call_args = mock_print.call_args[0][0]
            assert "[green]" in call_args
            assert "test success message" in call_args

    def test_warning_function_calls_console_print(self) -> None:
        """AC4: _warning() uses Rich console with yellow styling."""
        with patch.object(console, "print") as mock_print:
            _warning("test warning message")
            mock_print.assert_called_once()
            call_args = mock_print.call_args[0][0]
            assert "[yellow]" in call_args
            assert "test warning message" in call_args


# =============================================================================
# Test: Logging Configuration
# =============================================================================


class TestLoggingSetup:
    """Tests for logging configuration (AC10, AC11)."""

    def test_setup_logging_verbose_sets_debug(self) -> None:
        """AC10: --verbose sets DEBUG level."""
        _setup_logging(verbose=True, quiet=False)
        assert logging.getLogger().level == logging.DEBUG

    def test_setup_logging_quiet_sets_warning(self) -> None:
        """AC11: --quiet sets WARNING level."""
        _setup_logging(verbose=False, quiet=True)
        assert logging.getLogger().level == logging.WARNING

    def test_setup_logging_default_sets_info(self) -> None:
        """Default logging level is INFO."""
        _setup_logging(verbose=False, quiet=False)
        assert logging.getLogger().level == logging.INFO

    def test_setup_logging_verbose_takes_precedence(self) -> None:
        """AC10/AC11: --verbose takes precedence over --quiet."""
        _setup_logging(verbose=True, quiet=True)
        assert logging.getLogger().level == logging.DEBUG


# =============================================================================
# Test: Project Path Validation
# =============================================================================


class TestProjectPathValidation:
    """Tests for project path validation (AC1, AC8, AC9)."""

    def test_validate_existing_directory_returns_resolved_path(self, tmp_path: Path) -> None:
        """AC1: Valid directory returns resolved absolute path."""
        result = _validate_project_path(str(tmp_path))
        assert result == tmp_path.resolve()
        assert result.is_absolute()

    def test_validate_nonexistent_path_exits_with_error(self, tmp_path: Path) -> None:
        """AC8: Nonexistent path raises typer.Exit with EXIT_ERROR."""
        import typer

        nonexistent = tmp_path / "nonexistent"
        with pytest.raises(typer.Exit) as exc_info:
            _validate_project_path(str(nonexistent))
        assert exc_info.value.exit_code == EXIT_ERROR

    def test_validate_file_path_exits_with_error(self, tmp_path: Path) -> None:
        """AC8: File (not directory) path raises typer.Exit with EXIT_ERROR."""
        import typer

        file_path = tmp_path / "file.txt"
        file_path.write_text("test")

        with pytest.raises(typer.Exit) as exc_info:
            _validate_project_path(str(file_path))
        assert exc_info.value.exit_code == EXIT_ERROR

    def test_validate_relative_path_resolves_to_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC1: Relative paths are resolved to absolute."""
        monkeypatch.chdir(tmp_path)
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        result = _validate_project_path("subdir")
        assert result.is_absolute()
        assert result == subdir


class TestRunCommandProjectPath:
    """Integration tests for project path in run command (AC1, AC8, AC9)."""

    def test_nonexistent_project_path_exits_with_error_code(self, tmp_path: Path) -> None:
        """AC8: Nonexistent path returns exit code 1."""
        result = runner.invoke(app, ["run", "--project", str(tmp_path / "nonexistent")])
        assert result.exit_code == EXIT_ERROR
        assert "not found" in result.output.lower()

    def test_file_as_project_path_exits_with_error_code(self, tmp_path: Path) -> None:
        """AC8: File as project path returns exit code 1."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("test")

        result = runner.invoke(app, ["run", "--project", str(file_path)])
        assert result.exit_code == EXIT_ERROR
        assert "directory" in result.output.lower()

    def test_default_project_path_uses_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC9: Default project path is current working directory."""
        # Create a valid config in tmp_path
        config_file = tmp_path / "bmad-assist.yaml"
        config_file.write_text(
            """
providers:
  master:
    provider: claude
    model: opus_4
"""
        )

        # Create sprint-status.yaml to pass validation
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "sprint-status.yaml").write_text(
            """
development_status:
  1-1-test: backlog
"""
        )

        monkeypatch.chdir(tmp_path)

        # Mock run_loop and _load_epic_data to avoid actual execution
        with (
            patch("bmad_assist.cli.run_loop"),
            patch("bmad_assist.cli._load_epic_data", return_value=([1], {1: ["1.1"]})),
        ):
            result = runner.invoke(app, ["run"])

        # Should not fail on project validation (cwd exists)
        # May fail on config, but that's a different test
        assert result.exit_code in (EXIT_SUCCESS, EXIT_CONFIG_ERROR)


# =============================================================================
# Test: Configuration Loading Integration
# =============================================================================


class TestConfigIntegration:
    """Tests for configuration loading integration (AC2, AC6)."""

    def test_valid_config_loads_successfully(self, tmp_path: Path) -> None:
        """AC6: Valid config loads and run_loop is called."""
        # Create project directory
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create sprint-status.yaml (required by run command)
        sprint_dir = project_dir / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        (sprint_dir / "sprint-status.yaml").write_text("epics: []\n")

        # Create valid config
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
providers:
  master:
    provider: claude
    model: opus_4
"""
        )

        with (
            patch("bmad_assist.cli.run_loop") as mock_run_loop,
            patch("bmad_assist.cli._load_epic_data", return_value=([1], {1: ["1.1"]})),
        ):
            result = runner.invoke(
                app,
                [
                    "run",
                    "--project",
                    str(project_dir),
                    "--config",
                    str(config_file),
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        mock_run_loop.assert_called_once()
        # Verify Config and Path were passed
        call_args = mock_run_loop.call_args
        from bmad_assist.core.config import Config

        assert isinstance(call_args[0][0], Config)
        assert isinstance(call_args[0][1], Path)
        assert call_args[0][1] == project_dir

    def test_custom_config_path_used(self, tmp_path: Path) -> None:
        """AC2: --config option passes path to load_config_with_project."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create sprint-status.yaml (required by run command)
        sprint_dir = project_dir / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        (sprint_dir / "sprint-status.yaml").write_text("epics: []\n")

        custom_config = tmp_path / "custom-config.yaml"
        custom_config.write_text(
            """
providers:
  master:
    provider: gemini
    model: flash
"""
        )

        with (
            patch("bmad_assist.cli.run_loop") as mock_run_loop,
            patch("bmad_assist.cli._load_epic_data", return_value=([1], {1: ["1.1"]})),
        ):
            result = runner.invoke(
                app,
                [
                    "run",
                    "--project",
                    str(project_dir),
                    "--config",
                    str(custom_config),
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        # Verify the config was loaded with custom values
        loaded_config = mock_run_loop.call_args[0][0]
        assert loaded_config.providers.master.provider == "gemini"

    def test_invalid_yaml_config_exits_with_config_error(self, tmp_path: Path) -> None:
        """AC7: Invalid YAML returns exit code 2 (CONFIG_ERROR)."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: content: [")

        result = runner.invoke(
            app,
            [
                "run",
                "--project",
                str(project_dir),
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == EXIT_CONFIG_ERROR

    def test_missing_required_config_field_exits_with_config_error(self, tmp_path: Path) -> None:
        """AC7: Missing required fields return exit code 2."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
providers: {}
"""
        )  # Missing master

        result = runner.invoke(
            app,
            [
                "run",
                "--project",
                str(project_dir),
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == EXIT_CONFIG_ERROR


# =============================================================================
# Test: Verbose and Quiet Modes
# =============================================================================


class TestVerboseQuietModes:
    """Tests for verbose and quiet mode flags (AC10, AC11)."""

    def test_verbose_flag_accepted(self) -> None:
        """AC10: --verbose flag is accepted."""
        result = runner.invoke(app, ["run", "--verbose", "--help"])
        assert result.exit_code == 0

    def test_quiet_flag_accepted(self) -> None:
        """AC11: --quiet flag is accepted."""
        result = runner.invoke(app, ["run", "--quiet", "--help"])
        assert result.exit_code == 0

    def test_verbose_short_form_accepted(self) -> None:
        """AC10: -v short form works."""
        result = runner.invoke(app, ["run", "-v", "--help"])
        assert result.exit_code == 0

    def test_quiet_short_form_accepted(self) -> None:
        """AC11: -q short form works."""
        result = runner.invoke(app, ["run", "-q", "--help"])
        assert result.exit_code == 0

    def test_verbose_and_quiet_shows_warning(self, tmp_path: Path) -> None:
        """AC10/AC11: Both flags shows warning, verbose wins."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
providers:
  master:
    provider: claude
    model: opus_4
"""
        )

        with (
            patch("bmad_assist.cli.run_loop"),
            patch("bmad_assist.cli._load_epic_data", return_value=([1], {1: ["1.1"]})),
        ):
            result = runner.invoke(
                app,
                [
                    "run",
                    "--project",
                    str(project_dir),
                    "--config",
                    str(config_file),
                    "--verbose",
                    "--quiet",
                ],
            )

        assert "warning" in result.output.lower()


# =============================================================================
# Test: Help Output
# =============================================================================


class TestHelpOutput:
    """Tests for help text (AC3)."""

    def test_cli_help_exits_successfully(self) -> None:
        """CLI responds to --help with exit code 0."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_cli_help_contains_app_name(self) -> None:
        """CLI help contains application name."""
        result = runner.invoke(app, ["--help"])
        assert "bmad-assist" in result.output.lower()

    def test_cli_help_shows_run_command(self) -> None:
        """CLI help shows run command."""
        result = runner.invoke(app, ["--help"])
        assert "run" in result.output.lower()

    def test_run_help_shows_all_options(self) -> None:
        """AC3: Help shows all options with descriptions."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        # Long forms
        assert "--project" in result.output
        assert "--config" in result.output
        assert "--verbose" in result.output
        assert "--quiet" in result.output
        # Short forms
        assert "-p" in result.output
        assert "-c" in result.output
        assert "-v" in result.output
        assert "-q" in result.output


# =============================================================================
# Test: Main Loop Delegation
# =============================================================================


class TestMainLoopDelegation:
    """Tests for main loop delegation (AC5)."""

    def test_run_loop_called_with_config_and_path(self, tmp_path: Path) -> None:
        """AC5: run_loop receives Config and Path arguments."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create sprint-status.yaml (required by run command)
        sprint_dir = project_dir / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        (sprint_dir / "sprint-status.yaml").write_text("epics: []\n")

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
providers:
  master:
    provider: claude
    model: opus_4
"""
        )

        with (
            patch("bmad_assist.cli.run_loop") as mock_run_loop,
            patch("bmad_assist.cli._load_epic_data", return_value=([1], {1: ["1.1"]})),
        ):
            result = runner.invoke(
                app,
                [
                    "run",
                    "--project",
                    str(project_dir),
                    "--config",
                    str(config_file),
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        mock_run_loop.assert_called_once()

        # Verify argument types
        from bmad_assist.core.config import Config

        call_args = mock_run_loop.call_args[0]
        assert isinstance(call_args[0], Config)
        assert isinstance(call_args[1], Path)

    def test_run_loop_exception_exits_with_error(self, tmp_path: Path) -> None:
        """AC7: Unexpected exception in run_loop exits with code 1."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create sprint-status.yaml (required by run command)
        sprint_dir = project_dir / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        (sprint_dir / "sprint-status.yaml").write_text("epics: []\n")

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
providers:
  master:
    provider: claude
    model: opus_4
"""
        )

        with (
            patch(
                "bmad_assist.cli.run_loop",
                side_effect=RuntimeError("Unexpected error"),
            ),
            patch("bmad_assist.cli._load_epic_data", return_value=([1], {1: ["1.1"]})),
        ):
            result = runner.invoke(
                app,
                [
                    "run",
                    "--project",
                    str(project_dir),
                    "--config",
                    str(config_file),
                ],
            )

        assert result.exit_code == EXIT_ERROR
        assert "unexpected error" in result.output.lower()


# =============================================================================
# Test: Version
# =============================================================================


class TestVersion:
    """Tests for package version."""

    def test_version_is_importable(self) -> None:
        """Version is importable from package."""
        assert __version__ is not None

    def test_version_is_string(self) -> None:
        """Version is a string."""
        assert isinstance(__version__, str)

    def test_version_is_semver_format(self) -> None:
        """Version follows semantic versioning format."""
        parts = __version__.split(".")
        assert len(parts) == 3
        assert all(part.isdigit() for part in parts)


# =============================================================================
# Test: No Args Shows Help
# =============================================================================


class TestNoArgsIsHelp:
    """Tests for no_args_is_help behavior."""

    def test_no_args_shows_help(self) -> None:
        """Running without arguments shows help/usage."""
        result = runner.invoke(app, [])
        # CLI shows usage info and exits with EXIT_CONFIG_ERROR (2) when no command given
        assert result.exit_code == EXIT_CONFIG_ERROR
        # Help/usage should be displayed
        assert "usage" in result.output.lower()


# =============================================================================
# Test: Main Module
# =============================================================================


class TestMainModule:
    """Tests for __main__.py entry point."""

    def test_main_module_importable(self) -> None:
        """Main module is importable."""
        from bmad_assist import __main__  # noqa: F401

        assert True


# =============================================================================
# Test: Error Message Formatting
# =============================================================================


class TestErrorMessages:
    """Tests for user-friendly error messages."""

    def test_project_not_found_message_includes_path(self, tmp_path: Path) -> None:
        """Error message includes the path that wasn't found."""
        nonexistent = tmp_path / "my-project"
        result = runner.invoke(app, ["run", "--project", str(nonexistent)])
        assert "my-project" in result.output

    def test_file_not_directory_message_is_clear(self, tmp_path: Path) -> None:
        """Error message clearly states path must be directory."""
        file_path = tmp_path / "not-a-dir.txt"
        file_path.write_text("content")

        result = runner.invoke(app, ["run", "--project", str(file_path)])
        assert "directory" in result.output.lower()


# =============================================================================
# Test: --no-interactive Flag (Story 1.7)
# =============================================================================


class TestNoInteractiveFlag:
    """Tests for --no-interactive flag (AC6, AC7)."""

    def test_no_interactive_flag_in_help(self) -> None:
        """AC6: --no-interactive flag appears in help."""
        result = runner.invoke(app, ["run", "--help"])
        assert "--no-interactive" in result.output

    def test_no_interactive_short_form_in_help(self) -> None:
        """AC6: -n short form appears in help."""
        result = runner.invoke(app, ["run", "--help"])
        assert "-n" in result.output

    def test_no_interactive_flag_accepted(self) -> None:
        """AC6: --no-interactive flag is accepted."""
        result = runner.invoke(app, ["run", "--no-interactive", "--help"])
        assert result.exit_code == 0

    def test_no_interactive_short_form_accepted(self) -> None:
        """AC6: -n short form is accepted."""
        result = runner.invoke(app, ["run", "-n", "--help"])
        assert result.exit_code == 0

    def test_no_interactive_missing_config_exits_with_error(self, tmp_path: Path) -> None:
        """AC6: Missing config with --no-interactive exits with EXIT_CONFIG_ERROR."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Mock global config path to ensure no config is found
        fake_global_config = tmp_path / "nonexistent" / "config.yaml"
        with patch("bmad_assist.cli.GLOBAL_CONFIG_PATH", fake_global_config):
            result = runner.invoke(app, ["run", "--project", str(project_dir), "--no-interactive"])

        assert result.exit_code == EXIT_CONFIG_ERROR
        assert "configuration" in result.output.lower()
        assert "--no-interactive" in result.output

    def test_no_interactive_missing_config_error_message(self, tmp_path: Path) -> None:
        """AC6: Error message mentions setup wizard."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Mock global config path to ensure no config is found
        fake_global_config = tmp_path / "nonexistent" / "config.yaml"
        with patch("bmad_assist.cli.GLOBAL_CONFIG_PATH", fake_global_config):
            result = runner.invoke(app, ["run", "--project", str(project_dir), "-n"])

        assert "setup wizard" in result.output.lower()

    def test_no_interactive_with_existing_config_succeeds(self, tmp_path: Path) -> None:
        """AC7: --no-interactive with valid config proceeds normally."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create sprint-status.yaml fixture
        sprint_dir = project_dir / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        (sprint_dir / "sprint-status.yaml").write_text("epics: []\n")

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
providers:
  master:
    provider: claude
    model: opus_4
"""
        )

        with (
            patch("bmad_assist.cli.run_loop"),
            patch("bmad_assist.cli._load_epic_data", return_value=([1], {1: ["1.1"]})),
        ):
            result = runner.invoke(
                app,
                [
                    "run",
                    "--project",
                    str(project_dir),
                    "--config",
                    str(config_file),
                    "--no-interactive",
                ],
            )

        assert result.exit_code == EXIT_SUCCESS

    def test_no_interactive_with_project_config_succeeds(self, tmp_path: Path) -> None:
        """AC7: --no-interactive with project config proceeds normally."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create sprint-status.yaml fixture
        sprint_dir = project_dir / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        (sprint_dir / "sprint-status.yaml").write_text("epics: []\n")

        # Create project config
        (project_dir / "bmad-assist.yaml").write_text(
            """
providers:
  master:
    provider: claude
    model: opus_4
"""
        )

        with (
            patch("bmad_assist.cli.run_loop"),
            patch("bmad_assist.cli._load_epic_data", return_value=([1], {1: ["1.1"]})),
        ):
            result = runner.invoke(
                app,
                ["run", "--project", str(project_dir), "--no-interactive"],
            )

        assert result.exit_code == EXIT_SUCCESS


class TestConfigExistsHelper:
    """Tests for _config_exists helper function."""

    def test_no_config_returns_false(self, tmp_path: Path) -> None:
        """Returns False when no config exists."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Mock global config path to ensure it doesn't exist
        fake_global_config = tmp_path / "nonexistent" / "config.yaml"
        with patch("bmad_assist.cli.GLOBAL_CONFIG_PATH", fake_global_config):
            result = _config_exists(project_dir, None)

        assert result is False

    def test_project_config_exists_returns_true(self, tmp_path: Path) -> None:
        """Returns True when project config exists."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "bmad-assist.yaml").write_text("test: true")

        result = _config_exists(project_dir, None)

        assert result is True

    def test_global_config_exists_returns_true(self, tmp_path: Path) -> None:
        """Returns True when global config exists."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        global_config = tmp_path / "global-config.yaml"
        global_config.write_text("test: true")

        result = _config_exists(project_dir, global_config)

        assert result is True

    def test_directory_as_config_returns_false(self, tmp_path: Path) -> None:
        """Returns False if config path is a directory, not file."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        config_dir = tmp_path / "config-dir"
        config_dir.mkdir()

        result = _config_exists(project_dir, config_dir)

        assert result is False


class TestWizardIntegration:
    """Tests for wizard integration in CLI (AC1, AC8)."""

    @patch("bmad_assist.cli._load_epic_data", return_value=([1], {1: ["1.1"]}))
    @patch("bmad_assist.cli.run_config_wizard")
    @patch("bmad_assist.cli.run_loop")
    def test_missing_config_triggers_wizard(
        self,
        mock_run_loop: MagicMock,
        mock_wizard: MagicMock,
        mock_load_epic_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """AC1: Missing config triggers interactive questionnaire."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create sprint-status.yaml fixture
        sprint_dir = project_dir / "_bmad-output" / "implementation-artifacts"
        sprint_dir.mkdir(parents=True)
        (sprint_dir / "sprint-status.yaml").write_text("epics: []\n")

        # Wizard creates config file
        def create_config(path: Path, console: MagicMock) -> Path:
            config_path = path / "bmad-assist.yaml"
            config_path.write_text(
                """
providers:
  master:
    provider: claude
    model: opus_4
"""
            )
            return config_path

        mock_wizard.side_effect = create_config

        # Mock global config path to ensure no config is found initially
        fake_global_config = tmp_path / "nonexistent" / "config.yaml"
        with patch("bmad_assist.cli.GLOBAL_CONFIG_PATH", fake_global_config):
            result = runner.invoke(app, ["run", "--project", str(project_dir)])

        mock_wizard.assert_called_once()
        assert result.exit_code == EXIT_SUCCESS

    @patch("bmad_assist.cli.run_config_wizard")
    def test_wizard_keyboard_interrupt_exits_with_error(
        self, mock_wizard: MagicMock, tmp_path: Path
    ) -> None:
        """AC8: Wizard KeyboardInterrupt exits with EXIT_ERROR."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        mock_wizard.side_effect = KeyboardInterrupt()

        # Mock global config path to ensure no config is found
        fake_global_config = tmp_path / "nonexistent" / "config.yaml"
        with patch("bmad_assist.cli.GLOBAL_CONFIG_PATH", fake_global_config):
            result = runner.invoke(app, ["run", "--project", str(project_dir)])

        assert result.exit_code == EXIT_ERROR
        assert "cancelled" in result.output.lower()

    @patch("bmad_assist.cli.run_config_wizard")
    def test_wizard_eof_error_exits_with_error(
        self, mock_wizard: MagicMock, tmp_path: Path
    ) -> None:
        """AC8: Wizard EOFError exits with EXIT_ERROR."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        mock_wizard.side_effect = EOFError()

        # Mock global config path to ensure no config is found
        fake_global_config = tmp_path / "nonexistent" / "config.yaml"
        with patch("bmad_assist.cli.GLOBAL_CONFIG_PATH", fake_global_config):
            result = runner.invoke(app, ["run", "--project", str(project_dir)])

        assert result.exit_code == EXIT_ERROR
        assert "cancelled" in result.output.lower()

    @patch("bmad_assist.cli.run_config_wizard")
    def test_wizard_rejection_exits_with_error(
        self, mock_wizard: MagicMock, tmp_path: Path
    ) -> None:
        """AC10: Wizard rejection (SystemExit 1) propagates."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        mock_wizard.side_effect = SystemExit(1)

        result = runner.invoke(app, ["run", "--project", str(project_dir)])

        assert result.exit_code == EXIT_ERROR


# =============================================================================
# Test: CLI Start Point Parameters (Epic 22)
# =============================================================================


class TestRunStartPointParameters:
    """Tests for CLI start point parameters (--epic and --story flags).

    Tests verify that users can override state.yaml starting position
    using epic/story identifiers from the command line.
    """

    def test_epic_parameter_in_help(self) -> None:
        """--epic flag appears in help text."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--epic" in result.output
        assert "-e" in result.output

    def test_story_parameter_in_help(self) -> None:
        """--story flag appears in help text."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--story" in result.output
        assert "-s" in result.output

    def test_epic_parameter_accepted(self) -> None:
        """--epic flag is accepted without error."""
        result = runner.invoke(app, ["run", "--epic", "22", "--help"])
        assert result.exit_code == 0

    def test_epic_short_form_accepted(self) -> None:
        """-e short form is accepted."""
        result = runner.invoke(app, ["run", "-e", "22", "--help"])
        assert result.exit_code == 0

    def test_story_parameter_accepted(self) -> None:
        """--story flag is accepted."""
        result = runner.invoke(app, ["run", "--epic", "22", "--story", "3", "--help"])
        assert result.exit_code == 0

    def test_story_short_form_accepted(self) -> None:
        """-s short form is accepted."""
        result = runner.invoke(app, ["run", "-e", "22", "-s", "3", "--help"])
        assert result.exit_code == 0

    def test_story_without_epic_exits_with_error(self, tmp_path: Path) -> None:
        """--story without --epic exits with EXIT_CONFIG_ERROR."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create valid config
        (project_dir / "bmad-assist.yaml").write_text(
            """
providers:
  master:
    provider: claude
    model: opus_4
"""
        )

        # Create sprint-status.yaml to pass validation
        (project_dir / "docs").mkdir()
        (project_dir / "docs" / "sprint-status.yaml").write_text(
            """
development_status:
  1-1-test: backlog
"""
        )

        with (
            patch("bmad_assist.cli.run_loop"),
            patch(
                "bmad_assist.cli._load_epic_data",
                return_value=([1, 22], {1: ["1.1"], 22: ["22.1"]}),
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "run",
                    "--project",
                    str(project_dir),
                    "--story",
                    "3",
                ],
            )

        assert result.exit_code == EXIT_CONFIG_ERROR
        assert "requires --epic" in result.output.lower()

    def test_epic_string_id_accepted(self) -> None:
        """String epic IDs like "testarch" are accepted."""
        result = runner.invoke(app, ["run", "--epic", "testarch", "--help"])
        assert result.exit_code == 0


class TestApplyStartPointOverride:
    """Tests for apply_start_point_override() helper function.

    Tests verify state override logic including epic/story validation,
    status-to-phase mapping, and state persistence.
    """

    def test_epic_only_uses_first_undone_story(self, tmp_path: Path) -> None:
        """--epic without --story finds first story with status not 'done'."""
        from bmad_assist.cli_start_point import apply_start_point_override
        from bmad_assist.bmad.state_reader import ProjectState, EpicStory
        from bmad_assist.core.state import State

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create mock stories: 22.1 done, 22.2 backlog
        mock_stories = [
            EpicStory(number="22.1", title="Done Story", status="done"),
            EpicStory(number="22.2", title="Backlog Story", status="backlog"),
        ]
        mock_project_state = ProjectState(
            epics=[],
            all_stories=mock_stories,
            completed_stories=["22.1"],
            current_epic=22,
            current_story="22.2",
            bmad_path=str(project_dir / "docs"),
        )

        mock_config = MagicMock()

        with (
            patch("bmad_assist.cli_start_point.read_project_state", return_value=mock_project_state),
            patch("bmad_assist.cli_start_point.load_state", return_value=State()),
            patch("bmad_assist.cli_start_point.get_state_path", return_value=project_dir / "state.yaml"),
            patch("bmad_assist.cli_start_point.save_state") as mock_save,
        ):
            apply_start_point_override(
                mock_config,
                project_dir,
                project_dir / "docs",
                epic_id="22",
                story_id=None,
                epic_list=[1, 22],
                stories_by_epic={22: ["22.1", "22.2"]},
            )

            # Verify save was called with 22.2 (first undone story)
            call_args = mock_save.call_args[0]
            saved_state = call_args[0]
            assert saved_state.current_story == "22.2"

    def test_story_without_epic_returns_early(self, tmp_path: Path) -> None:
        """Function returns early when epic_id is None."""
        from bmad_assist.cli_start_point import apply_start_point_override
        from bmad_assist.core.state import State

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        mock_config = MagicMock()

        with (
            patch("bmad_assist.cli_start_point.load_state", return_value=State()),
            patch("bmad_assist.cli_start_point.save_state") as mock_save,
        ):
            apply_start_point_override(
                mock_config,
                project_dir,
                project_dir / "docs",
                epic_id=None,
                story_id=None,
                epic_list=[1, 22],
                stories_by_epic={22: ["22.1"]},
            )

            # Should not call save_state when epic_id is None
            mock_save.assert_not_called()

    def test_invalid_epic_exits_with_error(self, tmp_path: Path) -> None:
        """Invalid epic exits with EXIT_CONFIG_ERROR."""
        from bmad_assist.cli_start_point import apply_start_point_override
        from bmad_assist.bmad.state_reader import ProjectState, EpicStory
        import typer

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create mock stories only for epics 1 and 22 (not 999)
        mock_stories = [
            EpicStory(number="1.1", title="Story 1", status="backlog"),
            EpicStory(number="22.1", title="Story 22", status="backlog"),
        ]
        mock_project_state = ProjectState(
            epics=[],
            all_stories=mock_stories,
            completed_stories=[],
            current_epic=1,
            current_story="1.1",
            bmad_path=str(project_dir / "docs"),
        )

        mock_config = MagicMock()

        with (
            patch("bmad_assist.cli_start_point.read_project_state", return_value=mock_project_state),
            pytest.raises(typer.Exit) as exc_info,
        ):
            apply_start_point_override(
                mock_config,
                project_dir,
                project_dir / "docs",
                epic_id="999",
                story_id=None,
                epic_list=[1, 22],
                stories_by_epic={1: ["1.1"], 22: ["22.1"]},
            )

        assert exc_info.value.exit_code == EXIT_CONFIG_ERROR
