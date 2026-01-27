"""
Pytest configuration for webhook-relay behavioral tests.

These tests verify behavior based on the PRD and apply to ALL variants:
- webhook-relay-001 (baseline, no Strategic Context)
- webhook-relay-002 (with Strategic Context Optimization)
- webhook-relay (active development)

Usage:
    # Test specific variant
    pytest experiments/fixture-tests/webhook-relay/ --fixture-variant=webhook-relay-001

    # Test default (webhook-relay-001)
    pytest experiments/fixture-tests/webhook-relay/
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Generator

import pytest

if TYPE_CHECKING:
    import httpx

# ============================================================================
# Configuration
# ============================================================================

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"
DEFAULT_VARIANT = "webhook-relay-001"  # Baseline for comparison


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command line options."""
    parser.addoption(
        "--fixture-variant",
        action="store",
        default=DEFAULT_VARIANT,
        help=f"Which fixture variant to test (default: {DEFAULT_VARIANT})",
    )


def find_free_port() -> int:
    """Find an available port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def wait_for_port(port: int, timeout: float = 30.0) -> bool:
    """Wait for a port to become available."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=1.0):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


# ============================================================================
# Fixture Path Resolution
# ============================================================================


@pytest.fixture(scope="session")
def fixture_variant(request: pytest.FixtureRequest) -> str:
    """Return the fixture variant being tested."""
    return request.config.getoption("--fixture-variant")


@pytest.fixture(scope="session")
def fixture_path(fixture_variant: str) -> Path:
    """Return the path to the fixture being tested."""
    path = FIXTURES_DIR / fixture_variant
    if not path.exists():
        pytest.fail(
            f"Fixture variant not found: {path}\n"
            f"Available variants: {[d.name for d in FIXTURES_DIR.iterdir() if d.is_dir()]}"
        )
    return path


# ============================================================================
# App Startup Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def app_port() -> int:
    """Get a port for the fixture app."""
    return find_free_port()


@pytest.fixture(scope="session")
def app_url(app_port: int) -> str:
    """Return the base URL of the running fixture app."""
    return f"http://localhost:{app_port}"


@pytest.fixture(scope="session")
def running_app(
    fixture_path: Path, app_port: int
) -> Generator[subprocess.Popen, None, None]:
    """
    Build and start the webhook-relay fixture.

    This fixture:
    1. Builds the Go application
    2. Starts it on a free port
    3. Waits for it to become ready
    4. Yields control to tests
    5. Stops the application after tests complete
    """
    # Find main package
    main_dir = fixture_path / "cmd" / "relay"
    if not main_dir.exists():
        main_dir = fixture_path

    # Build
    build_result = subprocess.run(
        ["go", "build", "-o", "app", "."],
        cwd=main_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if build_result.returncode != 0:
        pytest.fail(f"Failed to build fixture: {build_result.stderr}")

    # Start
    env = os.environ.copy()
    env["PORT"] = str(app_port)
    env["RELAY_PORT"] = str(app_port)

    # Create a config.yaml for the test
    config_content = f"""
port: {app_port}
database:
  path: ":memory:"
log:
  level: debug
  format: json
"""
    config_path = fixture_path / "test-config.yaml"
    config_path.write_text(config_content)

    process = subprocess.Popen(
        [str(main_dir / "app"), "-config", str(config_path)],
        cwd=fixture_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for ready
    if not wait_for_port(app_port, timeout=30.0):
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        pytest.fail(
            f"Fixture failed to start on port {app_port}.\n"
            f"stdout: {stdout.decode()[:500]}\n"
            f"stderr: {stderr.decode()[:500]}"
        )

    yield process

    # Cleanup
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()

    # Remove test config
    if config_path.exists():
        config_path.unlink()


@pytest.fixture(scope="session")
def app_client(
    running_app: subprocess.Popen, app_url: str
) -> Generator[httpx.Client, None, None]:
    """
    HTTP client configured for the fixture app.

    Usage:
        def test_health(app_client):
            response = app_client.get("/health")
            assert response.status_code == 200
    """
    import httpx

    # Silence unused variable warning - running_app ensures app is started
    _ = running_app

    with httpx.Client(base_url=app_url, timeout=10.0) as client:
        yield client


# ============================================================================
# Mock Sink for Webhook Destination Testing
# ============================================================================


@pytest.fixture(scope="session")
def mock_sink_port() -> int:
    """Get a port for the mock sink server."""
    return find_free_port()


@pytest.fixture(scope="session")
def mock_sink_server(mock_sink_port: int) -> Generator[dict, None, None]:
    """
    Mock HTTP server that records received requests.

    Use this to verify webhook relay actually sends to destinations.

    Usage:
        def test_relay_sends_to_destination(app_client, mock_sink_server, test_route):
            # Configure route to send to mock sink
            app_client.post(
                f"/admin/routes/{test_route['id']}/destinations",
                json={"url": mock_sink_server["url"]}
            )

            # Send webhook
            app_client.post(f"/webhook/{test_route['id']}", json={"event": "push"})

            # Wait briefly for async delivery
            import time
            time.sleep(0.5)

            # Check mock received it
            assert len(mock_sink_server["requests"]) > 0
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            requests.append(
                {
                    "method": "POST",
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": body.decode("utf-8"),
                }
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "received"}')

        def log_message(self, format: str, *args: object) -> None:
            pass  # Suppress logging

    server = HTTPServer(("localhost", mock_sink_port), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    yield {
        "url": f"http://localhost:{mock_sink_port}",
        "port": mock_sink_port,
        "requests": requests,
        "clear": lambda: requests.clear(),
    }

    server.shutdown()
