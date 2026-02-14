# QA Plan Execute - E2E Test Runner

**Workflow:** `qa-plan-execute`
**Purpose:** Execute automated E2E tests from generated test plans
**Agent:** Test Architect (TEA) or Dev (Amelia)
**Language:** {communication_language}

---

## CRITICAL RESTRICTIONS - READ BEFORE EXECUTING ANY TEST

**FORBIDDEN ACTIONS (will crash the session):**
- NEVER use `run_in_background` parameter on Bash tool - causes output overflow and session crash
- NEVER create wrapper scripts (cat > /tmp/test.sh, cat > file.sh) - execute commands directly
- NEVER use pkill, kill, or terminate processes - let them run and timeout naturally
- NEVER run servers or commands in background (&, nohup, disown) - they fill up task output
- NEVER read task output files larger than 8000 chars - causes MaxFileReadTokenExceededError

**Bash tool output handling:**
- Bash tool stdout/stderr can overflow context - truncate with `| head -c 8000` if command produces large output
- This does NOT apply to YOUR responses - always report full test results and summaries
- For server tests: start server, run test, server exits naturally with test script

**Script execution:**
- Execute test scripts EXACTLY as provided in test plan - run whole script in single Bash call
- Scripts are SELF-CONTAINED: they have their own timeout, trap cleanup, and process management
- DO NOT interfere with script's internal background processes (&) - the script handles them
- DO NOT use TaskOutput or KillShell on test scripts - just wait for script to complete
- If script fails due to syntax/path errors: You MAY fix obvious issues (wrong paths, typos, missing quotes) and retry
- If script logic is fundamentally wrong: Report as FAIL with details, do NOT rewrite the entire test

---

## Overview

This workflow executes E2E tests defined in test plans:
1. Parses test plan markdown to extract test cases
2. Executes Category A tests (CLI/API/File)
3. Optionally executes Category B tests (Playwright)
4. Collects results in structured YAML format
5. Generates summary report and bug reports for failures

---

## Prerequisites

**Required:**
- Test plan exists: `{test_plan_file}`
- Project virtual environment available (for CLI tests)

**For Category B (Playwright):**
- Playwright installed (`npx playwright --version`)
- Test stubs exist in `playwright/epic-{epic_num}.spec.ts`

**Note:** This workflow does NOT require bmad-assist CLI. It runs standalone via LLM agents.

---

## Step 1: Initialize and Gather Input

<output>
**QA Test Execution Workflow**

I'll help you execute E2E tests from your generated test plans.
</output>

### 1.1 Epic Selection

<check if="epic_num not provided">
  <action>Scan {qa_artifacts}/test-plans/ for available test plans</action>

  <ask>
  **Which epic would you like to test?**

  Available test plans:
  {list each epic-N-e2e-plan.md file found}

  Enter epic number (e.g., 17):
  </ask>
</check>

### 1.2 Verify Test Plan Exists

<action>Check if test plan file exists: {test_plan_file}</action>

<check if="test plan not found">
  <output>
  **Test plan not found:** {test_plan_file}
  </output>

  <ask>
  Would you like me to:
  1. Generate a test plan now (`/qa-plan-generate {epic_num}`)
  2. Choose a different epic
  3. Cancel

  Your choice:
  </ask>
</check>

### 1.3 Category Selection

<ask>
**Test Category Selection**

Which tests would you like to run?

1. **Category A only** (CLI/API/File) - fully automated [RECOMMENDED]
2. **Category B only** (Playwright) - requires browser
3. **All automated** (A + B)

Your choice [1]:
</ask>

### 1.4 Execution Options

<ask>
**Execution Options**

- Run all tests or specific test ID? [all / E{epic_num}-A01]:
- Verbose output? [y/N]:
- Stop on first failure? [y/N]:
</ask>

### 1.5 Batch Mode Selection

<action>Count total tests for selected category</action>

<check if="test_count > 10 AND batch_mode is null AND NOT non_interactive">
  <output>
  **Large Test Set Detected**

  You have **{test_count} tests** to execute. Running all at once may cause:
  - Context overflow (LLM may "forget" early results)
  - No progress saved if execution fails mid-way
  - Potential for hallucinated results
  </output>

  <ask>
  **How would you like to execute tests?**

  1. **Batch mode** - Run in batches of {batch_size} tests (RECOMMENDED)
     - Results saved after each batch (crash-safe)
     - Progress visible in real-time
     - Can resume from last batch if interrupted

  2. **Single run** - Execute all {test_count} tests at once
     - Faster but riskier
     - No intermediate saves
     - May cause context issues for very large sets

  3. **Adjust batch size** - Change from default {batch_size}

  Your choice [1]:
  </ask>

  <check if="choice == 3">
    <ask>
    Enter batch size (5-20 recommended):
    </ask>
    <action>Set batch_size to user value</action>
  </check>
