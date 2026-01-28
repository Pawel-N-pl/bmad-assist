"""Tests for CLI compile command - Story 10.9: CLI Compile Command.

Comprehensive tests covering:
- Basic compilation success (AC1)
- Custom output path (AC2)
- Dry-run mode (AC3)
- Project path override (AC4)
- Exit code mapping (AC5)
- Error message display (AC6)
- Help text and argument validation (AC7)
- Default output directory creation (AC8)
- Output file overwrite and atomic write (AC9)
- Relative output path resolution (AC10)
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from bmad_assist.cli import app
from bmad_assist.cli_utils import (
    EXIT_AMBIGUOUS_ERROR,
    EXIT_COMPILER_ERROR,
    EXIT_CONFIG_ERROR,
    EXIT_ERROR,
    EXIT_FRAMEWORK_ERROR,
    EXIT_PARSER_ERROR,
    EXIT_SUCCESS,
    EXIT_VARIABLE_ERROR,
)
from bmad_assist.compiler import CompiledWorkflow
from bmad_assist.core.exceptions import (
    AmbiguousFileError,
    BmadAssistError,
    CompilerError,
    ParserError,
    VariableError,
)

runner = CliRunner()

# Mock target for compile_workflow - patched at the compiler module level
# because cli.py imports it lazily inside the compile function
COMPILE_WORKFLOW_PATCH = "bmad_assist.compiler.compile_workflow"


def _make_mock_result(xml: str = "<test></test>", token_estimate: int = 100) -> CompiledWorkflow:
    """Create a mock CompiledWorkflow result for testing.

    Args:
        xml: XML content to return (stored in .context field)
        token_estimate: Token estimate value

    Returns:
        CompiledWorkflow with test data.

    """
    return CompiledWorkflow(
        workflow_name="test",
        mission="Test mission",
        context=xml,  # XML is stored in context field
        variables={},
        instructions="",
        output_template="",
        token_estimate=token_estimate,
    )


# =============================================================================
# Test: Exit Code Constants (AC5)
# =============================================================================


class TestCompilerExitCodes:
    """Tests for compiler exit code constants (AC5)."""

    def test_exit_parser_error_is_ten(self) -> None:
        """AC5: ParserError exit code is 10."""
        assert EXIT_PARSER_ERROR == 10

    def test_exit_variable_error_is_eleven(self) -> None:
        """AC5: VariableError exit code is 11."""
        assert EXIT_VARIABLE_ERROR == 11

    def test_exit_ambiguous_error_is_twelve(self) -> None:
        """AC5: AmbiguousFileError exit code is 12."""
        assert EXIT_AMBIGUOUS_ERROR == 12

    def test_exit_compiler_error_is_thirteen(self) -> None:
        """AC5: CompilerError exit code is 13."""
        assert EXIT_COMPILER_ERROR == 13

    def test_exit_framework_error_is_fourteen(self) -> None:
        """AC5: BmadAssistError exit code is 14."""
        assert EXIT_FRAMEWORK_ERROR == 14


# =============================================================================
# Test: Help Text and Arguments (AC7)
# =============================================================================


@pytest.mark.skipif(os.geteuid() == 0, reason="Rich/Typer help broken in Docker as root")
class TestCompileHelpOutput:
    """Tests for compile command help text (AC7)."""

    def test_compile_help_exits_successfully(self, cli_isolated_env: Path) -> None:
        """AC7: compile --help exits with code 0."""
        result = runner.invoke(app, ["compile", "--help"])
        assert result.exit_code == 0

    def test_compile_help_shows_workflow_option(self, cli_isolated_env: Path) -> None:
        """AC7: Help shows --workflow / -w option."""
        result = runner.invoke(app, ["compile", "--help"])
        assert "--workflow" in result.output
        assert "-w" in result.output

    def test_compile_help_shows_epic_option(self, cli_isolated_env: Path) -> None:
        """AC7: Help shows --epic / -e option."""
        result = runner.invoke(app, ["compile", "--help"])
        assert "--epic" in result.output
        assert "-e" in result.output

    def test_compile_help_shows_story_option(self, cli_isolated_env: Path) -> None:
        """AC7: Help shows --story / -s option."""
        result = runner.invoke(app, ["compile", "--help"])
        assert "--story" in result.output
        assert "-s" in result.output

    def test_compile_help_shows_output_option(self, cli_isolated_env: Path) -> None:
        """AC7: Help shows --output / -o option."""
        result = runner.invoke(app, ["compile", "--help"])
        assert "--output" in result.output
        assert "-o" in result.output

    def test_compile_help_shows_project_option(self, cli_isolated_env: Path) -> None:
        """AC7: Help shows --project / -p option."""
        result = runner.invoke(app, ["compile", "--help"])
        assert "--project" in result.output
        assert "-p" in result.output

    def test_compile_help_shows_dry_run_option(self, cli_isolated_env: Path) -> None:
        """AC7: Help shows --dry-run / -d option."""
        result = runner.invoke(app, ["compile", "--help"])
        assert "--dry-run" in result.output
        assert "-d" in result.output

    def test_compile_help_shows_verbose_option(self, cli_isolated_env: Path) -> None:
        """AC7: Help shows --verbose / -v option."""
        result = runner.invoke(app, ["compile", "--help"])
        assert "--verbose" in result.output
        assert "-v" in result.output

    def test_compile_help_shows_command_in_cli_help(self, cli_isolated_env: Path) -> None:
        """AC7: Main CLI help shows compile command."""
        result = runner.invoke(app, ["--help"])
        assert "compile" in result.output


class TestEpicStoryValidation:
    """Tests for epic/story number validation."""

    def test_negative_epic_number_fails(self, cli_isolated_env: Path) -> None:
        """Negative epic number returns exit code 2 (config error)."""
        tmp_path = cli_isolated_env
        result = runner.invoke(
            app,
            ["compile", "-w", "create-story", "-e", "-1", "-s", "1", "-p", str(tmp_path)],
        )
        assert result.exit_code == EXIT_CONFIG_ERROR
        assert "positive integer" in result.output.lower()

    def test_zero_epic_number_fails(self, cli_isolated_env: Path) -> None:
        """Zero epic number returns exit code 2 (config error)."""
        tmp_path = cli_isolated_env
        result = runner.invoke(
            app,
            ["compile", "-w", "create-story", "-e", "0", "-s", "1", "-p", str(tmp_path)],
        )
        assert result.exit_code == EXIT_CONFIG_ERROR
        assert "positive integer" in result.output.lower()

    def test_negative_story_number_fails(self, cli_isolated_env: Path) -> None:
        """Negative story number returns exit code 2 (config error)."""
        tmp_path = cli_isolated_env
        result = runner.invoke(
            app,
            ["compile", "-w", "create-story", "-e", "1", "-s", "-5", "-p", str(tmp_path)],
        )
        assert result.exit_code == EXIT_CONFIG_ERROR
        assert "positive integer" in result.output.lower()

    def test_zero_story_number_fails(self, cli_isolated_env: Path) -> None:
        """Zero story number returns exit code 2 (config error)."""
        tmp_path = cli_isolated_env
        result = runner.invoke(
            app,
            ["compile", "-w", "create-story", "-e", "1", "-s", "0", "-p", str(tmp_path)],
        )
        assert result.exit_code == EXIT_CONFIG_ERROR
        assert "positive integer" in result.output.lower()


class TestMissingRequiredArguments:
    """Tests for missing required arguments (AC7)."""

    def test_missing_all_required_args_shows_error(self) -> None:
        """AC7: Missing all required args returns exit code 2."""
        result = runner.invoke(app, ["compile"])
        assert result.exit_code == 2
        assert "Missing option" in result.output or "--workflow" in result.output

    def test_missing_workflow_shows_error(self, tmp_path: Path) -> None:
        """AC7: Missing --workflow shows error."""
        result = runner.invoke(
            app,
            ["compile", "--epic", "1", "--story", "1", "--project", str(tmp_path)],
        )
        assert result.exit_code == 2
        assert "--workflow" in result.output

    def test_missing_epic_shows_error(self, tmp_path: Path) -> None:
        """AC7: Missing --epic shows error."""
        result = runner.invoke(
            app,
            ["compile", "--workflow", "create-story", "--story", "1", "--project", str(tmp_path)],
        )
        assert result.exit_code == 2
        assert "--epic" in result.output

    def test_missing_story_shows_error(self, tmp_path: Path) -> None:
        """AC7: Missing --story shows error."""
        result = runner.invoke(
            app,
            ["compile", "--workflow", "create-story", "--epic", "1", "--project", str(tmp_path)],
        )
        assert result.exit_code == 2
        assert "--story" in result.output


# =============================================================================
# Test: Basic Compilation (AC1)
# =============================================================================


class TestBasicCompilation:
    """Tests for basic compilation functionality (AC1)."""

    def test_compile_creates_output_file(self, cli_isolated_env: Path) -> None:
        """AC1: Successful compilation creates output file."""
        tmp_path = cli_isolated_env
        mock_result = _make_mock_result("<compiled-workflow></compiled-workflow>", 100)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            result = runner.invoke(
                app,
                ["compile", "-w", "create-story", "-e", "10", "-s", "9", "-p", str(tmp_path)],
            )

        assert result.exit_code == EXIT_SUCCESS
        output_path = tmp_path / "compiled-prompts" / "create-story-10-9.xml"
        assert output_path.exists()
        assert "<compiled-workflow>" in output_path.read_text()

    def test_compile_shows_success_message(self, cli_isolated_env: Path) -> None:
        """AC1: Success message shows output path and token count."""
        tmp_path = cli_isolated_env
        mock_result = _make_mock_result("<compiled-workflow></compiled-workflow>", 8234)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            result = runner.invoke(
                app,
                ["compile", "-w", "create-story", "-e", "10", "-s", "9", "-p", str(tmp_path)],
            )

        assert result.exit_code == EXIT_SUCCESS
        assert "✓" in result.output or "Compiled" in result.output
        assert "create-story" in result.output
        assert "8,234" in result.output or "8234" in result.output


# =============================================================================
# Test: Custom Output Path (AC2)
# =============================================================================


class TestCustomOutputPath:
    """Tests for custom output path functionality (AC2)."""

    def test_compile_custom_output_path(self, cli_isolated_env: Path) -> None:
        """AC2: Custom --output path is respected."""
        tmp_path = cli_isolated_env
        custom_output = tmp_path / "custom" / "my-prompt.xml"
        mock_result = _make_mock_result("<compiled-workflow></compiled-workflow>", 100)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "10",
                    "-s",
                    "9",
                    "-p",
                    str(tmp_path),
                    "-o",
                    str(custom_output),
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        assert custom_output.exists()
        # Output may be wrapped by Rich console, so check key parts exist
        output_no_newlines = result.output.replace("\n", "")
        assert "my-prompt.xml" in output_no_newlines

    def test_compile_creates_parent_directories(self, cli_isolated_env: Path) -> None:
        """AC2: Parent directories are created if they don't exist."""
        tmp_path = cli_isolated_env
        # Deep nested path that doesn't exist
        custom_output = tmp_path / "deep" / "nested" / "path" / "output.xml"
        mock_result = _make_mock_result("<compiled-workflow></compiled-workflow>", 100)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(tmp_path),
                    "-o",
                    str(custom_output),
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        assert custom_output.exists()


