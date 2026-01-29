"""QA plan executor.

Executes E2E tests from generated test plans using the qa-plan-execute workflow.
After qa-plan-generate creates a test plan, this module runs the tests.

Supports two execution modes:
1. Single run (default for <=10 tests): Execute all tests at once
2. Batch mode (recommended for >10 tests): Execute in batches with incremental saves
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.compiler import CompilerContext, compile_workflow
from bmad_assist.core.config import Config
from bmad_assist.core.paths import get_paths
from bmad_assist.core.types import EpicId
from bmad_assist.providers import get_provider
from bmad_assist.qa.checker import get_qa_plan_path

if TYPE_CHECKING:
    from bmad_assist.qa.batch_executor import RetryInfo

logger = logging.getLogger(__name__)

# Threshold for recommending batch mode
BATCH_THRESHOLD = 10


def _save_raw_output(output: str, epic_id: EpicId, suffix: str = "") -> Path | None:
    """Save raw LLM output for debugging and recovery.

    Always saves output regardless of exit code - if provider crashes
    but LLM produced useful output, we don't want to lose it.

    Args:
        output: Raw stdout from LLM invocation.
        epic_id: Epic identifier.
        suffix: Optional suffix for filename.

    Returns:
        Path to saved file, or None if save failed.

    """
    if not output or not output.strip():
        return None

    from datetime import UTC, datetime

    qa_artifacts = get_paths().output_folder / "qa-artifacts" / "raw-output"
    qa_artifacts.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"epic-{epic_id}-{timestamp}{suffix}.txt"
    output_path = qa_artifacts / filename

    try:
        output_path.write_text(output, encoding="utf-8")
        logger.debug("Saved raw output: %s (%d bytes)", output_path, len(output))
        return output_path
    except Exception as e:
        logger.warning("Failed to save raw output: %s", e)
        return None


DEFAULT_BATCH_SIZE = 10


@dataclass
class QAExecuteResult:
    """Result of QA plan execution.

    Attributes:
        success: Whether execution completed (not necessarily all tests passed).
        epic_id: Epic that was tested.
        results_path: Path to generated results YAML.
        summary_path: Path to generated summary markdown.
        tests_run: Number of tests executed.
        tests_passed: Number of tests that passed.
        tests_failed: Number of tests that failed.
        error: Error message if execution failed to start.
        batch_mode: Whether batch mode was used.
        batches_completed: Number of batches completed (batch mode only).

    """

    success: bool
    epic_id: EpicId
    results_path: Path | None = None
    summary_path: Path | None = None
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    error: str | None = None
    batch_mode: bool = False
    batches_completed: int = 0

    @classmethod
    def fail(cls, epic_id: EpicId, error: str) -> QAExecuteResult:
        """Create a failed result."""
        return cls(success=False, epic_id=epic_id, error=error)

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate as percentage."""
        if self.tests_run == 0:
            return 0.0
        return (self.tests_passed / self.tests_run) * 100


def _compile_qa_execute_prompt(
    project_path: Path,
    epic_id: EpicId,
    category: str = "A",
) -> str:
    """Compile qa-plan-execute workflow to prompt.

    Uses the workflow compiler to generate a complete prompt with
    the test plan embedded.

    Args:
        project_path: Project root directory.
        epic_id: Epic to execute tests for.
        category: Test category (A, B, or all).

    Returns:
        Compiled prompt XML string.

    Raises:
        CompilerError: If compilation fails.

    """
    paths = get_paths()
    context = CompilerContext(
        project_root=project_path,
        output_folder=paths.output_folder,
        project_knowledge=paths.project_knowledge,
        cwd=project_path,
        resolved_variables={
            "epic_num": epic_id,
            "category": category,
            "non_interactive": True,
            "auto_continue_on_fail": True,
        },
    )

    compiled = compile_workflow("qa-plan-execute", context)
    return compiled.context