</check>

<check if="test_count > 10 AND non_interactive">
  <output>
  **Auto-selecting batch mode** for {test_count} tests (batch size: {batch_size})
  </output>
  <action>Set batch_mode = "batch"</action>
</check>

<check if="test_count <= 10">
  <action>Set batch_mode = "all" (small set, no batching needed)</action>
</check>

### 1.6 Confirmation

<output>
**Configuration Summary**

Epic: {epic_num}
Test Plan: {test_plan_file}
Category: {category}
Tests: {test_id or "all"} ({test_count} total)
Execution: {batch_mode == "batch" ? "Batch mode (" + batch_size + " per batch)" : "Single run"}
Verbose: {verbose}
Fail-fast: {fail_fast}
</output>

<confirm>
Ready to execute tests. Proceed? [Y/n]
</confirm>

---

## Step 2: Parse Test Plan

<action>Read test plan markdown from {test_plan_file}</action>
<action>Extract Setup section (bash commands to run first)</action>
<action>Extract Master Checklist table</action>
<action>Parse Category A section for CLI/API/File tests</action>
<action>Parse Category B section for Playwright tests (if applicable)</action>

### Test Extraction Pattern

**Master Checklist Purpose:** Quick inventory of tests with IDs, names, categories. Use for filtering tests by category and building test list.

**Detailed Test Sections:** Contain actual test scripts. Use for execution.

For each test in Master Checklist (matching selected category):
1. Extract Test ID format: `E{epic}-{cat}{seq}` (e.g., E17-A01, E17-B05)
2. Extract Test Name
3. Extract Category (A/B/C from ID middle character)
4. Locate detailed test section by header: `### E{epic}-{cat}{seq}: {test_name}`
5. Extract for Category A:
   - **Full bash script block**: Extract ENTIRE content between ````bash` and closing ```
   - This includes: shebang, cleanup functions, trap handlers, heredocs, Python blocks
   - Script may span 20-100 lines - extract ALL of it
   - Pre-conditions (if mentioned before script)
   - Expected exit code (from script comments or default to 0)
6. Extract for Category B:
   - Test description and steps
   - Playwright spec reference

<output>
**Parsed {test_count} tests:**
- Category A: {a_count} tests (CLI/API/File)
- Category B: {b_count} tests (Playwright)
- Category C: {c_count} tests (skipped - requires human)

{if category == "A"}: Executing {a_count} Category A tests...
{if category == "B"}: Executing {b_count} Category B tests...
{if category == "all"}: Executing {a_count + b_count} automated tests...
</output>

---

## Step 3: Execute Setup (If Present)

<check if="setup section found in test plan">
  <output>
  **Running Setup Commands**
  </output>

  <action>Execute each setup command from the Setup section</action>
  <action>Verify environment is ready (e.g., venv activated)</action>

  <check if="setup failed">
    <output>
    **Setup Failed** - Cannot proceed with test execution.
    </output>

    <ask>
    Setup command failed. Options:
    1. Retry setup
    2. Skip setup and proceed anyway
    3. Abort execution

    Your choice:
    </ask>
  </check>
</check>

---

## Step 4: Execute Category A Tests

