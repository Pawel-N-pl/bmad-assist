"""Batch executor for QA tests with incremental saves.

Executes tests in configurable batches with atomic writes after each batch.
Prevents context overflow and enables crash-safe resumption.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from bmad_assist.core.config import Config
from bmad_assist.core.paths import get_paths
from bmad_assist.core.types import EpicId
from bmad_assist.providers import get_provider
from bmad_assist.qa.parser import ParsedTestPlan, TestCase

logger = logging.getLogger(__name__)

# Default batch size
DEFAULT_BATCH_SIZE = 10


@dataclass
class RetryEntry:
    """Record of a single retry attempt for a test.

    Attributes:
        at: Timestamp of retry attempt.
        previous_status: Status before this retry.
        previous_error: Error message before retry.
        previous_duration_ms: Duration before retry.

    """

    at: str
    previous_status: str
    previous_error: str = ""
    previous_duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        return {
            "at": self.at,
            "previous_status": self.previous_status,
            "previous_error": self.previous_error,
            "previous_duration_ms": self.previous_duration_ms,
        }


@dataclass
class TestResult:
    """Result of a single test execution.

    Attributes:
        test_id: Test identifier.
        name: Test name.
        category: Test category (A/B/C).
        status: Result status (PASS, FAIL, SKIP, ERROR).
        duration_ms: Execution duration in milliseconds.
        exit_code: Process exit code.
        output: Captured stdout (truncated).
        error: Error message if failed.
        retries: History of retry attempts (if any).

    """

    test_id: str
    name: str
    category: str
    status: str
    duration_ms: int = 0
    exit_code: int = 0
    output: str = ""
    error: str = ""
    retries: list[RetryEntry] = field(default_factory=list)


@dataclass
class BatchResult:
    """Result of a batch execution.

    Attributes:
        batch_id: Batch number (1-indexed).
        completed_at: Completion timestamp.
        tests: List of test results in this batch.
        passed: Count of passed tests.
        failed: Count of failed tests.
        skipped: Count of skipped tests.
        errors: Count of error tests.

    """

    batch_id: int
    completed_at: str
    tests: list[TestResult] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0

    def add_result(self, result: TestResult) -> None:
        """Add a test result and update counters."""
        self.tests.append(result)
        if result.status == "PASS":
            self.passed += 1
        elif result.status == "FAIL":
            self.failed += 1
        elif result.status == "SKIP":
            self.skipped += 1
        elif result.status == "ERROR":
            self.errors += 1


@dataclass
class ExecutionState:
    """State of batch execution for resume support.

    Attributes:
        epic_id: Epic being tested.
        category: Test category filter.
        batch_size: Tests per batch.
        run_id: Unique run identifier.
        started_at: Execution start time.
        results_path: Path to results YAML.
        summary_path: Path to generated summary markdown.
        completed_batches: List of completed batch results.
        total_tests: Total number of tests.
        total_batches: Total number of batches.
        retry_of: If this is a retry, the original run ID (DEPRECATED - use retry_count).
        retried_tests: List of test IDs being retried (DEPRECATED).
        retry_count: Number of retry attempts on this run.
        last_retry_at: Timestamp of last retry.

    """

    epic_id: EpicId
    category: str
    batch_size: int
    run_id: str
    started_at: str
    results_path: Path
    summary_path: Path | None = None
    completed_batches: list[BatchResult] = field(default_factory=list)
    total_tests: int = 0
    total_batches: int = 0
    retry_of: str | None = None  # DEPRECATED
    retried_tests: list[str] = field(default_factory=list)  # DEPRECATED
    retry_count: int = 0
    last_retry_at: str | None = None

    @property
    def completed_test_count(self) -> int:
        """Count of completed tests across all batches."""
        return sum(len(b.tests) for b in self.completed_batches)

    @property
    def last_completed_batch(self) -> int:
        """ID of last completed batch (0 if none)."""
        if not self.completed_batches:
            return 0
        return max(b.batch_id for b in self.completed_batches)

    @property
    def total_passed(self) -> int:
        """Total passed tests across all batches."""
        return sum(b.passed for b in self.completed_batches)

    @property
    def total_failed(self) -> int:
        """Total failed tests across all batches."""
        return sum(b.failed for b in self.completed_batches)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        meta: dict[str, Any] = {
            "epic": self.epic_id,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "category_filter": self.category,
            "batch_size": self.batch_size,
            "total_tests": self.total_tests,
            "total_batches": self.total_batches,
        }
        # Add retry info
        if self.retry_count > 0:
            meta["retry_count"] = self.retry_count
            meta["last_retry_at"] = self.last_retry_at

        def test_to_dict(t: TestResult) -> dict[str, Any]:
            """Convert test result to dict, including retries if present."""
            d: dict[str, Any] = {
                "id": t.test_id,
                "name": t.name,
                "category": t.category,
                "status": t.status,
                "duration_ms": t.duration_ms,
                "exit_code": t.exit_code,
                "output": t.output[:500] if t.output else "",
                "error": t.error,
            }
            if t.retries:
                d["retries"] = [r.to_dict() for r in t.retries]
            return d

        return {
            "meta": meta,
            "summary": {
                "completed_batches": len(self.completed_batches),
                "completed_tests": self.completed_test_count,
                "passed": self.total_passed,
                "failed": self.total_failed,
                "pass_rate": f"{(self.total_passed / self.completed_test_count * 100):.1f}%"
                if self.completed_test_count > 0
                else "0%",
            },
            "batches": [
                {
                    "batch_id": b.batch_id,
                    "completed_at": b.completed_at,
                    "passed": b.passed,
                    "failed": b.failed,
                    "skipped": b.skipped,
                    "errors": b.errors,
                    "tests": [test_to_dict(t) for t in b.tests],
                }
                for b in self.completed_batches
            ],
        }


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomically write YAML file using temp file + rename.

    Args:
        path: Target file path.
        data: Data to serialize as YAML.

    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first
    fd, temp_path = tempfile.mkstemp(
        suffix=".yaml",
        prefix=".qa-results-",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        # Atomic rename
        os.rename(temp_path, path)
        logger.debug("Atomic write: %s", path)
    except Exception:
        # Clean up temp file on failure
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def _build_batch_prompt(
    project_path: Path,
    epic_id: EpicId,
    tests: list[TestCase],
    batch_id: int,
    total_batches: int,
    previous_summary: str = "",
) -> str:
    """Build a focused prompt for a single batch of tests.

    Instead of compiling the full qa-plan-execute workflow (which embeds the entire
    50KB test plan), this builds a minimal prompt with ONLY the tests for this batch.

    Args:
        project_path: Project root directory.
        epic_id: Epic identifier.
        tests: List of tests in this batch.
        batch_id: Current batch number.
        total_batches: Total number of batches.
        previous_summary: Summary of previous batches for context.

    Returns:
        Focused prompt string for this batch only.

    """
    # Build test scripts section
    test_scripts = []
    for t in tests:
        if t.script:
            test_scripts.append(f"### {t.id}: {t.name}\n\n```bash\n{t.script}\n```")
        else:
            test_scripts.append(f"### {t.id}: {t.name}\n\n(No script provided - skip this test)")

    scripts_section = "\n\n".join(test_scripts)

    # Build focused prompt
    prompt = f"""# QA Test Execution - Epic {epic_id} - Batch {batch_id}/{total_batches}