def _parse_execution_results(output: str) -> dict[str, Any]:
    """Parse test execution results from LLM output.

    Extracts test counts and status from the execution output.
    Looks specifically for QA summary table format to avoid picking up
    pytest output like "100 passed in 5s".

    Args:
        output: Raw LLM output.

    Returns:
        Dict with tests_run, tests_passed, tests_failed.

    """
    import re

    result = {
        "tests_run": 0,
        "tests_passed": 0,
        "tests_failed": 0,
    }

    # Look for QA summary section first (after "QA EXECUTION COMPLETE" marker)
    qa_complete_marker = "QA EXECUTION COMPLETE"
    summary_section = output
    if qa_complete_marker in output:
        # Use only the section after the marker
        summary_section = output[output.rfind(qa_complete_marker) :]

    # Try markdown table format first: | PASS | 7 | or | PASS   | 7     |
    # This is more specific than just "PASS" followed by number
    table_pass = re.search(r"\|\s*PASS\s*\|\s*(\d+)\s*\|", summary_section, re.IGNORECASE)
    table_fail = re.search(r"\|\s*FAIL\s*\|\s*(\d+)\s*\|", summary_section, re.IGNORECASE)
    table_total = re.search(
        r"\|\s*\**Total\**\s*\|\s*\**(\d+)\**\s*\|", summary_section, re.IGNORECASE
    )

    if table_pass or table_fail or table_total:
        # Found markdown table format
        if table_pass:
            result["tests_passed"] = int(table_pass.group(1))
        if table_fail:
            result["tests_failed"] = int(table_fail.group(1))
        if table_total:
            result["tests_run"] = int(table_total.group(1))
        else:
            result["tests_run"] = result["tests_passed"] + result["tests_failed"]
        return result

    # Fallback: Look for "Pass Rate: XX%" pattern
    pass_rate_match = re.search(r"Pass Rate:\s*([\d.]+)%", summary_section)
    if pass_rate_match and table_total:
        pass_rate = float(pass_rate_match.group(1))
        total = result["tests_run"]
        if total > 0:
            result["tests_passed"] = round(total * pass_rate / 100)
            result["tests_failed"] = total - result["tests_passed"]
            return result

    # Last resort: generic patterns (but only in summary section)
    pass_match = re.search(r"PASS[^\d]*(\d+)", summary_section, re.IGNORECASE)
    fail_match = re.search(r"FAIL[^\d]*(\d+)", summary_section, re.IGNORECASE)
    total_match = re.search(r"Total[^\d]*(\d+)", summary_section, re.IGNORECASE)

    if pass_match:
        result["tests_passed"] = int(pass_match.group(1))
    if fail_match:
        result["tests_failed"] = int(fail_match.group(1))
    if total_match:
        result["tests_run"] = int(total_match.group(1))
    else:
        result["tests_run"] = result["tests_passed"] + result["tests_failed"]

    return result


def _execute_single_run(
    config: Config,
    project_path: Path,
    epic_id: EpicId,
    category: str,
) -> QAExecuteResult:
    """Execute all tests in a single LLM invocation.

    Used for small test sets (<=BATCH_THRESHOLD tests).

    Args:
        config: Configuration instance.
        project_path: Project root directory.
        epic_id: Epic to execute tests for.
        category: Test category to run.

    Returns:
        QAExecuteResult with execution summary.

    """
    from bmad_assist.core.io import save_prompt

    # Compile workflow to prompt
    logger.info("Compiling qa-plan-execute workflow...")
    prompt = _compile_qa_execute_prompt(project_path, epic_id, category)
    logger.info("Compiled prompt: %d chars", len(prompt))

    # Save prompt for debugging (always save for QA execution - useful for troubleshooting)
    # QA uses epic_id as pseudo-story for organization
    prompt_path = save_prompt(project_path, epic_id, "qa", f"execute-{category}", prompt)
    logger.info("Prompt saved: %s", prompt_path)

    # Get master provider
    provider = get_provider(config.providers.master.provider)
    logger.info(
        "Using provider: %s, model: %s",
        config.providers.master.provider,
        config.providers.master.model,
    )

    # Invoke LLM - this executes the tests
    # Note: tools are enabled by default (disable_tools=False)
    # Master LLM needs Bash, Read, Write to execute tests
    from bmad_assist.core.exceptions import ProviderExitCodeError

    effective_timeout = config.timeout * 3  # Tests take longer
    logger.info(
        "Invoking LLM (timeout: %ds, tools: enabled)... Output will stream below:",
        effective_timeout,
    )

    # Agent tracking
    from bmad_assist.core.tracking import track_agent_end, track_agent_start

    _track_cli = {
        "model": config.providers.master.model,
        "timeout": effective_timeout,
        "settings_file": config.providers.master.settings_path,
    }
    _track_start = track_agent_start(
        project_path, epic_id, "", "qa_plan_execute",
        config.providers.master.provider, config.providers.master.model or "unknown",
        prompt, cli_params=_track_cli,
    )

    # Try to get results even if provider exits with non-zero code
    # LLM may have completed tests but provider cleanup failed
    stdout_content = ""
    exit_code = 0
    stderr_content = ""
    try:
        result = provider.invoke(
            prompt,
            model=config.providers.master.model,
            timeout=effective_timeout,
            settings_file=config.providers.master.settings_path,
            # tools are enabled by default - Master needs Bash, Read, Write
        )
        stdout_content = result.stdout
        exit_code = result.exit_code
        stderr_content = result.stderr
    except ProviderExitCodeError as e:
        # Provider failed but may have produced useful output
        stdout_content = e.stdout
        exit_code = e.exit_code
        stderr_content = e.stderr
        logger.warning(
            "Provider exit_code=%d, preserving %d chars of output",
            e.exit_code,
            len(stdout_content),
        )

    track_agent_end(
        project_path, epic_id, "", "qa_plan_execute",
        config.providers.master.provider, config.providers.master.model or "unknown",
        prompt, _track_start, cli_params=_track_cli,
    )

    # Always save raw output first - don't lose work if provider crashed
    # after LLM finished producing useful output
    raw_output_path = _save_raw_output(stdout_content, epic_id, suffix="-single-run")
    if raw_output_path:
        logger.info("Raw output saved: %s", raw_output_path)

    # Try to parse results regardless of exit code
    # LLM may have completed successfully but provider cleanup failed
    parsed = _parse_execution_results(stdout_content)

    # Only fail if exit_code != 0 AND we got no useful results
    if exit_code != 0:
        if parsed["tests_run"] == 0:
            # No results at all - this is a real failure
            logger.error(
                "Provider failed (exit_code=%d) and no test results found: %s",
                exit_code,
                stderr_content[:200] if stderr_content else "(no stderr)",
            )
            return QAExecuteResult.fail(
                epic_id,
                f"Provider failed with no results. Raw output saved to: {raw_output_path}",
            )
        else:
            # We have results! Provider crashed but LLM did its job
            logger.warning(
                "Provider exit_code=%d but found %d test results - continuing with results",
                exit_code,
                parsed["tests_run"],
            )

    # Find results file (LLM should have created it)
    qa_artifacts = get_paths().output_folder / "qa-artifacts"
    results_dir = qa_artifacts / "test-results"
    results_pattern = f"epic-{epic_id}-run-*.yaml"
    results_files = sorted(results_dir.glob(results_pattern), reverse=True)

    results_path = results_files[0] if results_files else None
    summary_path = None
    if results_path:
        summary_path = results_path.parent / (results_path.stem + "-summary.md")
        if not summary_path.exists():
            summary_path = None

    logger.info(
        "QA execution complete: %d/%d passed (%.1f%%)",
        parsed["tests_passed"],
        parsed["tests_run"],
        (parsed["tests_passed"] / parsed["tests_run"] * 100) if parsed["tests_run"] > 0 else 0,
    )

    return QAExecuteResult(
        success=True,
        epic_id=epic_id,
        results_path=results_path,
        summary_path=summary_path,
        tests_run=parsed["tests_run"],
        tests_passed=parsed["tests_passed"],
        tests_failed=parsed["tests_failed"],
        batch_mode=False,
    )


