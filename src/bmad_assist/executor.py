"""QA plan executor.

Executes E2E tests from generated test plans using the qa-plan-execute workflow.
After qa-plan-generate creates a test plan, this module runs the tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bmad_assist.compiler import CompilerContext, compile_workflow
from bmad_assist.core.config import Config
from bmad_assist.core.paths import get_paths
from bmad_assist.core.types import EpicId
from bmad_assist.qa.checker import get_qa_plan_path

logger = logging.getLogger(__name__)


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

    """

    success: bool
    epic_id: EpicId
    results_path: Path | None = None
    summary_path: Path | None = None
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    error: str | None = None

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
        config: Configuration instance.
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

    Args:
        output: Raw LLM output.
        epic_id: Epic ID for context.

    Returns:
        Dict with tests_run, tests_passed, tests_failed.

    """
    import re

    result = {
        "tests_run": 0,
        "tests_passed": 0,
        "tests_failed": 0,
    }

    # Try to find summary section
    # Pattern: | ✓ PASS | 15 | or similar
    pass_match = re.search(r"PASS[^\d]*(\d+)", output, re.IGNORECASE)
    fail_match = re.search(r"FAIL[^\d]*(\d+)", output, re.IGNORECASE)
    total_match = re.search(r"Total[^\d]*(\d+)", output, re.IGNORECASE)

    if pass_match:
        result["tests_passed"] = int(pass_match.group(1))
    if fail_match:
        result["tests_failed"] = int(fail_match.group(1))
    if total_match:
        result["tests_run"] = int(total_match.group(1))
    else:
        result["tests_run"] = result["tests_passed"] + result["tests_failed"]

    return result


def execute_qa_plan(
    config: Config,
    project_path: Path,
    epic_id: EpicId,
    *,
    category: str = "A",
) -> QAExecuteResult:
    """Execute QA plan for an epic.

    This function:
    1. Checks if QA plan exists
    2. Compiles qa-plan-execute workflow with test plan embedded
    3. Invokes LLM to execute tests
    4. Parses results and returns summary

    Args:
        config: Configuration instance.
        project_path: Project root directory.
        epic_id: Epic to execute tests for.
        category: Test category to run (A, B, or all).

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

    try:
        # Compile workflow to prompt
        prompt = _compile_qa_execute_prompt(project_path, epic_id, category)
        logger.debug("Compiled prompt length: %d chars", len(prompt))


        # Get master provider (with fallbacks)
        from bmad_assist.core.provider_factory import create_provider

        provider = create_provider(config.providers.master)

        # Invoke LLM - this executes the tests
        logger.info("Invoking LLM to execute tests...")
        result = provider.invoke(
            prompt,
            model=config.providers.master.model,
            timeout=config.timeout * 3,  # Tests take longer
            settings_file=config.providers.master.settings_path,
        )

        if result.exit_code != 0:
            logger.error("LLM invocation failed: %s", result.stderr)
            return QAExecuteResult.fail(epic_id, f"LLM failed: {result.stderr[:200]}")

        # Parse results from output
        parsed = _parse_execution_results(result.stdout)

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
        )

    except Exception as e:
        logger.error("Failed to execute QA plan for epic %s: %s", epic_id, e)
        return QAExecuteResult.fail(epic_id, str(e))
