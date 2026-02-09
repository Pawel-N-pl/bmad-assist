# QA Plan Generate Workflow

**Workflow ID**: `qa-plan-generate`
**Version**: 1.0

---

## Overview

Generate comprehensive E2E test plans for completed epics. The test plan categorizes tests into:
- **Category A (Full Automation)**: CLI commands, REST API, file validation - 100% automatable
- **Category B (Playwright)**: UI tests requiring browser - automatable with Playwright
- **Category C (Human)**: External integrations, credentials, subjective assessment

---

## Preflight Checks

### Step 0.1: Validate Epic Number

1. Check that `{epic_num}` is provided
2. If not provided, ask user: "Which epic should I generate a QA plan for?"

### Step 0.2: Check Existing Plan

1. Check if `{output_file}` already exists
2. If exists AND `{force}` is false:
   - Inform user: "QA plan already exists at {output_file}. Use --force to regenerate."
   - HALT workflow
3. If exists AND `{force}` is true:
   - Continue (will overwrite)

---

## Step 1: Load Context

### 1.1: Load Epic Definition

Search for epic file in these locations:
- `{project-root}/docs/epics/epic-{epic_num}.md`
- `{project-root}/docs/epics/epic-{epic_num}-*.md`
- `{output_folder}/planning-artifacts/*epic*{epic_num}*.md`

If found, load and note key information:
- Epic title and description
- Functional requirements
- User stories referenced
- Technical scope

### 1.2: Load Stories

Search for story files:
- `{output_folder}/implementation-artifacts/stories/{epic_num}-*.md`

Load up to 10 stories. For each story note:
- Story title and acceptance criteria
- Technical implementation details
- Any UI components mentioned

### 1.3: Load Traceability (Optional)

Check if trace file exists: `{trace_file}`

If exists, load and use for:
- Requirement coverage mapping
- Existing test references
- Gap analysis

### 1.4: Load UX Elements Documentation (CRITICAL for Category B)

**This step is MANDATORY before generating any Category B tests.**

Search for `ux-elements.md` in these locations:
1. `{project-root}/docs/modules/dashboard/ux-elements.md`
2. `{project-root}/docs/modules/experiments/ux-elements.md`
3. `{project-root}/docs/ux-elements.md`
4. `{project-root}/docs/epics/epic-{epic_num}-ux.md`

**If UX elements file found:**
- Load the COMPLETE file
- This contains ALL valid `data-testid` selectors
- You MUST use ONLY selectors from this document for Category B tests
- **NEVER invent or guess `data-testid` values**

**If UX elements file NOT found:**
- Mark all Category B tests as "requires manual selector discovery"
- Add note: "UX elements documentation not found - selectors need verification"

### 1.5: Load PRD Requirements (CRITICAL for Traceability)

**This step is MANDATORY for proper test-to-requirement mapping.**

Load `{project-root}/docs/prd.md` and extract:
1. **Functional Requirements (FR)** section - FR-1 through FR-XX
2. **Non-Functional Requirements (NFR)** section - NFR-1 through NFR-XX

These requirements MUST be used in:
- Test comments: `# Requirement: FR-26, AC-3`
- Traceability Matrix: mapping every test to FR/NFR/AC/DoD

### 1.6: Load Additional Context (Optional)

If available, also load:
- `{project-root}/docs/architecture.md` - Technical architecture (for NFR context)

---

## Step 2: Analyze Requirements

### 2.1: Extract Testable Requirements

From loaded context, identify:
1. **Functional Requirements (FR)** - What the system should do
2. **Acceptance Criteria (AC)** - Specific conditions for each story
3. **Technical Behaviors** - API endpoints, CLI commands, file operations
4. **UI Interactions** - Dashboard elements, forms, buttons (only if ux-elements.md exists)

### 2.2: Classify Test Categories

For each requirement, determine category:

**Category A (CLI/API/File)**:
- CLI command execution and output validation
- REST API endpoint testing
- File system operations (read/write/validate)
- Database state verification
- Configuration validation

**Category B (Playwright/UI)**:
- Dashboard interactions
- Form submissions
- Navigation flows
- Visual state verification
- **ONLY if ux-elements.md exists and provides selectors**

**Category C (Human Verification)**:
- External service integrations
- Credential/auth flows requiring real accounts
- Subjective quality assessment
- Third-party API interactions
- Performance under real conditions

---

## Step 3: Generate Test Plan

### 3.1: Test ID Format

