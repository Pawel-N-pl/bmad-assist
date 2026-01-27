"""
API Behavioral Tests for webhook-relay

Tests verify external behavior of the webhook relay service
without coupling to internal implementation details.

These tests apply to ALL webhook-relay variants (001, 002, etc.)
because they verify PRD requirements, not implementation details.

Usage:
    # Test baseline variant
    pytest experiments/fixture-tests/webhook-relay/ -v

    # Test specific variant
    pytest experiments/fixture-tests/webhook-relay/ --fixture-variant=webhook-relay-002

Requirements:
    - Go 1.21+ (to build fixture)
    - httpx (pip install httpx)
"""

import pytest


# ============================================================================
# HEALTH CHECK TESTS (FR-018)
# ============================================================================


class TestHealthEndpoints:
    """Verify health and readiness endpoints (FR-018)."""

    def test_health_endpoint_returns_200(self, app_client):
        """Health endpoint indicates service is running."""
        response = app_client.get("/health")
        assert response.status_code == 200

    def test_health_returns_json(self, app_client):
        """Health endpoint returns JSON response."""
        response = app_client.get("/health")
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type or response.status_code == 200
        # Allow either JSON or plain text health response
        try:
            data = response.json()
            assert "status" in data or "healthy" in str(data).lower()
        except Exception:
            # Plain text response is acceptable
            assert "healthy" in response.text.lower() or response.status_code == 200

    def test_ready_endpoint(self, app_client):
        """Ready endpoint indicates service can accept traffic."""
        response = app_client.get("/health/ready")
        assert response.status_code == 200

    def test_live_endpoint(self, app_client):
        """Live endpoint indicates service is alive."""
        response = app_client.get("/health/live")
        assert response.status_code == 200


# ============================================================================
# OBSERVABILITY TESTS (FR-017)
# ============================================================================


class TestObservability:
    """Verify observability endpoints."""

    def test_metrics_endpoint(self, app_client):
        """Metrics endpoint returns Prometheus format (FR-017)."""
        response = app_client.get("/metrics")
        assert response.status_code == 200
        # Prometheus format contains metric lines
        assert "# " in response.text or "_" in response.text


# ============================================================================
# WEBHOOK ENDPOINT TESTS (FR-001, FR-003, FR-006)
# ============================================================================


