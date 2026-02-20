"""HARDENING phase handler.

Generates a Story 0 (Hardening Story) based on the Retrospective Report.
This phase reads the retrospective report for the current epic and uses the LLM
to synthesize actionable items into a concrete backlog story.

"""

import logging
from typing import Any

from bmad_assist.core.io import atomic_write, strip_code_block
from bmad_assist.core.loop.handlers.base import BaseHandler
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.retrospective.reports import get_latest_retrospective_report
from bmad_assist.sprint import parse_sprint_status, write_sprint_status

logger = logging.getLogger(__name__)


class HardeningHandler(BaseHandler):
    """Handler for HARDENING phase.

    Reads the last retrospective report and prompts the LLM to generate
    a "Hardening Story" (Story 0) for the next epic.

    """

    @property
    def phase_name(self) -> str:
        """Returns the name of the phase."""
        return "hardening"

    @property
    def track_timing(self) -> bool:
        """Enable timing tracking for this handler."""
        return True

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for hardening prompt template.

        Loads the retrospective report content.

        Args:
            state: Current loop state.

        Returns:
            Context dict with 'retrospective_report_content'.

        """
        base_context = self._build_common_context(state)

        epic_id = state.current_epic
        if epic_id is None:
            return {**base_context, "retrospective_report_content": "No active epic."}

        # Find retrospective report
        # Note: Retrospective runs for current epic, so we look for report of current epic
        report_path, content = get_latest_retrospective_report(epic_id)

        if not content:
            logger.warning("No retrospective report found for epic %s", epic_id)
            return {**base_context, "retrospective_report_content": "No retrospective report found."}

        logger.info("Using retrospective report from: %s", report_path)
        return {**base_context, "retrospective_report_content": content}

    def execute(self, state: State) -> PhaseResult:
        """Execute hardening phase.

        1. Invoke LLM to generate story content.
        2. Save content to Story 0 file.

        """
        # Check preconditions
        epic_id = state.current_epic
        if not epic_id:
             return PhaseResult.fail("Cannot run hardening phase: no current epic")

        # Invoke LLM via BaseHandler
        result = super().execute(state)

        if not result.success:
            return result

        raw_output = result.outputs.get("response", "")
        if not raw_output:
            return PhaseResult.fail("LLM returned no output for hardening story")

        # Extract and clean content
        content = strip_code_block(raw_output)

        # Determine target file path
        # The hardening story is for the NEXT epic (current_epic + 1).
        # During teardown, state.current_epic is the completed epic.
        # The action items from the retrospective form Story 0 of the next epic.
        next_epic_id = epic_id + 1 if isinstance(epic_id, int) else epic_id

        paths = get_paths()
        # Save to implementation-artifacts/hardening/ (NOT planning-artifacts/epics/
        # which would break the sharded epic loader)
        target_dir = paths.implementation_artifacts / "hardening"
        target_dir.mkdir(parents=True, exist_ok=True)

        # Default filename if we can't parse ID from content
        # We try to find `# Story X.0` in content to key the file.
        import re
        match = re.search(r"^#\s*Story\s+([A-Za-z0-9_.-]+)(\.0)?", content, re.MULTILINE | re.IGNORECASE)

        if match:
            # e.g., "5.0" -> id="5"
            file_naming_id = match.group(1)
        else:
            # Fallback: use next epic ID
            file_naming_id = str(next_epic_id)

        filename = f"epic-{file_naming_id}-0-hardening.md"
        file_path = target_dir / filename

        if file_path.exists():
            logger.warning("Overwriting existing hardening story: %s", file_path)

        try:
            atomic_write(file_path, content)
            logger.info("Created hardening story: %s", file_path)
            result.outputs["hardening_story"] = str(file_path)

            # Register the hardening story in sprint-status.yaml so the
            # story loader discovers it on the next run (Story 5.0 before 5.1)
            sprint_status_path = paths.implementation_artifacts / "sprint-status.yaml"
            if sprint_status_path.exists():
                try:
                    from bmad_assist.sprint.classifier import EntryType

                    status = parse_sprint_status(sprint_status_path)

                    # Add the story entry (e.g., "5-0-retrospective-hardening: backlog")
                    story_key = f"{next_epic_id}-0-retrospective-hardening"
                    if story_key not in status.entries:
                        from bmad_assist.sprint.models import SprintStatusEntry

                        status.entries[story_key] = SprintStatusEntry(
                            key=story_key,
                            status="backlog",
                            entry_type=EntryType.EPIC_STORY,
                            source="hardening",
                        )
                        write_sprint_status(status, sprint_status_path)
                        logger.info("Added hardening story %s to sprint status", story_key)
                    else:
                        logger.debug("Hardening story %s already in sprint status", story_key)

                except Exception as e:
                    logger.error("Failed to update sprint status for hardening story: %s", e)

        except OSError as e:
            logger.error("Failed to save hardening story: %s", e)
            return PhaseResult.fail(f"Failed to save hardening story: {e}")

        return result
