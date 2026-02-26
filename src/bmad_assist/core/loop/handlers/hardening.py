"""HARDENING phase handler.

Hybrid triage handler that assesses retrospective action items and can do both:
- direct fixes for trivial items (inline), and
- hardening story generation for complex items.

The hardening story is attached to the CURRENT epic ({epic_id}-{story_num}-hardening.md)
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

# Legacy decision values retained for backward compatibility.
_LEGACY_DECISIONS = frozenset({"no_action", "direct_fix", "story_needed", "mixed"})


def _fallback_triage_decision() -> dict[str, Any]:
    """Return safe fallback triage payload (story-first)."""
    return {
        "decision": "story_needed",
        "reason": "",
        "has_direct_fixes": False,
        "story_needed": True,
        "fixes_applied": [],
        "story_content": "",
    }


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    """Best-effort bool coercion for triage fields."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _normalize_fixes(value: Any) -> list[str]:
    """Normalize fixes_applied into a clean list of non-empty strings."""
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []

    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _derive_triage_decision(has_direct_fixes: bool, story_needed: bool) -> str:
    """Derive a canonical decision label from normalized booleans."""
    if has_direct_fixes and story_needed:
        return "mixed"
    if has_direct_fixes:
        return "direct_fix"
    if story_needed:
        return "story_needed"
    return "no_action"


def _parse_triage_decision(raw_output: str) -> dict[str, Any]:
    """Parse the triage decision JSON from LLM output.

    Looks for ``<!-- HARDENING_TRIAGE_START -->`` / ``<!-- HARDENING_TRIAGE_END -->``
    markers wrapping a JSON object.

    Expected JSON shape::

        {
            "has_direct_fixes": true | false,
            "story_needed": true | false,
            "reason": "<human-readable justification>",
            "fixes_applied": ["<description>", ...],
            "story_content": "<markdown>"
        }

    Legacy ``decision`` values (``no_action`` / ``direct_fix`` /
    ``story_needed`` / ``mixed``) are still accepted.

    Args:
        raw_output: Raw LLM output.

    Returns:
        Normalized triage dict, or a story-first fallback when
        the structured block cannot be found/parsed (backward compat).

    """
    content = extract_report(raw_output, HARDENING_TRIAGE_MARKERS)

    # extract_report returns the full output when markers are missing.
    # If the content doesn't look like JSON, fall back.
    if not content or not content.lstrip().startswith("{"):
        # Try to find a JSON block anywhere in the output
        match = re.search(r"\{.*\}", raw_output, re.DOTALL)
        if match:
            content = match.group(0)
        else:
            logger.info("No triage decision block found — falling back to story_needed")
            return _fallback_triage_decision()

    try:
        data = cast(dict[str, Any], json.loads(content))
    except json.JSONDecodeError:
        # Content from extract_report may have trailing text; try narrow regex on raw
        match = re.search(r"\{.*\}", raw_output, re.DOTALL)
        if match:
            try:
                data = cast(dict[str, Any], json.loads(match.group(0)))
            except json.JSONDecodeError as exc2:
                logger.warning("Failed to parse triage JSON: %s — falling back to story_needed", exc2)
                return _fallback_triage_decision()
        else:
            logger.warning("Failed to parse triage JSON — falling back to story_needed")
            return _fallback_triage_decision()

    has_direct_fixes = _coerce_bool(data.get("has_direct_fixes"), default=False)
    story_needed = _coerce_bool(data.get("story_needed"), default=False)

    legacy_decision = data.get("decision")
    if isinstance(legacy_decision, str):
        normalized_decision = legacy_decision.strip().lower()
        if normalized_decision in _LEGACY_DECISIONS:
            if normalized_decision in {"direct_fix", "mixed"}:
                has_direct_fixes = True
            if normalized_decision in {"story_needed", "mixed"}:
                story_needed = True
        else:
            logger.warning(
                "Unknown triage decision '%s' — falling back to story_needed",
                legacy_decision,
            )
            story_needed = True

    fixes_applied = _normalize_fixes(data.get("fixes_applied"))
    if fixes_applied:
        has_direct_fixes = True

    story_content = data.get("story_content")
    if not isinstance(story_content, str):
        story_content = ""
    if story_content.strip():
        story_needed = True

    reason = data.get("reason")
    if not isinstance(reason, str):
        reason = ""

    return {
        "decision": _derive_triage_decision(has_direct_fixes, story_needed),
        "reason": reason,
        "has_direct_fixes": has_direct_fixes,
        "story_needed": story_needed,
        "fixes_applied": fixes_applied,
        "story_content": story_content,
    }


