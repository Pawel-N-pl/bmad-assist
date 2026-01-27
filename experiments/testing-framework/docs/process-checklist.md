# Process Checklist

Step-by-step guide for creating behavioral tests for a new fixture.

---

## Prerequisites

- [ ] Fixture is complete (all stories marked "done" in sprint-status.yaml)
- [ ] Fixture builds successfully
- [ ] You have read the fixture's PRD and architecture docs

---

## Phase 1: Fixture Setup (5 min)

### 1.1 Add Fixture Metadata

```bash
# Copy template
cp experiments/testing-framework/templates/FIXTURE_META.yaml \
   experiments/fixtures/{fixture-name}/FIXTURE_META.yaml
```

Edit `FIXTURE_META.yaml`:
- [ ] Set `bmad_assist_version` (check run-manifest.yaml or .bmad-assist/state.yaml)
- [ ] Set `created_at` date
- [ ] Set `model_config` (master/multi providers)
- [ ] Add any `implementation_notes`

### 1.2 Create Test Directory

```bash
mkdir -p experiments/fixture-tests/{fixture-name}
```

---

## Phase 2: Requirements Mapping (15-30 min)

### 2.1 Create Requirements Map

```bash
cp experiments/testing-framework/templates/requirements_map.yaml \
   experiments/fixture-tests/{fixture-name}/requirements_map.yaml
```

### 2.2 Extract Requirements from PRD

Open `experiments/fixtures/{fixture-name}/docs/prd.md` and identify:

- [ ] Functional Requirements (FR-1, FR-2, etc.)
- [ ] Key acceptance criteria from stories
- [ ] Critical user journeys

### 2.3 Map Requirements to Test Cases

For each requirement, define test cases:

```yaml
requirements:
  FR-1:
    description: "Accept webhooks via HTTP POST"
    priority: high
    tests:
      - test_api_behavior.py::TestWebhook::test_accepts_post
      - test_api_behavior.py::TestWebhook::test_rejects_get
```

**Tip:** Start with high-priority requirements. You can add more tests later.

---

## Phase 3: API Contract (10-20 min)

### 3.1 Create Contract File

```bash
cp experiments/testing-framework/templates/contract.yaml \
   experiments/fixture-tests/{fixture-name}/contract.yaml
```

### 3.2 Document Endpoints

From `docs/architecture.md`, extract:

- [ ] All HTTP endpoints (path, methods)
- [ ] Request formats (content-type, required fields)
- [ ] Response formats (status codes, body structure)
- [ ] Error responses

**Minimal contract example:**

```yaml
endpoints:
  - path: /webhook/{name}
    methods: [POST]
    request:
      content_type: application/json
      required_fields: []
    responses:
      200: { body_type: json, fields: [id, status] }
      400: { body_type: json, fields: [error] }
```

---

## Phase 4: API Tests (30-60 min)

### 4.1 Create Test File

```bash
cp experiments/testing-framework/templates/test_api_template.py \
   experiments/fixture-tests/{fixture-name}/test_api_behavior.py
```

### 4.2 Configure Test for Fixture

Edit the top of `test_api_behavior.py`:

```python
FIXTURE_NAME = "{fixture-name}"
FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / FIXTURE_NAME
```

### 4.3 Write Tests for Each Endpoint

For each endpoint in `contract.yaml`:

- [ ] Happy path test (valid request → expected response)
- [ ] Validation test (missing required field → 400)
- [ ] Method test (wrong HTTP method → 405)

**Example pattern:**

```python
class TestWebhookEndpoint:
    """Tests for /webhook/{name} endpoint."""

    def test_accepts_valid_webhook(self, app_client):
        response = app_client.post("/webhook/test", json={"event": "push"})
        assert response.status_code == 200
        assert "id" in response.json()

    def test_rejects_empty_body(self, app_client):
        response = app_client.post("/webhook/test", json={})
        # Accept either 200 (lenient) or 400 (strict)
        assert response.status_code in (200, 400)
```

### 4.4 Run Tests

```bash
# Single test file
pytest experiments/fixture-tests/{fixture-name}/test_api_behavior.py -v

# Stop on first failure
pytest experiments/fixture-tests/{fixture-name}/ -v -x
```

---

## Phase 5: UI Journey Tests (30-60 min, if applicable)

### 5.1 Check if UI Exists

