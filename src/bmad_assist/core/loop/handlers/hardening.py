"""HARDENING phase handler.

Hybrid triage handler that assesses retrospective action items and decides:
- no_action: No actionable items — epic closes immediately.
- direct_fix: Trivial fixes applied inline — no story generated.
- story_needed: Complex items require a dedicated hardening story.

The hardening story is now attached to the CURRENT epic (epic-{N}-hardening.md)
to avoid collisions with prerequisite Story 0 entries and orphaned tasks.

"""

import json
import logging
import re
from typing import Any, cast

from bmad_assist.core.extraction import HARDENING_TRIAGE_MARKERS, extract_report
from bmad_assist.core.io import atomic_write, strip_code_block
from bmad_assist.core.loop.handlers.base import BaseHandler
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.retrospective.reports import get_latest_retrospective_report
from bmad_assist.sprint import parse_sprint_status, write_sprint_status

logger = logging.getLogger(__name__)

# Valid triage decisions the LLM can return
_VALID_DECISIONS = frozenset({"no_action", "direct_fix", "story_needed"})


def _parse_triage_decision(raw_output: str) -> dict[str, Any]:
    """Parse the triage decision JSON from LLM output.

    Looks for ``<!-- HARDENING_TRIAGE_START -->`` / ``<!-- HARDENING_TRIAGE_END -->``
    markers wrapping a JSON object.

    Expected JSON shape::

        {
            "decision": "no_action" | "direct_fix" | "story_needed",
            "reason": "<human-readable justification>",
            "fixes_applied": ["<description>", ...],  // only for direct_fix
            "story_content": "<markdown>"              // only for story_needed
        }

    Args:
        raw_output: Raw LLM output.

    Returns:
        Parsed dict, or a fallback ``{"decision": "story_needed"}`` when
        the structured block cannot be found/parsed (backward compat).

    """
    content = extract_report(raw_output, HARDENING_TRIAGE_MARKERS)

    # extract_report returns the full output when markers are missing.
    # If the content doesn't look like JSON, fall back.
    if not content or not content.lstrip().startswith("{"):
        # Try to find a JSON block anywhere in the output
        match = re.search(
            r"\{[^{}]*\"decision\"\s*:\s*\"[^\"]+\"[^{}]*\}",
            raw_output,
            re.DOTALL,
        )
        if match:
            content = match.group(0)
        else:
            logger.info("No triage decision block found — falling back to story_needed")
            return {"decision": "story_needed"}

    try:
        data = cast(dict[str, Any], json.loads(content))
    except json.JSONDecodeError:
        # Content from extract_report may have trailing text; try narrow regex on raw
        match = re.search(
            r"\{[^{}]*\"decision\"\s*:\s*\"[^\"]+\"[^{}]*\}",
            raw_output,
            re.DOTALL,
        )
        if match:
            try:
                data = cast(dict[str, Any], json.loads(match.group(0)))
            except json.JSONDecodeError as exc2:
                logger.warning("Failed to parse triage JSON: %s — falling back to story_needed", exc2)
                return {"decision": "story_needed"}
        else:
            logger.warning("Failed to parse triage JSON — falling back to story_needed")
            return {"decision": "story_needed"}

    decision = data.get("decision", "story_needed")
    if decision not in _VALID_DECISIONS:
        logger.warning("Unknown triage decision '%s' — falling back to story_needed", decision)
        data["decision"] = "story_needed"

    return data