Use consistent ID format:
- `E{epic_num}-A##` for Category A tests (e.g., E17-A01)
- `E{epic_num}-B##` for Category B tests (e.g., E17-B01)
- `E{epic_num}-C##` for Category C tests (e.g., E17-C01)

### 3.2: Generate Category A Tests

For each CLI/API/File requirement:

```bash
# E{epic_num}-A##: {Test Name}
# Requirement: {FR/AC reference}
# Expected: {Expected outcome}

# Setup
export PROJECT_ROOT="$(pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate

# Test
{actual test commands}

# Verify
echo "Expected exit code: 0"

# Cleanup
{cleanup commands if needed}
```

**Rules:**
- NEVER hardcode absolute paths - use `$PROJECT_ROOT`
- Always activate venv before Python/CLI commands
- Include cleanup for any created files/state
- Each test must be idempotent (can run multiple times)

### 3.3: Generate Category B Tests (ONLY with UX Elements)

**CRITICAL: Only generate if ux-elements.md was loaded in Step 1.4**

For each UI interaction:

```typescript
// E{epic_num}-B##: {Test Name}
// Requirement: {FR/AC reference}
// Selectors from: ux-elements.md

test('{test description}', async ({ page }) => {
  await page.goto('http://localhost:8765/');

  // Use forceClick for footer buttons (experiments-button, settings-button)
  await forceClick(page, '[data-testid="{selector-from-ux-elements}"]');

  // Wait for panel/modal
  await expect(page.locator('[data-testid="{another-selector}"]')).toBeVisible();

  // Interactions...
});
```

**forceClick Helper (include in all Category B tests):**
```typescript
async function forceClick(page: Page, selector: string) {
  await page.evaluate((sel: string) => {
    const el = document.querySelector(sel) as HTMLElement;
    if (el) { el.scrollIntoView({ block: 'center' }); el.click(); }
  }, selector);
}
```

**Category B Rules:**
- ONLY use `data-testid` selectors from ux-elements.md
- NEVER invent selector names
- Footer buttons (experiments-button, settings-button) need forceClick helper
- Always wait for panels/modals with `toBeVisible()`
- **NEVER use `aria-selected`, `aria-checked`** - not present in UI
- **NEVER use classes like `active`, `selected`** - UI uses Tailwind CSS
- **Check visibility, NOT classes** - Alpine.js controls state via x-show
- **NEVER guess dropdown option values** - verify dynamically or move to Cat C

### 3.4: Generate Category C Tests

For each human verification item:

```markdown
### E{epic_num}-C##: {Test Name}

**Requirement:** {FR/AC reference}

**Prerequisites:**
- {list prerequisites}

**Steps:**
1. {step 1}
2. {step 2}
...

**Expected Result:**
- {expected outcome}

**Pass Criteria:**
- [ ] {criterion 1}
- [ ] {criterion 2}
```

---

## Step 4: Write Output

### 4.1: Create Output Directory

Ensure `{qa_artifacts}/test-plans/` exists.

### 4.2: Write Test Plan File

Write to `{output_file}` using the template structure:

1. **Header** - Epic info, generation date
2. **Test Categories Summary** - Count by category
3. **Master Checklist** - All tests with ID, name, category, status
4. **Category A Tests** - Full bash scripts
5. **Category B Tests** - Playwright test specs (or note if ux-elements missing)
6. **Category C Tests** - Human verification checklists
7. **Traceability Matrix** - FR/AC to Test mapping
8. **Notes** - Any warnings about missing selectors, etc.

### 4.3: Report Summary

After writing, output:

```
## QA Plan Generated

**Epic:** {epic_num}
**Output:** {output_file}

**Test Counts:**
- Category A (CLI/API): X tests
- Category B (Playwright): Y tests
- Category C (Human): Z tests
- **Total:** X+Y+Z tests

**Notes:**
- {any warnings about ux-elements, missing context, etc.}

**Next Steps:**
1. Review generated test plan
2. Run Category A tests: `bmad-assist qa execute --epic {epic_num} --category A`
3. Run Category B tests: `bmad-assist qa execute --epic {epic_num} --category B`
4. Complete Category C manual tests
```

---

## Important Notes

### Path Variables
- `$PROJECT_ROOT` - Use in all bash scripts, NEVER hardcode paths
- Always use relative paths from project root

### Test Isolation
- Each test must be independent
- Clean up any created state
- Use temp directories for file operations: `TMPDIR=$(mktemp -d)`

### UX Elements (Category B)
- If ux-elements.md not found, Category B tests are marked as incomplete
- NEVER guess or invent `data-testid` values
- Footer buttons always need forceClick helper due to viewport issues