def _execute_batch_mode(
    config: Config,
    project_path: Path,
    epic_id: EpicId,
    category: str,
    batch_size: int,
    qa_plan_path: Path,
    retry_info: "RetryInfo | None" = None,  # noqa: UP037
    include_skipped: bool = False,
) -> QAExecuteResult:
    """Execute tests in batches with incremental saves.

    Used for large test sets (>BATCH_THRESHOLD tests) to prevent
    context overflow and enable crash recovery.

    Args:
        config: Configuration instance.
        project_path: Project root directory.
        epic_id: Epic to execute tests for.
        category: Test category to run.
        batch_size: Number of tests per batch.
        qa_plan_path: Path to QA plan file.
        retry_info: If retrying, info from previous run.
        include_skipped: When retrying, include SKIP tests.

    Returns:
        QAExecuteResult with execution summary.

    """
    from bmad_assist.qa.batch_executor import execute_tests_in_batches
    from bmad_assist.qa.parser import parse_test_plan_file

    # Parse test plan
    logger.info("Parsing test plan for batch execution...")
    parsed_plan = parse_test_plan_file(qa_plan_path, epic_id)

    test_count = len(parsed_plan.get_tests_by_category(category))
    logger.info(
        "Found %d tests for category %s (batch size: %d)",
        test_count,
        category,
        batch_size,
    )

    if test_count == 0:
        return QAExecuteResult.fail(
            epic_id,
            f"No tests found for category {category} in test plan",
        )

    # Execute in batches (with optional retry filter)
    state = execute_tests_in_batches(
        config,
        project_path,
        epic_id,
        parsed_plan,
        category=category,
        batch_size=batch_size,
        retry_info=retry_info,
        include_skipped=include_skipped,
    )

    return QAExecuteResult(
        success=True,
        epic_id=epic_id,
        results_path=state.results_path,
        summary_path=state.summary_path,  # Generated by batch_executor via helper LLM
        tests_run=state.completed_test_count,
        tests_passed=state.total_passed,
        tests_failed=state.total_failed,
        batch_mode=True,
        batches_completed=len(state.completed_batches),
    )


