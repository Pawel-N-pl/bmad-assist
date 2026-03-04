"""Dashboard E2E test fixtures.

Provides dashboard_server (URL string) and page (Playwright Page) fixtures.
These fixtures require pytest-playwright and Playwright browsers to be installed.
Tests using them are auto-skipped by the parent conftest.py when unavailable.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Generator

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page


def _find_free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def dashboard_server() -> Generator[str, None, None]:
    """Start a dashboard server and yield its URL.

    Uses a random free port to avoid conflicts. Server is started as a
    subprocess using the current Python interpreter to test local code.
    Killed after all tests complete.
    """
    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"

    proc = subprocess.Popen(
        [sys.executable, "-m", "bmad_assist.cli", "serve", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Merge stderr into stdout for diagnostics
    )

    # Wait for server to be ready (up to 10 seconds)
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    else:
        # Capture output for diagnostics before killing
        proc.kill()
        output = ""
        if proc.stdout:
            output = proc.stdout.read().decode(errors="replace")[:2000]
        pytest.fail(
            f"Dashboard server failed to start on port {port}.\n"
            f"Server output:\n{output}"
        )

    yield url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def _browser():
    """Session-scoped browser instance shared across all E2E tests."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    yield browser
    browser.close()
    pw.stop()


@pytest.fixture()
def page(_browser, dashboard_server: str) -> Generator[Page, None, None]:  # type: ignore[type-arg]
    """Create a Playwright browser page.

    Uses session-scoped browser for efficiency, but creates a fresh
    context per test for isolation.
    """
    context = _browser.new_context()
    pg = context.new_page()
    yield pg
    context.close()
