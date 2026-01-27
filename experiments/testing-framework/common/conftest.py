"""
Pytest configuration and fixtures for behavioral tests.

This conftest provides fixtures for:
- Starting/stopping fixture applications
- HTTP clients for API testing
- Mock servers for webhook testing

Usage:
    Copy this file to experiments/fixture-tests/{fixture-name}/conftest.py
    or import fixtures from here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Generator

import pytest

if TYPE_CHECKING:
    import httpx

    from experiments.testing_framework.common.strategies import AppStrategy


# ============================================================================
# Configuration
# ============================================================================


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command line options."""
    parser.addoption(
        "--fixture-port",
        action="store",
        type=int,
        default=None,
        help="Port to run fixture app on (default: auto)",
    )
    parser.addoption(
        "--skip-build",
        action="store_true",
        default=False,
        help="Skip building fixture (assume already built)",
    )
    parser.addoption(
        "--keep-running",
        action="store_true",
        default=False,
        help="Keep fixture running after tests (for debugging)",
    )


# ============================================================================
# Fixture Path Discovery
# ============================================================================


def find_fixture_path(test_path: Path) -> Path:
    """
    Find the fixture path for a test file.

    Given: experiments/fixture-tests/webhook-relay-001/test_api.py
    Returns: experiments/fixtures/webhook-relay-001/
    """
    # Navigate up to find fixture-tests directory
    current = test_path
    while current.name != "fixture-tests" and current != current.parent:
        current = current.parent

    if current.name != "fixture-tests":
        raise ValueError(f"Could not find fixture-tests directory for {test_path}")

    # Get fixture name from test directory
    fixture_name = test_path.parent.name
    fixtures_dir = current.parent / "fixtures"

    fixture_path = fixtures_dir / fixture_name
    if not fixture_path.exists():
        raise ValueError(f"Fixture not found: {fixture_path}")

    return fixture_path


# ============================================================================
# App Startup Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def fixture_path(request: pytest.FixtureRequest) -> Path:
    """Return the path to the fixture being tested."""
    # Try to find from test file location
    test_path = Path(request.fspath) if request.fspath else Path.cwd()
    return find_fixture_path(test_path)


@pytest.fixture(scope="session")
def app_strategy(
    request: pytest.FixtureRequest, fixture_path: Path
) -> Generator[AppStrategy, None, None]:
    """
    Create and manage the app strategy for the fixture.

    This fixture handles:
    - Auto-detecting the appropriate strategy (Go, Python, Node, Docker)
    - Building the application (unless --skip-build)
    - Starting the application
    - Stopping the application after tests
    """
    from experiments.testing_framework.common.strategies import discover_strategy

    port = request.config.getoption("--fixture-port")
    skip_build = request.config.getoption("--skip-build")
    keep_running = request.config.getoption("--keep-running")

    strategy = discover_strategy(fixture_path, port)

    # Build if needed
    if not skip_build:
        if not strategy.build():
            pytest.fail(f"Failed to build fixture: {fixture_path}")

    # Start the application
    if not strategy.start():
        pytest.fail(f"Failed to start fixture: {fixture_path}")

    yield strategy

    # Cleanup
    if not keep_running:
        strategy.stop()


@pytest.fixture(scope="session")
def app_url(app_strategy: AppStrategy) -> str:
    """Return the base URL of the running fixture app."""
    return app_strategy.base_url


@pytest.fixture(scope="session")
def running_fixture(app_strategy: AppStrategy) -> AppStrategy:
    """Alias for app_strategy - ensures fixture is running."""
    return app_strategy


# ============================================================================
# HTTP Client Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def app_client(app_url: str) -> Generator[httpx.Client, None, None]:
    """
    HTTP client configured for the fixture app.

    Usage:
        def test_health(app_client):
            response = app_client.get("/health")
            assert response.status_code == 200
    """
    import httpx

    with httpx.Client(base_url=app_url, timeout=10.0) as client:
        yield client


@pytest.fixture
def fresh_client(app_url: str) -> Generator[httpx.Client, None, None]:
    """
    Fresh HTTP client per test (no shared state/cookies).

    Use this when tests need isolated client state.
    """
    import httpx

    with httpx.Client(base_url=app_url, timeout=10.0) as client:
        yield client


# ============================================================================
# Mock Server Fixtures (for webhook relay testing)
# ============================================================================


@pytest.fixture(scope="session")
def mock_sink_port() -> int:
    """Get a port for the mock sink server."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def mock_sink_server(mock_sink_port: int) -> Generator[dict, None, None]:
    """
    Mock HTTP server that records received requests.

    Useful for testing webhook relay destinations.

    Usage:
        def test_relay(app_client, mock_sink_server):
            # Configure route to send to mock sink
            app_client.post("/admin/routes", json={
                "path": "/webhook/test",
                "destinations": [{"url": mock_sink_server["url"]}]
            })

            # Send webhook
            app_client.post("/webhook/test", json={"event": "push"})

            # Check mock received it
            assert len(mock_sink_server["requests"]) == 1
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
    }

    server.shutdown()


# ============================================================================
# Playwright Fixtures (for UI tests)
# ============================================================================


@pytest.fixture(scope="session")
def browser(playwright) -> Generator:
    """Launch browser for UI tests."""
    browser = playwright.chromium.launch(headless=True)
    yield browser
    browser.close()


@pytest.fixture(scope="session")
def browser_context(browser, app_url: str) -> Generator:
    """Create browser context with base URL configured."""
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        base_url=app_url,
    )
    yield context
    context.close()


@pytest.fixture
def page(browser_context) -> Generator:
    """Create a new page for each UI test."""
    page = browser_context.new_page()
    yield page
    page.close()
