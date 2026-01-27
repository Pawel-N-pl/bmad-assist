"""
API Behavioral Tests Template

Copy this file to experiments/fixture-tests/{fixture-name}/test_api_behavior.py
and customize for your fixture's API.

Usage:
    pytest experiments/fixture-tests/{fixture-name}/test_api_behavior.py -v
"""

from pathlib import Path

import pytest

# ============================================================================
# CONFIGURATION - Edit these for your fixture
# ============================================================================

FIXTURE_NAME = "your-fixture-name"  # e.g., "webhook-relay-001"
FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / FIXTURE_NAME

# ============================================================================
# FIXTURES - Provided by common/conftest.py
# ============================================================================
# The following fixtures are available:
#   - app_client: httpx.Client connected to running fixture app
#   - app_url: str - base URL of the running app (e.g., "http://localhost:8080")
#   - running_fixture: ensures fixture app is started before tests


# ============================================================================
# HEALTH CHECK TESTS
# ============================================================================


class TestHealthEndpoints:
    """Verify health and readiness endpoints."""

    def test_health_endpoint_returns_200(self, app_client):
        """Health endpoint indicates service is running."""
        response = app_client.get("/health")
        assert response.status_code == 200

    def test_health_returns_json(self, app_client):
        """Health endpoint returns JSON response."""
        response = app_client.get("/health")
        assert response.headers.get("content-type", "").startswith("application/json")
        data = response.json()
        assert "status" in data or "healthy" in str(data).lower()

    @pytest.mark.skip(reason="Uncomment if fixture has /ready endpoint")
    def test_ready_endpoint(self, app_client):
        """Ready endpoint indicates service can accept traffic."""
        response = app_client.get("/ready")
        assert response.status_code == 200


# ============================================================================
# WEBHOOK ENDPOINT TESTS (Example - customize for your API)
# ============================================================================


class TestWebhookEndpoint:
    """Verify webhook ingestion endpoint behavior."""

    def test_accepts_valid_json_payload(self, app_client):
        """Webhook endpoint accepts valid JSON POST."""
        response = app_client.post(
            "/webhook/test",
            json={"event": "push", "data": {"commit": "abc123"}},
        )
        assert response.status_code == 200
        data = response.json()
        # Verify response contains expected fields
        assert "id" in data or "status" in data

    def test_rejects_get_request(self, app_client):
        """Webhook endpoint does not accept GET requests."""
        response = app_client.get("/webhook/test")
        assert response.status_code in (404, 405)  # Not Found or Method Not Allowed

    def test_handles_empty_body(self, app_client):
        """Webhook endpoint handles empty JSON body gracefully."""
        response = app_client.post("/webhook/test", json={})
        # Accept either success (lenient) or client error (strict validation)
        assert response.status_code in (200, 400)

    def test_handles_invalid_json(self, app_client):
        """Webhook endpoint rejects invalid JSON."""
        response = app_client.post(
            "/webhook/test",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400

    def test_route_not_found(self, app_client):
        """Unknown webhook route returns 404."""
        response = app_client.post(
            "/webhook/nonexistent-route-12345",
            json={"event": "test"},
        )
        assert response.status_code == 404


# ============================================================================
# ADMIN API TESTS (Example - customize for your API)
# ============================================================================


class TestAdminRoutes:
    """Verify admin route management API."""

    def test_list_routes(self, app_client):
        """Admin can list all routes."""
        response = app_client.get("/admin/routes")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))  # Either array or wrapped response

    def test_create_route(self, app_client):
        """Admin can create a new route."""
        route_data = {
            "path": "/webhook/test-create",
            "destinations": [{"url": "http://localhost:9999/sink"}],
        }
        response = app_client.post("/admin/routes", json=route_data)
        assert response.status_code in (200, 201)

    def test_create_route_validates_required_fields(self, app_client):
        """Route creation requires path and destinations."""
        response = app_client.post("/admin/routes", json={})
        assert response.status_code == 400

    @pytest.mark.skip(reason="Uncomment and customize for your fixture")
    def test_get_single_route(self, app_client):
        """Admin can retrieve a specific route."""
        # First create a route
        create_resp = app_client.post(
            "/admin/routes",
            json={"path": "/webhook/test-get", "destinations": []},
        )
        route_id = create_resp.json().get("id")

        # Then retrieve it
        response = app_client.get(f"/admin/routes/{route_id}")
        assert response.status_code == 200
        assert response.json()["path"] == "/webhook/test-get"


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================


class TestErrorHandling:
    """Verify API error responses are well-formed."""

    def test_404_returns_json(self, app_client):
        """404 errors return JSON response."""
        response = app_client.get("/nonexistent-endpoint-12345")
        assert response.status_code == 404
        # Optionally verify JSON error format
        # data = response.json()
        # assert "error" in data

    def test_method_not_allowed(self, app_client):
        """Wrong HTTP method returns 405."""
        response = app_client.delete("/health")  # DELETE on health endpoint
        assert response.status_code in (404, 405)


# ============================================================================
# CONTRACT COMPLIANCE TESTS
# ============================================================================


class TestContractCompliance:
    """Verify API responses match documented contract."""

    def test_response_content_type(self, app_client):
        """All API responses use application/json."""
        endpoints = ["/health", "/admin/routes"]
        for endpoint in endpoints:
            response = app_client.get(endpoint)
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                assert "application/json" in content_type, f"{endpoint} should return JSON"

    @pytest.mark.skip(reason="Customize for your fixture's specific fields")
    def test_webhook_response_fields(self, app_client):
        """Webhook response contains required fields per contract."""
        response = app_client.post("/webhook/test", json={"event": "test"})
        if response.status_code == 200:
            data = response.json()
            # Verify fields from contract.yaml
            required_fields = ["id", "status"]
            for field in required_fields:
                assert field in data, f"Response missing required field: {field}"


# ============================================================================
# CUSTOM TESTS - Add fixture-specific tests below
# ============================================================================

# class TestDeliveryHistory:
#     """Verify delivery history API."""
#
#     def test_list_deliveries(self, app_client):
#         """Can retrieve delivery history."""
#         response = app_client.get("/admin/deliveries")
#         assert response.status_code == 200