class HardeningHandler(BaseHandler):
    """Handler for HARDENING phase — hybrid triage.

    Reads the last retrospective report and prompts the LLM to triage
    action items.  Depending on the triage decision:

    * **no_action** — Nothing to do, epic closes immediately.
    * **direct_fix** — Trivial items fixed inline, no story file.
    * **story_needed** — Complex items → ``epic-{N}-hardening.md`` created.

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
        report_path, content = get_latest_retrospective_report(epic_id)

        if not content:
            logger.warning("No retrospective report found for epic %s", epic_id)
            return {**base_context, "retrospective_report_content": "No retrospective report found."}

        logger.info("Using retrospective report from: %s", report_path)
        return {**base_context, "retrospective_report_content": content}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self, state: State) -> PhaseResult:
        """Execute hardening phase with hybrid triage.

        1. Invoke LLM to triage retrospective action items.
        2. Parse triage decision.
        3. Handle each decision path (no_action / direct_fix / story_needed).

        """
        epic_id = state.current_epic
        if not epic_id:
            return PhaseResult.fail("Cannot run hardening phase: no current epic")

        # Invoke LLM via BaseHandler
        result = super().execute(state)

        if not result.success:
            return result

        raw_output = result.outputs.get("response", "")
        if not raw_output:
            return PhaseResult.fail("LLM returned no output for hardening")

        # Parse triage decision
        triage = _parse_triage_decision(raw_output)
        decision = triage.get("decision", "story_needed")
        result.outputs["hardening_decision"] = decision
        result.outputs["hardening_reason"] = triage.get("reason", "")

        logger.info("Hardening triage decision: %s (reason: %s)", decision, triage.get("reason", "-"))

        if decision == "no_action":
            return self._handle_no_action(result, epic_id)

        if decision == "direct_fix":
            return self._handle_direct_fix(result, epic_id, triage)

        # decision == "story_needed" (or fallback)
        return self._handle_story_needed(result, state, triage, raw_output)

    # ------------------------------------------------------------------
    # Decision handlers
    # ------------------------------------------------------------------

    def _handle_no_action(
        self,
        result: PhaseResult,
        epic_id: Any,
    ) -> PhaseResult:
        """No actionable items — mark hardening done immediately."""
        logger.info("No actionable hardening items for epic %s — skipping story creation", epic_id)
        self._mark_hardening_done(epic_id)
        return result

    def _handle_direct_fix(
        self,
        result: PhaseResult,
        epic_id: Any,
        triage: dict[str, Any],
    ) -> PhaseResult:
        """Trivial fixes already applied by LLM — mark done, no story."""
        fixes = triage.get("fixes_applied", [])
        logger.info(
            "Hardening: %d trivial fix(es) applied directly for epic %s",
            len(fixes),
            epic_id,
        )
        result.outputs["hardening_fixes_applied"] = fixes
        self._mark_hardening_done(epic_id)
        return result

    def _get_hardening_story_num(self, epic_id: Any) -> int:
        """Find the existing or next available story number Y for epic X hardening."""
        paths = get_paths()
        sprint_status_path = paths.sprint_status_file

        max_y = 0
        existing_hardening_y = None
        if sprint_status_path.exists():
            from bmad_assist.sprint.classifier import _EPIC_STORY_PATTERN
            from bmad_assist.sprint import parse_sprint_status
            try:
                sprint_status = parse_sprint_status(sprint_status_path)
                for key in sprint_status.entries:
                    match = _EPIC_STORY_PATTERN.match(key)
                    if match and match.group(1) == str(epic_id):
                        y = int(match.group(2))
                        if key.endswith("-hardening"):
                            if existing_hardening_y is None or y > existing_hardening_y:
                                existing_hardening_y = y
                        if y > max_y:
                            max_y = y
            except Exception as e:
                logger.error("Failed to parse sprint-status to find next story num: %s", e)

        if existing_hardening_y is not None:
            return existing_hardening_y

        # Use max_y + 1 (e.g. if highest is 6.7, next is 6.8)
        # If no stories found, default to 1
        return max(1, max_y + 1)

    def _handle_story_needed(
        self,
        result: PhaseResult,
        state: State,
        triage: dict[str, Any],
        raw_output: str,
    ) -> PhaseResult:
        """Complex items — create ``{epic_id}-{Y}-hardening.md`` story."""
        epic_id = state.current_epic
        # Get story content: prefer triage.story_content, fall back to raw LLM output
        story_content = triage.get("story_content", "")
        if not story_content:
            story_content = strip_code_block(raw_output)

        paths = get_paths()
        target_dir = paths.implementation_artifacts / "hardening"
        target_dir.mkdir(parents=True, exist_ok=True)

        next_y = self._get_hardening_story_num(epic_id)
        filename = f"{epic_id}-{next_y}-hardening.md"
        file_path = target_dir / filename

        if file_path.exists():
            logger.warning("Overwriting existing hardening story: %s", file_path)

        try:
            atomic_write(file_path, story_content)
            logger.info("Created hardening story: %s", file_path)
            result.outputs["hardening_story"] = str(file_path)
        except OSError as e:
            logger.error("Failed to save hardening story: %s", e)
            return PhaseResult.fail(f"Failed to save hardening story: {e}")

        # Register in sprint-status as backlog
        self._register_hardening_in_sprint(epic_id, next_y, status="backlog")

        # Cleanup state for re-runs: if story or epic was already marked done in a 
        # previous run, we must un-complete them here so the loop picks it up again.
        story_id = f"{epic_id}.{next_y}"
        if story_id in state.completed_stories:
            state.completed_stories.remove(story_id)
            logger.info("Cleared %s from completed_stories for re-run", story_id)
            
        if epic_id in state.completed_epics:
            state.completed_epics.remove(epic_id)
            logger.info("Cleared epic %s from completed_epics for re-run", epic_id)

        return result

    # ------------------------------------------------------------------
    # Sprint-status helpers
    # ------------------------------------------------------------------

    def _mark_hardening_done(self, epic_id: Any) -> None:
        """Mark hardening as done in sprint-status (no story file created)."""
        next_y = self._get_hardening_story_num(epic_id)
        self._register_hardening_in_sprint(epic_id, next_y, status="done")

    def _register_hardening_in_sprint(
        self,
        epic_id: Any,
        story_num: int,
        *,
        status: str = "backlog",
    ) -> None:
        """Add or update the ``{epic_id}-{Y}-hardening`` entry in sprint-status."""
        paths = get_paths()
        sprint_status_path = paths.sprint_status_file

        if not sprint_status_path.exists():
            logger.debug("No sprint-status.yaml — skipping hardening registration")
            return

        try:
            from bmad_assist.sprint.classifier import EntryType
            from bmad_assist.sprint.models import SprintStatusEntry, ValidStatus

            sprint_status = parse_sprint_status(sprint_status_path)
            story_key = f"{epic_id}-{story_num}-hardening"

            existing = sprint_status.entries.get(story_key)
            if existing is not None and existing.status == status:
                logger.debug("Hardening key %s already has status '%s'", story_key, status)
                return

            new_entry = SprintStatusEntry(
                key=story_key,
                status=cast(ValidStatus, status),
                # Using EPIC_STORY since it has a standard numeric format now
                entry_type=EntryType.EPIC_STORY,
                source="hardening",
            )

            if story_key in sprint_status.entries:
                sprint_status.entries[story_key] = new_entry
            else:
                # Insert after epic-{epic_id}-retrospective, or epic-{epic_id}, or at the end
                new_entries = {}
                target_retro = f"epic-{epic_id}-retrospective"
                target_epic = f"epic-{epic_id}"
                inserted = False

                for k, v in sprint_status.entries.items():
                    new_entries[k] = v
                    if k == target_retro:
                        new_entries[story_key] = new_entry
                        inserted = True

                if not inserted:
                    new_entries = {}
                    for k, v in sprint_status.entries.items():
                        new_entries[k] = v
                        if k == target_epic:
                            new_entries[story_key] = new_entry
                            inserted = True

                if not inserted:
                    new_entries[story_key] = new_entry

                sprint_status.entries = new_entries

            write_sprint_status(sprint_status, sprint_status_path)
            logger.info("Set hardening key %s → %s in sprint-status", story_key, status)

        except Exception as e:
            logger.error("Failed to update sprint-status for hardening: %s", e)