## Critical Instructions

You are executing **ONLY** the tests listed below. Do NOT look for or execute any other tests.
This is batch {batch_id} of {total_batches}. Execute these {len(tests)} tests and report results.

{previous_summary}

## Project Context

- **Project Root:** {project_path}
- **Epic:** {epic_id}
- **Virtual Environment:** Activate with `source .venv/bin/activate`

## Tests to Execute (ONLY THESE {len(tests)} TESTS)

{scripts_section}

## CRITICAL RESTRICTIONS - READ FIRST

**FORBIDDEN ACTIONS (will crash the session):**
- NEVER use `run_in_background` parameter - it causes output overflow
- NEVER create wrapper scripts in /tmp or elsewhere (cat > file.sh)
- NEVER use pkill, kill, or terminate processes
- NEVER run servers or commands in background (&, nohup, disown)
- NEVER read task output files larger than 8000 chars

**Bash tool output handling:**
- Bash tool stdout/stderr can overflow context
- Truncate with `| head -c 8000` if command produces large output
- This does NOT apply to YOUR responses - always report full test results and summaries

## Execution Instructions

For each test above:
1. Activate venv: `source .venv/bin/activate`
2. Execute the **ENTIRE** bash script in a **SINGLE** Bash tool call - do NOT split it
3. Scripts are SELF-CONTAINED: they have timeout, trap cleanup, and process management built-in
4. **DO NOT interfere** with script's internal `&` background processes - the script handles them
5. **DO NOT use TaskOutput or KillShell** - just wait for script to complete naturally
6. **If script fails due to syntax/path errors**: You MAY fix obvious issues and retry
7. **If script logic is wrong**: Report as FAIL with details, do NOT rewrite the test
8. Record: exit code, stdout, stderr
9. Determine status based on:
   - Look for markers: `✓ E{epic_id}-* PASSED` or `✗ E{epic_id}-* FAILED`
   - If no marker: exit code 0 = PASS, non-zero = FAIL

## Required Output Format

After executing all tests, output a summary like:

```
BATCH {batch_id} RESULTS:
✓ E{epic_id}-Xxx: Test Name - PASS (exitcode=0, 234ms)
✗ E{epic_id}-Yyy: Test Name - FAIL (exitcode=1, 567ms, error: assertion failed)
○ E{epic_id}-Zzz: Test Name - SKIP (no script)
...

Summary: X passed, Y failed, Z skipped
```

IMPORTANT: Include duration in milliseconds for each test (time from script start to finish).

