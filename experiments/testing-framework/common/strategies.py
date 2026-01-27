"""
App Discovery and Startup Strategies.

Provides automatic detection of fixture technology stack and
handles starting/stopping the application for tests.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from subprocess import Popen


class AppStrategy(ABC):
    """Base class for app startup strategies."""

    name: str = "base"

    def __init__(self, fixture_path: Path, port: int | None = None):
        self.fixture_path = fixture_path
        self.port = port or self._find_free_port()
        self.process: Popen | None = None

    @abstractmethod
    def build(self) -> bool:
        """Build the application. Returns True on success."""
        ...

    @abstractmethod
    def start(self, timeout: float = 30.0) -> bool:
        """Start the application. Returns True when ready."""
        ...

    def stop(self) -> None:
        """Stop the application."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None

    def is_ready(self, timeout: float = 1.0) -> bool:
        """Check if application is responding on its port."""
        try:
            with socket.create_connection(("localhost", self.port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def wait_ready(self, timeout: float = 30.0, interval: float = 0.5) -> bool:
        """Wait for application to become ready."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_ready(timeout=1.0):
                return True
            time.sleep(interval)
        return False

    @property
    def base_url(self) -> str:
        """Return the base URL for the running application."""
        return f"http://localhost:{self.port}"

    @staticmethod
    def _find_free_port() -> int:
        """Find an available port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    def _run_command(
        self,
        cmd: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess:
        """Run a command and return result."""
        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        return subprocess.run(
            cmd,
            cwd=cwd or self.fixture_path,
            env=full_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )


class GoStrategy(AppStrategy):
    """Strategy for Go applications using go.mod."""

    name = "go"

    def __init__(self, fixture_path: Path, port: int | None = None):
        super().__init__(fixture_path, port)
        self.binary_path = self._find_main_package()

    def _find_main_package(self) -> Path:
        """Find the main package to build."""
        # Check common locations
        candidates = [
            self.fixture_path / "cmd" / "relay" / "main.go",
            self.fixture_path / "cmd" / "server" / "main.go",
            self.fixture_path / "main.go",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.parent
        # Default to first cmd/* directory
        cmd_dir = self.fixture_path / "cmd"
        if cmd_dir.exists():
            for item in cmd_dir.iterdir():
                if item.is_dir() and (item / "main.go").exists():
                    return item
        return self.fixture_path

    def build(self) -> bool:
        """Build the Go application."""
        result = self._run_command(
            ["go", "build", "-o", "app", "."],
            cwd=self.binary_path,
            timeout=120,
        )
        return result.returncode == 0

    def start(self, timeout: float = 30.0) -> bool:
        """Start the Go application."""
        binary = self.binary_path / "app"
        if not binary.exists():
            if not self.build():
                return False

        env = {
            "PORT": str(self.port),
            "RELAY_PORT": str(self.port),
            "SERVER_PORT": str(self.port),
        }

        self.process = subprocess.Popen(
            [str(binary)],
            cwd=self.fixture_path,
            env={**os.environ, **env},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        return self.wait_ready(timeout=timeout)


class PythonStrategy(AppStrategy):
    """Strategy for Python applications."""

    name = "python"

    def __init__(self, fixture_path: Path, port: int | None = None):
        super().__init__(fixture_path, port)
        self.venv_python = self._find_python()
        self.entry_point = self._find_entry_point()

    def _find_python(self) -> str:
        """Find Python executable."""
        # Check for venv in fixture
        venv_python = self.fixture_path / ".venv" / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)

        # Check for global venv
        global_venv = Path.cwd() / ".venv" / "bin" / "python"
        if global_venv.exists():
            return str(global_venv)

        # Fall back to system Python
        return shutil.which("python3") or "python3"

    def _find_entry_point(self) -> list[str]:
        """Find how to run the application."""
        # Check for common patterns
        if (self.fixture_path / "manage.py").exists():
            return ["manage.py", "runserver", f"0.0.0.0:{self.port}"]
        if (self.fixture_path / "app.py").exists():
            return ["app.py"]
        if (self.fixture_path / "main.py").exists():
            return ["main.py"]
        if (self.fixture_path / "src").exists():
            # Try to find a main module
            for item in (self.fixture_path / "src").iterdir():
                if item.is_dir() and (item / "__main__.py").exists():
                    return ["-m", item.name]
        return []

    def build(self) -> bool:
        """Install dependencies."""
        if (self.fixture_path / "pyproject.toml").exists():
            result = self._run_command(
                [self.venv_python, "-m", "pip", "install", "-e", "."],
                timeout=120,
            )
        elif (self.fixture_path / "requirements.txt").exists():
            result = self._run_command(
                [self.venv_python, "-m", "pip", "install", "-r", "requirements.txt"],
                timeout=120,
            )
        else:
            return True  # No deps to install
        return result.returncode == 0

    def start(self, timeout: float = 30.0) -> bool:
        """Start the Python application."""
        if not self.entry_point:
            return False

        cmd = [self.venv_python, *self.entry_point]
        env = {
            "PORT": str(self.port),
            "PYTHONUNBUFFERED": "1",
        }

        self.process = subprocess.Popen(
            cmd,
            cwd=self.fixture_path,
            env={**os.environ, **env},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        return self.wait_ready(timeout=timeout)


class NodeStrategy(AppStrategy):
    """Strategy for Node.js applications."""

    name = "node"

    def __init__(self, fixture_path: Path, port: int | None = None):
        super().__init__(fixture_path, port)
        self.npm = shutil.which("npm") or "npm"

    def build(self) -> bool:
        """Install dependencies and build."""
        # Install
        result = self._run_command(
            [self.npm, "install"],
            timeout=120,
        )
        if result.returncode != 0:
            return False

        # Build if script exists
        package_json = self.fixture_path / "package.json"
        if package_json.exists():
            import json

            pkg = json.loads(package_json.read_text())
            if "build" in pkg.get("scripts", {}):
                result = self._run_command(
                    [self.npm, "run", "build"],
                    timeout=120,
                )
                return result.returncode == 0

        return True

    def start(self, timeout: float = 30.0) -> bool:
        """Start the Node.js application."""
        env = {
            "PORT": str(self.port),
            "NODE_ENV": "test",
        }

        self.process = subprocess.Popen(
            [self.npm, "start"],
            cwd=self.fixture_path,
            env={**os.environ, **env},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        return self.wait_ready(timeout=timeout)


class DockerComposeStrategy(AppStrategy):
    """Strategy for Docker Compose applications."""

    name = "docker-compose"

    def __init__(self, fixture_path: Path, port: int | None = None):
        super().__init__(fixture_path, port)
        self.compose_cmd = self._find_compose_command()

    def _find_compose_command(self) -> list[str]:
        """Find docker-compose or docker compose command."""
        if shutil.which("docker-compose"):
            return ["docker-compose"]
        return ["docker", "compose"]

    def build(self) -> bool:
        """Build Docker images."""
        result = self._run_command(
            [*self.compose_cmd, "build"],
            timeout=300,
        )
        return result.returncode == 0

    def start(self, timeout: float = 60.0) -> bool:
        """Start Docker Compose services."""
        # Use port from environment
        env = {"PORT": str(self.port)}

        self.process = subprocess.Popen(
            [*self.compose_cmd, "up", "--remove-orphans"],
            cwd=self.fixture_path,
            env={**os.environ, **env},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        return self.wait_ready(timeout=timeout)

    def stop(self) -> None:
        """Stop Docker Compose services."""
        self._run_command([*self.compose_cmd, "down", "--remove-orphans"], timeout=30)
        super().stop()


def discover_strategy(fixture_path: Path, port: int | None = None) -> AppStrategy:
    """
    Auto-detect the appropriate strategy for a fixture.

    Checks for:
    1. docker-compose.yaml → DockerComposeStrategy
    2. go.mod → GoStrategy
    3. package.json → NodeStrategy
    4. pyproject.toml / requirements.txt → PythonStrategy

    Raises ValueError if no strategy matches.
    """
    path = Path(fixture_path)

    # Check for Docker Compose first (takes precedence)
    if (path / "docker-compose.yaml").exists() or (path / "docker-compose.yml").exists():
        return DockerComposeStrategy(path, port)

    # Check for Go
    if (path / "go.mod").exists():
        return GoStrategy(path, port)

    # Check for Node.js
    if (path / "package.json").exists():
        return NodeStrategy(path, port)

    # Check for Python
    if (path / "pyproject.toml").exists() or (path / "requirements.txt").exists():
        return PythonStrategy(path, port)

    raise ValueError(f"Cannot determine app strategy for {fixture_path}")