<check if="category in ['A', 'all']">

  ### 4.0 Batch Execution Setup

  <check if="batch_mode == 'batch'">
    <action>Split tests into batches of {batch_size}</action>
    <action>Calculate total batches: ceil(test_count / batch_size)</action>

    <output>
    **Batch Execution Mode**

    Total tests: {test_count}
    Batch size: {batch_size}
    Batches: {total_batches}

    Results will be saved after each batch to:
    {qa_artifacts}/test-results/epic-{epic_num}-run-{timestamp}.yaml
    </output>

    <action>For each batch (1 to total_batches):</action>

    <output>
    ─────────────────────────────────────────────
    **BATCH {current_batch}/{total_batches}**
    Tests: {batch_start} - {batch_end}
    ─────────────────────────────────────────────
    </output>

    <action>Execute tests in current batch (see 4.1-4.6 below)</action>

    <action>After batch completes, atomic write results to YAML:</action>
    ```yaml
    # Append to existing file or create new
    batches:
      - batch_id: {current_batch}
        completed_at: "{iso_timestamp}"
        tests:
          - id: "{test_id}"
            status: "{status}"
            duration_ms: {ms}
            # ... full test result
    ```

    <output>
    **Batch {current_batch} complete:** {batch_passed}/{batch_total} passed
    Progress: {total_completed}/{test_count} tests ({progress_pct}%)
    Results saved to: {results_file}
    </output>

    <check if="NOT last_batch AND NOT fail_fast AND NOT non_interactive">
      <ask>
      Continue to batch {next_batch}? [Y/n/skip to summary]:
      </ask>
    </check>

    <action>Continue to next batch</action>
  </check>

  <check if="batch_mode != 'batch'">
    <action>Execute all tests in single run (original behavior)</action>
  </check>

  <action>For each Category A test in order:</action>

  ### 4.1 Pre-Execution Check
  <action>Verify required tools/commands exist</action>
  <action>Check pre-conditions if specified</action>

  ### 4.2 Test Execution
  <action>Execute the bash script block with timeout</action>
  <action>Capture stdout, stderr, exit code</action>
  <action>Record execution start time and duration</action>

  ### 4.3 Result Evaluation

  **Priority Order (CRITICAL):**
  1. **First**: Check stdout for explicit markers: `✓ E{epic}-{id} PASSED` or `✗ E{epic}-{id} FAILED`
  2. **If marker found** → Use marker status (ignore exit code - tests may intentionally exit 1)
  3. **If no marker** → Compare exit code against expected (default: 0)
  4. Check for expected output patterns if specified

  <action>Scan stdout for "✓ E{epic}-" and "PASSED" to detect pass</action>
  <action>Scan stdout for "✗ E{epic}-" and "FAILED" to detect fail</action>
  <action>If no marker: compare exit code against expected</action>

  ### 4.4 Status Determination

  **Status codes:**
  - **PASS**: Exit code 0, expected output matched (or no expected output)
  - **PASS***: Core criteria met with minor deviations noted in output
  - **FAIL**: Non-zero exit code OR expected output not matched
  - **SKIP**: Pre-conditions not satisfied OR command not found
  - **ERROR**: Execution error (timeout, permission denied, crash)

  ### 4.5 Progress Output

  <output for each test>
  {status_icon} **{test_id}**: {test_name}
     Duration: {duration_ms}ms
     Exit code: {exit_code}
     {if verbose}: Output: {truncated_output}
     {if status == "FAIL"}: Error: {error_summary}
  </output>

  ### 4.6 Failure Handling

  <check if="test failed AND NOT fail_fast AND NOT non_interactive">
    <ask>
    **Test {test_id} FAILED**

    Exit code: {exit_code}
    Error: {error_summary}

    What would you like to do?
    1. Continue with remaining tests [default]
    2. Retry this test
    3. Skip remaining tests and generate report
    4. Abort execution (no report)

    Your choice [1]:
    </ask>
  </check>

  <check if="test failed AND fail_fast">
    <output>
    **Stopping execution (fail-fast mode)**
    </output>
    <action>Proceed to result generation with partial results</action>
  </check>

  <check if="test failed AND non_interactive">
    <action>Log failure and continue to next test (auto-continue mode)</action>
  </check>
</check>

---

## Step 5: Execute Category B Tests (Playwright)

<check if="category in ['B', 'all'] AND playwright_enabled">
  <action>Verify Playwright installation: `npx playwright --version`</action>

  <check if="playwright not available">
    <output>
    **Playwright not installed** - Skipping Category B tests.
    Install with: `npm install -D @playwright/test`
    </output>
    <action>Mark all Category B tests as SKIP</action>
  </check>

  <check if="playwright available">
    <action>Check if Playwright test file exists: {qa_artifacts}/playwright/epic-{epic_num}.spec.ts</action>

    <check if="test file not found">
      <output>
      Playwright test file not found. Generate with: `/qa-plan-generate {epic_num}`
      </output>
      <action>Mark all Category B tests as SKIP</action>
    </check>

    <check if="test file exists">
      <output>
      **Running Playwright Tests**
      </output>

      <action>Execute Playwright tests</action>
      ```bash
      npx playwright test {qa_artifacts}/playwright/epic-{epic_num}.spec.ts \
        {if NOT playwright_headless}: --headed \
        --reporter=json \
        --output={qa_artifacts}/test-results/playwright/
      ```

      <action>Parse Playwright JSON results</action>
      <action>Map to standard result format</action>

      <check if="playwright_screenshot_on_fail AND test failed">
        <action>Save screenshot to bugs directory</action>
      </check>
    </check>
  </check>
