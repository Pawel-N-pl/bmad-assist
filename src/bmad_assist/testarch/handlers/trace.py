"""Trace handler for testarch module.

Runs the testarch-trace workflow on epic completion alongside the retrospective,
generating traceability matrices and quality gate decisions.

Note: This handler is NOT registered in dispatch.py since it's not a Phase.
It's invoked directly by RetrospectiveHandler.

"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.compiler import compile_workflow
from bmad_assist.compiler.types import CompilerContext
from bmad_assist.core.io import get_original_cwd
from bmad_assist.core.loop.handlers.base import BaseHandler
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.providers import get_provider

if TYPE_CHECKING:
    from bmad_assist.core.config import Config

logger = logging.getLogger(__name__)


class TraceHandler(BaseHandler):
    """Handler for trace workflow.

    Executes the testarch-trace workflow when enabled. Unlike ATDDHandler,
    this handler is NOT dispatched by the main loop - it's invoked directly
    by RetrospectiveHandler before the retrospective workflow runs.

    The handler:
    1. Checks trace mode (off/auto/on) to determine if trace should run
    2. Invokes the trace workflow for eligible epics (placeholder until testarch-8)
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

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for trace prompt template.

        Args:
            state: Current loop state.

        Returns:
            Context dict with common variables:
            epic_num, story_num, story_id, project_path.

        """
        return self._build_common_context(state)

    def _check_trace_mode(self, state: State) -> tuple[str, bool]:
        """Check trace mode and return (mode, should_run).

        Returns:
            Tuple of (mode: str, should_run: bool)
            - ("off", False) - skip trace entirely
            - ("on", True) - run trace unconditionally
            - ("auto", True/False) - check atdd_ran_in_epic flag
            - ("not_configured", False) - no testarch config

        """
        if not hasattr(self.config, "testarch") or self.config.testarch is None:
            return ("not_configured", False)

        mode = self.config.testarch.trace_on_epic_complete
        if mode == "off":
            return ("off", False)
        elif mode == "on":
            return ("on", True)
        else:  # auto
            should_run = state.atdd_ran_in_epic
            return ("auto", should_run)

    def _extract_gate_decision(self, output: str) -> str | None:
        """Extract gate decision from trace workflow output.

        Uses case-insensitive regex with word boundaries to avoid
        partial matches (e.g., "PASSED" should not match "PASS").

        Returns highest priority match: FAIL > CONCERNS > PASS > WAIVED.
        Priority is determined by check order, not by position in string.
        For example, if output contains both "PASS" and "FAIL", returns "FAIL".

        Args:
            output: Raw trace workflow output.

        Returns:
            Gate decision string (PASS/CONCERNS/FAIL/WAIVED) or None if not found.

        """
        # Priority order: strictest first (FAIL has highest priority)
        # Checks in order, returns first match found
        for decision in ["FAIL", "CONCERNS", "PASS", "WAIVED"]:
            pattern = rf"\b{decision}\b"
            if re.search(pattern, output, re.IGNORECASE):
                return decision
        return None

    def _invoke_trace_workflow(self, state: State) -> PhaseResult:
        """Invoke trace workflow via master provider.

        Creates a CompilerContext with state variables, compiles the
        testarch-trace workflow, invokes the master provider, and saves
        the traceability matrix to file.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with workflow output containing:
            - response: Provider output
            - gate_decision: PASS/CONCERNS/FAIL/WAIVED
            - trace_file: Path to saved traceability matrix

        """
        from bmad_assist.core.exceptions import CompilerError

        epic_id = state.current_epic or "unknown"
        logger.info("Invoking trace workflow for epic %s", epic_id)

        try:
            # 1. Create CompilerContext from state
            # Use get_original_cwd() to preserve original CWD when running as subprocess
            paths = get_paths()
            context = CompilerContext(
                project_root=self.project_path,
                output_folder=paths.output_folder,
                project_knowledge=paths.project_knowledge,
                cwd=get_original_cwd(),
            )

            # Set resolved variables
            context.resolved_variables = {
                "epic_num": state.current_epic,
            }

            # 2. Compile workflow
            compiled = compile_workflow("testarch-trace", context)
            logger.debug("Trace workflow compiled successfully")

            # 3. Get provider from config
            provider_name = self.config.providers.master.provider
            provider = get_provider(provider_name)
            model = self.config.providers.master.model

            logger.debug("Using provider %s with model %s", provider_name, model)

            # Agent tracking
            from bmad_assist.core.tracking import track_agent_end, track_agent_start

            _timeout = getattr(self.config, "timeout", 120)
            _track_cli = {"model": model, "timeout": _timeout, "cwd": self.project_path}
            _track_start = track_agent_start(
                self.project_path, state.current_epic or "", "",
                "trace", provider_name, model or "unknown", compiled.context,
                cli_params=_track_cli,
            )

            # 4. Invoke provider with compiled prompt
            result = provider.invoke(
                prompt=compiled.context,
                model=model,
                timeout=_timeout,
                cwd=self.project_path,
            )

            track_agent_end(
                self.project_path, state.current_epic or "", "",
                "trace", provider_name, model or "unknown", compiled.context,
                _track_start, cli_params=_track_cli,
            )

            # 5. Parse result
            if result.exit_code != 0:
                logger.error("Trace provider error for epic %s: %s", epic_id, result.stderr)
                return PhaseResult.fail(f"Provider error: {result.stderr}")

            # 6. Extract gate decision
            gate_decision = self._extract_gate_decision(result.stdout)
            logger.info("Trace gate decision for epic %s: %s", epic_id, gate_decision)

            # 7. Create traceability directory
            traceability_dir = paths.output_folder / "traceability"
            traceability_dir.mkdir(parents=True, exist_ok=True)

            # 8. Save trace file using atomic write
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            trace_filename = f"trace-{epic_id}-{timestamp}.md"
            trace_path = traceability_dir / trace_filename

            # Atomic write: write to temp file, then rename
            fd, temp_path = tempfile.mkstemp(
                suffix=".md",
                prefix="trace_",
                dir=str(traceability_dir),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(result.stdout)
                os.rename(temp_path, trace_path)
                logger.info("Trace file saved: %s", trace_path)
            except Exception:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

            return PhaseResult.ok(
                {
                    "response": result.stdout,
                    "gate_decision": gate_decision,
                    "trace_file": str(trace_path),
                }
            )

        except CompilerError as e:
            logger.error("Trace compiler error for epic %s: %s", epic_id, e)
            return PhaseResult.fail(f"Compiler error: {e}")
        except Exception as e:
            logger.error("Trace workflow failed for epic %s: %s", epic_id, e)
            return PhaseResult.fail(f"Trace workflow failed: {e}")

    def run(self, state: State) -> PhaseResult:
        """Run trace check. Called by RetrospectiveHandler.

        This method:
        1. Checks trace mode configuration
        2. Skips if mode=off or (mode=auto and no ATDD ran)
        3. Invokes trace workflow if enabled
        4. Extracts gate decision from output

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with success/failure and outputs.

        """
        epic_id = state.current_epic or "unknown"
        logger.info("Trace handler starting for epic %s", epic_id)

        # Check trace mode
        mode, should_run = self._check_trace_mode(state)
        logger.info(
            "Trace mode: %s, ATDD ran in epic: %s",
            mode,
            state.atdd_ran_in_epic,
        )

        # Handle not configured case
        if mode == "not_configured":
            logger.info("Trace skipped: testarch not configured")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": "testarch not configured",
                    "trace_mode": "not_configured",
                }
            )

        # Handle mode=off
        if mode == "off":
            logger.info("Trace skipped: trace_on_epic_complete=off")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": "trace_on_epic_complete=off",
                    "trace_mode": "off",
                }
            )

        # Handle mode=auto with no ATDD
        if not should_run:
            logger.info("Trace skipped: no ATDD ran in epic")
            return PhaseResult.ok(
                {
                    "skipped": True,
                    "reason": "no ATDD ran in epic",
                    "trace_mode": "auto",
                }
            )

        # Invoke trace workflow
        try:
            workflow_result = self._invoke_trace_workflow(state)

            if workflow_result.success:
                outputs = dict(workflow_result.outputs)

                # Extract gate decision if not already in outputs
                if "gate_decision" not in outputs or outputs["gate_decision"] is None:
                    response = outputs.get("response", "")
                    gate_decision = self._extract_gate_decision(response)
                    outputs["gate_decision"] = gate_decision

                logger.info(
                    "Trace workflow completed: gate_decision=%s",
                    outputs.get("gate_decision"),
                )

                return PhaseResult.ok(outputs)
            else:
                logger.warning("Trace failed: %s", workflow_result.error)
                return workflow_result

        except Exception as e:
            logger.warning("Trace failed: %s", e)
            return PhaseResult.fail(f"Trace workflow failed: {e}")