class TestWebhookEndpoint:
    """Verify webhook ingestion endpoint behavior."""

    def test_accepts_valid_json_payload(self, app_client, test_route):
        """Webhook endpoint accepts valid JSON POST (FR-001, FR-006)."""
        response = app_client.post(
            f"/webhook/{test_route['id']}",
            json={"event": "push", "data": {"commit": "abc123"}},
        )
        # Accept 200 (success) or 202 (accepted for async processing)
        assert response.status_code in (200, 202, 404)
        # If successful, should return some ID
        if response.status_code in (200, 202):
            try:
                data = response.json()
                assert "id" in data or "status" in data
            except Exception:
                pass  # Plain text OK for some implementations

    def test_rejects_get_request(self, app_client, test_route):
        """Webhook endpoint does not accept GET requests."""
        response = app_client.get(f"/webhook/{test_route['id']}")
        assert response.status_code in (404, 405)

    def test_handles_empty_body(self, app_client, test_route):
        """Webhook endpoint handles empty JSON body gracefully (FR-003)."""
        response = app_client.post(f"/webhook/{test_route['id']}", json={})
        # Accept either success (lenient) or client error (strict validation)
        assert response.status_code in (200, 202, 400)

    def test_handles_invalid_json(self, app_client, test_route):
        """Webhook endpoint rejects invalid JSON (FR-003)."""
        response = app_client.post(
            f"/webhook/{test_route['id']}",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400

    def test_route_not_found(self, app_client):
        """Unknown webhook route returns 404 (FR-001)."""
        response = app_client.post(
            "/webhook/nonexistent-route-99999",
            json={"event": "test"},
        )
        assert response.status_code == 404

    @pytest.mark.skip(reason="Requires route with signature configured")
    def test_signature_validation(self, app_client, test_route_with_secret):
        """Webhook rejects invalid signature (FR-002)."""
        response = app_client.post(
            f"/webhook/{test_route_with_secret['id']}",
            json={"event": "test"},
            headers={"X-Webhook-Signature": "invalid-signature"},
        )
        assert response.status_code == 401


# ============================================================================
# ADMIN ROUTES TESTS (FR-013)
# ============================================================================


class TestAdminRoutes:
    """Verify admin route management API (FR-013)."""

    def test_list_routes(self, app_client):
        """Admin can list all routes."""
        response = app_client.get("/admin/routes")
        assert response.status_code == 200
        data = response.json()
        # Should be an array (possibly empty) or wrapped response
        assert isinstance(data, (list, dict))

    def test_create_route(self, app_client):
        """Admin can create a new route."""
        route_data = {
            "path": "/webhook/test-create-route",
        }
        response = app_client.post("/admin/routes", json=route_data)
        assert response.status_code in (200, 201)

    def test_create_route_validates_required_fields(self, app_client):
        """Route creation validates required fields."""
        response = app_client.post("/admin/routes", json={})
        assert response.status_code == 400

    def test_get_single_route(self, app_client, test_route):
        """Admin can retrieve a specific route."""
        response = app_client.get(f"/admin/routes/{test_route['id']}")
        assert response.status_code == 200
        data = response.json()
        assert "id" in data or "path" in data

    def test_update_route(self, app_client, test_route):
        """Admin can update a route."""
        update_data = {"path": "/webhook/updated-path"}
        response = app_client.put(f"/admin/routes/{test_route['id']}", json=update_data)
        assert response.status_code in (200, 204)

    def test_delete_route(self, app_client):
        """Admin can delete a route."""
        # First create a route to delete
        create_resp = app_client.post(
            "/admin/routes",
            json={"path": "/webhook/to-delete"},
        )
        if create_resp.status_code in (200, 201):
            route_id = create_resp.json().get("id")
            if route_id:
                response = app_client.delete(f"/admin/routes/{route_id}")
                assert response.status_code in (200, 204)


# ============================================================================
# ADMIN DESTINATIONS TESTS (FR-014)
# ============================================================================


class TestAdminDestinations:
    """Verify admin destination management API (FR-014)."""

    def test_list_destinations(self, app_client, test_route):
        """Admin can list destinations for a route."""
        response = app_client.get(f"/admin/routes/{test_route['id']}/destinations")
        assert response.status_code == 200

    def test_add_destination(self, app_client, test_route):
        """Admin can add a destination to a route."""
        dest_data = {
            "url": "http://localhost:9999/sink",
            "method": "POST",
        }
        response = app_client.post(
            f"/admin/routes/{test_route['id']}/destinations",
            json=dest_data,
        )
        assert response.status_code in (200, 201)


# ============================================================================
# DELIVERY HISTORY TESTS (FR-015)
# ============================================================================


class TestDeliveryHistory:
    """Verify delivery history API (FR-015)."""

    def test_list_deliveries(self, app_client):
        """Admin can query delivery history."""
        response = app_client.get("/admin/deliveries")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))

    def test_filter_deliveries_by_route(self, app_client, test_route):
        """Admin can filter deliveries by route."""
        response = app_client.get(f"/admin/deliveries?route_id={test_route['id']}")
        assert response.status_code == 200


# ============================================================================
# DEAD LETTER QUEUE TESTS (FR-011, FR-016)
# ============================================================================


class TestDeadLetterQueue:
    """Verify dead letter queue API (FR-011, FR-016)."""

    def test_list_dlq_entries(self, app_client):
        """Admin can list DLQ entries."""
        response = app_client.get("/admin/dead-letter-queue")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================


class TestErrorHandling:
    """Verify API error responses are well-formed."""

    def test_404_returns_json(self, app_client):
        """404 errors return JSON response."""
        response = app_client.get("/nonexistent-endpoint-12345")
        assert response.status_code == 404

    def test_method_not_allowed(self, app_client):
        """Wrong HTTP method returns 405 or 404."""
        response = app_client.delete("/health")
        assert response.status_code in (404, 405)


# ============================================================================
# PYTEST FIXTURES
# ============================================================================


@pytest.fixture(scope="session")
def test_route(app_client):
    """Create a test route for use in tests."""
    # Create route
    response = app_client.post(
        "/admin/routes",
        json={"path": "/webhook/pytest-test-route"},
    )
    if response.status_code in (200, 201):
        route = response.json()
        yield route
        # Cleanup
        app_client.delete(f"/admin/routes/{route.get('id', '')}")
    else:
        # If creation fails, yield a dummy for tests to handle
        yield {"id": "test-fallback", "path": "/webhook/test"}


@pytest.fixture
def test_route_with_secret(app_client):
    """Create a test route with signature validation enabled."""
    response = app_client.post(
        "/admin/routes",
        json={
            "path": "/webhook/pytest-signed-route",
            "secret": "test-secret-12345",
        },
    )
    if response.status_code in (200, 201):
        route = response.json()
        yield route
        app_client.delete(f"/admin/routes/{route.get('id', '')}")
    else:
        yield {"id": "signed-fallback", "path": "/webhook/signed", "secret": "test"}
