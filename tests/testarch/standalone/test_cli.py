"""Tests for TEA CLI command group.

Story 25.13: TEA Standalone Runner & CLI.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from bmad_assist.cli import app

runner = CliRunner()

# Patch location for StandaloneRunner (imported inside _get_runner)
RUNNER_PATCH = "bmad_assist.testarch.standalone.runner.StandaloneRunner"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with minimal structure."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    return tmp_path


# =============================================================================
# CLI Option Parsing Tests (6 tests - one per command)
# =============================================================================


class TestCLIOptionParsing:
    """Tests for CLI option parsing for each command."""

    def test_framework_command_options(self, tmp_project: Path) -> None:
        """Test framework command parses options correctly."""
        with patch(RUNNER_PATCH) as mock_runner_cls:
            mock_instance = MagicMock()
            mock_instance.run_framework.return_value = {
                "success": True,
                "output_path": Path("/tmp/out.md"),
                "error": None,
                "metrics": {},
            }
            mock_runner_cls.return_value = mock_instance

            result = runner.invoke(
                app,
                [
                    "tea",
                    "framework",
                    "-r",
                    str(tmp_project),
                    "-m",
                    "validate",
                    "-v",
                ],
            )

            # Check runner was called with correct params
            mock_runner_cls.assert_called_once()
            call_kwargs = mock_runner_cls.call_args[1]
            assert call_kwargs["project_root"] == tmp_project

    def test_ci_command_options(self, tmp_project: Path) -> None:
        """Test ci command parses platform option correctly."""
        with patch(RUNNER_PATCH) as mock_runner_cls:
            mock_instance = MagicMock()
            mock_instance.run_ci.return_value = {
                "success": True,
                "output_path": Path("/tmp/out.md"),
                "error": None,
                "metrics": {},
            }
            mock_runner_cls.return_value = mock_instance

            result = runner.invoke(
                app,
                [
                    "tea",
                    "ci",
                    "-r",
                    str(tmp_project),
                    "--ci-platform",
                    "github",
                ],
            )

            mock_instance.run_ci.assert_called_once_with(
                ci_platform="github", mode="create"
            )

    def test_test_design_command_options(self, tmp_project: Path) -> None:
        """Test test-design command parses level option correctly."""
        with patch(RUNNER_PATCH) as mock_runner_cls:
            mock_instance = MagicMock()
            mock_instance.run_test_design.return_value = {
                "success": True,
                "output_path": Path("/tmp/out.md"),
                "error": None,
                "metrics": {},
            }
            mock_runner_cls.return_value = mock_instance

            result = runner.invoke(
                app,
                [
                    "tea",
                    "test-design",
                    "-r",
                    str(tmp_project),
                    "--level",
                    "epic",
                ],
            )

            mock_instance.run_test_design.assert_called_once_with(
                level="epic", mode="create"
            )

    def test_automate_command_options(self, tmp_project: Path) -> None:
        """Test automate command parses component option correctly."""
        with patch(RUNNER_PATCH) as mock_runner_cls:
            mock_instance = MagicMock()
            mock_instance.run_automate.return_value = {
                "success": True,
                "output_path": Path("/tmp/out.md"),
                "error": None,
                "metrics": {},
            }
            mock_runner_cls.return_value = mock_instance

            result = runner.invoke(
                app,
                [
                    "tea",
                    "automate",
                    "-r",
                    str(tmp_project),
                    "--component",
                    "auth",
                ],
            )

            mock_instance.run_automate.assert_called_once_with(
                component="auth", mode="create"
            )

    def test_nfr_assess_command_options(self, tmp_project: Path) -> None:
        """Test nfr-assess command parses category option correctly."""
        with patch(RUNNER_PATCH) as mock_runner_cls:
            mock_instance = MagicMock()
            mock_instance.run_nfr_assess.return_value = {
                "success": True,
                "output_path": Path("/tmp/out.md"),
                "error": None,
                "metrics": {},
            }
            mock_runner_cls.return_value = mock_instance

            result = runner.invoke(
                app,
                [
                    "tea",
                    "nfr-assess",
                    "-r",
                    str(tmp_project),
                    "--category",
                    "security",
                ],
            )

            mock_instance.run_nfr_assess.assert_called_once_with(
                category="security", mode="create"
            )

    def test_common_options_provider(self, tmp_project: Path) -> None:
        """Test provider override option works across commands."""
        with patch(RUNNER_PATCH) as mock_runner_cls:
            mock_instance = MagicMock()
            mock_instance.run_framework.return_value = {
                "success": True,
                "output_path": Path("/tmp/out.md"),
                "error": None,
                "metrics": {},
            }
            mock_runner_cls.return_value = mock_instance

            result = runner.invoke(
                app,
                [
                    "tea",
                    "framework",
                    "-r",
                    str(tmp_project),
                    "--provider",
                    "gemini",
                ],
            )

            call_kwargs = mock_runner_cls.call_args[1]
            assert call_kwargs["provider_name"] == "gemini"


# =============================================================================
# Dry-Run Mode Tests (2 tests)
# =============================================================================


class TestDryRunMode:
    """Tests for dry-run mode."""

    def test_dry_run_compiles_workflow(self, tmp_project: Path) -> None:
        """Test dry-run mode compiles workflow without executing."""
        # compile_workflow is imported inside _handle_dry_run, so patch at source
        with patch("bmad_assist.compiler.compile_workflow") as mock_compile:
            mock_compile.return_value = MagicMock(
                context="<xml>...</xml>",
                token_estimate=5000,
            )

            result = runner.invoke(
                app,
                [
                    "tea",
                    "framework",
                    "-r",
                    str(tmp_project),
                    "--dry-run",
                ],
            )

            assert result.exit_code == 0
            mock_compile.assert_called_once()
            # Should show compiled output
            assert "Token estimate" in result.output or "Compiled" in result.output

    def test_dry_run_does_not_execute(self, tmp_project: Path) -> None:
        """Test dry-run mode does not call StandaloneRunner methods."""
        # compile_workflow is imported inside _handle_dry_run, so patch at source
        with patch("bmad_assist.compiler.compile_workflow") as mock_compile:
            mock_compile.return_value = MagicMock(
                context="<xml>...</xml>",
                token_estimate=5000,
            )
            with patch(RUNNER_PATCH) as mock_runner_cls:
                result = runner.invoke(
                    app,
                    [
                        "tea",
                        "ci",
                        "-r",
                        str(tmp_project),
                        "-d",
                    ],
                )

                # StandaloneRunner should not be instantiated in dry-run
                mock_runner_cls.assert_not_called()


# =============================================================================
# Provider Override Tests (2 tests)
# =============================================================================


class TestProviderOverride:
    """Tests for provider override functionality."""

    def test_default_provider(self, tmp_project: Path) -> None:
        """Test default provider is claude-subprocess."""
        with patch(RUNNER_PATCH) as mock_runner_cls:
            mock_instance = MagicMock()
            mock_instance.run_framework.return_value = {
                "success": True,
                "output_path": Path("/tmp/out.md"),
                "error": None,
                "metrics": {},
            }
            mock_runner_cls.return_value = mock_instance

            result = runner.invoke(
                app,
                ["tea", "framework", "-r", str(tmp_project)],
            )

            call_kwargs = mock_runner_cls.call_args[1]
            # When not specified, provider_name should be None
            # (runner defaults to claude-subprocess internally)
            assert call_kwargs.get("provider_name") is None

    def test_provider_override_passed(self, tmp_project: Path) -> None:
        """Test provider override is passed to runner."""
        with patch(RUNNER_PATCH) as mock_runner_cls:
            mock_instance = MagicMock()
            mock_instance.run_framework.return_value = {
                "success": True,
                "output_path": Path("/tmp/out.md"),
                "error": None,
                "metrics": {},
            }
            mock_runner_cls.return_value = mock_instance

            result = runner.invoke(
                app,
                ["tea", "framework", "-r", str(tmp_project), "-P", "codex"],
            )

            call_kwargs = mock_runner_cls.call_args[1]
            assert call_kwargs["provider_name"] == "codex"


# =============================================================================
# Error Case Tests (3 tests)
# =============================================================================


class TestErrorCases:
    """Tests for error handling in CLI commands."""

    def test_invalid_project_path(self) -> None:
        """Test error when project path doesn't exist."""
        result = runner.invoke(
            app,
            ["tea", "framework", "-r", "/nonexistent/path/to/project"],
        )

        assert result.exit_code != 0

    def test_invalid_level_value(self, tmp_project: Path) -> None:
        """Test error when invalid level is provided."""
        result = runner.invoke(
            app,
            [
                "tea",
                "test-design",
                "-r",
                str(tmp_project),
                "--level",
                "invalid",
            ],
        )

        assert result.exit_code != 0
        assert "Invalid level" in result.output

    def test_invalid_category_value(self, tmp_project: Path) -> None:
        """Test error when invalid category is provided."""
        result = runner.invoke(
            app,
            [
                "tea",
                "nfr-assess",
                "-r",
                str(tmp_project),
                "--category",
                "invalid",
            ],
        )

        assert result.exit_code != 0
        assert "Invalid category" in result.output