</check>

<check if="category == 'B' AND NOT playwright_enabled">
  <output>
  **Playwright not enabled** - Set `playwright_enabled: true` in config to run Category B tests.
  </output>
</check>

---

## Step 6: Generate Results YAML

<action>Compile all test results into structured YAML</action>
<action>Calculate summary statistics</action>
<action>Generate unique run_id with timestamp</action>

### Result File Structure

```yaml
# epic-{epic_num}-run-{timestamp}.yaml
meta:
  epic: {epic_num}
  run_id: "run-{timestamp}"
  timestamp: "{iso_timestamp}"
  duration_total_ms: {total_ms}
  category_filter: "{category}"
  test_filter: {test_id or null}

summary:
  total: {total_count}
  passed: {pass_count}
  passed_with_notes: {pass_star_count}
  failed: {fail_count}
  skipped: {skip_count}
  errors: {error_count}
  pass_rate: "{pass_rate}%"

tests:
  - id: "E{epic}.A01"
    name: "{test_name}"
    category: "A"
    status: "PASS"
    duration_ms: {ms}
    command: "{executed_command}"
    expected_exit_code: 0
    actual_exit_code: 0
    output_snippet: "{first 500 chars of stdout}"
    notes: null

  - id: "E{epic}.A02"
    name: "{test_name}"
    category: "A"
    status: "FAIL"
    duration_ms: {ms}
    command: "{executed_command}"
    expected_exit_code: 0
    actual_exit_code: 1
    output_snippet: "{first 500 chars of stdout}"
    error: "{stderr or error message}"
    bug_report: "BUG-{epic}-2.md"
```

<action>Write to {qa_artifacts}/test-results/epic-{epic_num}-run-{timestamp}.yaml</action>

---

## Step 7: Generate Bug Reports (For Failures)

<check if="generate_bug_reports AND failures exist">
  <action>Count existing bug reports in {bugs_dir} for this epic</action>
  <action>Track bug_sequence starting from (existing_count + 1)</action>
  <action>For each failed test, generate bug report with incrementing sequence</action>

  ### Bug Report Format

  ```markdown
  # BUG-{epic}-{seq}: {Test Name} Failed

  **Epic:** {epic_num}
  **QA Test:** {test_id}
  **Severity:** {auto_severity based on category}
  **Status:** Open
  **Detected:** {timestamp}

  ## Environment
  - OS: {os_info from `uname -a`}
  - Python: {python_version from `python --version`}
  - Project: bmad-assist
  - Branch: {git_branch from `git branch --show-current`}
  - Commit: {git_commit from `git rev-parse HEAD`}

  ## Test Details

  **Category:** {category}
  **Command Executed:**
  ```bash
  {command}
  ```

  ## Expected Behavior
  Exit code: {expected_exit_code}
  {expected_output if specified}

  ## Actual Behavior
  Exit code: {actual_exit_code}
  ```
  {actual_output}
  ```

  ## Error Output
  ```
  {stderr}
  ```

  ## Reproduction Steps
  1. Activate venv: `source .venv/bin/activate`
  2. Run: `{command}`
  3. Observe exit code and output differ from expected

  ## Related
  - Test Plan: {test_plan_file}
  - Story: (extracted from test plan if available)
  ```

  <action>Write to {qa_artifacts}/bugs/BUG-{epic}-{seq}.md</action>

  <output>
  Bug report generated: BUG-{epic}-{seq}.md
  </output>
</check>

---

## Step 8: Generate Summary Report

<action>Generate human-readable summary markdown</action>

### Summary Format

```markdown
# QA Execution Summary - Epic {epic_num}

**Run ID:** run-{timestamp}
**Date:** {date}
**Duration:** {formatted_duration}

## Results Overview

| Status | Count | Percentage |
|--------|-------|------------|
| PASS | {pass} | {pass_pct}% |
| PASS* | {pass_star} | {pass_star_pct}% |
| FAIL | {fail} | {fail_pct}% |
| SKIP | {skip} | {skip_pct}% |
| ERROR | {error} | {error_pct}% |
| **Total** | **{total}** | **100%** |

## Pass Rate: {pass_rate}%

## Test Results

### Passed Tests
{for each passed test}
- {status_icon} **{test_id}**: {test_name} ({duration_ms}ms)
{end for}

### Failed Tests
{for each failure}
### {test_id}: {name}
- **Status:** FAIL
- **Exit Code:** {exit_code}
- **Error:** {error_summary}
- **Bug Report:** {bug_link}
{end for}

### Skipped Tests
{for each skip}
- {test_id}: {skip_reason}
{end for}

## Recommendations

{auto_generated_recommendations based on failure patterns}

## Artifacts

- Full Results: {results_file}
- Bug Reports: {bugs_dir}
- Test Plan: {test_plan_file}
```