# =============================================================================
# Test: Dry-Run Mode (AC3)
# =============================================================================


class TestDryRunMode:
    """Tests for dry-run mode functionality (AC3)."""

    def test_compile_dry_run_prints_xml_to_stdout(self, cli_isolated_env: Path) -> None:
        """AC3: Dry-run prints XML to stdout, not file."""
        tmp_path = cli_isolated_env
        xml_content = "<compiled-workflow><test>content</test></compiled-workflow>"
        mock_result = _make_mock_result(xml_content, 100)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "10",
                    "-s",
                    "9",
                    "-p",
                    str(tmp_path),
                    "--dry-run",
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        assert "<compiled-workflow>" in result.output
        # No file should be created
        default_path = tmp_path / "compiled-prompts" / "create-story-10-9.xml"
        assert not default_path.exists()

    def test_compile_dry_run_no_file_created(self, cli_isolated_env: Path) -> None:
        """AC3: Dry-run does not create output file."""
        tmp_path = cli_isolated_env
        mock_result = _make_mock_result("<test></test>", 50)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(tmp_path),
                    "-d",
                ],
            )

        # Verify no files were created
        compiled_prompts = tmp_path / "compiled-prompts"
        assert not compiled_prompts.exists()


# =============================================================================
# Test: Project Path Override (AC4)
# =============================================================================


