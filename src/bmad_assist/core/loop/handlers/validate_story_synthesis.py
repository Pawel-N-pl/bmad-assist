"""VALIDATE_STORY_SYNTHESIS phase handler.

Master LLM synthesizes Multi-LLM validation reports.

Story 11.7: Validation Phase Loop Integration
Story 13.6: Synthesizer Schema Integration

This handler:
1. Loads anonymized validations from previous phase (via file cache)
2. Compiles synthesis workflow with validations injected
3. Invokes Master LLM to synthesize findings
4. Master LLM applies changes directly to story file
5. Extracts metrics and saves synthesizer evaluation record (Story 13.6)

The synthesis phase receives anonymized validator outputs and
has write permission to modify the story file.

"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bmad_assist.compiler import compile_workflow
from bmad_assist.compiler.types import CompilerContext
from bmad_assist.core.exceptions import ConfigError
from bmad_assist.core.io import get_original_cwd
from bmad_assist.core.loop.handlers.base import BaseHandler, check_for_edit_failures
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.core.types import EpicId
from bmad_assist.validation.orchestrator import (
    ValidationError,
    load_validations_for_synthesis,
)
from bmad_assist.validation.reports import (
    extract_synthesis_report,
    save_synthesis_report,
)
from bmad_assist.validation.validation_metrics import (
    calculate_aggregate_metrics,
    extract_validator_metrics,
    format_deterministic_metrics_header,
)

logger = logging.getLogger(__name__)


class ValidateStorySynthesisHandler(BaseHandler):
    """Handler for VALIDATE_STORY_SYNTHESIS phase.

    Invokes Master LLM to synthesize validation reports from
    multiple validators. Uses the validate-story-synthesis
    workflow compiler.

    """

    @property
    def phase_name(self) -> str:
        """Returns the name of the phase."""
        return "validate_story_synthesis"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for validate_story_synthesis prompt template.

        Available variables: epic_num, story_num, story_id, project_path

        """
        return self._build_common_context(state)

    def _get_session_id_from_state(self, state: State) -> str | None:
        """Retrieve session_id from state.

        The session_id is saved to state file after validation phase.
        Falls back to reading from cache file if not in state.

        Args:
            state: Current loop state.

        Returns:
            Session ID string or None if not found.

        """
        # TODO: In future, session_id could be stored in state file
        # For now, we search for the most recent validations cache file
        cache_dir = self.project_path / ".bmad-assist" / "cache"
        if not cache_dir.exists():
            return None

        # Find most recent validations file
        # Use safe_mtime to handle TOCTOU race (file may be deleted between glob and stat)
        def safe_mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except (OSError, FileNotFoundError):
                return 0.0  # Treat missing files as oldest

        validation_files = sorted(
            cache_dir.glob("validations-*.json"),
            key=safe_mtime,
            reverse=True,
        )

        if not validation_files:
            return None

        # Extract session_id from filename
        latest_file = validation_files[0]
        # Filename format: validations-{session_id}.json
        # Use removeprefix for safer string manipulation
        session_id = latest_file.stem.removeprefix("validations-")

        logger.debug("Found latest validation session: %s", session_id)
        return session_id

    def render_prompt(self, state: State) -> str:
        """Render synthesis prompt with validation data.

        Overrides base render_prompt to use synthesis compiler
        with validations injected.

        Args:
            state: Current loop state.

        Returns:
            Compiled prompt XML with validations.

        """
        # Get story info
        epic_num = state.current_epic
        story_num_str = self._extract_story_num(state.current_story)

        if epic_num is None or story_num_str is None:
            raise ConfigError("Cannot synthesize: missing epic_num or story_num in state")

        story_num = int(story_num_str)

        # Get session_id for loading validations
        session_id = self._get_session_id_from_state(state)
        if session_id is None:
            raise ConfigError(
                "Cannot synthesize: no validation session found. Run VALIDATE_STORY phase first."
            )

        # Load anonymized validations from cache
        # Story 22.8 AC#4: Unpack tuple with failed_validators
        # TIER 2: Also loads pre-calculated evidence_score
        try:
            anonymized_validations, _, _evidence_score = load_validations_for_synthesis(
                session_id,
                self.project_path,
            )
        except ValidationError as e:
            raise ConfigError(f"Cannot load validations: {e}") from e

        if not anonymized_validations:
            raise ConfigError("No validations found for synthesis. Run VALIDATE_STORY phase first.")

        logger.info(
            "Compiling synthesis for story %s.%s with %d validations",
            epic_num,
            story_num,
            len(anonymized_validations),
        )

        # Get configured paths
        paths = get_paths()

        # Build compiler context with validations
        # Use get_original_cwd() to preserve original CWD when running as subprocess
        context = CompilerContext(
            project_root=self.project_path,
            output_folder=paths.implementation_artifacts,
            project_knowledge=paths.project_knowledge,
            cwd=get_original_cwd(),
            resolved_variables={
                "epic_num": epic_num,
                "story_num": story_num,
                "session_id": session_id,
                "anonymized_validations": anonymized_validations,
            },
        )

        # Compile synthesis workflow
        compiled = compile_workflow("validate-story-synthesis", context)

        logger.info(
            "Synthesis prompt compiled: ~%d tokens",
            compiled.token_estimate,
        )

        return compiled.context

    def execute(self, state: State) -> PhaseResult:
        """Execute synthesis phase.

        Compiles synthesis workflow with validations and invokes
        Master LLM to synthesize findings and apply changes.

        After successful synthesis, extracts metrics and saves synthesizer
        evaluation record (Story 13.6).

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with synthesis output.

        """
        from bmad_assist.core.io import save_prompt

        try:
            # Get story info for report saving
            epic_num = state.current_epic
            story_num_str = self._extract_story_num(state.current_story)

            if epic_num is None or story_num_str is None:
                raise ConfigError("Cannot synthesize: missing epic_num or story_num in state")

            story_num = int(story_num_str)

            # Get session_id and load validations for report saving
            session_id = self._get_session_id_from_state(state)
            if session_id is None:
                raise ConfigError(
                    "Cannot synthesize: no validation session found. "
                    "Run VALIDATE_STORY phase first."
                )

            # Story 22.8 AC#4: Unpack tuple with failed_validators
            # TIER 2: Also loads pre-calculated evidence_score for synthesis context
            anonymized_validations, failed_validators, evidence_score_data = load_validations_for_synthesis( # noqa: E501
                session_id,
                self.project_path,
            )
            validators_used = [v.validator_id for v in anonymized_validations]

            # Render prompt with validations
            prompt = self.render_prompt(state)

            # Save prompt to .bmad-assist/prompts/ (atomic write, always saved)
            save_prompt(self.project_path, epic_num, story_num, self.phase_name, prompt)

            # Record start time for benchmarking
            start_time = datetime.now(UTC)

            # Agent tracking
            from bmad_assist.core.config import get_phase_timeout
            from bmad_assist.core.tracking import track_agent_end, track_agent_start

            _phase_config = self._get_phase_config()
            if isinstance(_phase_config, list):
                _tp = _phase_config[0].provider if _phase_config else "unknown"
                _cfg = _phase_config[0] if _phase_config else None
                _tm = (_cfg.model_name or _cfg.model) if _cfg else "unknown"
            else:
                _tp = _phase_config.provider
                _tm = _phase_config.model_name or _phase_config.model or "unknown"
            _track_cli = {
                "model": self.get_cli_model(),
                "timeout": get_phase_timeout(self.config, self.phase_name),
                "cwd": self.project_path,
            }
            _track_start = track_agent_start(
                self.project_path, epic_num, story_num, self.phase_name,
                _tp, _tm, prompt, cli_params=_track_cli,
            )

            # Invoke Master LLM
            result = self.invoke_provider(prompt)

            # Agent tracking END
            track_agent_end(
                self.project_path, epic_num, story_num, self.phase_name,
                _tp, _tm, prompt, _track_start, cli_params=_track_cli,
            )

            # Record end time for benchmarking
            end_time = datetime.now(UTC)

            # Check for errors
            if result.exit_code != 0:
                error_msg = result.stderr or f"Master LLM exited with code {result.exit_code}"
                logger.warning(
                    "Synthesis failed: exit_code=%d, stderr=%s",
                    result.exit_code,
                    result.stderr[:500] if result.stderr else "(empty)",
                )
                phase_result = PhaseResult.fail(error_msg)
            else:
                # Success - save synthesis report
                logger.info(
                    "Synthesis complete: %d chars output",
                    len(result.stdout),
                )

                # Story 22.4 AC5: Check for Edit tool failures (best-effort logging)
                check_for_edit_failures(result.stdout, target_hint="story file")

                # Extract synthesis report using priority-based extraction
                # 1. Markers, 2. Summary header, 3. Full content
                extracted_synthesis = extract_synthesis_report(
                    result.stdout, synthesis_type="validation"
                )

                # Extract deterministic metrics from validation reports
                deterministic_header = self._extract_deterministic_metrics(anonymized_validations)

                # Prepend deterministic metrics to extracted synthesis
                synthesis_content = deterministic_header + extracted_synthesis

                # Save synthesis report with YAML frontmatter
                paths = get_paths()
                validations_dir = paths.validations_dir
                validations_dir.mkdir(parents=True, exist_ok=True)

                master_validator_id = f"master-{self.get_model()}"
                # Story 22.8 AC#2, AC#4: Pass failed_validators to synthesis report
                save_synthesis_report(
                    content=synthesis_content,
                    master_validator_id=master_validator_id,
                    session_id=session_id,
                    validators_used=validators_used,
                    epic=epic_num,
                    story=story_num,
                    duration_ms=result.duration_ms or 0,
                    validations_dir=validations_dir,
                    failed_validators=failed_validators,
                )

                # Extract antipatterns for create-story (best-effort, non-blocking)
                try:
                    from bmad_assist.antipatterns import extract_and_append_antipatterns

                    extract_and_append_antipatterns(
                        synthesis_content=synthesis_content,
                        epic_id=epic_num,
                        story_id=f"{epic_num}-{story_num}",
                        antipattern_type="story",
                        project_path=self.project_path,
                        config=self.config,
                    )
                except Exception as e:
                    logger.warning("Antipatterns extraction failed (non-blocking): %s", e)

                # Story 13.6: Extract metrics and save synthesizer record
                # Estimate tokens from char count (~4 chars per token)
                # Consistent with code_review_synthesis.py token estimation
                estimated_output_tokens = len(result.stdout) // 4 if result.stdout else 0
                self._save_synthesizer_record(
                    synthesis_output=result.stdout,
                    epic_num=epic_num,
                    story_num=story_num,
                    story_title=state.current_story or "",
                    start_time=start_time,
                    end_time=end_time,
                    input_tokens=0,  # Not available from current provider result
                    output_tokens=estimated_output_tokens,
                    validator_count=len(validators_used),
                )

                phase_result = PhaseResult.ok(
                    {
                        "response": result.stdout,
                        "model": result.model,
                        "duration_ms": result.duration_ms,
                    }
                )

            return phase_result

        except ConfigError as e:
            logger.error("Synthesis config error: %s", e)
            return PhaseResult.fail(str(e))

        except Exception as e:
            logger.error("Synthesis handler failed: %s", e, exc_info=True)
            return PhaseResult.fail(f"Synthesis failed: {e}")

    def _extract_deterministic_metrics(
        self,
        anonymized_validations: list[Any],
    ) -> str:
        """Extract deterministic metrics from validation reports.

        Parses each validation report to extract scores, issue counts,
        and other metrics that can be calculated without LLM judgment.

        Args:
            anonymized_validations: List of AnonymizedValidation objects.

        Returns:
            Formatted markdown header with deterministic metrics.
            Returns empty string if extraction fails.

        """
        try:
            # Extract metrics from each validation
            validator_metrics = [
                extract_validator_metrics(v.content, v.validator_id) for v in anonymized_validations
            ]

            # Calculate aggregate metrics
            aggregate = calculate_aggregate_metrics(validator_metrics)

            # Format as markdown header
            header = format_deterministic_metrics_header(aggregate)

            logger.info(
                "Extracted deterministic metrics: %d validators, avg evidence score %.1f",
                aggregate.validator_count,
                aggregate.evidence_score_avg or 0,
            )

            return header

        except Exception as e:
            logger.warning(
                "Failed to extract deterministic metrics: %s",
                e,
                exc_info=True,
            )
            return ""

    def _save_synthesizer_record(
        self,
        synthesis_output: str,
        epic_num: EpicId,
        story_num: int,
        story_title: str,
        start_time: datetime,
        end_time: datetime,
        input_tokens: int,
        output_tokens: int,
        validator_count: int,
    ) -> None:
        """Extract metrics and save synthesizer evaluation record.

        Story 13.6: Synthesizer Schema Integration

        Creates and saves an LLMEvaluationRecord for the synthesizer
        with extracted quality and consensus metrics.

        Args:
            synthesis_output: Raw synthesis LLM output.
            epic_num: Epic number.
            story_num: Story number within epic.
            story_title: Story title/key.
            start_time: Synthesis start time (UTC).
            end_time: Synthesis end time (UTC).
            input_tokens: Input token count.
            output_tokens: Output token count.
            validator_count: Number of validators (for sequence_position).

        """
        from bmad_assist.benchmarking import PatchInfo, StoryInfo, WorkflowInfo
        from bmad_assist.benchmarking.storage import get_benchmark_base_dir, save_evaluation_record
        from bmad_assist.validation.benchmarking_integration import (
            create_synthesizer_record,
            should_collect_benchmarking,
        )

        # Check if benchmarking is enabled (use self.config from handler)
        if not should_collect_benchmarking(self.config):
            logger.debug("Benchmarking disabled, skipping synthesizer record")
            return

        try:
            # Create workflow info
            workflow_info = WorkflowInfo(
                id="validate-story-synthesis",
                version="1.0.0",
                variant="default",
                patch=PatchInfo(applied=True),  # Synthesis always uses patch
            )

            # Create story info
            story_info = StoryInfo(
                epic_num=epic_num,
                story_num=story_num,
                title=story_title,
                complexity_flags={},
            )

            # Create synthesizer record
            record = create_synthesizer_record(
                synthesis_output=synthesis_output,
                workflow_info=workflow_info,
                story_info=story_info,
                provider=self.get_provider().provider_name,
                model=self.get_model() or "unknown",
                start_time=start_time,
                end_time=end_time,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                validator_count=validator_count,
            )

            # Get base directory for storage
            # CRITICAL: Use centralized path utility, not get_paths() singleton!
            # get_paths() is initialized for CLI working directory, but records
            # must be saved to the TARGET project directory.
            base_dir = get_benchmark_base_dir(self.project_path)

            # Save record
            record_path = save_evaluation_record(record, base_dir)
            logger.info("Saved synthesizer evaluation record: %s", record_path)

        except Exception as e:
            # Log but don't fail synthesis phase due to benchmarking error
            logger.warning(
                "Failed to save synthesizer evaluation record: %s",
                e,
                exc_info=True,
            )