Look for:
- [ ] `static/` or `public/` directories
- [ ] Frontend build in package.json
- [ ] HTML templates
- [ ] Web routes in code (e.g., serving index.html)

If no UI exists, skip to Phase 6.

### 5.2 Create UI Test File

```bash
cp experiments/testing-framework/templates/test_ui_template.py \
   experiments/fixture-tests/{fixture-name}/test_user_journeys.py
```

### 5.3 Identify Key Journeys

From PRD or stories, identify 3-5 critical user journeys:

Example journeys for admin dashboard:
- [ ] View list of routes
- [ ] Create new route
- [ ] Edit existing route
- [ ] View delivery history
- [ ] Retry failed delivery

### 5.4 Write Journey Tests

```python
class TestRouteManagement:
    """Admin can manage webhook routes."""

    def test_view_routes(self, page, app_url):
        page.goto(f"{app_url}/admin/routes")
        assert page.locator("h1").text_content() == "Routes"

    def test_create_route(self, page, app_url):
        page.goto(f"{app_url}/admin/routes")
        page.click("text=New Route")
        page.fill("[name=path]", "/webhook/test")
        page.click("text=Save")
        assert page.locator("text=/webhook/test").is_visible()
```

### 5.5 Run UI Tests

```bash
# Install Playwright browsers (first time)
playwright install chromium

# Run UI tests
pytest experiments/fixture-tests/{fixture-name}/test_user_journeys.py -v

# Run with browser visible (debugging)
pytest experiments/fixture-tests/{fixture-name}/test_user_journeys.py -v --headed
```

---

## Phase 6: Verification (10 min)

### 6.1 Run Full Test Suite

```bash
pytest experiments/fixture-tests/{fixture-name}/ -v
```

All tests should pass.

### 6.2 Check Requirements Coverage

Review `requirements_map.yaml`:
- [ ] Every FR has at least one test
- [ ] High-priority requirements have multiple tests
- [ ] Tests are correctly named

### 6.3 Validate Contract Accuracy

Compare `contract.yaml` against actual API responses:
- [ ] All documented endpoints exist
- [ ] Response fields match documentation
- [ ] Status codes are accurate

---

## Phase 7: Scorecard (5 min)

### 7.1 Generate Automated Scorecard

```bash
python -m experiments.testing_framework.common.scorecard {fixture-name}
```

### 7.2 Review and Complete Manual Sections

If fixture has UI:
- [ ] Open scorecard at `experiments/analysis/scorecards/{fixture-name}.yaml`
- [ ] Complete `ui_ux.details` section manually
- [ ] Update `ui_ux.score` with total

### 7.3 Save Final Scorecard

Ensure scorecard is committed:

```bash
git add experiments/analysis/scorecards/{fixture-name}.yaml
```

---

## Phase 8: Archive (Optional)

If this fixture represents a baseline to preserve:

### 8.1 Generate Checksums

```bash
cd experiments/fixtures/{fixture-name}
find . -type f -exec sha256sum {} \; > ../checksums-{fixture-name}.txt
```

### 8.2 Tag in Git

```bash
git tag fixtures-{fixture-name}-$(date +%Y%m%d)
```

---

## Summary Checklist

| Phase | Output | Time |
|-------|--------|------|
| 1. Setup | `FIXTURE_META.yaml`, test directory | 5 min |
| 2. Requirements | `requirements_map.yaml` | 15-30 min |
| 3. Contract | `contract.yaml` | 10-20 min |
| 4. API Tests | `test_api_behavior.py` | 30-60 min |
| 5. UI Tests | `test_user_journeys.py` | 30-60 min |
| 6. Verify | All tests pass | 10 min |
| 7. Scorecard | `{fixture}.yaml` in scorecards/ | 5 min |
| 8. Archive | Checksums + git tag | 5 min |

**Total time:** 1.5-3 hours per fixture (depending on UI complexity)

---

## Troubleshooting

### Tests can't connect to fixture

1. Check app discovery strategy in `conftest.py`
2. Verify port isn't in use: `lsof -i :8080`
3. Check fixture logs for startup errors

### Flaky tests

1. Increase timeouts in assertions
2. Add explicit waits for async operations
3. Ensure tests don't share state

### Playwright can't find elements

1. Use `page.pause()` to debug selectors
2. Prefer `data-testid` over CSS selectors
3. Wait for page load: `page.wait_for_load_state("networkidle")`
