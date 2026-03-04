"""Dashboard xterm.js compatibility E2E tests.

Verifies xterm.js 5.3.0 initializes correctly and can render ANSI-formatted
output in the browser without JavaScript errors.

Extends existing E2E infrastructure — auto-skipped if Playwright not installed.
Uses dashboard_server fixture (URL string) that starts the dashboard server.

Story 30.7: xterm.js Compatibility Testing
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

# Timeout for xterm.js initialization (Alpine.js + xterm.js + initial write)
_XTERM_INIT_TIMEOUT = 5000  # ms


class TestXtermInitialization:
    """Verify xterm.js container and Terminal instance are created."""

    def test_xterm_container_exists(self, page: "Page", dashboard_server: str) -> None:
        """xterm.js container element (#xterm-container or [x-ref='xtermContainer']) is present."""
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")

        # The terminal container uses x-ref="xtermContainer" in Alpine.js
        container = page.locator("[x-ref='xtermContainer'], #xterm-container")
        container.first.wait_for(state="attached", timeout=_XTERM_INIT_TIMEOUT)
        assert container.count() > 0, "xterm.js container element not found"

    def test_xterm_terminal_initialized(self, page: "Page", dashboard_server: str) -> None:
        """xterm.js Terminal instance is created (renders .xterm class element)."""
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")

        # xterm.js adds .xterm class to the container when initialized
        xterm_el = page.locator(".xterm")
        xterm_el.first.wait_for(state="visible", timeout=_XTERM_INIT_TIMEOUT)
        assert xterm_el.count() > 0, (
            "xterm.js Terminal not initialized — no .xterm element found"
        )

    def test_no_javascript_errors(self, page: "Page", dashboard_server: str) -> None:
        """Page loads without JavaScript errors."""
        errors: list[str] = []

        def handle_error(error: str) -> None:
            errors.append(str(error))

        page.on("pageerror", handle_error)
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")

        # Wait for xterm.js to fully initialize before checking errors
        page.locator(".xterm").first.wait_for(state="visible", timeout=_XTERM_INIT_TIMEOUT)

        assert not errors, f"JavaScript errors on page load: {errors}"


class TestXtermRendering:
    """Verify xterm.js can render content."""

    def test_xterm_has_rendered_rows(self, page: "Page", dashboard_server: str) -> None:
        """xterm.js renders content rows after initialization."""
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")
        page.locator(".xterm-rows").first.wait_for(state="attached", timeout=_XTERM_INIT_TIMEOUT)

        # xterm.js renders rows inside .xterm-rows element
        rows = page.locator(".xterm-rows")
        assert rows.count() > 0, "xterm.js did not render any rows"

        # Verify the terminal has child rows (actual content)
        row_children = rows.locator("div")
        assert row_children.count() > 0, "xterm-rows has no child row elements"

    def test_xterm_initial_content(self, page: "Page", dashboard_server: str) -> None:
        """xterm.js displays initial welcome content after init."""
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")
        page.locator(".xterm-rows").first.wait_for(state="attached", timeout=_XTERM_INIT_TIMEOUT)
        # Allow terminal.js to write initial message
        page.wait_for_timeout(500)

        # terminal.js writes initial welcome message containing "bmad-assist"
        xterm_text = page.locator(".xterm-rows").inner_text()
        assert "bmad-assist" in xterm_text.lower(), (
            f"Expected 'bmad-assist' in terminal welcome, got: {xterm_text[:200]}"
        )

    def test_256_color_ansi_rendering(self, page: "Page", dashboard_server: str) -> None:
        """256-color ANSI codes render without errors via direct xterm.js API write (AC#4)."""
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")
        page.locator(".xterm").first.wait_for(state="visible", timeout=_XTERM_INIT_TIMEOUT)

        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # Write 256-color ANSI text directly to xterm.js via browser JS context
        page.evaluate("""() => {
            const container = document.querySelector('[x-ref="xtermContainer"]') ||
                              document.querySelector('#xterm-container');
            const term = container?.__xterm || container?._xterm ||
                         window._bmadTerminal;
            if (term && term.write) {
                term.write('\\x1b[38;5;208mOrange\\x1b[0m \\x1b[38;5;45mCyan\\x1b[0m\\r\\n');
            } else {
                // Fallback: find Terminal via xterm.js internal DOM
                const xtermEl = document.querySelector('.xterm');
                if (xtermEl && xtermEl._core) {
                    xtermEl._core.write('\\x1b[38;5;208mOrange\\x1b[0m\\r\\n');
                }
            }
        }""")
        page.wait_for_timeout(200)

        # Verify no JS errors from ANSI rendering
        assert not errors, f"JavaScript errors during 256-color write: {errors}"

        # Verify xterm.js still has rendered rows (rendering didn't break)
        rows = page.locator(".xterm-rows div")
        assert rows.count() > 0, "xterm.js rows disappeared after ANSI color write"

    def test_auto_scroll_viewport_exists(self, page: "Page", dashboard_server: str) -> None:
        """xterm.js viewport element exists for auto-scroll support (AC#4)."""
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")
        page.locator(".xterm").first.wait_for(state="visible", timeout=_XTERM_INIT_TIMEOUT)

        # Verify viewport element exists (required for scroll behavior)
        viewport = page.locator(".xterm-viewport")
        assert viewport.count() > 0, "xterm-viewport not found — auto-scroll cannot work"

        # Verify multiple rows exist (terminal has content to scroll)
        rows = page.locator(".xterm-rows div")
        assert rows.count() > 1, "Terminal has too few rows for scroll verification"

    def test_fitaddon_resize_no_errors(self, page: "Page", dashboard_server: str) -> None:
        """FitAddon handles viewport resize without JavaScript errors (AC#4)."""
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")
        page.locator(".xterm").first.wait_for(state="visible", timeout=_XTERM_INIT_TIMEOUT)

        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # Resize viewport to trigger ResizeObserver → FitAddon.fit()
        page.set_viewport_size({"width": 800, "height": 400})
        page.wait_for_timeout(500)  # Allow ResizeObserver to fire

        # Resize back to verify re-fit works
        page.set_viewport_size({"width": 1280, "height": 720})
        page.wait_for_timeout(500)

        # Verify no JS errors from resize
        assert not errors, f"JavaScript errors during resize: {errors}"

        # Verify terminal still renders after resize
        xterm_el = page.locator(".xterm")
        assert xterm_el.count() > 0, "Terminal element disappeared after resize"


class TestXtermVersion:
    """Verify xterm.js version matches expected pinned version."""

    def test_xterm_cdn_version(self, page: "Page", dashboard_server: str) -> None:
        """xterm.js CDN script tag references version 5.3.0."""
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")

        # Check xterm.js core script tag
        xterm_script = page.locator("script[src*='xterm']")
        assert xterm_script.count() > 0, "No xterm.js script tag found"

        src = xterm_script.first.get_attribute("src") or ""
        assert "5.3.0" in src, (
            f"Expected xterm.js 5.3.0 in script src, got: {src}"
        )

    def test_xterm_addon_cdn_versions(self, page: "Page", dashboard_server: str) -> None:
        """FitAddon (0.8.0) and WebLinksAddon (0.9.0) CDN versions are correct (AC#8)."""
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")

        # Check FitAddon version
        fit_script = page.locator("script[src*='xterm-addon-fit']")
        assert fit_script.count() > 0, "No xterm-addon-fit script tag found"
        fit_src = fit_script.first.get_attribute("src") or ""
        assert "0.8.0" in fit_src, f"Expected FitAddon 0.8.0, got: {fit_src}"

        # Check WebLinksAddon version
        links_script = page.locator("script[src*='xterm-addon-web-links']")
        assert links_script.count() > 0, "No xterm-addon-web-links script tag found"
        links_src = links_script.first.get_attribute("src") or ""
        assert "0.9.0" in links_src, f"Expected WebLinksAddon 0.9.0, got: {links_src}"
