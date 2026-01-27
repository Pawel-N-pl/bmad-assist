"""
UI Journey Tests Template (Playwright)

Copy this file to experiments/fixture-tests/{fixture-name}/test_user_journeys.py
and customize for your fixture's UI.

Requirements:
    pip install playwright pytest-playwright
    playwright install chromium

Usage:
    pytest experiments/fixture-tests/{fixture-name}/test_user_journeys.py -v

    # Run with visible browser (debugging)
    pytest experiments/fixture-tests/{fixture-name}/test_user_journeys.py -v --headed

    # Run with slow motion (debugging)
    pytest experiments/fixture-tests/{fixture-name}/test_user_journeys.py -v --headed --slowmo 500
"""

from pathlib import Path

import pytest

# ============================================================================
# CONFIGURATION - Edit these for your fixture
# ============================================================================

FIXTURE_NAME = "your-fixture-name"  # e.g., "webhook-relay-001"
FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / FIXTURE_NAME

# Skip all UI tests if fixture has no UI
pytestmark = pytest.mark.skipif(
    not (FIXTURE_PATH / "static").exists()
    and not (FIXTURE_PATH / "public").exists()
    and not (FIXTURE_PATH / "templates").exists(),
    reason="Fixture has no UI (no static/, public/, or templates/ directory)",
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture(scope="module")
def browser_context(playwright, app_url):
    """Create browser context for UI tests."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        base_url=app_url,
    )
    yield context
    context.close()
    browser.close()


@pytest.fixture
def page(browser_context):
    """Create a new page for each test."""
    page = browser_context.new_page()
    yield page
    page.close()


# ============================================================================
# NAVIGATION TESTS
# ============================================================================


class TestNavigation:
    """Verify basic navigation works."""

    def test_home_page_loads(self, page, app_url):
        """Home page loads without errors."""
        response = page.goto(app_url)
        assert response.ok
        # Verify page has content
        assert page.title() or page.locator("body").text_content()

    def test_admin_dashboard_accessible(self, page, app_url):
        """Admin dashboard is accessible."""
        page.goto(f"{app_url}/admin")
        # Wait for page to load
        page.wait_for_load_state("networkidle")
        # Verify dashboard elements exist
        assert page.locator("h1, h2, [data-testid=dashboard]").count() > 0

    @pytest.mark.skip(reason="Customize for your fixture's navigation")
    def test_navigation_menu(self, page, app_url):
        """Navigation menu links work."""
        page.goto(app_url)
        # Click nav link
        page.click("nav >> text=Routes")
        # Verify navigation
        assert "/routes" in page.url or page.locator("text=Routes").is_visible()


# ============================================================================
# ROUTE MANAGEMENT JOURNEY
# ============================================================================


class TestRouteManagementJourney:
    """User journey: Managing webhook routes."""

    def test_view_routes_list(self, page, app_url):
        """User can view list of routes."""
        page.goto(f"{app_url}/admin/routes")
        page.wait_for_load_state("networkidle")

        # Verify routes list is displayed
        assert page.locator("table, [data-testid=routes-list], .routes").count() > 0

    @pytest.mark.skip(reason="Customize for your fixture's route creation UI")
    def test_create_new_route(self, page, app_url):
        """User can create a new route via UI."""
        page.goto(f"{app_url}/admin/routes")

        # Click "New Route" button
        page.click("text=New Route")
        # Or: page.click("[data-testid=new-route-btn]")

        # Fill form
        page.fill("[name=path], [data-testid=route-path]", "/webhook/ui-test")
        page.fill(
            "[name=destination_url], [data-testid=destination-url]",
            "http://localhost:9999/sink",
        )

        # Submit
        page.click("text=Save")
        # Or: page.click("button[type=submit]")

        # Verify route appears in list
        page.wait_for_selector("text=/webhook/ui-test")
        assert page.locator("text=/webhook/ui-test").is_visible()

    @pytest.mark.skip(reason="Customize for your fixture's route editing UI")
    def test_edit_route(self, page, app_url):
        """User can edit an existing route."""
        page.goto(f"{app_url}/admin/routes")

        # Click edit on first route
        page.click("text=Edit >> nth=0")
        # Or: page.click("[data-testid=edit-btn] >> nth=0")

        # Modify path
        page.fill("[name=path]", "/webhook/edited-route")

        # Save
        page.click("text=Save")

        # Verify change
        page.wait_for_selector("text=/webhook/edited-route")


# ============================================================================
# DELIVERY HISTORY JOURNEY
# ============================================================================


class TestDeliveryHistoryJourney:
    """User journey: Viewing delivery history."""

    @pytest.mark.skip(reason="Customize for your fixture's history UI")
    def test_view_delivery_history(self, page, app_url):
        """User can view delivery history."""
        page.goto(f"{app_url}/admin/history")
        page.wait_for_load_state("networkidle")

        # Verify history list/table exists
        assert page.locator("table, [data-testid=history-list]").count() > 0

    @pytest.mark.skip(reason="Customize for your fixture's history search")
    def test_filter_by_status(self, page, app_url):
        """User can filter history by delivery status."""
        page.goto(f"{app_url}/admin/history")

        # Select status filter
        page.select_option("[data-testid=status-filter]", "failed")
        # Or: page.click("text=Failed")

        # Verify filter applied
        page.wait_for_load_state("networkidle")
        # All visible items should show "failed" status
        # assert page.locator("[data-status=failed]").count() > 0


# ============================================================================
# ERROR HANDLING JOURNEY
# ============================================================================


class TestErrorHandling:
    """Verify UI handles errors gracefully."""

    def test_404_page(self, page, app_url):
        """404 page is user-friendly."""
        page.goto(f"{app_url}/nonexistent-page-12345")

        # Should show some error indication
        content = page.content().lower()
        assert "404" in content or "not found" in content or "error" in content

    @pytest.mark.skip(reason="Customize for your fixture's form validation")
    def test_form_validation_errors(self, page, app_url):
        """Form shows validation errors."""
        page.goto(f"{app_url}/admin/routes/new")

        # Submit empty form
        page.click("button[type=submit]")

        # Should show validation error
        assert page.locator(".error, [data-testid=error], text=required").count() > 0


# ============================================================================
# RESPONSIVE DESIGN
# ============================================================================


class TestResponsiveDesign:
    """Verify UI works on different screen sizes."""

    @pytest.mark.skip(reason="Enable for responsive UI testing")
    def test_mobile_viewport(self, browser_context, app_url):
        """UI is usable on mobile viewport."""
        page = browser_context.new_page()
        page.set_viewport_size({"width": 375, "height": 667})  # iPhone SE

        page.goto(app_url)
        page.wait_for_load_state("networkidle")

        # Verify critical elements are visible
        assert page.locator("nav, header, [data-testid=nav]").is_visible()

        page.close()


# ============================================================================
# CUSTOM JOURNEYS - Add fixture-specific journeys below
# ============================================================================

# class TestWebhookTestingJourney:
#     """User journey: Testing webhooks from UI."""
#
#     def test_send_test_webhook(self, page, app_url):
#         """User can send a test webhook from UI."""
#         page.goto(f"{app_url}/admin/routes")
#         page.click("text=Test >> nth=0")
#         page.fill("[data-testid=test-payload]", '{"event": "test"}')
#         page.click("text=Send")
#         page.wait_for_selector("text=Success")
