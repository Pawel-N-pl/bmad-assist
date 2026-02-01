"""Trace handler for testarch module.

Runs the testarch-trace workflow on epic completion before retrospective,
generating traceability matrices and quality gate decisions.

Note: TraceHandler is registered as Phase.TRACE in dispatch.py and runs
as a configured phase in loop.epic_teardown before retrospective.

"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import warnings

from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.testarch.core import extract_gate_decision
from bmad_assist.testarch.handlers.base import TestarchBaseHandler

if TYPE_CHECKING:
    from bmad_assist.core.config import Config

logger = logging.getLogger(__name__)


class TraceHandler(TestarchBaseHandler):
    """Handler for trace workflow.

    Executes the testarch-trace workflow when enabled. This handler runs
    as Phase.TRACE in the epic_teardown phase sequence before retrospective.

    The handler:
    1. Checks trace mode (off/auto/on) to determine if trace should run
    2. Invokes the trace workflow for eligible epics
    3. Extracts gate decision (PASS/CONCERNS/FAIL/WAIVED) from output
    4. Returns results for RetrospectiveHandler to include in context

    """

    def __init__(self, config: Config, project_path: Path) -> None:
        """Initialize handler with config and project path.

        Args:
            config: Application configuration with provider settings.
            project_path: Path to the project root directory.

        """
        super().__init__(config, project_path)

    @property
    def phase_name(self) -> str:
        """Return the phase name."""
        return "trace"

    @property
    def workflow_id(self) -> str:
        """Return the workflow identifier for engagement model checks."""
        return "trace"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for trace prompt template.

        Args:
            state: Current loop state.

        Returns:
            Context dict with common variables:
            epic_num, story_num, story_id, project_path.

        """
        return self._build_common_context(state)

    def _extract_gate_decision(self, output: str) -> str | None:
        """Extract gate decision from trace workflow output.

        Delegates to centralized extraction function from testarch.core.

        Args:
            output: Raw trace workflow output.

        Returns:
            Gate decision string (PASS/CONCERNS/FAIL/WAIVED) or None if not found.

        """
        return extract_gate_decision(output)

    def _invoke_trace_workflow(self, state: State) -> PhaseResult:
        """Invoke trace workflow via master provider.

        Delegates to base handler's _invoke_generic_workflow with trace
        specific parameters.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with workflow output containing:
            - response: Provider output
            - gate_decision: PASS/CONCERNS/FAIL/WAIVED
            - file: Path to saved traceability matrix

        """
        epic_id = str(state.current_epic or "unknown")

        try:
            paths = get_paths()
            report_dir = paths.output_folder / "traceability"
        except RuntimeError:
            logger.error("Paths not initialized")
            return PhaseResult.fail("Paths not initialized")

        return self._invoke_generic_workflow(
            workflow_name="testarch-trace",
            state=state,
            extractor_fn=self._extract_gate_decision,
            report_dir=report_dir,
            report_prefix="trace",
            story_id=epic_id,  # Trace is epic-level
            metric_key="gate_decision",
            file_key="trace_file",
        )

    def execute(self, state: State) -> PhaseResult:
        """Execute trace check. Standard entry point for handlers.

        Delegates to base handler's _execute_with_mode_check for standardized
        mode handling and workflow invocation.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        epic_id = state.current_epic or "unknown"
        logger.info("Trace handler starting for epic %s", epic_id)

        # Engagement model check (before all other checks)
        should_run, skip_reason = self._check_engagement_model()
        if not should_run:
            logger.info("Trace skipped: %s", skip_reason)
            return self._make_engagement_skip_result(skip_reason or "engagement_model disabled")

        return self._execute_with_mode_check(
            state=state,
            mode_field="trace_on_epic_complete",
            state_flag="atdd_ran_in_epic",
            workflow_fn=self._invoke_trace_workflow,
            mode_output_key="trace_mode",
            skip_reason_auto="no ATDD ran in epic",
        )

    def run(self, state: State) -> PhaseResult:
        """Run trace check. DEPRECATED: Use execute() instead.

        This method is deprecated and will be removed in a future version.
        It delegates to execute() for backwards compatibility with
        RetrospectiveHandler.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        warnings.warn(
            "TraceHandler.run() is deprecated, use execute() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.execute(state)