# =============================================================================
# Help Text Validation Tests (2 tests)
# =============================================================================


class TestHelpText:
    """Tests for help text validation."""

    def test_tea_help_shows_commands(self) -> None:
        """Test tea --help shows all commands."""
        result = runner.invoke(app, ["tea", "--help"])

        assert result.exit_code == 0
        assert "framework" in result.output
        assert "ci" in result.output
        assert "test-design" in result.output
        assert "automate" in result.output
        assert "nfr-assess" in result.output

    def test_framework_help_shows_options(self) -> None:
        """Test framework --help shows all options."""
        result = runner.invoke(app, ["tea", "framework", "--help"])

        assert result.exit_code == 0
        assert "--project-root" in result.output or "-r" in result.output
        assert "--mode" in result.output or "-m" in result.output
        assert "--output-dir" in result.output or "-o" in result.output
        assert "--dry-run" in result.output or "-d" in result.output
        assert "--verbose" in result.output or "-v" in result.output


# =============================================================================
# Success and Failure Output Tests
# =============================================================================


class TestOutputMessages:
    """Tests for CLI output messages."""

    def test_success_message_shown(self, tmp_project: Path) -> None:
        """Test success message is shown on successful execution."""
        with patch(RUNNER_PATCH) as mock_runner_cls:
            mock_instance = MagicMock()
            mock_instance.run_framework.return_value = {
                "success": True,
                "output_path": Path("/tmp/framework-report.md"),
                "error": None,
                "metrics": {},
            }
            mock_runner_cls.return_value = mock_instance

            result = runner.invoke(
                app,
                ["tea", "framework", "-r", str(tmp_project)],
            )

            assert result.exit_code == 0
            assert "complete" in result.output.lower()

    def test_error_message_shown(self, tmp_project: Path) -> None:
        """Test error message is shown on failed execution."""
        with patch(RUNNER_PATCH) as mock_runner_cls:
            mock_instance = MagicMock()
            mock_instance.run_framework.return_value = {
                "success": False,
                "output_path": None,
                "error": "Provider timeout",
                "metrics": {},
            }
            mock_runner_cls.return_value = mock_instance

            result = runner.invoke(
                app,
                ["tea", "framework", "-r", str(tmp_project)],
            )

            assert result.exit_code != 0
            assert "failed" in result.output.lower()

    def test_skip_message_shown(self, tmp_project: Path) -> None:
        """Test skip message is shown when workflow is skipped."""
        with patch(RUNNER_PATCH) as mock_runner_cls:
            mock_instance = MagicMock()
            mock_instance.run_framework.return_value = {
                "success": True,
                "output_path": None,
                "error": None,
                "metrics": {"skipped": True, "reason": "framework already exists"},
            }
            mock_runner_cls.return_value = mock_instance

            result = runner.invoke(
                app,
                ["tea", "framework", "-r", str(tmp_project)],
            )

            assert result.exit_code == 0
            assert "skipped" in result.output.lower()
