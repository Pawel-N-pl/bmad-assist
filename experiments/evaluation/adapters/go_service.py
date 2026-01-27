"""Go service adapter for Go HTTP services and CLI tools.

For projects that use:
- Go 1.21+
- go test for testing
- HTTP server (chi, gin, stdlib)

Examples:
- webhook-relay (Go HTTP service with chi)
"""

import os
import re
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

from .base import BaseEvaluator
from ..core.scoring import ratio_score, time_score


class GoServiceAdapter(BaseEvaluator):
    """Base adapter for Go service projects.

    Subclasses should set:
        - go_module: Go module name (from go.mod)
        - main_package: Path to main package (e.g., "./cmd/relay")
        - server_port: Port for HTTP server
        - startup_timeout: Max seconds to wait for server

    Example:
        class WebhookRelayEvaluator(GoServiceAdapter):
            main_package = "./cmd/relay"
            server_port = 8080
    """

    stack_name = "go-service"

    # Go configuration
    go_version: str = "1.21"
    main_package: str = "./cmd/server"  # or "." for root
    build_tags: list[str] = []

    # Server configuration
    server_port: int = 8080
    server_host: str = "localhost"
    startup_timeout: int = 10
    shutdown_timeout: int = 5

    # Test configuration
    test_timeout: int = 120
    test_tags: list[str] = []
    coverage_threshold: float = 0.8

    def __init__(self, project_root: Path):
        super().__init__(project_root)
        self._server_process: subprocess.Popen | None = None
        self._go_mod_exists = False
        self._go_available = False

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def setup(self) -> None:
        """Check Go installation and project structure."""
        super().setup()
        self._setup_success = False

        # Check for go.mod
        go_mod_path = self.project_root / "go.mod"
        self._go_mod_exists = go_mod_path.exists()
        if not self._go_mod_exists:
            return

        # Check for Go installation
        self._go_available = shutil.which("go") is not None
        if not self._go_available:
            return

        # Run go mod download
        if not self._download_dependencies():
            return

        self._setup_success = True

    def teardown(self) -> None:
        """Stop server if running."""
        self._stop_server()
        super().teardown()

    def _has_meaningful_benchmark(self) -> bool:
        """Check if Go project is properly set up."""
        return self._setup_success and self._go_available

    # =========================================================================
    # GO COMMANDS
    # =========================================================================

    def _run_go(
        self,
        *args: str,
        timeout: int = 60,
        env: dict | None = None,
    ) -> tuple[int, str, str]:
        """Run a go command.

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        cmd = ["go", *args]

        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=full_env,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "timeout"
        except Exception as e:
            return -1, "", str(e)

    def _download_dependencies(self) -> bool:
        """Download Go module dependencies."""
        code, _, stderr = self._run_go("mod", "download", timeout=120)
        return code == 0

    def _build(self, output: str = "") -> tuple[bool, str]:
        """Build the Go project.

        Args:
            output: Output binary path (optional)

        Returns:
            Tuple of (success, error_message)
        """
        args = ["build"]

        if self.build_tags:
            args.extend(["-tags", ",".join(self.build_tags)])

        if output:
            args.extend(["-o", output])

        args.append(self.main_package)

        code, stdout, stderr = self._run_go(*args, timeout=120)
        if code != 0:
            return False, stderr[:500]
        return True, ""

    def _run_tests(
        self,
        package: str = "./...",
        coverage: bool = False,
    ) -> tuple[int, int, float, str]:
        """Run Go tests.

        Args:
            package: Package pattern to test
            coverage: Whether to collect coverage

        Returns:
            Tuple of (passed, total, coverage_pct, output)
        """
        args = ["test", "-v"]

        if self.test_tags:
            args.extend(["-tags", ",".join(self.test_tags)])

        if coverage:
            args.append("-cover")

        args.append(package)

        code, stdout, stderr = self._run_go(*args, timeout=self.test_timeout)
        output = stdout + stderr

        # Parse test results
        passed, total = self._parse_test_output(output)

        # Parse coverage
        coverage_pct = 0.0
        if coverage:
            match = re.search(r"coverage:\s*([\d.]+)%", output)
            if match:
                coverage_pct = float(match.group(1))

        return passed, total, coverage_pct, output

    def _parse_test_output(self, output: str) -> tuple[int, int]:
        """Parse go test output for pass/fail counts."""
        # Count PASS and FAIL lines
        passed = len(re.findall(r"^---\s*PASS:", output, re.MULTILINE))
        failed = len(re.findall(r"^---\s*FAIL:", output, re.MULTILINE))

        # Also count ok/FAIL package lines
        passed += len(re.findall(r"^ok\s+", output, re.MULTILINE))
        pkg_failed = len(re.findall(r"^FAIL\s+", output, re.MULTILINE))

        return passed, passed + failed + pkg_failed

    # =========================================================================
    # SERVER MANAGEMENT
    # =========================================================================

    def _start_server(self) -> bool:
        """Build and start the HTTP server."""
        # Build first
        binary_path = self.project_root / "server_binary"
        success, err = self._build(str(binary_path))
        if not success:
            return False

        # Start server
        env = os.environ.copy()
        env["PORT"] = str(self.server_port)

        try:
            self._server_process = subprocess.Popen(
                [str(binary_path)],
                cwd=self.project_root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Wait for server to start
            if not self._wait_for_server():
                self._stop_server()
                return False

            return True
        except Exception:
            return False

    def _wait_for_server(self) -> bool:
        """Wait for server to become responsive."""
        deadline = time.time() + self.startup_timeout

        while time.time() < deadline:
            # Check if process died
            if self._server_process and self._server_process.poll() is not None:
                return False

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((self.server_host, self.server_port))
                sock.close()

                if result == 0:
                    time.sleep(0.5)
                    # Verify process is still running
                    if self._server_process and self._server_process.poll() is not None:
                        return False
                    return True
            except Exception:
                pass

            time.sleep(0.1)

        return False

    def _stop_server(self) -> None:
        """Stop the server process."""
        if self._server_process is None:
            return

        try:
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=self.shutdown_timeout)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
                self._server_process.wait(timeout=1)
        except Exception:
            pass
        finally:
            self._server_process = None

        # Clean up binary
        binary_path = self.project_root / "server_binary"
        if binary_path.exists():
            try:
                binary_path.unlink()
            except Exception:
                pass

    # =========================================================================
    # HTTP CLIENT (for behavioral tests)
    # =========================================================================

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict | None = None,
        headers: dict | None = None,
        timeout: float = 10.0,
    ) -> tuple[int, dict | str | None]:
        """Make an HTTP request to the server.

        Returns:
            Tuple of (status_code, response_body)
        """
        import urllib.request
        import urllib.error
        import json

        url = f"http://{self.server_host}:{self.server_port}{path}"
        headers = headers or {}
        data = None

        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body_bytes = response.read()
                try:
                    body = json.loads(body_bytes)
                except Exception:
                    body = body_bytes.decode()
                return response.status, body
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read())
            except Exception:
                body = str(e)
            return e.code, body
        except urllib.error.URLError as e:
            return 0, str(e.reason)
        except Exception as e:
            return 0, str(e)

    def get(self, path: str, **kwargs) -> tuple[int, dict | str | None]:
        """GET request."""
        return self._request("GET", path, **kwargs)

    def post(self, path: str, json: dict | None = None, **kwargs) -> tuple[int, dict | str | None]:
        """POST request."""
        return self._request("POST", path, json_body=json, **kwargs)

    # =========================================================================
    # DEFAULT TEST IMPLEMENTATIONS
    # =========================================================================

    def test_c1_tests(self) -> tuple[int, str]:
        """C1: Run go test suite."""
        if not self._setup_success:
            return 0, "setup failed"

        passed, total, coverage, output = self._run_tests(coverage=True)

        if total == 0:
            return 0, "no tests found"

        # Score based on pass rate and coverage
        pass_rate = passed / total if total > 0 else 0
        pts, note = ratio_score(passed, total)

        # Bonus/penalty for coverage
        if coverage >= 80:
            note += f" ({coverage:.0f}% cov)"
        elif coverage >= 50:
            note += f" ({coverage:.0f}% cov)"
        elif coverage > 0:
            note += f" (low cov: {coverage:.0f}%)"

        return pts, note

    def test_q3_performance(self) -> tuple[int, str]:
        """Q3: Build time."""
        if not self._setup_success:
            return 0, "setup failed"

        start = time.perf_counter()
        success, err = self._build()
        elapsed = time.perf_counter() - start

        if not success:
            return 0, f"build failed: {err[:100]}"

        return time_score(elapsed, [
            (2, 5),   # < 2s
            (5, 4),   # < 5s
            (10, 3),  # < 10s
            (30, 2),  # < 30s
            (60, 1),  # < 1 min
        ])

    def test_q4_consistency(self) -> tuple[int, str]:
        """Q4: go vet and staticcheck pass."""
        if not self._setup_success:
            return 0, "setup failed"

        issues = 0

        # Run go vet
        code, stdout, stderr = self._run_go("vet", "./...")
        if code != 0:
            vet_issues = len(stderr.strip().split("\n")) if stderr.strip() else 1
            issues += vet_issues

        # Try staticcheck if available
        if shutil.which("staticcheck"):
            try:
                result = subprocess.run(
                    ["staticcheck", "./..."],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    sc_issues = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 1
                    issues += sc_issues
            except Exception:
                pass

        if issues == 0:
            return 5, "vet OK"
        elif issues <= 2:
            return 4, f"{issues} issues"
        elif issues <= 5:
            return 3, f"{issues} issues"
        elif issues <= 10:
            return 2, f"{issues} issues"
        else:
            return 1, f"{issues}+ issues"