class TestProjectPathOverride:
    """Tests for project path override functionality (AC4)."""

    def test_compile_project_path_used(self, cli_isolated_env: Path) -> None:
        """AC4: Project path override is used for compilation."""
        tmp_path = cli_isolated_env
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()

        mock_result = _make_mock_result("<test></test>", 50)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result) as mock_compile:
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(project_dir),
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        # Verify compile_workflow was called with correct project path
        call_args = mock_compile.call_args
        context = call_args[0][1]
        assert context.project_root == project_dir

    def test_compile_nonexistent_project_path_exits_error(self, cli_isolated_env: Path) -> None:
        """AC4: Nonexistent project path returns exit code 1."""
        tmp_path = cli_isolated_env
        nonexistent = tmp_path / "nonexistent"

        result = runner.invoke(
            app,
            [
                "compile",
                "-w",
                "create-story",
                "-e",
                "1",
                "-s",
                "1",
                "-p",
                str(nonexistent),
            ],
        )

        assert result.exit_code == EXIT_ERROR
        assert "not found" in result.output.lower()


# =============================================================================
# Test: Exit Code Mapping (AC5)
# =============================================================================


class TestExitCodeMapping:
    """Tests for exit code mapping (AC5)."""

    @pytest.mark.parametrize(
        "error_class,exit_code",
        [
            (ParserError, EXIT_PARSER_ERROR),
            (VariableError, EXIT_VARIABLE_ERROR),
            (AmbiguousFileError, EXIT_AMBIGUOUS_ERROR),
            (CompilerError, EXIT_COMPILER_ERROR),
            (BmadAssistError, EXIT_FRAMEWORK_ERROR),
        ],
    )
    def test_exit_code_mapping(
        self,
        error_class: type[Exception],
        exit_code: int,
        cli_isolated_env: Path,
    ) -> None:
        """AC5: Each exception type maps to correct exit code (codes 10-14)."""
        tmp_path = cli_isolated_env

        def mock_compile(*args, **kwargs):
            raise error_class("Test error")

        with patch(COMPILE_WORKFLOW_PATCH, side_effect=mock_compile):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == exit_code


