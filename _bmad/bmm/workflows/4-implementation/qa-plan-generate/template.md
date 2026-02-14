# E2E Test Plan - Epic {epic_num}

**Generated:** {date}
**Epic:** {epic_title}

---

## Setup

Run once before executing tests:

```bash
export PROJECT_ROOT="$(pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate
```

---

## Test Categories Summary

| Category | Description | Count | Automation |
|----------|-------------|-------|------------|
| A | CLI/API/File | {count_a} | 100% |
| B | Playwright/UI | {count_b} | 100% (with selectors) |
| C | Human Verification | {count_c} | Manual |
| **Total** | | **{total}** | |

---

## Master Checklist

| ID | Test Name | Category | Status |
|----|-----------|----------|--------|
{checklist_rows}

---

## Category A Tests (CLI/API/File)

### Prerequisites

- Python virtual environment activated
- Project dependencies installed
- Required services running (if applicable)

{category_a_tests}

---

## Category B Tests (Playwright/UI)

### Prerequisites

- Playwright installed: `npm install -D @playwright/test`
- Browsers installed: `npx playwright install`
- Dashboard server running: `bmad-assist dashboard --port 8765`

### forceClick Helper

Include this helper in all spec files for footer button interactions:

```typescript
async function forceClick(page: Page, selector: string) {
  await page.evaluate((sel: string) => {
    const el = document.querySelector(sel) as HTMLElement;
    if (el) { el.scrollIntoView({ block: 'center' }); el.click(); }
  }, selector);
}
```

{category_b_tests}

---

## Category C Tests (Human Verification)

{category_c_tests}

---

## Traceability Matrix

| Requirement | Test IDs | Coverage |
|-------------|----------|----------|
{traceability_rows}

---

## Notes

{notes}

---

## Automation Recommendations

{recommendations}

<!-- QA_PLAN_END -->