def execute_qa_plan(
    config: Config,
    project_path: Path,
    epic_id: EpicId,
    *,
    category: str = "A",
    batch_size: int = DEFAULT_BATCH_SIZE,
    batch_mode: str | None = None,
    retry: bool = False,
    include_skipped: bool = False,
    retry_run: str | None = None,
) -> QAExecuteResult:
    """Execute QA plan for an epic.

    This function:
    1. Checks if QA plan exists
    2. Parses plan to count tests
    3. Chooses execution mode (single run vs batch)
    4. Executes tests and returns results

    For >10 tests, batch mode is automatically used unless overridden.

    Args:
        config: Configuration instance.
        project_path: Project root directory.
        epic_id: Epic to execute tests for.
        category: Test category to run (A, B, or all).
        batch_size: Number of tests per batch (default: 10).
        batch_mode: Override mode selection:
            - None: Auto-select based on test count
            - "batch": Force batch mode
            - "all": Force single run mode
        retry: Retry failed/error tests from last run (also executes new tests).
        include_skipped: When retrying, also include SKIP tests.
        retry_run: Specific run ID to retry from (default: latest run).

    Returns:
        QAExecuteResult with execution summary.

    """
    # Check if QA plan exists
    qa_plan_path = get_qa_plan_path(config, project_path, epic_id)
    if not qa_plan_path.exists():
        return QAExecuteResult.fail(
            epic_id,
            f"QA plan not found: {qa_plan_path}. Run qa-plan-generate first.",
        )

    logger.info("Executing QA plan for epic %s (category %s)...", epic_id, category)
    logger.info("QA plan file: %s", qa_plan_path)

    try:
        # Handle retry mode - find run to retry from
        retry_info_obj = None
        if retry:
            from bmad_assist.qa.batch_executor import (
                find_latest_run,
                find_run_by_id,
                get_retry_info,
            )

            # Find the run to retry from
            if retry_run:
                run_path = find_run_by_id(epic_id, retry_run)
                if not run_path:
                    return QAExecuteResult.fail(
                        epic_id,
                        f"Run not found: {retry_run}. Check run ID and try again.",
                    )
            else:
                run_path = find_latest_run(epic_id)
                if not run_path:
                    return QAExecuteResult.fail(
                        epic_id,
                        f"No previous runs found for epic {epic_id}. Run without --retry first.",
                    )

            logger.info("Retrying from run: %s", run_path.name)
            retry_info_obj = get_retry_info(run_path)

            if not retry_info_obj:
                return QAExecuteResult.fail(
                    epic_id,
                    f"Failed to parse run file: {run_path}",
                )

            # Check if there's anything to retry
            retry_ids = retry_info_obj.get_retry_ids(include_skipped)
            if not retry_ids:
                logger.info("No tests to retry - all passed in previous run!")
                return QAExecuteResult(
                    success=True,
                    epic_id=epic_id,
                    tests_run=0,
                    tests_passed=0,
                    tests_failed=0,
                    error="No tests to retry - all passed in previous run",
                )

            logger.info(
                "Found %d tests to retry: %d failed, %d errors%s",
                len(retry_ids),
                len(retry_info_obj.failed_tests),
                len(retry_info_obj.error_tests),
                f", {len(retry_info_obj.skipped_tests)} skipped" if include_skipped else "",
            )

            # Force batch mode for retries (simpler flow)
            batch_mode = "batch"

        # Determine execution mode
        if batch_mode == "all":
            # Force single run (not supported with retry)
            if retry:
                logger.warning("--retry requires batch mode, ignoring --no-batch")
            else:
                logger.info("Using single run mode (forced)")
                return _execute_single_run(config, project_path, epic_id, category)

        if batch_mode == "batch":
            # Force batch mode
            logger.info("Using batch mode (forced, batch size: %d)", batch_size)
            return _execute_batch_mode(
                config,
                project_path,
                epic_id,
                category,
                batch_size,
                qa_plan_path,
                retry_info=retry_info_obj,
                include_skipped=include_skipped,
            )

        # Auto-select based on test count
        from bmad_assist.qa.parser import parse_test_plan_file

        parsed_plan = parse_test_plan_file(qa_plan_path, epic_id)
        test_count = len(parsed_plan.get_tests_by_category(category))

        if test_count > BATCH_THRESHOLD:
            logger.info(
                "Auto-selecting batch mode for %d tests (threshold: %d, batch size: %d)",
                test_count,
                BATCH_THRESHOLD,
                batch_size,
            )
            return _execute_batch_mode(
                config,
                project_path,
                epic_id,
                category,
                batch_size,
                qa_plan_path,
                retry_info=retry_info_obj,
                include_skipped=include_skipped,
            )
        else:
            logger.info(
                "Using single run mode for %d tests (below threshold: %d)",
                test_count,
                BATCH_THRESHOLD,
            )
            return _execute_single_run(config, project_path, epic_id, category)

    except Exception as e:
        logger.error("Failed to execute QA plan for epic %s: %s", epic_id, e)
        return QAExecuteResult.fail(epic_id, str(e))
