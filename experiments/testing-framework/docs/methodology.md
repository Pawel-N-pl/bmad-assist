# Behavioral Testing Methodology

## Purpose & Scope

This methodology defines how to create **behavioral tests** for AI-generated projects (fixtures). Unlike unit tests that verify internal implementation, behavioral tests verify:

1. **External behavior** - What the application does from a user/consumer perspective
2. **Contract compliance** - API responses match documented specifications
3. **User journeys** - End-to-end workflows function correctly

### Why Behavioral Testing?

AI-generated code varies significantly between runs. Testing internal implementation details would require rewriting tests for each fixture. Behavioral tests are:

- **Implementation-agnostic** - Same tests work for Go, Python, or Node implementations
- **Stable** - Changes to internal code don't break tests unless behavior changes
- **Meaningful** - Test what users actually experience

### Out of Scope

- Unit tests (these should exist within the fixture itself)
- Performance benchmarks (handled by bmad-assist benchmarking module)
- Security audits (require specialized tooling)

---

## Test Categories

### 1. API Behavior Tests

Test HTTP endpoints for correct request/response handling.

**What to test:**
- Endpoint availability (correct HTTP methods)
- Request validation (required fields, types, formats)
- Response structure (JSON schema, status codes)
- Error handling (4xx/5xx responses)
- Edge cases (empty inputs, special characters)

**What NOT to test:**
- Internal database queries
- Specific error message wording
- Implementation-specific headers

**Example structure:**
```python
class TestWebhookEndpoint:
    """Verify webhook ingestion endpoint behavior."""

    def test_accepts_valid_webhook(self, app_client):
        """Webhook endpoint accepts valid JSON payload."""
        response = app_client.post("/webhook/test", json={"event": "push"})
        assert response.status_code == 200

    def test_rejects_invalid_content_type(self, app_client):
        """Webhook endpoint rejects non-JSON content."""
        response = app_client.post("/webhook/test", data="plain text")
        assert response.status_code in (400, 415)  # Bad Request or Unsupported Media
```

### 2. UI Journey Tests

Test end-to-end user workflows using browser automation (Playwright).

**What to test:**
- Navigation flows (user can reach key pages)
- Form submissions (data persists correctly)
- Interactive elements (buttons, dropdowns work)
- Feedback (success/error messages appear)

**What NOT to test:**
- Exact CSS styling
- Animation timing
- Browser-specific rendering

**Example structure:**
```python
class TestAdminDashboardJourney:
    """Verify admin can manage webhook routes."""

    def test_create_route(self, page):
        """Admin can create a new webhook route."""
        page.goto("/admin/routes")
        page.click("button:has-text('New Route')")
        page.fill("[name=path]", "/webhook/github")
        page.click("button:has-text('Save')")

        # Verify route appears in list
        assert page.locator("text=/webhook/github").is_visible()
```

### 3. Data Integrity Tests

Test that data operations maintain consistency.

**What to test:**
- CRUD operations complete correctly
- Relationships are maintained
- Constraints are enforced

---

## Test Design Process

### Step 1: Extract Requirements from PRD

Read the fixture's `docs/prd.md` and extract testable requirements:

```yaml
# requirements_map.yaml
requirements:
  FR-1:
    description: "System accepts webhooks via HTTP POST"
    tests:
      - test_api_behavior.py::TestWebhookEndpoint::test_accepts_valid_webhook
      - test_api_behavior.py::TestWebhookEndpoint::test_rejects_get_request
```

### Step 2: Define API Contract

Create a minimal contract from `docs/architecture.md`:

```yaml
# contract.yaml
endpoints:
  - path: /webhook/{name}
    methods: [POST]
    request:
      content_type: application/json
    responses:
      200: { description: "Webhook accepted" }
      400: { description: "Invalid payload" }
```

### Step 3: Write Tests from Outside-In

Start with the most visible behavior, then work inward:

1. **Happy path first** - Does the basic use case work?
2. **Error cases** - What happens with bad input?
3. **Edge cases** - Empty arrays, large payloads, special characters

### Step 4: Use Fixtures for Setup

Create pytest fixtures for common setup:

```python
@pytest.fixture
def seeded_database(app_client):
    """Pre-populate database with test routes."""
    app_client.post("/admin/routes", json={
        "path": "/webhook/test",
        "destinations": [{"url": "http://localhost:9999/sink"}]
    })
    yield
    # Cleanup happens when fixture app restarts
```

---

## Conventions & Standards

### Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Test files | `test_{feature}_behavior.py` | `test_api_behavior.py` |
| Test classes | `Test{Feature}{Aspect}` | `TestWebhookValidation` |
| Test methods | `test_{action}_{expected}` | `test_post_returns_200` |

### Selector Strategy (UI Tests)

Prefer selectors that survive implementation changes:

| Priority | Selector Type | Example |
|----------|---------------|---------|
| 1 | data-testid | `[data-testid="submit-btn"]` |
| 2 | Role + name | `button:has-text('Save')` |
| 3 | Semantic HTML | `form >> button[type=submit]` |
| 4 | CSS class | `.btn-primary` (avoid) |

### Assertion Guidelines

**DO:**
```python
# Assert behavior, not implementation
assert response.status_code == 200
assert "id" in response.json()
assert len(routes) > 0
```

**DON'T:**
```python
# Too specific to implementation
assert response.json()["internal_id"] == "uuid-123"
assert response.headers["X-Custom-Header"] == "v1.2.3"
```

### Timeouts

Use generous timeouts for CI stability:

```python
# API tests: 5-10 seconds per request
response = app_client.post("/webhook", timeout=10.0)

# UI tests: explicit waits
page.wait_for_selector("[data-testid=result]", timeout=15000)
```

---

## Definition of Done

A fixture's test suite is complete when:

### Coverage
- [ ] All PRD functional requirements have at least one test
- [ ] All API endpoints are tested (happy path + main error cases)
- [ ] Critical user journeys are covered (if UI exists)
- [ ] Requirements map is complete (`requirements_map.yaml`)

### Quality
- [ ] Tests pass consistently (no flaky tests)
- [ ] Tests are independent (no shared state between tests)
- [ ] Setup/teardown is handled by fixtures
- [ ] Test names clearly describe what's being verified

### Documentation
- [ ] `requirements_map.yaml` links tests to PRD requirements
- [ ] `contract.yaml` documents expected API behavior
- [ ] Complex test logic has inline comments

---

## Handling Fixture Variations

When the same project is generated multiple times (e.g., webhook-relay-001 vs webhook-relay-002):

### Shared Tests

Tests that verify PRD requirements should be identical:

```
experiments/fixture-tests/
├── webhook-relay-001/
│   ├── test_api_behavior.py      # Identical content
│   └── requirements_map.yaml     # Identical mappings
└── webhook-relay-002/
    ├── test_api_behavior.py      # Copy from 001
    └── requirements_map.yaml     # Copy from 001
```

### Fixture-Specific Adjustments

If implementation differs significantly (e.g., different port, different binary name):

```python
# conftest.py (per-fixture)
@pytest.fixture
def app_config():
    return {
        "port": 8081,  # Differs from webhook-relay-001's 8080
        "binary": "./cmd/relay/relay",
    }
```

### Tracking Differences

Document implementation differences in `FIXTURE_META.yaml`:

```yaml
implementation_notes:
  - "Uses port 8081 instead of 8080"
  - "Admin API path changed from /admin to /api/admin"
```
