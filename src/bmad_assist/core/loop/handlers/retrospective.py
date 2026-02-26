"""RETROSPECTIVE phase handler.

Runs epic retrospective after the last story completes.

Bug Fix: Retrospective Report Persistence
- Extracts report from LLM output using markers
- Saves report to retrospectives directory

Note: Trace is now a separate Phase (Phase.TRACE) and can be configured
in loop.epic_teardown to run before retrospective. The trace invocation
has been removed from this handler to decouple core from testarch.

"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from bmad_assist.core.loop.handlers.base import BaseHandler
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.retrospective import (
    extract_retrospective_report,
    save_retrospective_report,
)
from bmad_assist.sprint import parse_sprint_status, write_sprint_status

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RetrospectiveHandler(BaseHandler):
    """Handler for RETROSPECTIVE phase.

    Invokes Master LLM to conduct epic retrospective.

    Note: Trace is now a separate Phase (Phase.TRACE) and should be
    configured in loop.epic_teardown to run before retrospective.

    """

    @property
    def phase_name(self) -> str:
        """Returns the name of the phase."""
        return "retrospective"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for retrospective prompt template.

        Args:
            state: Current loop state.

        Returns:
            Context dict with common variables.

        """
        return self._build_common_context(state)

    def execute(self, state: State) -> PhaseResult:
        """Execute the retrospective handler.

        Runs the retrospective workflow. After successful execution, extracts
        and saves the retrospective report.

        Note: Trace is now a separate Phase and should be configured in
        loop.epic_teardown to run before retrospective.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult from retrospective execution, with report_file in outputs.

        """
        # Run parent's execute() for actual retrospective
        result = super().execute(state)

        # Extract and save retrospective report if successful
        if result.success and state.current_epic is not None:
            self._save_retrospective_report(result, state)

        return result

    def _save_retrospective_report(self, result: PhaseResult, state: State) -> None:
        """Extract and save retrospective report from LLM output.

        Bug Fix: Retrospective Report Persistence (AC #3)

        Args:
            result: Successful PhaseResult with response in outputs.
            state: Current loop state with epic information.

        """
        try:
            raw_output = result.outputs.get("response", "")
            if not raw_output:
                logger.warning("No response in retrospective result, skipping save")
                return

            # Extract report using markers or fallback heuristics
            report_content = extract_retrospective_report(raw_output)

            # Get retrospectives directory from project paths
            paths = get_paths()
            retrospectives_dir = paths.retrospectives_dir

            # Save report
            # Note: state.current_epic is guaranteed non-None by the caller's guard
            assert state.current_epic is not None  # Type narrowing for mypy
            timestamp = datetime.now(UTC)
            report_path = save_retrospective_report(
                content=report_content,
                epic_id=state.current_epic,
                retrospectives_dir=retrospectives_dir,
                timestamp=timestamp,
            )

            # Add report path to result outputs
            # Note: PhaseResult is frozen=True, but outputs dict is intentionally
            # mutable to allow handlers to enrich results without recreating the
            # entire dataclass. This is a deliberate design choice - see types.py.
            result.outputs["report_file"] = str(report_path)

            logger.info("Retrospective report saved: %s", report_path)

            # Update sprint-status.yaml to mark retrospective as done
            # This prevents the runner from prompting to re-run it
            sprint_status_path = paths.implementation_artifacts / "sprint-status.yaml"
            if sprint_status_path.exists():
                try:
                    status = parse_sprint_status(sprint_status_path)
                    retro_key = f"epic-{state.current_epic}-retrospective"

                    if retro_key in status.entries:
                        # Only update if not already done to avoid unnecessary writes
                        if status.entries[retro_key].status != "done":
                            status.entries[retro_key].status = "done"
                            write_sprint_status(status, sprint_status_path)
                            logger.info("Updated sprint status for %s to done", retro_key)
                    else:
                        logger.warning("Retrospective key %s not found in sprint status", retro_key)

                except Exception as e:
                    logger.error("Failed to update sprint status for %s: %s", retro_key, e)

        except Exception as e:
            # Non-blocking: log error but don't fail the retrospective
            # AC #5: graceful degradation
            logger.error(
                "Failed to save retrospective report for epic %s: %s",
                state.current_epic,
                e,
                exc_info=True,  # Include traceback for debugging
            )
