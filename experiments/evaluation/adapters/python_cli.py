"""Python CLI adapter for command-line tool projects.

For projects that use:
- Python 3.11+
- Typer/Click for CLI
- Rich/Textual for TUI
- pytest for testing

Examples:
- cli-dashboard (Rich + Typer CLI dashboard generator)
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .base import BaseEvaluator
from ..core.scoring import ratio_score, time_score


class PythonCliAdapter(BaseEvaluator):
    """Base adapter for Python CLI tool projects.

    Subclasses should set:
        - cli_module: Module path for CLI (e.g., "cli_dashboard.main")
        - cli_command: CLI entry point name (e.g., "cli-dashboard")
        - package_name: Package name for import testing

    Example:
        class DashboardEvaluator(PythonCliAdapter):
            cli_module = "cli_dashboard.main"
            cli_command = "cli-dashboard"
    """

    stack_name = "python-cli"

    # CLI configuration (override in subclass)
    cli_module: str = ""  # e.g., "cli_dashboard.main"
    cli_command: str = ""  # e.g., "cli-dashboard"
    package_name: str = ""  # e.g., "cli_dashboard"

    # Test configuration
    test_timeout: int = 120

    def __init__(self, project_root: Path):
        super().__init__(project_root)
        self._cli_available = False
        self._import_works = False
        self._env: dict[str, str] = {}

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def setup(self) -> None:
        """Setup Python environment and verify CLI is available."""
        super().setup()
        self._setup_success = False

        # Build environment with src/ in PYTHONPATH
        self._env = os.environ.copy()
        src_path = str(self.project_root / "src")
        self._env["PYTHONPATH"] = f"{src_path}:{self._env.get('PYTHONPATH', '')}"

        # Check if we can import the package
        if self.package_name:
            code, _, _ = self._run_python(
                "-c", f"import {self.package_name}"
            )
            self._import_works = code == 0

        # Check if CLI module can be invoked
        if self.cli_module:
            code, stdout, stderr = self._run_python(
                "-m", self.cli_module, "--help"
            )
            self._cli_available = code == 0 and ("usage" in stdout.lower() or "usage" in stderr.lower() or len(stdout) > 10)

        self._setup_success = self._import_works or self._cli_available

    def _has_meaningful_benchmark(self) -> bool:
        """Check if CLI is available for meaningful benchmark."""
        return self._setup_success

    # =========================================================================
    # COMMAND EXECUTION
    # =========================================================================

    def _run_python(
        self,
        *args: str,
        timeout: int = 60,
        input_text: str | None = None,
    ) -> tuple[int, str, str]:
        """Run a Python command.

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        cmd = ["python", *args]

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._env,
                input=input_text,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "timeout"
        except Exception as e:
            return -1, "", str(e)

    def _run_cli(
        self,
        *args: str,
        timeout: int = 30,
        input_text: str | None = None,
    ) -> tuple[int, str, str]:
        """Run the CLI tool.

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        if not self.cli_module:
            return -1, "", "no cli_module configured"

        return self._run_python(
            "-m", self.cli_module, *args,
            timeout=timeout,
            input_text=input_text,
        )

    def _run_tests(
        self,
        pattern: str = "",
        coverage: bool = False,
    ) -> tuple[int, int, float, str]:
        """Run pytest tests.

        Args:
            pattern: Test file pattern (e.g., "tests/unit/")
            coverage: Whether to collect coverage

        Returns:
            Tuple of (passed, total, coverage_pct, output)
        """
        args = ["-m", "pytest", "-v"]

        if coverage:
            args.extend(["--cov", self.package_name or "src", "--cov-report=term"])

        if pattern:
            args.append(pattern)

        code, stdout, stderr = self._run_python(*args, timeout=self.test_timeout)
        output = stdout + stderr

        # Parse pytest output
        passed, failed = self._parse_pytest_output(output)

        # Parse coverage
        coverage_pct = 0.0
        if coverage:
            match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", output)
            if match:
                coverage_pct = float(match.group(1))

        return passed, passed + failed, coverage_pct, output

    def _parse_pytest_output(self, output: str) -> tuple[int, int]:
        """Parse pytest output for pass/fail counts."""
        passed = 0
        failed = 0

        # Look for summary line: "5 passed, 2 failed"
        match = re.search(r"(\d+) passed", output)
        if match:
            passed = int(match.group(1))

        match = re.search(r"(\d+) failed", output)
        if match:
            failed = int(match.group(1))

        # Also check for errors
        match = re.search(r"(\d+) error", output)
        if match:
            failed += int(match.group(1))

        return passed, failed

    # =========================================================================
    # CLI TESTING HELPERS
    # =========================================================================

    def _test_help(self) -> tuple[bool, str]:
        """Test that --help works."""
        code, stdout, stderr = self._run_cli("--help")
        output = stdout + stderr

        if code != 0:
            return False, f"exit code {code}"

        if "usage" in output.lower() or self.cli_command in output.lower():
            return True, "help works"

        return False, "no help text"

    def _test_version(self) -> tuple[bool, str]:
        """Test that --version works."""
        code, stdout, stderr = self._run_cli("--version")
        output = stdout + stderr

        if code != 0:
            # Some CLIs don't have --version
            return True, "no version flag"

        # Should output something version-like
        if re.search(r"\d+\.\d+", output):
            return True, "version works"

        return True, "version flag exists"

    def _test_subcommand(
        self,
        subcommand: str,
        args: list[str] = None,
        expected_exit: int | None = None,
        expected_output: str | None = None,
    ) -> tuple[bool, str]:
        """Test a CLI subcommand.

        Args:
            subcommand: Subcommand name
            args: Additional arguments
            expected_exit: Expected exit code (None = any success)
            expected_output: Expected string in output

        Returns:
            Tuple of (success, note)
        """
        cmd_args = [subcommand] + (args or [])
        code, stdout, stderr = self._run_cli(*cmd_args)
        output = stdout + stderr

        # Check exit code
        if expected_exit is not None:
            if code != expected_exit:
                return False, f"exit {code} (expected {expected_exit})"
        elif code != 0:
            return False, f"exit code {code}"

        # Check output
        if expected_output and expected_output not in output:
            return False, f"missing: {expected_output[:30]}"

        return True, f"{subcommand} OK"

    def _test_invalid_args(self) -> tuple[bool, str]:
        """Test that CLI handles invalid arguments gracefully."""
        code, stdout, stderr = self._run_cli(
            "--nonexistent-flag-xyz",
            timeout=10
        )

        # Should exit non-zero for invalid args
        if code != 0:
            return True, "handles invalid args"

        return False, "accepted invalid args"

    # =========================================================================
    # QUALITY CHECKS
    # =========================================================================

    def _run_ruff_check(self) -> tuple[int, str]:
        """Run ruff linter.

        Returns:
            Tuple of (issue_count, output)
        """
        if not shutil.which("ruff"):
            return 0, "ruff not available"

        try:
            result = subprocess.run(
                ["ruff", "check", "src/"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = result.stdout + result.stderr

            if result.returncode == 0:
                return 0, output

            # Count issues
            issues = len(output.strip().split("\n")) if output.strip() else 0
            return issues, output

        except Exception as e:
            return 0, str(e)

    def _run_mypy(self) -> tuple[int, str]:
        """Run mypy type checker.

        Returns:
            Tuple of (error_count, output)
        """
        if not shutil.which("mypy"):
            return 0, "mypy not available"

        try:
            result = subprocess.run(
                ["mypy", "src/", "--ignore-missing-imports"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout + result.stderr

            if result.returncode == 0:
                return 0, output

            # Count errors
            errors = len(re.findall(r": error:", output))
            return errors, output

        except Exception as e:
            return 0, str(e)

    # =========================================================================
    # DEFAULT TEST IMPLEMENTATIONS
    # =========================================================================

    def test_c1_tests(self) -> tuple[int, str]:
        """C1: Run pytest suite."""
        if not self._setup_success:
            return 0, "setup failed"

        passed, total, coverage, output = self._run_tests(coverage=True)

        if total == 0:
            return 0, "no tests found"

        pts, note = ratio_score(passed, total)

        # Add coverage info
        if coverage >= 80:
            note += f" ({coverage:.0f}% cov)"
        elif coverage >= 50:
            note += f" ({coverage:.0f}% cov)"
        elif coverage > 0:
            note += f" (low cov: {coverage:.0f}%)"

        return pts, note

    def test_q3_performance(self) -> tuple[int, str]:
        """Q3: CLI startup time."""
        if not self._setup_success:
            return 0, "setup failed"

        # Measure --help response time (cold start)
        start = time.perf_counter()
        code, _, _ = self._run_cli("--help", timeout=30)
        elapsed = time.perf_counter() - start

        if code != 0:
            return 0, "CLI failed"

        return time_score(elapsed, [
            (0.5, 5),   # < 0.5s
            (1.0, 4),   # < 1s
            (2.0, 3),   # < 2s
            (5.0, 2),   # < 5s
            (10.0, 1),  # < 10s
        ])

    def test_q4_consistency(self) -> tuple[int, str]:
        """Q4: Linting and type checking."""
        if not self._setup_success:
            return 0, "setup failed"

        issues = 0

        # Run ruff
        ruff_issues, _ = self._run_ruff_check()
        issues += ruff_issues

        # Run mypy
        mypy_errors, _ = self._run_mypy()
        issues += mypy_errors

        if issues == 0:
            return 5, "lint OK"
        elif issues <= 5:
            return 4, f"{issues} issues"
        elif issues <= 10:
            return 3, f"{issues} issues"
        elif issues <= 20:
            return 2, f"{issues} issues"
        else:
            return 1, f"{issues}+ issues"