class HardeningHandler(BaseHandler):
    """Handler for HARDENING phase — hybrid triage.

    Reads the last retrospective report and prompts the LLM to triage
    action items, then executes a pipeline:

    * record direct fixes (if any),
    * create hardening story for complex work (if any),
    * mark hardening done when no story is generated.

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
        2. Parse triage payload (supports mixed direct-fix + story output).
        3. Run pipeline:
           - Step 1: record direct fixes if ``fixes_applied`` has items.
           - Step 2: create hardening story if complex work is present.
           - Step 3: if no story created, mark hardening done.

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
        fixes_applied = _normalize_fixes(triage.get("fixes_applied", []))
        story_needed = _coerce_bool(triage.get("story_needed"), default=False)
        story_content = triage.get("story_content", "")
        has_story_content = isinstance(story_content, str) and bool(story_content.strip())

        result.outputs["hardening_decision"] = decision
        result.outputs["hardening_reason"] = triage.get("reason", "")
        result.outputs["hardening_has_direct_fixes"] = bool(fixes_applied)
        result.outputs["hardening_story_needed"] = story_needed or has_story_content

        logger.info(
            "Hardening triage parsed: decision=%s has_direct_fixes=%s story_needed=%s",
            decision,
            bool(fixes_applied),
            story_needed or has_story_content,
        )

        # Step 1: record direct fixes (if any)
        fixes_recorded = False
        if fixes_applied:
            triage["fixes_applied"] = fixes_applied
            self._handle_direct_fix(result, epic_id, triage)
            fixes_recorded = True

        # Step 2: create hardening story for complex work (if needed)
        story_created = False
        if story_needed or has_story_content:
            story_result = self._handle_story_needed(result, state, triage, raw_output)
            if not story_result.success:
                return story_result
            result = story_result
            story_created = True

        if story_created:
            result.outputs["hardening_decision"] = "mixed" if fixes_recorded else "story_needed"
            return result

        # Step 3: no story was created -> hardening is done.
        if fixes_recorded:
            self._mark_hardening_done(epic_id)
            result.outputs["hardening_decision"] = "direct_fix"
            return result

        result.outputs["hardening_decision"] = "no_action"
        return self._handle_no_action(result, epic_id)

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
        """Record trivial fixes already applied by LLM."""
        fixes = _normalize_fixes(triage.get("fixes_applied", []))
        logger.info(
            "Hardening: %d trivial fix(es) applied directly for epic %s",
            len(fixes),
            epic_id,
        )
        result.outputs["hardening_fixes_applied"] = fixes
        return result

    def _get_hardening_story_num(self, epic_id: Any) -> int:
        """Find the existing or next available story number Y for epic X hardening."""
        paths = get_paths()
        sprint_status_path = paths.sprint_status_file

        max_y = 0
        existing_hardening_y = None
        if sprint_status_path.exists():
            from bmad_assist.sprint import parse_sprint_status
            from bmad_assist.sprint.classifier import _EPIC_STORY_PATTERN

            try:
                sprint_status = parse_sprint_status(sprint_status_path)
                for key in sprint_status.entries:
                    match = _EPIC_STORY_PATTERN.match(key)
                    if match and match.group(1) == str(epic_id):
                        y = int(match.group(2))
                        if key.endswith("-hardening") and (
                            existing_hardening_y is None or y > existing_hardening_y
                        ):
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

        from bmad_assist.core.state import EpicLifecycle

        state.epic_lifecycle = EpicLifecycle.HARDENING
        logger.info("Set epic lifecycle to HARDENING for epic %s", epic_id)

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
                comment=None,
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
