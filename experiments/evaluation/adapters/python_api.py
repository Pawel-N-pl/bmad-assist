"""Python API adapter for FastAPI/Flask projects.

Provides helpers for testing HTTP APIs:
- Server lifecycle management (start/stop)
- HTTP client utilities
- Common test patterns for REST APIs
"""

import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from .base import BaseEvaluator
from ..core.scoring import ratio_score

# Try to import httpx, fall back to urllib if not available
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    import urllib.request
    import urllib.error
    import json


class PythonApiAdapter(BaseEvaluator):
    """Base adapter for Python HTTP API projects (FastAPI, Flask, etc.)

    Subclasses should set:
        - server_command: Command to start the server
        - server_host: Host to connect to (default: localhost)
        - server_port: Port to connect to (default: 8000)
        - startup_timeout: Max seconds to wait for server start

    Example:
        class MyApiEvaluator(PythonApiAdapter):
            server_command = ["uvicorn", "myapp.main:app"]
            server_port = 8000
    """

    stack_name = "python-api"

    # Server configuration (override in subclass)
    server_command: list[str] = []
    server_module: str = ""  # e.g., "auth_service.main:app"
    server_host: str = "localhost"
    server_port: int = 8000
    startup_timeout: int = 10
    shutdown_timeout: int = 5

    def __init__(self, project_root: Path):
        super().__init__(project_root)
        self._server_process: subprocess.Popen | None = None
        self._client: Any = None

    @property
    def base_url(self) -> str:
        """Base URL for API requests."""
        return f"http://{self.server_host}:{self.server_port}"

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def setup(self) -> None:
        """Start the API server."""
        super().setup()
        self._setup_success = False  # Reset until server starts

        if not self.server_command and not self.server_module:
            return  # No server to start

        # Build command
        cmd = self.server_command or [
            "uvicorn",
            self.server_module,
            "--host", self.server_host,
            "--port", str(self.server_port),
        ]

        # Add PYTHONPATH to include src/
        env = os.environ.copy()
        src_path = str(self.project_root / "src")
        env["PYTHONPATH"] = f"{src_path}:{env.get('PYTHONPATH', '')}"

        # Start server
        self._server_process = subprocess.Popen(
            cmd,
            cwd=self.project_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to start
        if not self._wait_for_server():
            # Get any error output
            stderr = ""
            if self._server_process.stderr:
                try:
                    stderr = self._server_process.stderr.read().decode()[:500]
                except Exception:
                    pass
            self._kill_server()
            raise RuntimeError(f"Server failed to start: {stderr}")

        # Server started successfully
        self._setup_success = True

    def teardown(self) -> None:
        """Stop the API server."""
        self._kill_server()
        super().teardown()

    def _has_meaningful_benchmark(self) -> bool:
        """Check if server is running for meaningful benchmark."""
        return self._setup_success and self._server_process is not None

    def _wait_for_server(self) -> bool:
        """Wait for server to become responsive.

        Checks both:
        1. Port is accepting connections
        2. Our server process is still running (not crashed)
        """
        deadline = time.time() + self.startup_timeout

        while time.time() < deadline:
            # Check if our process died
            if self._server_process and self._server_process.poll() is not None:
                # Server process died
                return False

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((self.server_host, self.server_port))
                sock.close()
                if result == 0:
                    # Port is open - but verify OUR process is still alive
                    # Give it a moment to fully initialize
                    time.sleep(0.5)

                    # Double-check process didn't crash during startup
                    if self._server_process and self._server_process.poll() is not None:
                        # Process died after port opened - likely crashed during init
                        return False

                    return True
            except Exception:
                pass

            time.sleep(0.1)

        return False

    def _kill_server(self) -> None:
        """Kill the server process."""
        if self._server_process is None:
            return

        try:
            # Try graceful shutdown first
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=self.shutdown_timeout)
            except subprocess.TimeoutExpired:
                # Force kill
                self._server_process.kill()
                self._server_process.wait(timeout=1)
        except Exception:
            pass
        finally:
            self._server_process = None

    # =========================================================================
    # HTTP CLIENT
    # =========================================================================

    def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        headers: dict | None = None,
        timeout: float = 10.0,
    ) -> tuple[int, dict | str | None]:
        """Make an HTTP request.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: URL path (will be joined with base_url)
            json: JSON body for POST/PUT
            headers: Additional headers
            timeout: Request timeout in seconds

        Returns:
            Tuple of (status_code, response_body)
            Body is parsed as JSON if possible, otherwise string
        """
        url = f"{self.base_url}{path}"

        if HAS_HTTPX:
            return self._request_httpx(method, url, json, headers, timeout)
        else:
            return self._request_urllib(method, url, json, headers, timeout)

    def _request_httpx(
        self,
        method: str,
        url: str,
        json_body: dict | None,
        headers: dict | None,
        timeout: float,
    ) -> tuple[int, dict | str | None]:
        """Make request using httpx."""
        try:
            response = httpx.request(
                method,
                url,
                json=json_body,
                headers=headers,
                timeout=timeout,
            )
            try:
                body = response.json()
            except Exception:
                body = response.text
            return response.status_code, body
        except httpx.TimeoutException:
            return 0, "timeout"
        except httpx.ConnectError:
            return 0, "connection refused"
        except Exception as e:
            return 0, str(e)

    def _request_urllib(
        self,
        method: str,
        url: str,
        json_body: dict | None,
        headers: dict | None,
        timeout: float,
    ) -> tuple[int, dict | str | None]:
        """Make request using urllib (fallback)."""
        import json as json_module

        headers = headers or {}
        data = None

        if json_body is not None:
            data = json_module.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body_bytes = response.read()
                try:
                    body = json_module.loads(body_bytes)
                except Exception:
                    body = body_bytes.decode()
                return response.status, body
        except urllib.error.HTTPError as e:
            try:
                body = json_module.loads(e.read())
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
        return self._request("POST", path, json=json, **kwargs)

    def put(self, path: str, json: dict | None = None, **kwargs) -> tuple[int, dict | str | None]:
        """PUT request."""
        return self._request("PUT", path, json=json, **kwargs)

    def delete(self, path: str, **kwargs) -> tuple[int, dict | str | None]:
        """DELETE request."""
        return self._request("DELETE", path, **kwargs)

    # =========================================================================
    # TEST HELPERS
    # =========================================================================

    def test_endpoints(
        self,
        endpoints: list[dict],
    ) -> tuple[int, int, list[str]]:
        """Test a list of endpoint specifications.

        Args:
            endpoints: List of endpoint specs:
                {
                    "method": "POST",
                    "path": "/api/users",
                    "json": {"name": "test"},  # optional
                    "expected_status": 201,    # optional, default any 2xx
                    "expected_keys": ["id"],   # optional, keys in response
                }

        Returns:
            Tuple of (passed, total, failed_endpoints)
        """
        passed = 0
        failed = []

        for spec in endpoints:
            method = spec.get("method", "GET")
            path = spec["path"]
            json_body = spec.get("json")
            expected_status = spec.get("expected_status")
            expected_keys = spec.get("expected_keys", [])

            status, body = self._request(method, path, json=json_body)

            # Check status
            if expected_status:
                status_ok = status == expected_status
            else:
                status_ok = 200 <= status < 300

            # Check keys in response
            keys_ok = True
            if expected_keys and isinstance(body, dict):
                for key in expected_keys:
                    if key not in body:
                        keys_ok = False
                        break

            if status_ok and keys_ok:
                passed += 1
            else:
                failed.append(f"{method} {path}: {status}")

        return passed, len(endpoints), failed

    def check_endpoint(
        self,
        method: str,
        path: str,
        expected_status: int | None = None,
        **kwargs,
    ) -> bool:
        """Check if an endpoint returns expected status.

        Args:
            method: HTTP method
            path: URL path
            expected_status: Expected status code (None = any 2xx)
            **kwargs: Additional args for _request

        Returns:
            True if endpoint returned expected status
        """
        status, _ = self._request(method, path, **kwargs)
        if expected_status:
            return status == expected_status
        return 200 <= status < 300
