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
        # Story 26.16: Also loads Deep Verify result
        try:
            anonymized_validations, _, _evidence_score, dv_data = load_validations_for_synthesis(
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

        # === Adaptive Synthesis Prompt Compression Pipeline ===
        import math
        import time

        from bmad_assist.core.loop.handlers.synthesis_utils import (
            decide_compression_steps,
            estimate_base_context_tokens,
            estimate_synthesis_tokens,
            pre_extract_reviews,
            progressive_synthesize,
        )
        from bmad_assist.core.retry import invoke_with_timeout_retry
        from bmad_assist.providers.registry import get_provider

        synthesis_config = self.config.compiler.synthesis
        base_tokens = estimate_base_context_tokens(
            self.project_path, self.config, "validate_story_synthesis"
        )
        total_tokens = estimate_synthesis_tokens(
            anonymized_validations, base_tokens, synthesis_config.safety_factor
        )
        steps = decide_compression_steps(
            total_tokens,
            base_tokens,
            synthesis_config.token_budget,
            synthesis_config.base_context_limit,
        )

        skip_source_files = False
        compression_start = time.monotonic()
        original_token_estimate = total_tokens
        extraction_llm_calls = 0
        validations_to_use = anonymized_validations

        if steps:
            logger.info(
                "Compression pipeline: steps=%s, total=%d, budget=%d, base=%d",
                steps,
                total_tokens,
                synthesis_config.token_budget,
                base_tokens,
            )

            if "step0" in steps:
                skip_source_files = True
                base_tokens = max(base_tokens - 5000, 0)
                total_tokens = estimate_synthesis_tokens(
                    anonymized_validations, base_tokens, synthesis_config.safety_factor
                )
                logger.info("Step 0: skip_source_files, revised total=%d", total_tokens)

            if "step1" in steps:
                # Provider resolution: extraction_provider > helper > master
                if synthesis_config.extraction_provider:
                    ext_provider = get_provider(synthesis_config.extraction_provider)
                    ext_model = synthesis_config.extraction_model or (
                        self.config.providers.helper.model
                        if self.config.providers.helper
                        else self.config.providers.master.model
                    )
                elif self.config.providers.helper:
                    ext_provider = get_provider(self.config.providers.helper.provider)
                    ext_model = (
                        synthesis_config.extraction_model or self.config.providers.helper.model
                    )
                else:
                    ext_provider = get_provider(self.config.providers.master.provider)
                    ext_model = (
                        synthesis_config.extraction_model or self.config.providers.master.model
                    )

                expected_calls = (
                    math.ceil(len(anonymized_validations) / synthesis_config.extraction_batch_size)
                    + 2
                )
                per_call_timeout = max(
                    synthesis_config.max_compression_timeout // max(expected_calls, 1),
                    30,
                )

                def invoke_fn(prompt: str) -> str:
                    res = invoke_with_timeout_retry(
                        ext_provider.invoke,
                        timeout_retries=1,
                        phase_name=f"{self.phase_name}_extraction",
                        prompt=prompt,
                        model=ext_model,
                        timeout=per_call_timeout,
                        disable_tools=True,
                        cwd=self.project_path,
                    )
                    if res.exit_code != 0:
                        raise RuntimeError(
                            f"Extraction failed: {res.stderr[:200] if res.stderr else 'unknown'}"
                        )
                    return res.stdout

                cache_dir = self.project_path / ".bmad-assist" / "cache"
                validations_to_use = pre_extract_reviews(
                    reviews=anonymized_validations,
                    batch_size=synthesis_config.extraction_batch_size,
                    base_context_summary=f"Project at {self.project_path.name}",
                    invoke_fn=invoke_fn,
                    log=logger,
                    cache_dir=cache_dir,
                    session_id=session_id,
                )
                extraction_llm_calls = math.ceil(
                    len(anonymized_validations) / synthesis_config.extraction_batch_size
                )

                total_tokens = estimate_synthesis_tokens(
                    validations_to_use, base_tokens, synthesis_config.safety_factor
                )
                logger.info(
                    "Step 1: %d validations in %d batches, revised total=%d",
                    len(validations_to_use),
                    extraction_llm_calls,
                    total_tokens,
                )

                elapsed = time.monotonic() - compression_start
                if elapsed > synthesis_config.max_compression_timeout:
                    logger.warning(
                        "Compression timeout after Step 1 (%.1fs > %ds)",
                        elapsed,
                        synthesis_config.max_compression_timeout,
                    )
                elif total_tokens > synthesis_config.token_budget:
                    validations_to_use = progressive_synthesize(
                        extracted_reviews=validations_to_use,
                        batch_size=synthesis_config.progressive_batch_size,
                        base_context_summary=f"Project at {self.project_path.name}",
                        token_budget=synthesis_config.token_budget,
                        invoke_fn=invoke_fn,
                        log=logger,
                        cache_dir=cache_dir,
                        session_id=session_id,
                    )
                    prog_calls = (
                        math.ceil(
                            len(anonymized_validations) / synthesis_config.progressive_batch_size
                        )
                        + 1
                    )
                    extraction_llm_calls += prog_calls
                    total_tokens = estimate_synthesis_tokens(
                        validations_to_use, base_tokens, synthesis_config.safety_factor
                    )
                    logger.info("Step 2: progressive synthesis, final=%d", total_tokens)
        else:
            logger.info(
                "Compression: passthrough (total=%d <= budget=%d)",
                total_tokens,
                synthesis_config.token_budget,
            )

        compression_end = time.monotonic()
        self._compressed_reviews = validations_to_use
        self._compression_metrics: dict[str, object] = {
            "compression_steps_applied": steps,
            "original_token_estimate": original_token_estimate,
            "compressed_token_estimate": total_tokens,
            "extraction_llm_calls": extraction_llm_calls,
            "extraction_duration_ms": int((compression_end - compression_start) * 1000),
        }

        # Get configured paths
        paths = get_paths()

        # Build compiler context with (possibly compressed) validations
        # Use get_original_cwd() to preserve original CWD when running as subprocess
        # Story 26.16: Include Deep Verify findings in synthesis context
        resolved_vars: dict[str, Any] = {
            "epic_num": epic_num,
            "story_num": story_num,
            "session_id": session_id,
            "anonymized_validations": validations_to_use,
            "skip_source_files": skip_source_files,
        }

        # Add DV findings to synthesis context if available
        if dv_data is not None:
            from bmad_assist.deep_verify.core.types import serialize_validation_result

            resolved_vars["deep_verify_findings"] = serialize_validation_result(dv_data)
            logger.debug(
                "Including Deep Verify findings in synthesis: verdict=%s, findings=%d",
                dv_data.verdict.value,
                len(dv_data.findings),
            )

        context = CompilerContext(
            project_root=self.project_path,
            output_folder=paths.implementation_artifacts,
            project_knowledge=paths.project_knowledge,
            cwd=get_original_cwd(),
            resolved_variables=resolved_vars,
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
            # Story 26.16: Also loads Deep Verify result
            anonymized_validations, failed_validators, evidence_score_data, _dv_data = (
                load_validations_for_synthesis(  # noqa: E501
                    session_id,
                    self.project_path,
                )
            )
            validators_used = [v.validator_id for v in anonymized_validations]

            # Render prompt with validations
            prompt = self.render_prompt(state)

            # Save prompt to .bmad-assist/prompts/ (atomic write, always saved)
            save_prompt(self.project_path, epic_num, story_num, self.phase_name, prompt)

            # Record start time for benchmarking
            start_time = datetime.now(UTC)

            # Invoke Master LLM
            result = self.invoke_provider(prompt)

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

                # Guard against silent provider failure: if provider returns
                # exit_code=0 but empty/minimal output, synthesis is useless.
                # A real synthesis has thousands of chars (issues, verdicts, changes).
                min_synthesis_chars = 200
                if len(extracted_synthesis.strip()) < min_synthesis_chars:
                    logger.error(
                        "Synthesis output too short (%d chars, min %d). "
                        "Provider returned exit_code=0 but produced no meaningful synthesis. "
                        "Raw stdout (%d chars): %.500s",
                        len(extracted_synthesis.strip()),
                        min_synthesis_chars,
                        len(result.stdout),
                        result.stdout[:500] if result.stdout else "(empty)",
                    )
                    return PhaseResult.fail(
                        f"Synthesis failed: provider returned empty/minimal output "
                        f"({len(extracted_synthesis.strip())} chars, "
                        f"duration={result.duration_ms}ms). "
                        f"Check provider config and model availability."
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

            # Add compression metrics if available
            compression_metrics = getattr(self, "_compression_metrics", None)
            if compression_metrics:
                custom: dict[str, object] = {
                    "phase": "validate-story-synthesis",
                    "validator_count": validator_count,
                }
                custom.update(compression_metrics)
                if record.custom is not None:
                    custom = {**record.custom, **custom}
                record = record.model_copy(update={"custom": custom})

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
