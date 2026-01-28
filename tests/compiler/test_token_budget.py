"""Tests for token budget validation - Story 10.10: Token Budget Validation.

Comprehensive tests covering:
- Validation passes under limits (AC1, AC5)
- Soft limit warning at 15k tokens (AC1)
- Hard limit error at 20k tokens (AC2)
- Custom --max-tokens flag honored (AC3)
- Validation disabled with --max-tokens 0 (AC4)
- Exit code 15 for TokenBudgetError (AC5)
- Warning format and suggestions (AC8)
- Dry-run mode behaviors (AC8, AC9)
- Edge cases (exactly at limits, custom soft warning ratio)
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from bmad_assist.cli import app
from bmad_assist.cli_utils import (
    EXIT_SUCCESS,
    EXIT_TOKEN_BUDGET_ERROR,
)
from bmad_assist.compiler import CompiledWorkflow
from bmad_assist.compiler.output import (
    DEFAULT_HARD_LIMIT_TOKENS,
    DEFAULT_SOFT_LIMIT_TOKENS,
    SOFT_LIMIT_RATIO,
    validate_token_budget,
)
from bmad_assist.core.exceptions import TokenBudgetError

runner = CliRunner()

# Mock target for compile_workflow - patched at the compiler module level
COMPILE_WORKFLOW_PATCH = "bmad_assist.compiler.compile_workflow"


def _make_mock_result(token_estimate: int) -> CompiledWorkflow:
    """Create a mock CompiledWorkflow result with specified token estimate."""
    return CompiledWorkflow(
        workflow_name="create-story",
        mission="Test mission",
        context="<test/>",
        variables={},
        instructions="<step>Test</step>",
        output_template="",
        token_estimate=token_estimate,
    )


class TestValidateTokenBudget:
    """Unit tests for validate_token_budget function."""

    def test_passes_under_limits(self) -> None:
        """Validation passes when under both limits."""
        warnings = validate_token_budget(token_estimate=10000, hard_limit=20000)
        assert warnings == []

    def test_warns_at_soft_limit(self) -> None:
        """Warning returned when exceeding soft limit (default 15k)."""
        warnings = validate_token_budget(token_estimate=16000, hard_limit=20000)
        assert len(warnings) == 1
        assert "soft limit" in warnings[0].lower()
        assert "15,000" in warnings[0]
        assert "16,000" in warnings[0]

    def test_errors_at_hard_limit(self) -> None:
        """TokenBudgetError raised when exceeding hard limit (default 20k)."""
        with pytest.raises(TokenBudgetError) as exc_info:
            validate_token_budget(token_estimate=25000, hard_limit=20000)
        error_msg = str(exc_info.value)
        assert "Token budget exceeded" in error_msg
        assert "25,000" in error_msg
        assert "20,000" in error_msg
        assert "How to fix" in error_msg

    def test_custom_limit_honored(self) -> None:
        """Custom hard limit is honored."""
        # Custom limit of 10000 - 12000 tokens should error
        with pytest.raises(TokenBudgetError):
            validate_token_budget(token_estimate=12000, hard_limit=10000)

    def test_custom_limit_soft_warning_ratio(self) -> None:
        """Custom limit uses 75% for soft warning."""
        # 10000 hard limit -> 7500 soft limit
        # 8000 tokens should warn but not error
        warnings = validate_token_budget(token_estimate=8000, hard_limit=10000)
        assert len(warnings) == 1
        assert "7,500" in warnings[0]  # Soft limit = 10000 * 0.75

    def test_disabled_with_zero(self) -> None:
        """Validation disabled when hard_limit=0."""
        # Even huge token count should pass with limit=0
        warnings = validate_token_budget(token_estimate=1000000, hard_limit=0)
        assert warnings == []  # No warnings, no errors

    def test_exactly_at_soft_limit_no_warning(self) -> None:
        """No warning when exactly at soft limit."""
        warnings = validate_token_budget(token_estimate=15000, hard_limit=20000)
        assert warnings == []

    def test_exactly_at_hard_limit_passes(self) -> None:
        """Exactly at hard limit passes (> check, not >=), may have soft warning."""
        # The check is `token_estimate > hard_limit`, so exactly at limit passes
        # 20000 tokens > 15000 soft limit = warning expected, but no error
        warnings = validate_token_budget(token_estimate=20000, hard_limit=20000)
        assert len(warnings) <= 1  # May have soft warning, but no exception raised

    def test_over_hard_limit_errors(self) -> None:
        """Error raised when over hard limit by 1 token."""
        with pytest.raises(TokenBudgetError):
            validate_token_budget(token_estimate=20001, hard_limit=20000)

    def test_warning_message_includes_suggestions(self) -> None:
        """Warning message includes actionable suggestions."""
        warnings = validate_token_budget(token_estimate=17000, hard_limit=20000)
        assert len(warnings) == 1
        warning = warnings[0]
        assert "Reduce context files" in warning
        assert "section extraction" in warning
        assert "sharding" in warning

    def test_error_message_includes_why_and_how(self) -> None:
        """Error message follows Story 10.8 format with Why/How."""
        with pytest.raises(TokenBudgetError) as exc_info:
            validate_token_budget(token_estimate=25000, hard_limit=20000)
        error_msg = str(exc_info.value)
        assert "Why it's needed" in error_msg
        assert "How to fix" in error_msg
        assert "--max-tokens" in error_msg

    def test_default_limits_match_constants(self) -> None:
        """Default limits match module constants."""
        assert DEFAULT_SOFT_LIMIT_TOKENS == 15_000
        assert DEFAULT_HARD_LIMIT_TOKENS == 20_000
        assert SOFT_LIMIT_RATIO == 0.75


class TestCliTokenBudget:
    """CLI integration tests for token budget validation."""

    def test_max_tokens_flag_honored(self, cli_isolated_env: Path) -> None:
        """Custom --max-tokens limit is used."""
        tmp_path = cli_isolated_env
        # 15000 tokens > 10000 custom limit = should fail
        mock_result = _make_mock_result(token_estimate=15000)

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
                    "10000",
                ],
            )

        assert result.exit_code == EXIT_TOKEN_BUDGET_ERROR

    def test_exit_code_15_for_token_budget_error(self, cli_isolated_env: Path) -> None:
        """TokenBudgetError maps to exit code 15."""
        tmp_path = cli_isolated_env
        mock_result = _make_mock_result(token_estimate=25000)

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

        assert result.exit_code == EXIT_TOKEN_BUDGET_ERROR
        assert result.exit_code == 15

    def test_soft_limit_warning_success(self, cli_isolated_env: Path) -> None:
        """Soft limit warning displayed but compilation succeeds."""
        tmp_path = cli_isolated_env
        # 17000 tokens: over soft (15k) but under hard (20k)
        mock_result = _make_mock_result(token_estimate=17000)

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
        assert "Warning" in result.output
        assert "17,000" in result.output

    def test_max_tokens_zero_disables_validation(self, cli_isolated_env: Path) -> None:
        """--max-tokens 0 disables validation entirely."""
        tmp_path = cli_isolated_env
        # Even huge token count should pass
        mock_result = _make_mock_result(token_estimate=100000)

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
                    "0",
                ],
            )

        assert result.exit_code == EXIT_SUCCESS

    def test_dry_run_hard_limit_no_stdout(self, cli_isolated_env: Path) -> None:
        """Dry-run with hard limit exceeded: no XML to stdout."""
        tmp_path = cli_isolated_env
        mock_result = _make_mock_result(token_estimate=25000)

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
                    "--dry-run",
                ],
            )

        assert result.exit_code == EXIT_TOKEN_BUDGET_ERROR
        # stdout should NOT contain the XML content (error prevented output)
        assert "<test/>" not in result.output

    def test_dry_run_soft_warning_continues(self, cli_isolated_env: Path) -> None:
        """Dry-run with soft limit warning still produces XML output."""
        tmp_path = cli_isolated_env
        mock_result = _make_mock_result(token_estimate=17000)

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
                    "--dry-run",
                ],
            )

        assert result.exit_code == EXIT_SUCCESS
        # XML should still be in output (dry-run prints to stdout)
        assert "<test/>" in result.output

    def test_error_message_includes_token_count(self, cli_isolated_env: Path) -> None:
        """Error message includes current token count."""
        tmp_path = cli_isolated_env
        mock_result = _make_mock_result(token_estimate=24512)

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

        assert result.exit_code == EXIT_TOKEN_BUDGET_ERROR
        assert "24,512" in result.output

    @pytest.mark.skipif(os.geteuid() == 0, reason="Rich/Typer help broken in Docker as root")
    def test_help_shows_max_tokens_option(self, cli_isolated_env: Path) -> None:
        """--help shows --max-tokens option."""
        result = runner.invoke(app, ["compile", "--help"])
        assert result.exit_code == 0
        assert "--max-tokens" in result.output
        assert "-m" in result.output
        # Help text includes info about disabling
        assert "disable" in result.output.lower()

    def test_negative_max_tokens_rejected(self, cli_isolated_env: Path) -> None:
        """Negative --max-tokens value is rejected with exit code 2."""
        tmp_path = cli_isolated_env
        from bmad_assist.cli import EXIT_CONFIG_ERROR

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
                "-1",
            ],
        )

        assert result.exit_code == EXIT_CONFIG_ERROR
        assert "--max-tokens must be >= 0" in result.output

    def test_no_file_written_on_hard_limit_error(self, cli_isolated_env: Path) -> None:
        """No output file written when hard limit exceeded."""
        tmp_path = cli_isolated_env
        mock_result = _make_mock_result(token_estimate=25000)

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

        assert result.exit_code == EXIT_TOKEN_BUDGET_ERROR
        output_file = tmp_path / "compiled-prompts" / "create-story-1-1.xml"
        assert not output_file.exists()

    def test_file_written_on_soft_limit_warning(self, cli_isolated_env: Path) -> None:
        """Output file still written when only soft limit exceeded."""
        tmp_path = cli_isolated_env
        mock_result = _make_mock_result(token_estimate=17000)

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
        output_file = tmp_path / "compiled-prompts" / "create-story-1-1.xml"
        assert output_file.exists()


class TestTokenBudgetExceptionHierarchy:
    """Tests for TokenBudgetError exception hierarchy."""

    def test_inherits_from_compiler_error(self) -> None:
        """TokenBudgetError inherits from CompilerError."""
        from bmad_assist.core.exceptions import CompilerError

        assert issubclass(TokenBudgetError, CompilerError)

    def test_inherits_from_bmad_assist_error(self) -> None:
        """TokenBudgetError inherits from BmadAssistError."""
        from bmad_assist.core.exceptions import BmadAssistError

        assert issubclass(TokenBudgetError, BmadAssistError)

    def test_can_be_caught_as_compiler_error(self) -> None:
        """TokenBudgetError can be caught as CompilerError."""
        from bmad_assist.core.exceptions import CompilerError

        try:
            raise TokenBudgetError("test")
        except CompilerError:
            pass  # Expected - should catch
        else:
            pytest.fail("TokenBudgetError not caught as CompilerError")

    def test_importable_from_core_exceptions(self) -> None:
        """TokenBudgetError is importable from core.exceptions."""
        from bmad_assist.core.exceptions import TokenBudgetError as ImportedError

        assert ImportedError is TokenBudgetError
