"""Playwright installation detection and setup guidance.

Detects whether Playwright is properly installed and configured for
headless browser testing on Ubuntu 22.04+.

Usage:
    from bmad_assist.utils import check_playwright, print_status

    status = check_playwright()
    if not status.ready:
        print_status(status)  # Shows what's missing and how to fix
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PlaywrightStatus:
    """Playwright installation status."""

    package_installed: bool = False
    version: str | None = None
    chromium: bool = False
    firefox: bool = False
    webkit: bool = False
    deps_ok: bool = False
    error: str | None = None

    @property
    def ready(self) -> bool:
        """Check if Playwright is ready for headless testing.

        Requires at least Chromium + system deps.
        """
        return self.package_installed and self.chromium and self.deps_ok

    @property
    def browsers_installed(self) -> bool:
        """Check if any browser is installed."""
        return self.chromium or self.firefox or self.webkit

    @property
    def browsers_list(self) -> list[str]:
        """Get list of installed browsers."""
        browsers = []
        if self.chromium:
            browsers.append("chromium")
        if self.firefox:
            browsers.append("firefox")
        if self.webkit:
            browsers.append("webkit")
        return browsers


def check_playwright() -> PlaywrightStatus:
    """Detect Playwright installation status.

    Checks:
    1. Python package installed
    2. Browser binaries present
    3. System dependencies OK (via quick launch test)

    Returns:
        PlaywrightStatus with detection results

    """
    status = PlaywrightStatus()

    # 1. Check Python package
    try:
        import playwright

        status.package_installed = True
        status.version = getattr(playwright, "__version__", "unknown")
    except ImportError:
        status.error = "playwright package not installed"
        return status

    # 2. Check browser binaries
    try:
        from playwright._impl._driver import compute_driver_executable

        driver_dir = Path(compute_driver_executable()[0]).parent

        # Browser executable patterns (Linux)
        browser_patterns = {
            "chromium": "chromium-*/chrome-linux/chrome",
            "firefox": "firefox-*/firefox/firefox",
            "webkit": "webkit-*/pw_run.sh",
        }

        for name, pattern in browser_patterns.items():
            matches = list(driver_dir.glob(pattern))
            setattr(status, name, len(matches) > 0)

    except Exception as e:
        status.error = f"browser detection failed: {e}"
        return status

    # 3. Quick sanity check - can we actually launch a browser?
    if status.chromium:
        status.deps_ok, status.error = _test_browser_launch()
    elif status.firefox:
        status.deps_ok, status.error = _test_browser_launch("firefox")
    elif status.webkit:
        status.deps_ok, status.error = _test_browser_launch("webkit")

    return status


def _test_browser_launch(browser: str = "chromium") -> tuple[bool, str | None]:
    """Test if browser can actually launch.

    Args:
        browser: Browser to test (chromium, firefox, webkit)

    Returns:
        Tuple of (success, error_message)

    """
    test_code = f"""
from playwright.sync_api import sync_playwright
try:
    p = sync_playwright().start()
    b = p.{browser}.launch(headless=True)
    b.close()
    p.stop()
    print("OK")
except Exception as e:
    print(f"ERROR: {{e}}")
"""

    try:
        result = subprocess.run(
            [sys.executable, "-c", test_code],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0 and "OK" in result.stdout:
            return True, None

        # Extract error message
        error = result.stderr.strip() or result.stdout.strip()
        if "ERROR:" in error:
            error = error.split("ERROR:")[-1].strip()

        # Common error patterns
        if "libnss3" in error or "libatk" in error or "shared libraries" in error:
            return False, "missing system dependencies"
        if "not found" in error.lower() or "executable doesn't exist" in error.lower():
            return False, "browser binary not found"

        return False, error[:200] if error else "launch failed"

    except subprocess.TimeoutExpired:
        return False, "browser launch timeout (30s)"
    except Exception as e:
        return False, str(e)


def get_install_commands(status: PlaywrightStatus) -> list[str]:
    """Get shell commands needed to fix Playwright installation.

    Args:
        status: Current PlaywrightStatus

    Returns:
        List of commands to run (in order)

    """
    commands = []

    if not status.package_installed:
        commands.append("pip install playwright")

    if not status.browsers_installed:
        # Install only Chromium by default (smaller, most compatible)
        commands.append("python -m playwright install chromium")

    if status.browsers_installed and not status.deps_ok:
        # System deps require sudo on Ubuntu
        commands.append("sudo python -m playwright install-deps")

    return commands


def get_install_script(status: PlaywrightStatus) -> str:
    """Get a complete install script for copy-paste.

    Args:
        status: Current PlaywrightStatus

    Returns:
        Multi-line shell script

    """
    commands = get_install_commands(status)
    if not commands:
        return "# Playwright is already properly configured!"

    lines = [
        "#!/bin/bash",
        "# Playwright installation for Ubuntu 22.04+",
        "set -e",
        "",
    ]
    lines.extend(commands)
    return "\n".join(lines)


def print_status(status: PlaywrightStatus) -> None:
    """Print human-readable status to stdout.

    Args:
        status: PlaywrightStatus to display

    """

    def icon(ok: bool) -> str:
        return "✓" if ok else "✗"

    print("Playwright Status:")

    # Package info
    if status.package_installed:
        print(f"  Package:  {icon(True)} v{status.version}")
    else:
        print(f"  Package:  {icon(False)} not installed")

    # Browsers
    print(f"  Chromium: {icon(status.chromium)}")
    print(f"  Firefox:  {icon(status.firefox)}")
    print(f"  WebKit:   {icon(status.webkit)}")

    # Deps
    print(f"  Deps OK:  {icon(status.deps_ok)}")

    # Error details
    if status.error:
        print(f"  Error:    {status.error}")

    # Summary
    print()
    if status.ready:
        print("  ✓ Ready for headless testing")
    else:
        print("  ✗ Not ready - run these commands:")
        for cmd in get_install_commands(status):
            print(f"    $ {cmd}")


def check_and_report() -> bool:
    """Check Playwright and print status.

    Convenience function for CLI usage.

    Returns:
        True if Playwright is ready, False otherwise

    """
    status = check_playwright()
    print_status(status)
    return status.ready