Execute the tests now. Start with `source .venv/bin/activate`.
"""
    return prompt


def _parse_batch_results(output: str, tests: list[TestCase]) -> list[TestResult]:
    """Parse LLM output to extract test results.

    Args:
        output: Raw LLM output.
        tests: List of tests that were executed.

    Returns:
        List of TestResult objects.

    """
    import re

    results: list[TestResult] = []

    for test in tests:
        # Look for test result markers in output
        # Pattern: ✓ E17-A01 PASSED or ✗ E17-A01 FAILED
        pass_pattern = rf"[✓✔]\s*{re.escape(test.id)}.*?PASS"
        fail_pattern = rf"[✗✘×]\s*{re.escape(test.id)}.*?FAIL"
        skip_pattern = rf"[○◯]\s*{re.escape(test.id)}.*?SKIP"
        error_pattern = rf"[⚠!]\s*{re.escape(test.id)}.*?ERROR"

        status = "PASS"  # Default optimistic
        error_msg = ""

        if re.search(fail_pattern, output, re.IGNORECASE):
            status = "FAIL"
            # Try to extract error message - multiple patterns for flexibility
            # Pattern 1: "error: message)" format from our prompt template
            error_match = re.search(
                rf"{re.escape(test.id)}.*?error:\s*([^)\n]+)",
                output,
                re.IGNORECASE,
            )
            if error_match:
                error_msg = error_match.group(1).strip()[:200]
            else:
                # Pattern 2: "Error: message" or "Failed: message" format
                error_match = re.search(
                    rf"{re.escape(test.id)}.*?(?:Error|Failed|Failure):\s*(.+?)(?:\n|$)",
                    output,
                    re.IGNORECASE,
                )
                if error_match:
                    error_msg = error_match.group(1).strip()[:200]
                else:
                    # Pattern 3: Capture the whole FAIL line as fallback
                    fail_line = re.search(
                        rf"[✗✘×]\s*{re.escape(test.id)}[^\n]+",
                        output,
                    )
                    if fail_line:
                        error_msg = fail_line.group(0).strip()[:200]
        elif re.search(skip_pattern, output, re.IGNORECASE):
            status = "SKIP"
        elif re.search(error_pattern, output, re.IGNORECASE):
            status = "ERROR"
        elif not re.search(pass_pattern, output, re.IGNORECASE):
            # No explicit marker found - check if test ID mentioned at all
            if test.id not in output:
                status = "SKIP"
                error_msg = "Test not found in output"

        # Try to extract duration
        duration_ms = 0
        duration_match = re.search(
            rf"{re.escape(test.id)}.*?(\d+)\s*ms",
            output,
            re.IGNORECASE,
        )
        if duration_match:
            duration_ms = int(duration_match.group(1))

        results.append(
            TestResult(
                test_id=test.id,
                name=test.name,
                category=test.category,
                status=status,
                duration_ms=duration_ms,
                error=error_msg,
            )
        )

    return results


def execute_batch(
    config: Config,
    project_path: Path,
    epic_id: EpicId,
    tests: list[TestCase],
    batch_id: int,
    total_batches: int,
    previous_summary: str = "",
) -> BatchResult:
    """Execute a single batch of tests.

    Args:
        config: Configuration instance.
        project_path: Project root directory.
        epic_id: Epic identifier.
        tests: Tests in this batch.
        batch_id: Current batch number.
        total_batches: Total number of batches.
        previous_summary: Summary of previous batches.

    Returns:
        BatchResult with test outcomes.

    """
    logger.info(
        "Executing batch %d/%d (%d tests)...",
        batch_id,
        total_batches,
        len(tests),
    )

    # Build focused batch prompt (NOT using full workflow - avoids embedding entire test plan)
    prompt = _build_batch_prompt(
        project_path,
        epic_id,
        tests,
        batch_id,
        total_batches,
        previous_summary,
    )

    logger.debug("Batch prompt: %d chars", len(prompt))

    # Get provider and execute
    # Note: tools enabled by default - Master needs Bash, Read, Write to run tests
    from bmad_assist.core.exceptions import ProviderExitCodeError

    provider = get_provider(config.providers.master.provider)
    timeout = config.timeout * 2  # Shorter timeout for smaller batches
    logger.info("Invoking LLM for batch %d (timeout: %ds, tools: enabled)", batch_id, timeout)

    # Agent tracking
    from bmad_assist.core.tracking import track_agent_end, track_agent_start

    _track_cli = {
        "model": config.providers.master.model,
        "timeout": timeout,
        "settings_file": config.providers.master.settings_path,
    }
    _track_start = track_agent_start(
        project_path, epic_id, "", "qa_plan_execute_batch",
        config.providers.master.provider, config.providers.master.model or "unknown",
        prompt, cli_params=_track_cli,
    )

    # Try to get results even if provider exits with non-zero code
    # LLM may have completed tests but provider cleanup failed
    stdout_content = ""
    try:
        result = provider.invoke(
            prompt,
            model=config.providers.master.model,
            timeout=timeout,
            settings_file=config.providers.master.settings_path,
            # tools enabled by default - Master LLM needs Bash/Read/Write
        )
        stdout_content = result.stdout
    except ProviderExitCodeError as e:
        # Provider failed but may have produced useful output
        stdout_content = e.stdout
        if stdout_content:
            logger.warning(
                "Batch %d: provider exit_code=%d but got %d chars of output - continuing",
                batch_id,
                e.exit_code,
                len(stdout_content),
            )
        else:
            logger.error(
                "Batch %d: provider failed with no output: %s",
                batch_id,
                str(e)[:200],
            )
            # Agent tracking END (error path)
            track_agent_end(
                project_path, epic_id, "", "qa_plan_execute_batch",
                config.providers.master.provider,
                config.providers.master.model or "unknown",
                prompt, _track_start, cli_params=_track_cli,
            )
            # Return empty results for this batch
            batch_result = BatchResult(
                batch_id=batch_id,
                completed_at=datetime.now(UTC).isoformat(),
            )
            for tc in tests:
                batch_result.add_result(
                    TestResult(
                        test_id=tc.id,
                        name=tc.name,
                        category=tc.category,
                        status="ERROR",
                        error=f"Provider failed: {str(e)[:100]}",
                    )
                )
            return batch_result

    # Agent tracking END (success/partial path)
    track_agent_end(
        project_path, epic_id, "", "qa_plan_execute_batch",
        config.providers.master.provider, config.providers.master.model or "unknown",
        prompt, _track_start, cli_params=_track_cli,
    )

    # Parse results from stdout (whether from success or exception)
    test_results = _parse_batch_results(stdout_content, tests)

    batch_result = BatchResult(
        batch_id=batch_id,
        completed_at=datetime.now(UTC).isoformat(),
    )

    for tr in test_results:
        batch_result.add_result(tr)

    logger.info(
        "Batch %d complete: %d passed, %d failed, %d skipped",
        batch_id,
        batch_result.passed,
        batch_result.failed,
        batch_result.skipped,
    )

    return batch_result


def _execute_playwright_category(
    config: Config,
    project_path: Path,
    epic_id: EpicId,
    tests: list[Any],
) -> ExecutionState:
    """Execute Category B tests using Playwright directly.

    No LLM is used - Playwright runs the tests directly.
    Server lifecycle is managed based on config.qa.playwright settings.

    Args:
        config: Configuration instance.
        project_path: Project root directory.
        epic_id: Epic identifier.
        tests: List of Category B test cases.

    Returns:
        ExecutionState with test results.

    """
    from bmad_assist.qa.playwright_executor import execute_playwright_tests

    run_id = f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    started_at = datetime.now(UTC).isoformat()
    qa_artifacts = get_paths().output_folder / "qa-artifacts"
    results_path = qa_artifacts / "test-results" / f"epic-{epic_id}-{run_id}.yaml"

    # Get Playwright config (if available)
    playwright_config = config.qa.playwright if config.qa else None

    logger.info(
        "Executing %d Category B tests via Playwright (no LLM)...",
        len(tests),
    )
    if playwright_config and playwright_config.server.command:
        logger.info("Server management enabled: %s", playwright_config.server.command)

    # Execute via Playwright (handles server lifecycle)
    pw_result = execute_playwright_tests(
        tests=tests,
        epic_id=epic_id,
        project_path=project_path,
        timeout=playwright_config.timeout if playwright_config else config.timeout,
        headless=playwright_config.headless if playwright_config else True,
        config=playwright_config,
    )

    # Convert Playwright results to our format
    batch_result = BatchResult(
        batch_id=1,
        completed_at=datetime.now(UTC).isoformat(),
    )

    for pw_test in pw_result.results:
        test_result = TestResult(
            test_id=pw_test.test_id,
            name=pw_test.name,
            category="B",
            status=pw_test.status,
            duration_ms=pw_test.duration_ms,
            error=pw_test.error,
            output=pw_test.output,
        )
        batch_result.add_result(test_result)

    # Build execution state
    state = ExecutionState(
        epic_id=epic_id,
        category="B",
        batch_size=len(tests),  # All in one "batch"
        run_id=run_id,
        started_at=started_at,
        results_path=results_path,
        completed_batches=[batch_result],
        total_tests=len(tests),
        total_batches=1,
    )

    # Save results
    _atomic_write_yaml(results_path, state.to_dict())

    logger.info(
        "=" * 50 + "\n"
        "PLAYWRIGHT EXECUTION COMPLETE\n"
        "Total: %d tests, %d passed, %d failed (%.1f%%)\n"
        "Results: %s\n" + "=" * 50,
        state.completed_test_count,
        state.total_passed,
        state.total_failed,
        state.total_passed / state.completed_test_count * 100
        if state.completed_test_count > 0
        else 0,
        results_path,
    )

    # Generate summary
    from bmad_assist.qa.summary import generate_summary

    state.summary_path = generate_summary(results_path, config)

    return state


def _merge_execution_states(
    state_a: ExecutionState,
    state_b: ExecutionState,
    results_path: Path,
) -> ExecutionState:
    """Merge two execution states (e.g., Category A + Category B).

    Combines batches from both states into a single state for unified
    results when running -c all.

    Args:
        state_a: Results from Category A execution.
        state_b: Results from Category B execution.
        results_path: Path for combined results file.

    Returns:
        Merged ExecutionState with all batches.

    """
    # Renumber B batches to continue after A batches
    a_batch_count = len(state_a.completed_batches)
    for batch in state_b.completed_batches:
        batch.batch_id += a_batch_count

    merged = ExecutionState(
        epic_id=state_a.epic_id,
        category="all",
        batch_size=state_a.batch_size,
        run_id=state_a.run_id,
        started_at=state_a.started_at,
        results_path=results_path,
        completed_batches=state_a.completed_batches + state_b.completed_batches,
        total_tests=state_a.total_tests + state_b.total_tests,
        total_batches=len(state_a.completed_batches) + len(state_b.completed_batches),
    )

    return merged


def execute_tests_in_batches(
    config: Config,
    project_path: Path,
    epic_id: EpicId,
    parsed_plan: ParsedTestPlan,
    category: str = "A",
    batch_size: int = DEFAULT_BATCH_SIZE,
    retry_info: RetryInfo | None = None,
    include_skipped: bool = False,
) -> ExecutionState:
    """Execute tests in batches with incremental saves.

    Main entry point for batch execution. Splits tests into batches,
    executes each batch, and saves results after each batch.

    Args:
        config: Configuration instance.
        project_path: Project root directory.
        epic_id: Epic to test.
        parsed_plan: Parsed test plan with test cases.
        category: Test category filter (A, B, or all).
        batch_size: Number of tests per batch.
        retry_info: If provided, only run tests that failed/errored (+ new tests).
        include_skipped: When retry_info is set, also include SKIP tests.

    Returns:
        ExecutionState with all batch results.

    """
    # Handle "all" category by splitting into A and B executions
    # This prevents mixing CLI tests with Playwright tests in same batch
    if category.lower() == "all":
        logger.info("Category 'all' requested - executing A and B separately")

        # Get tests by category
        a_tests = parsed_plan.get_tests_by_category("A")
        b_tests = parsed_plan.get_tests_by_category("B")

        # Apply retry filter if retrying
        if retry_info:
            a_tests = filter_tests_for_retry(a_tests, retry_info, include_skipped)
            b_tests = filter_tests_for_retry(b_tests, retry_info, include_skipped)

        if not a_tests and not b_tests:
            logger.warning("No tests found for any category")
            return ExecutionState(
                epic_id=epic_id,
                category="all",
                batch_size=batch_size,
                run_id=f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
                started_at=datetime.now(UTC).isoformat(),
                results_path=Path(),
            )

        # Prepare combined results path
        run_id = f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        qa_artifacts = get_paths().output_folder / "qa-artifacts"
        combined_results_path = qa_artifacts / "test-results" / f"epic-{epic_id}-{run_id}.yaml"

        state_a = None
        state_b = None

        # Execute Category A tests (LLM batches)
        if a_tests:
            logger.info(
                "=" * 50 + "\nPHASE 1: CATEGORY A TESTS (%d tests)\n" + "=" * 50,
                len(a_tests),
            )
            # Recursive call with category="A"
            state_a = execute_tests_in_batches(
                config,
                project_path,
                epic_id,
                parsed_plan,
                category="A",
                batch_size=batch_size,
                retry_info=retry_info,
                include_skipped=include_skipped,
            )

        # Execute Category B tests (Playwright)
        if b_tests:
            logger.info(
                "=" * 50 + "\nPHASE 2: CATEGORY B TESTS (%d tests)\n" + "=" * 50,
                len(b_tests),
            )
            state_b = _execute_playwright_category(config, project_path, epic_id, b_tests)

        # Merge results
        if state_a and state_b:
            merged = _merge_execution_states(state_a, state_b, combined_results_path)
            _atomic_write_yaml(combined_results_path, merged.to_dict())

            # Generate combined summary
            from bmad_assist.qa.summary import generate_summary

            merged.summary_path = generate_summary(combined_results_path, config)

            logger.info(
                "=" * 50 + "\n"
                "ALL CATEGORIES COMPLETE\n"
                "Category A: %d passed, %d failed\n"
                "Category B: %d passed, %d failed\n"
                "Combined: %s\n" + "=" * 50,
                state_a.total_passed,
                state_a.total_failed,
                state_b.total_passed,
                state_b.total_failed,
                combined_results_path,
            )
            return merged
        elif state_a:
            return state_a
        elif state_b:
            return state_b
        else:
            # Should not happen, but handle gracefully
            return ExecutionState(
                epic_id=epic_id,
                category="all",
                batch_size=batch_size,
                run_id=run_id,
                started_at=datetime.now(UTC).isoformat(),
                results_path=Path(),
            )

    # Filter tests by category (for A or B specifically)
    tests = parsed_plan.get_tests_by_category(category)

    # Apply retry filter if retrying from previous run
    if retry_info:
        tests = filter_tests_for_retry(tests, retry_info, include_skipped)

    if not tests:
        logger.warning("No tests found for category %s", category)
        return ExecutionState(
            epic_id=epic_id,
            category=category,
            batch_size=batch_size,
            run_id=f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
            started_at=datetime.now(UTC).isoformat(),
            results_path=Path(),
        )

    # Category B: Use Playwright directly (no LLM)
    if category.upper() == "B":
        return _execute_playwright_category(config, project_path, epic_id, tests)

    # Calculate batches
    total_tests = len(tests)
    total_batches = math.ceil(total_tests / batch_size)

    logger.info(
        "Batch execution: %d tests in %d batches (size: %d)",
        total_tests,
        total_batches,
        batch_size,
    )

    # Determine if this is a retry (merge mode) or new run
    is_retry = retry_info is not None
    original_run_path = retry_info.run_path if retry_info else None

    # Initialize execution state
    if is_retry:
        # For retry, we'll merge into original file
        # Use original run_id but track this is a retry
        assert retry_info is not None  # narrowing for type checker
        assert original_run_path is not None  # retry_info always has run_path
        run_id = retry_info.run_id
        results_path = original_run_path
        logger.info("Retry mode: will merge results into %s", results_path.name)
    else:
        # New run
        run_id = f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        qa_artifacts = get_paths().output_folder / "qa-artifacts"
        results_path = qa_artifacts / "test-results" / f"epic-{epic_id}-{run_id}.yaml"

    # For retry, we collect results in memory and merge at end
    # For new run, we save incrementally
    state = ExecutionState(
        epic_id=epic_id,
        category=category,
        batch_size=batch_size,
        run_id=run_id,
        started_at=datetime.now(UTC).isoformat(),
        results_path=results_path,
        total_tests=total_tests,
        total_batches=total_batches,
    )

    # Execute batches
    for batch_num in range(1, total_batches + 1):
        start_idx = (batch_num - 1) * batch_size
        end_idx = min(start_idx + batch_size, total_tests)
        batch_tests = tests[start_idx:end_idx]

        logger.info(
            "─" * 50 + "\nBATCH %d/%d (tests %d-%d)\n" + "─" * 50,
            batch_num,
            total_batches,
            start_idx + 1,
            end_idx,
        )

        # Build previous summary for context
        previous_summary = ""
        if state.completed_batches:
            previous_summary = (
                f"Previous batches: {len(state.completed_batches)} completed, "
                f"{state.total_passed} passed, {state.total_failed} failed"
            )

        # Execute batch
        batch_result = execute_batch(
            config,
            project_path,
            epic_id,
            batch_tests,
            batch_num,
            total_batches,
            previous_summary,
        )

        # Add to state
        state.completed_batches.append(batch_result)

        # Incremental save (only for new runs, not retries)
        if not is_retry:
            _atomic_write_yaml(results_path, state.to_dict())
            logger.info(
                "Progress: %d/%d tests (%.1f%%) - saved to %s",
                state.completed_test_count,
                total_tests,
                state.completed_test_count / total_tests * 100,
                results_path.name,
            )
        else:
            logger.info(
                "Progress: %d/%d retry tests (%.1f%%)",
                state.completed_test_count,
                total_tests,
                state.completed_test_count / total_tests * 100,
            )

    # Final save/merge
    if is_retry and original_run_path:
        # Merge results into original file
        # Collect all test results from all batches
        all_retry_results: list[TestResult] = []
        for batch in state.completed_batches:
            all_retry_results.extend(batch.tests)

        retry_timestamp = datetime.now(UTC).isoformat()
        merged_state = merge_retry_results(original_run_path, all_retry_results, retry_timestamp)

        if merged_state:
            logger.info(
                "=" * 50 + "\n"
                "RETRY COMPLETE\n"
                "Retried: %d tests, %d passed, %d failed\n"
                "Overall: %d passed, %d failed (%.1f%%)\n"
                "Results merged into: %s\n" + "=" * 50,
                state.completed_test_count,
                state.total_passed,
                state.total_failed,
                merged_state.total_passed,
                merged_state.total_failed,
                merged_state.total_passed / merged_state.completed_test_count * 100
                if merged_state.completed_test_count > 0
                else 0,
                original_run_path.name,
            )

            # Generate summary (retry updates same summary file)
            from bmad_assist.qa.summary import generate_summary

            merged_state.summary_path = generate_summary(original_run_path, config)
            return merged_state
        else:
            logger.error("Failed to merge retry results, saving as separate file")
            # Fall through to normal save

    # Normal completion (new run or failed merge)
    _atomic_write_yaml(results_path, state.to_dict())
    logger.info(
        "=" * 50 + "\n"
        "EXECUTION COMPLETE\n"
        "Total: %d tests, %d passed, %d failed (%.1f%%)\n"
        "Results: %s\n" + "=" * 50,
        state.completed_test_count,
        state.total_passed,
        state.total_failed,
        state.total_passed / state.completed_test_count * 100
        if state.completed_test_count > 0
        else 0,
        results_path,
    )

    # Generate summary
    from bmad_assist.qa.summary import generate_summary

    state.summary_path = generate_summary(results_path, config)

    return state


def load_execution_state(results_path: Path) -> ExecutionState | None:
    """Load existing execution state for resume.

    Args:
        results_path: Path to results YAML file.

    Returns:
        ExecutionState if file exists and is valid, None otherwise.

    """
    if not results_path.exists():
        return None

    try:
        with open(results_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "meta" not in data:
            return None

        meta = data["meta"]
        batches_data = data.get("batches", [])

        completed_batches = []
        for bd in batches_data:
            batch = BatchResult(
                batch_id=bd["batch_id"],
                completed_at=bd["completed_at"],
                passed=bd.get("passed", 0),
                failed=bd.get("failed", 0),
                skipped=bd.get("skipped", 0),
                errors=bd.get("errors", 0),
            )
            for td in bd.get("tests", []):
                # Load retry history if present
                retries = []
                for rd in td.get("retries", []):
                    retries.append(
                        RetryEntry(
                            at=rd.get("at", ""),
                            previous_status=rd.get("previous_status", ""),
                            previous_error=rd.get("previous_error", ""),
                            previous_duration_ms=rd.get("previous_duration_ms", 0),
                        )
                    )

                batch.tests.append(
                    TestResult(
                        test_id=td["id"],
                        name=td.get("name", ""),
                        category=td.get("category", "A"),
                        status=td.get("status", "SKIP"),
                        duration_ms=td.get("duration_ms", 0),
                        exit_code=td.get("exit_code", 0),
                        output=td.get("output", ""),
                        error=td.get("error", ""),
                        retries=retries,
                    )
                )
            completed_batches.append(batch)

        return ExecutionState(
            epic_id=meta.get("epic"),
            category=meta.get("category_filter", "A"),
            batch_size=meta.get("batch_size", DEFAULT_BATCH_SIZE),
            run_id=meta.get("run_id", ""),
            started_at=meta.get("started_at", ""),
            results_path=results_path,
            completed_batches=completed_batches,
            total_tests=meta.get("total_tests", 0),
            total_batches=meta.get("total_batches", 0),
            retry_count=meta.get("retry_count", 0),
            last_retry_at=meta.get("last_retry_at"),
        )

    except Exception as e:
        logger.warning("Failed to load execution state from %s: %s", results_path, e)
        return None


def merge_retry_results(
    original_path: Path,
    retry_results: list[TestResult],
    retry_timestamp: str,
) -> ExecutionState | None:
    """Merge retry results into the original run file.

    Updates test statuses in-place, adds retry history, and recalculates
    batch statistics. The original file is updated atomically.

    Args:
        original_path: Path to original run results file.
        retry_results: New results from retry execution.
        retry_timestamp: Timestamp of the retry.

    Returns:
        Updated ExecutionState, or None if merge failed.

    """
    # Load original state
    state = load_execution_state(original_path)
    if not state:
        logger.error("Failed to load original run for merge: %s", original_path)
        return None

    # Build lookup of retry results by test ID
    retry_by_id = {r.test_id: r for r in retry_results}

    # Update tests in each batch
    for batch in state.completed_batches:
        # Reset batch counters - we'll recalculate
        batch.passed = 0
        batch.failed = 0
        batch.skipped = 0
        batch.errors = 0

        for test in batch.tests:
            if test.test_id in retry_by_id:
                new_result = retry_by_id[test.test_id]

                # Add retry history entry
                retry_entry = RetryEntry(
                    at=retry_timestamp,
                    previous_status=test.status,
                    previous_error=test.error,
                    previous_duration_ms=test.duration_ms,
                )
                test.retries.append(retry_entry)

                # Update test with new result
                test.status = new_result.status
                test.duration_ms = new_result.duration_ms
                test.exit_code = new_result.exit_code
                test.output = new_result.output
                test.error = new_result.error

                logger.debug(
                    "Updated %s: %s -> %s",
                    test.test_id,
                    retry_entry.previous_status,
                    test.status,
                )

            # Recalculate batch counters
            if test.status == "PASS":
                batch.passed += 1
            elif test.status == "FAIL":
                batch.failed += 1
            elif test.status == "SKIP":
                batch.skipped += 1
            elif test.status == "ERROR":
                batch.errors += 1

    # Update state metadata
    state.retry_count += 1
    state.last_retry_at = retry_timestamp

    # Atomic write back to original file
    _atomic_write_yaml(original_path, state.to_dict())

    logger.info(
        "Merged %d retry results into %s (retry #%d)",
        len(retry_results),
        original_path.name,
        state.retry_count,
    )

    return state


# ============================================================================
# Retry functionality
# ============================================================================


@dataclass
class RetryInfo:
    """Information about tests to retry from a previous run.

    Attributes:
        run_id: Original run identifier.
        run_path: Path to original run file.
        failed_tests: Test IDs with FAIL status.
        error_tests: Test IDs with ERROR status.
        skipped_tests: Test IDs with SKIP status.
        executed_tests: All test IDs that were executed.
        total_in_run: Total tests in the original run.

    """

    run_id: str
    run_path: Path
    failed_tests: list[str] = field(default_factory=list)
    error_tests: list[str] = field(default_factory=list)
    skipped_tests: list[str] = field(default_factory=list)
    executed_tests: set[str] = field(default_factory=set)
    total_in_run: int = 0

    def get_retry_ids(self, include_skipped: bool = False) -> list[str]:
        """Get test IDs that need retry.

        Args:
            include_skipped: Include SKIP tests in retry list.

        Returns:
            List of test IDs to retry.

        """
        ids = self.failed_tests + self.error_tests
        if include_skipped:
            ids.extend(self.skipped_tests)
        return ids


def find_latest_run(
    epic_id: EpicId,
    category: str | None = None,
) -> Path | None:
    """Find the most recent run file for an epic.

    Searches in the test-results directory for files matching:
    epic-{id}-run-*.yaml

    Args:
        epic_id: Epic identifier to find runs for.
        category: Optional category filter (not currently used for matching).

    Returns:
        Path to most recent run file, or None if no runs found.

    """
    qa_artifacts = get_paths().output_folder / "qa-artifacts"
    results_dir = qa_artifacts / "test-results"

    if not results_dir.exists():
        logger.debug("Results directory does not exist: %s", results_dir)
        return None

    # Find all run files for this epic
    pattern = f"epic-{epic_id}-run-*.yaml"
    run_files = list(results_dir.glob(pattern))

    if not run_files:
        logger.debug("No run files found for epic %s", epic_id)
        return None

    # Sort by filename (timestamp is in the name: run-YYYYMMDD-HHMMSS)
    # Most recent will be last
    run_files.sort()
    latest = run_files[-1]

    logger.debug("Found %d runs for epic %s, latest: %s", len(run_files), epic_id, latest.name)
    return latest


def find_run_by_id(
    epic_id: EpicId,
    run_id: str,
) -> Path | None:
    """Find a specific run file by its ID.

    Args:
        epic_id: Epic identifier.
        run_id: Run identifier (e.g., "run-20260112-115110").

    Returns:
        Path to run file, or None if not found.

    """
    qa_artifacts = get_paths().output_folder / "qa-artifacts"
    results_dir = qa_artifacts / "test-results"

    # Try exact match first
    exact_path = results_dir / f"epic-{epic_id}-{run_id}.yaml"
    if exact_path.exists():
        return exact_path

    # Try with glob in case run_id is partial
    pattern = f"epic-{epic_id}-*{run_id}*.yaml"
    matches = list(results_dir.glob(pattern))

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        logger.warning("Multiple runs match '%s': %s", run_id, [m.name for m in matches])
        return matches[-1]  # Return most recent

    return None


def get_retry_info(run_path: Path) -> RetryInfo | None:
    """Extract retry information from a run file.

    Parses the run file and extracts test statuses to determine
    which tests need to be retried.

    Args:
        run_path: Path to run results YAML file.

    Returns:
        RetryInfo with test status breakdown, or None if parsing fails.

    """
    if not run_path.exists():
        logger.error("Run file does not exist: %s", run_path)
        return None

    try:
        with open(run_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "meta" not in data:
            logger.error("Invalid run file format: %s", run_path)
            return None

        meta = data["meta"]
        run_id = meta.get("run_id", run_path.stem)

        info = RetryInfo(
            run_id=run_id,
            run_path=run_path,
            total_in_run=meta.get("total_tests", 0),
        )

        # Extract test statuses from all batches
        for batch in data.get("batches", []):
            for test in batch.get("tests", []):
                test_id = test.get("id")
                status = test.get("status", "").upper()

                if not test_id:
                    continue

                info.executed_tests.add(test_id)

                if status == "FAIL":
                    info.failed_tests.append(test_id)
                elif status == "ERROR":
                    info.error_tests.append(test_id)
                elif status == "SKIP":
                    info.skipped_tests.append(test_id)

        logger.info(
            "Run %s: %d executed, %d failed, %d errors, %d skipped",
            run_id,
            len(info.executed_tests),
            len(info.failed_tests),
            len(info.error_tests),
            len(info.skipped_tests),
        )

        return info

    except Exception as e:
        logger.error("Failed to parse run file %s: %s", run_path, e)
        return None


def filter_tests_for_retry(
    all_tests: list[TestCase],
    retry_info: RetryInfo,
    include_skipped: bool = False,
) -> list[TestCase]:
    """Filter test list to only include tests needing retry.

    Returns tests that:
    1. Failed or errored in the previous run
    2. Were skipped (if include_skipped=True)
    3. Were never executed (not in previous run at all)

    Args:
        all_tests: Full list of tests from test plan.
        retry_info: Retry information from previous run.
        include_skipped: Include SKIP tests in retry.

    Returns:
        Filtered list of tests to execute.

    """
    retry_ids = set(retry_info.get_retry_ids(include_skipped))
    executed_ids = retry_info.executed_tests

    filtered = []
    for test in all_tests:
        # Include if: needs retry OR was never executed
        if test.id in retry_ids or test.id not in executed_ids:
            filtered.append(test)

    # Log what we're doing
    retry_count = len([t for t in filtered if t.id in retry_ids])
    new_count = len([t for t in filtered if t.id not in executed_ids])

    logger.info(
        "Retry filter: %d tests to retry, %d new tests, %d total",
        retry_count,
        new_count,
        len(filtered),
    )

    return filtered