# =============================================================================
# Test: Error Message Display (AC6)
# =============================================================================


class TestErrorMessageDisplay:
    """Tests for error message display (AC6)."""

    def test_error_message_shows_red_error(self, cli_isolated_env: Path) -> None:
        """AC6: Error messages show with Error: prefix."""
        tmp_path = cli_isolated_env

        def mock_compile(*args, **kwargs):
            raise CompilerError("Test error message")

        with patch(COMPILE_WORKFLOW_PATCH, side_effect=mock_compile):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(tmp_path),
                ],
            )

        assert "Error:" in result.output
        assert "Test error message" in result.output

    def test_error_message_preserves_multiline(self, cli_isolated_env: Path) -> None:
        """AC6: Multiline error messages preserve Why/How format."""
        tmp_path = cli_isolated_env
        error_msg = (
            "project_context.md not found: /path/to/file\n"
            "  Why it's needed: Critical for AI agents\n"
            "  How to fix: Run generate-project-context"
        )

        def mock_compile(*args, **kwargs):
            raise CompilerError(error_msg)

        with patch(COMPILE_WORKFLOW_PATCH, side_effect=mock_compile):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(tmp_path),
                ],
            )

        assert "Why it's needed:" in result.output
        assert "How to fix:" in result.output

    def test_verbose_mode_shows_traceback(self, cli_isolated_env: Path) -> None:
        """AC6: Verbose mode shows full traceback on error."""
        tmp_path = cli_isolated_env

        def mock_compile(*args, **kwargs):
            raise CompilerError("Test error")

        with patch(COMPILE_WORKFLOW_PATCH, side_effect=mock_compile):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(tmp_path),
                    "-v",
                ],
            )

        assert result.exit_code == EXIT_COMPILER_ERROR
        # Verbose mode shows traceback
        assert "Traceback" in result.output or "CompilerError" in result.output


# =============================================================================
# Test: Default Output Directory Creation (AC8)
# =============================================================================


class TestOutputDirectoryCreation:
    """Tests for output directory creation (AC8)."""

    def test_creates_compiled_prompts_directory(self, cli_isolated_env: Path) -> None:
        """AC8: compiled-prompts/ directory is created automatically."""
        tmp_path = cli_isolated_env
        mock_result = _make_mock_result("<test></test>", 50)

        # Ensure directory doesn't exist
        compiled_prompts = tmp_path / "compiled-prompts"
        assert not compiled_prompts.exists()

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        assert compiled_prompts.exists()
        assert (compiled_prompts / "create-story-1-1.xml").exists()


# =============================================================================
# Test: Output File Overwrite and Atomic Write (AC9)
# =============================================================================


