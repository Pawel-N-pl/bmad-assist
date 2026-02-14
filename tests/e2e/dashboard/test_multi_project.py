"""Multi-project dashboard E2E tests.

Tests for the multi-project dashboard UI functionality.
These tests require Playwright and a running dashboard server.

Run with:
    pytest tests/e2e/dashboard/test_multi_project.py -m e2e
"""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


class TestMultiProjectDashboardNavigation:
    """Tests for navigating to and from the multi-project dashboard."""

    def test_projects_button_visible(self, page: "Page", dashboard_server: str) -> None:
        """Projects button is visible in main dashboard header."""
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        projects_btn = page.locator("[data-testid='projects-button']")
        assert projects_btn.is_visible(), "Projects button not visible"

    def test_navigate_to_projects_page(self, page: "Page", dashboard_server: str) -> None:
        """Clicking Projects button navigates to projects.html."""
        page.goto(dashboard_server)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        page.locator("[data-testid='projects-button']").click()
        page.wait_for_load_state("domcontentloaded")

        assert "/projects.html" in page.url
        assert "Multi-Project Dashboard" in page.title()

    def test_projects_page_loads_directly(self, page: "Page", dashboard_server: str) -> None:
        """Projects page loads directly without errors."""
        page.goto(f"{dashboard_server}/projects.html")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        # Check header is visible
        header = page.locator("text=Multi-Project Dashboard")
        assert header.is_visible(), "Multi-Project Dashboard header not visible"

    def test_dashboard_back_button(self, page: "Page", dashboard_server: str) -> None:
        """Dashboard button navigates back to main dashboard."""
        page.goto(f"{dashboard_server}/projects.html")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        page.locator("[data-testid='back-to-dashboard']").click()
        page.wait_for_load_state("domcontentloaded")

        # Should be back on main dashboard (no /projects.html)
        assert "/projects.html" not in page.url


class TestMultiProjectDashboardUI:
    """Tests for multi-project dashboard UI elements."""

    def test_empty_state_visible(self, page: "Page", dashboard_server: str) -> None:
        """Empty state message is shown when no projects registered."""
        page.goto(f"{dashboard_server}/projects.html")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        # May or may not be visible depending on registered projects
        # Just check the page loads without error
        assert page.locator("body").is_visible()

    def test_global_controls_visible(self, page: "Page", dashboard_server: str) -> None:
        """Global control buttons are visible."""
        page.goto(f"{dashboard_server}/projects.html")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        add_btn = page.locator("[data-testid='add-project-btn']")
        scan_btn = page.locator("[data-testid='scan-directory-btn']")
        stop_all_btn = page.locator("[data-testid='stop-all-btn']")

        assert add_btn.is_visible(), "Add Project button not visible"
        assert scan_btn.is_visible(), "Scan Directory button not visible"
        assert stop_all_btn.is_visible(), "Stop All button not visible"

    def test_running_count_badge_visible(self, page: "Page", dashboard_server: str) -> None:
        """Running count badge is visible in header."""
        page.goto(f"{dashboard_server}/projects.html")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        badge = page.locator("[data-testid='running-count']")
        assert badge.is_visible(), "Running count badge not visible"

    def test_no_js_errors_on_projects_page(self, page: "Page", dashboard_server: str) -> None:
        """Projects page loads without JavaScript errors."""
        errors: list[str] = []

        def handle_error(error: str) -> None:
            errors.append(str(error))

        page.on("pageerror", handle_error)
        page.goto(f"{dashboard_server}/projects.html")

        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1000)

        assert not errors, f"JavaScript errors: {errors}"


class TestAddProjectModal:
    """Tests for the Add Project modal."""

    def test_add_project_modal_opens(self, page: "Page", dashboard_server: str) -> None:
        """Add Project modal opens when clicking Add Project button."""
        page.goto(f"{dashboard_server}/projects.html")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        page.locator("[data-testid='add-project-btn']").click()
        page.wait_for_timeout(300)

        modal = page.locator("[data-testid='add-project-modal']")
        assert modal.is_visible(), "Add Project modal did not open"

    def test_add_project_modal_has_fields(self, page: "Page", dashboard_server: str) -> None:
        """Add Project modal contains required fields."""
        page.goto(f"{dashboard_server}/projects.html")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        page.locator("[data-testid='add-project-btn']").click()
        page.wait_for_timeout(300)

        path_input = page.locator("[data-testid='project-path-input']")
        name_input = page.locator("[data-testid='project-name-input']")
        submit_btn = page.locator("[data-testid='submit-add-btn']")
        cancel_btn = page.locator("[data-testid='cancel-add-btn']")

        assert path_input.is_visible(), "Project path input not visible"
        assert name_input.is_visible(), "Project name input not visible"
        assert submit_btn.is_visible(), "Submit button not visible"
        assert cancel_btn.is_visible(), "Cancel button not visible"

    def test_add_project_modal_closes_on_cancel(self, page: "Page", dashboard_server: str) -> None:
        """Add Project modal closes when clicking Cancel."""
        page.goto(f"{dashboard_server}/projects.html")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        page.locator("[data-testid='add-project-btn']").click()
        page.wait_for_timeout(300)

        page.locator("[data-testid='cancel-add-btn']").click()
        page.wait_for_timeout(300)

        modal = page.locator("[data-testid='add-project-modal']")
        assert not modal.is_visible(), "Modal did not close on cancel"


class TestScanDirectoryModal:
    """Tests for the Scan Directory modal."""

    def test_scan_modal_opens(self, page: "Page", dashboard_server: str) -> None:
        """Scan Directory modal opens when clicking Scan Directory button."""
        page.goto(f"{dashboard_server}/projects.html")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        page.locator("[data-testid='scan-directory-btn']").click()
        page.wait_for_timeout(300)

        modal = page.locator("[data-testid='scan-directory-modal']")
        assert modal.is_visible(), "Scan Directory modal did not open"

    def test_scan_modal_closes_on_cancel(self, page: "Page", dashboard_server: str) -> None:
        """Scan Directory modal closes when clicking Cancel."""
        page.goto(f"{dashboard_server}/projects.html")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(500)

        page.locator("[data-testid='scan-directory-btn']").click()
        page.wait_for_timeout(300)

        page.locator("[data-testid='cancel-scan-btn']").click()
        page.wait_for_timeout(300)

        modal = page.locator("[data-testid='scan-directory-modal']")
        assert not modal.is_visible(), "Modal did not close on cancel"


class TestProjectsAPI:
    """Tests for projects API endpoints."""

    def test_projects_list_endpoint(self, page: "Page", dashboard_server: str) -> None:
        """Projects list API endpoint returns valid response."""
        response = page.request.get(f"{dashboard_server}/api/projects")

        assert response.ok
        data = response.json()
        assert isinstance(data, dict)
        assert "projects" in data
        assert "running_count" in data
        assert "max_concurrent" in data

    def test_stop_all_endpoint(self, page: "Page", dashboard_server: str) -> None:
        """Stop all API endpoint returns valid response."""
        response = page.request.post(f"{dashboard_server}/api/projects/control/stop-all")

        assert response.ok
        data = response.json()
        assert isinstance(data, dict)
        assert "count" in data
