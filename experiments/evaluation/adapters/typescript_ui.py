"""TypeScript UI adapter for React/Svelte/Vue frontend projects.

For projects that use:
- TypeScript/JavaScript
- Vitest/Jest for unit testing
- Playwright/Cypress for e2e testing
- npm/pnpm/yarn for package management

Examples:
- component-library (React + Vitest + Storybook)
- markdown-notes (SvelteKit + Vitest + Playwright)
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .base import BaseEvaluator
from ..core.scoring import ratio_score, time_score


class TypeScriptUiAdapter(BaseEvaluator):
    """Base adapter for TypeScript/JavaScript UI projects.

    Subclasses should set:
        - package_manager: "npm", "pnpm", or "yarn"
        - test_framework: "vitest" or "jest"
        - e2e_framework: "playwright", "cypress", or None
        - dev_server_command: Command to start dev server (optional)
        - dev_server_port: Port for dev server

    Example:
        class ComponentLibraryEvaluator(TypeScriptUiAdapter):
            package_manager = "npm"
            test_framework = "vitest"
    """

    stack_name = "typescript-ui"

    # Package management (override in subclass)
    package_manager: str = "npm"  # npm, pnpm, yarn
    node_version: str = "18"  # Minimum Node.js version

    # Test configuration
    test_framework: str = "vitest"  # vitest or jest
    test_command: list[str] = []  # Auto-generated if empty
    e2e_framework: str | None = None  # playwright, cypress, or None
    e2e_command: list[str] = []  # Auto-generated if empty

    # Dev server (for e2e tests)
    dev_server_command: list[str] = []
    dev_server_port: int = 5173
    dev_server_timeout: int = 30

    # TypeScript
    typecheck_command: list[str] = []  # Auto-generated if empty

    def __init__(self, project_root: Path):
        super().__init__(project_root)
        self._dev_server_process: subprocess.Popen | None = None
        self._node_modules_exists = False
        self._package_json: dict = {}

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def setup(self) -> None:
        """Install dependencies and prepare for testing."""
        super().setup()
        self._setup_success = False

        # Check for package.json
        package_json_path = self.project_root / "package.json"
        if not package_json_path.exists():
            return  # No package.json = not a valid project

        # Load package.json
        try:
            self._package_json = json.loads(package_json_path.read_text())
        except Exception:
            return

        # Check for node_modules
        self._node_modules_exists = (self.project_root / "node_modules").exists()

        # Install dependencies if needed
        if not self._node_modules_exists:
            if not self._install_dependencies():
                return

        self._setup_success = True

    def teardown(self) -> None:
        """Stop dev server if running."""
        self._stop_dev_server()
        super().teardown()

    def _has_meaningful_benchmark(self) -> bool:
        """Check if project is properly set up."""
        return self._setup_success and self._node_modules_exists

    # =========================================================================
    # PACKAGE MANAGEMENT
    # =========================================================================

    def _get_pm_command(self, *args: str) -> list[str]:
        """Get package manager command."""
        if self.package_manager == "pnpm":
            return ["pnpm", *args]
        elif self.package_manager == "yarn":
            return ["yarn", *args]
        else:
            return ["npm", *args]

    def _install_dependencies(self) -> bool:
        """Install npm dependencies."""
        cmd = self._get_pm_command("install")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=300,  # 5 min timeout for npm install
            )
            self._node_modules_exists = (self.project_root / "node_modules").exists()
            return result.returncode == 0 and self._node_modules_exists
        except Exception:
            return False

    def _run_npm_script(
        self,
        script: str,
        timeout: int = 120,
    ) -> tuple[int, str, str]:
        """Run an npm script.

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        cmd = self._get_pm_command("run", script)

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "timeout"
        except Exception as e:
            return -1, "", str(e)

    # =========================================================================
    # DEV SERVER
    # =========================================================================

    def _start_dev_server(self) -> bool:
        """Start the development server for e2e tests."""
        if not self.dev_server_command:
            # Try common dev server scripts
            scripts = self._package_json.get("scripts", {})
            if "dev" in scripts:
                cmd = self._get_pm_command("run", "dev")
            elif "start" in scripts:
                cmd = self._get_pm_command("run", "start")
            else:
                return False
        else:
            cmd = self.dev_server_command

        try:
            self._dev_server_process = subprocess.Popen(
                cmd,
                cwd=self.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Wait for server to start
            return self._wait_for_dev_server()
        except Exception:
            return False

    def _wait_for_dev_server(self) -> bool:
        """Wait for dev server to become responsive."""
        import socket

        deadline = time.time() + self.dev_server_timeout

        while time.time() < deadline:
            if self._dev_server_process and self._dev_server_process.poll() is not None:
                return False

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(("localhost", self.dev_server_port))
                sock.close()

                if result == 0:
                    time.sleep(1)  # Give it a moment to fully initialize
                    # Verify process is still running
                    if self._dev_server_process and self._dev_server_process.poll() is not None:
                        return False
                    return True
            except Exception:
                pass

            time.sleep(0.5)

        return False

    def _stop_dev_server(self) -> None:
        """Stop the development server."""
        if self._dev_server_process is None:
            return

        try:
            self._dev_server_process.terminate()
            try:
                self._dev_server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._dev_server_process.kill()
                self._dev_server_process.wait(timeout=1)
        except Exception:
            pass
        finally:
            self._dev_server_process = None

    # =========================================================================
    # TEST HELPERS
    # =========================================================================

    def _run_unit_tests(self) -> tuple[int, int, str]:
        """Run unit tests with vitest/jest.

        Returns:
            Tuple of (passed, total, output)
        """
        if self.test_command:
            cmd = self.test_command
        else:
            # Auto-detect test command
            scripts = self._package_json.get("scripts", {})
            if "test" in scripts:
                cmd = self._get_pm_command("run", "test", "--", "--reporter=json")
            elif self.test_framework == "vitest":
                cmd = self._get_pm_command("exec", "vitest", "run", "--reporter=json")
            else:
                cmd = self._get_pm_command("exec", "jest", "--json")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=self.test_timeout,
            )

            # Try to parse JSON output
            output = result.stdout + result.stderr

            # Parse vitest/jest output
            passed, total = self._parse_test_output(output)
            return passed, total, output

        except subprocess.TimeoutExpired:
            return 0, 0, "timeout"
        except Exception as e:
            return 0, 0, str(e)

    def _parse_test_output(self, output: str) -> tuple[int, int]:
        """Parse test output to get pass/fail counts."""
        import re

        # Try vitest format: "Tests  42 passed (42)"
        match = re.search(r"(\d+)\s+passed.*\((\d+)\)", output)
        if match:
            passed = int(match.group(1))
            total = int(match.group(2))
            return passed, total

        # Try vitest format: "✓ 42 tests passed"
        match = re.search(r"(\d+)\s+tests?\s+passed", output, re.IGNORECASE)
        if match:
            passed = int(match.group(1))
            # Look for total
            total_match = re.search(r"(\d+)\s+tests?", output)
            total = int(total_match.group(1)) if total_match else passed
            return passed, total

        # Try jest format in JSON
        try:
            data = json.loads(output)
            if "numPassedTests" in data:
                return data["numPassedTests"], data["numTotalTests"]
        except Exception:
            pass

        # Fallback: count "✓" and "✗" symbols
        passed = output.count("✓") + output.count("√")
        failed = output.count("✗") + output.count("×")
        return passed, passed + failed

    def _run_e2e_tests(self) -> tuple[int, int, str]:
        """Run e2e tests with playwright/cypress.

        Returns:
            Tuple of (passed, total, output)
        """
        if not self.e2e_framework:
            return 0, 0, "no e2e framework configured"

        # Check Playwright installation if using it
        if self.e2e_framework == "playwright":
            try:
                from bmad_assist.utils.playwright_check import check_playwright
                status = check_playwright()
                if not status.ready:
                    return 0, 0, f"playwright not ready: {status.error or 'run check-playwright'}"
            except ImportError:
                pass  # bmad_assist not installed, skip check

        # Start dev server for e2e tests
        if not self._start_dev_server():
            return 0, 0, "dev server failed to start"

        try:
            if self.e2e_command:
                cmd = self.e2e_command
            elif self.e2e_framework == "playwright":
                cmd = self._get_pm_command("exec", "playwright", "test", "--reporter=json")
            else:  # cypress
                cmd = self._get_pm_command("exec", "cypress", "run", "--reporter", "json")

            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=300,  # 5 min for e2e
            )

            output = result.stdout + result.stderr
            passed, total = self._parse_test_output(output)
            return passed, total, output

        except subprocess.TimeoutExpired:
            return 0, 0, "timeout"
        except Exception as e:
            return 0, 0, str(e)
        finally:
            self._stop_dev_server()

    def _run_typecheck(self) -> tuple[bool, str]:
        """Run TypeScript type checking.

        Returns:
            Tuple of (success, output)
        """
        if self.typecheck_command:
            cmd = self.typecheck_command
        else:
            # Check for tsc in scripts or use npx
            scripts = self._package_json.get("scripts", {})
            if "typecheck" in scripts:
                cmd = self._get_pm_command("run", "typecheck")
            elif "type-check" in scripts:
                cmd = self._get_pm_command("run", "type-check")
            else:
                cmd = self._get_pm_command("exec", "tsc", "--noEmit")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output
        except Exception as e:
            return False, str(e)

    def _check_build(self) -> tuple[bool, str]:
        """Run production build.

        Returns:
            Tuple of (success, output)
        """
        scripts = self._package_json.get("scripts", {})
        if "build" not in scripts:
            return True, "no build script"

        code, stdout, stderr = self._run_npm_script("build", timeout=180)
        return code == 0, stdout + stderr

    # =========================================================================
    # DEFAULT TEST IMPLEMENTATIONS
    # =========================================================================

    def test_c1_tests(self) -> tuple[int, str]:
        """C1: Run project's test suite."""
        if not self._setup_success:
            return 0, "setup failed"

        passed, total, output = self._run_unit_tests()

        if total == 0:
            return 0, "no tests found"

        return ratio_score(passed, total)

    def test_q3_performance(self) -> tuple[int, str]:
        """Q3: Build performance."""
        if not self._setup_success:
            return 0, "setup failed"

        start = time.perf_counter()
        success, output = self._check_build()
        elapsed = time.perf_counter() - start

        if not success:
            return 0, f"build failed: {output[:100]}"

        return time_score(elapsed, [
            (5, 5),   # < 5s
            (15, 4),  # < 15s
            (30, 3),  # < 30s
            (60, 2),  # < 1 min
            (120, 1), # < 2 min
        ])

    def test_q4_consistency(self) -> tuple[int, str]:
        """Q4: TypeScript type checking passes."""
        if not self._setup_success:
            return 0, "setup failed"

        success, output = self._run_typecheck()

        if success:
            return 5, "types OK"

        # Count errors
        import re
        errors = len(re.findall(r"error TS\d+", output))
        if errors == 0:
            errors = output.count("error")

        if errors <= 2:
            return 4, f"{errors} type errors"
        elif errors <= 5:
            return 3, f"{errors} type errors"
        elif errors <= 10:
            return 2, f"{errors} type errors"
        else:
            return 1, f"{errors}+ type errors"