class TestAtomicWriteAndOverwrite:
    """Tests for output file overwrite and atomic write (AC9)."""

    def test_overwrites_existing_file(self, cli_isolated_env: Path) -> None:
        """AC9: Existing file is overwritten silently."""
        tmp_path = cli_isolated_env
        # Create existing file
        compiled_prompts = tmp_path / "compiled-prompts"
        compiled_prompts.mkdir()
        output_file = compiled_prompts / "create-story-1-1.xml"
        output_file.write_text("old content")

        mock_result = _make_mock_result("<new>content</new>", 50)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        assert output_file.read_text() == "<new>content</new>"

    def test_atomic_write_no_partial_on_error(self, cli_isolated_env: Path) -> None:
        """AC9: No partial output is written if compilation fails mid-write."""
        tmp_path = cli_isolated_env
        compiled_prompts = tmp_path / "compiled-prompts"
        compiled_prompts.mkdir()
        output_file = compiled_prompts / "create-story-1-1.xml"

        # Create mock that raises during file write (after mkdir, before rename)
        mock_result = _make_mock_result("<test>content</test>", 50)

        # Patch os.replace to simulate write failure
        with (
            patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result),
            patch("bmad_assist.cli.os.replace", side_effect=OSError("Disk full")),
        ):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(tmp_path),
                ],
            )

        # Error should be raised
        assert result.exit_code != EXIT_SUCCESS
        # No partial file should exist
        assert not output_file.exists()
        # Temp file should be cleaned up
        temp_file = output_file.with_suffix(".tmp")
        assert not temp_file.exists()


# =============================================================================
# Test: Relative Output Path Resolution (AC10)
# =============================================================================


class TestRelativeOutputPathResolution:
    """Tests for relative output path resolution (AC10)."""

    def test_relative_output_resolved_to_cwd(
        self,
        cli_isolated_env: Path,
    ) -> None:
        """AC10: Relative --output path resolved against CWD, not --project."""
        tmp_path = cli_isolated_env
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        # CWD is already set to tmp_path by cli_isolated_env
        cwd = tmp_path

        mock_result = _make_mock_result("<test></test>", 50)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(project_dir),
                    "-o",
                    "./output.xml",
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        # Output should be in CWD, not project dir
        assert (cwd / "output.xml").exists()
        assert not (project_dir / "output.xml").exists()

    def test_absolute_output_path_honored(self, cli_isolated_env: Path) -> None:
        """AC10: Absolute output path is used as-is."""
        tmp_path = cli_isolated_env
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        absolute_output = tmp_path / "absolute" / "output.xml"

        mock_result = _make_mock_result("<test></test>", 50)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(project_dir),
                    "-o",
                    str(absolute_output),
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        assert absolute_output.exists()


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_invalid_workflow_name_returns_compiler_error(self, cli_isolated_env: Path) -> None:
        """Invalid workflow name returns exit code 13 (CompilerError)."""
        tmp_path = cli_isolated_env

        def mock_compile(*args, **kwargs):
            raise CompilerError("Unknown workflow: invalid-workflow")

        with patch(COMPILE_WORKFLOW_PATCH, side_effect=mock_compile):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "invalid-workflow",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == EXIT_COMPILER_ERROR

    def test_large_output_not_truncated(self, cli_isolated_env: Path) -> None:
        """Large output is not truncated."""
        tmp_path = cli_isolated_env
        # Generate large XML content (> 100KB)
        large_content = "<compiled-workflow>" + ("x" * 200_000) + "</compiled-workflow>"
        mock_result = _make_mock_result(large_content, 50000)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "1",
                    "-s",
                    "1",
                    "-p",
                    str(tmp_path),
                    "--max-tokens",
                    "0",  # Disable token validation for size test
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        output_file = tmp_path / "compiled-prompts" / "create-story-1-1.xml"
        assert len(output_file.read_text()) == len(large_content)

    def test_default_output_path_formula(self, cli_isolated_env: Path) -> None:
        """Default path follows formula: {project}/compiled-prompts/{workflow}-{e}-{s}.xml."""
        tmp_path = cli_isolated_env
        mock_result = _make_mock_result("<test></test>", 50)

        with patch(COMPILE_WORKFLOW_PATCH, return_value=mock_result):
            result = runner.invoke(
                app,
                [
                    "compile",
                    "-w",
                    "create-story",
                    "-e",
                    "10",
                    "-s",
                    "9",
                    "-p",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        expected_path = tmp_path / "compiled-prompts" / "create-story-10-9.xml"
        assert expected_path.exists()