### Traceability
- Link each test to specific FR or AC
- Note coverage gaps
- Use trace file if available for enhanced coverage analysis

---

## CRITICAL Output Requirements

**THIS SECTION OVERRIDES ALL OTHER INSTRUCTIONS IF THERE IS ANY CONFLICT.**

### You MUST Generate Complete Test Code

This is NOT a summary document. This is NOT a test plan outline.
You MUST generate **ACTUAL EXECUTABLE TEST CODE** for every single test.

**For Category A tests** - Each test MUST include:
- Full bash script in a code block
- Actual Python code where needed (using heredoc)
- Setup, test execution, and verification
- Cleanup with trap
- Expected exit code echo

**Example of REQUIRED output quality for Category A:**
```bash
# E{epic_num}-A01: {Descriptive test name}
# Requirement: {AC/FR reference}
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT
TMPDIR=$(mktemp -d)

# Create test fixture
cat > "$TMPDIR/test.yaml" << 'EOF'
name: test-config
providers:
  master:
    provider: claude
    model: opus
EOF

# Execute test
$PROJECT_ROOT/.venv/bin/python << 'PYEOF'
from pathlib import Path
from bmad_assist.experiments.config import load_config_template

template = load_config_template(Path("$TMPDIR/test.yaml"))
assert template.name == "test-config"
print("PASS: Config loaded successfully")
PYEOF

echo "Expected exit code: 0"
```

**For Category B tests** - Each test MUST include:
- Full Playwright test function in TypeScript
- Actual selectors from ux-elements.md (NEVER invented)
- Wait conditions and assertions
- forceClick helper usage for footer buttons
- **Page navigation:** `await page.goto('http://localhost:8765');`
- **Wait for load:** `await page.waitForLoadState('domcontentloaded');` (NOT 'networkidle' - SSE breaks it)

**For Category C tests** - Each test MUST include:
- Numbered step-by-step instructions
- Prerequisites section
- Pass criteria checklist with checkbox syntax

### Minimum Test Requirements

- **Minimum 20 Category A tests** for any non-trivial epic
- **At least 5 tests per story** in the epic
- **Every acceptance criterion** must have at least one test
- If Category B tests are generated, minimum 10 UI tests

### Output Format Rules

1. **Start with:** `# E2E Test Plan - Epic {epic_num}`
2. **Include Setup section** with PROJECT_ROOT and venv activation
3. **Include Master Checklist table** with ALL tests listed
4. **Each test has its own subsection** with full code
5. **End with:** `<!-- QA_PLAN_END -->`

### CRITICAL: Test Script Format (DO NOT IGNORE!)

**EACH TEST MUST BE IN ITS OWN MARKDOWN SUBSECTION with separate code block!**

The test plan will be parsed by automated tooling that extracts individual tests.
DO NOT generate one big file with all tests together.

Each test needs:
- A markdown header: `### E19-A01: Test Name` or `### E19-B01: Test Name`
- Its own fenced code block (```bash or ```typescript)

**WRONG FORMAT (DO NOT DO THIS):**
```typescript
test.describe('All tests', () => {
  test('E19-B01: ...') { ... }
  test('E19-B02: ...') { ... }
});
```

**CORRECT FORMAT (DO THIS):**

### E19-B01: Test name
```typescript
test('E19-B01: test name', async ({ page }) => {
  await page.goto('http://localhost:8765');
  await page.waitForLoadState('domcontentloaded');
  // test code here
});
```

### E19-B02: Another test
```typescript
test('E19-B02: another test', async ({ page }) => {
  await page.goto('http://localhost:8765');
  await page.waitForLoadState('domcontentloaded');
  // test code here
});
```

Each Category B test MUST be a **standalone** `test()` function - NOT inside `test.describe()`.

### What NOT To Do

- DO NOT generate summaries like "Tests cover X functionality"
- DO NOT generate placeholder code like "# Add test code here"
- DO NOT skip tests with "See documentation"
- DO NOT generate test descriptions without actual code
- DO NOT reduce test count to save tokens
- **DO NOT put multiple tests in one `test.describe()` block**
- **DO NOT generate one big TypeScript file with all tests**
- **DO NOT use `'networkidle'` wait state (breaks with SSE)**

### This Plan Will Be Executed

Remember: This test plan will be **EXECUTED** by automated tooling and humans.
Every test must be immediately runnable without modification.
If you cannot generate a complete test, mark it as Category C with manual steps.