<action>Write to {qa_artifacts}/test-results/epic-{epic_num}-run-{timestamp}-summary.md</action>

---

## Step 9: Final Output

<output>
===============================================================
QA EXECUTION COMPLETE
===============================================================

**Epic:** {epic_num}
**Run ID:** run-{timestamp}
**Duration:** {formatted_duration}

**Results:**
| Status | Count |
|--------|-------|
| PASS   | {pass} |
| PASS*  | {pass_star} |
| FAIL   | {fail} |
| SKIP   | {skip} |
| ERROR  | {error} |

**Pass Rate:** {pass_rate}%

**Artifacts:**
- Results: {results_file}
- Summary: {summary_file}
{if fail > 0}: - Bug Reports: {bugs_dir}

{if fail > 0}:
**Action Required:** Review {fail} failed tests and bug reports.
{else}:
All tests passed! Great job!
{endif}
===============================================================
</output>

---

## Dry Run Mode

<check if="dry_run == true">
  <action>Skip all execution steps (3, 4, 5)</action>
  <action>Only perform test plan parsing</action>
  <action>Report what would be executed</action>

  <output>
  **DRY RUN COMPLETE**

  Would execute:
  - {a_count} Category A tests
  - {b_count} Category B tests

  Test IDs:
  {list all test IDs}

  No tests were actually run.
  </output>
</check>

---

## Rerun Failed Mode

<check if="rerun_failed == true">
  <action>Glob all result files: {qa_artifacts}/test-results/epic-{epic_num}-run-*.yaml</action>
  <action>Sort by timestamp in filename (format: run-YYYYMMDD-HHMMSS)</action>
  <action>Select most recent file as previous_run</action>
  <action>Load previous run results YAML</action>
  <action>Filter tests array to only status: FAIL or status: ERROR</action>
  <action>Build test_ids list from filtered tests</action>
  <action>Execute only tests matching test_ids from previous failures</action>

  <output>
  **RERUN MODE**

  Previous run: {previous_run_id}
  Re-running {failed_count} failed/error tests:
  {list failed test IDs}
  </output>
</check>

---

## Error Handling

### Timeout
- Default: 60 seconds per test
- Configurable via `timeout_seconds`
- On timeout: status = ERROR, note "Execution timed out after {timeout}s"

### Command Not Found
- Check if command exists before running
- Status = SKIP with reason "Command not found: {cmd}"

### Permission Errors
- Log error details
- Status = ERROR
- Suggest fix: "Check file permissions or run with sudo"

### Python Import Errors
- Common in CLI tests
- Status = ERROR
- Include full traceback in bug report

---

## Slash Command Examples

### Basic Usage (Interactive)
```
/qa-plan-execute
```
Starts interactive session, asks for epic number and options.

### With Epic Number
```
/qa-plan-execute 17
```
Tests Epic 17, still asks for category and options.

### Full Specification
```
/qa-plan-execute 17 --category A --verbose
```
Runs all Category A tests for Epic 17 with verbose output.

### Single Test
```
/qa-plan-execute 17 --test E17-A01
```
Runs only the specified test.

### Rerun Failures
```
/qa-plan-execute 17 --rerun-failed
```
Re-runs only tests that failed in the previous run.

---

## Status Icons Reference

| Status | Icon | Meaning |
|--------|------|---------|
| PASS | ✓ | Test passed completely |
| PASS* | ✓* | Passed with notes/warnings |
| FAIL | ✗ | Test failed |
| SKIP | ○ | Test skipped |
| ERROR | ⚠ | Execution error |

---

## Non-Interactive Mode

When `non_interactive=true` (set by bmad-assist compiler):
- All `<ask>` prompts are skipped
- All `<confirm>` prompts auto-approve
- Failures auto-continue (no user prompt)
- Uses default values for all options
- Generates report regardless of failures

---

<!-- Powered by BMAD-METHOD -->
