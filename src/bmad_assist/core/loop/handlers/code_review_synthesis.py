"""CODE_REVIEW_SYNTHESIS phase handler.

Master LLM synthesizes Multi-LLM code review reports.

Story 13.10: Code Review Benchmarking Integration

This handler:
1. Loads anonymized code reviews from previous phase (via file cache)
2. Compiles code-review-synthesis workflow with reviews injected
3. Invokes Master LLM to synthesize findings
4. Master LLM applies changes directly to story file
5. Extracts metrics and saves synthesizer evaluation record

The synthesis phase receives anonymized reviewer outputs and
has write permission to modify the story file.

"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bmad_assist.code_review.orchestrator import (
    CODE_REVIEW_SYNTHESIS_WORKFLOW_ID,
    CodeReviewError,
    load_reviews_for_synthesis,
)
from bmad_assist.compiler import compile_workflow
from bmad_assist.compiler.types import CompilerContext
from bmad_assist.core.config import get_phase_timeout
from bmad_assist.core.exceptions import ConfigError
from bmad_assist.core.io import get_original_cwd
from bmad_assist.core.loop.handlers.base import BaseHandler, check_for_edit_failures
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.core.types import EpicId
from bmad_assist.validation.reports import extract_synthesis_report

logger = logging.getLogger(__name__)


class CodeReviewSynthesisHandler(BaseHandler):
    """Handler for CODE_REVIEW_SYNTHESIS phase.

    Invokes Master LLM to synthesize code review reports from
    multiple reviewers. Uses the code-review-synthesis
    workflow compiler.

    """

    @property
    def phase_name(self) -> str:
        """Returns the name of the phase."""
        return "code_review_synthesis"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for code_review_synthesis prompt template.

        Available variables: epic_num, story_num, story_id, project_path

        """
        return self._build_common_context(state)

    def _get_session_id_from_cache(self) -> str | None:
        """Find most recent code review session from cache.

        The session_id is saved to cache file after code review phase.
        Searches for the most recent code-reviews cache file.

        Returns:
            Session ID string or None if not found.

        """
        cache_dir = self.project_path / ".bmad-assist" / "cache"
        if not cache_dir.exists():
            return None

        # Find most recent code-reviews file
        def safe_mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except (OSError, FileNotFoundError):
                return 0.0  # Treat missing files as oldest

        review_files = sorted(
            cache_dir.glob("code-reviews-*.json"),
            key=safe_mtime,
            reverse=True,
        )

        if not review_files:
            return None

        # Extract session_id from filename
        latest_file = review_files[0]
        # Filename format: code-reviews-{session_id}.json
        session_id = latest_file.stem.replace("code-reviews-", "")

        logger.debug("Found latest code review session: %s", session_id)
        return session_id

    def render_prompt(self, state: State) -> str:
        """Render synthesis prompt with code review data.

        Overrides base render_prompt to use synthesis compiler
        with reviews injected.

        Args:
            state: Current loop state.

        Returns:
            Compiled prompt XML with code reviews.

        """
        # Get story info
        epic_num = state.current_epic
        story_num_str = self._extract_story_num(state.current_story)

        if epic_num is None or story_num_str is None:
            raise ConfigError("Cannot synthesize: missing epic_num or story_num in state")

        story_num = story_num_str  # Keep as str to support EpicId = int | str (TD-001)

        # Get session_id for loading reviews
        session_id = self._get_session_id_from_cache()
        if session_id is None:
            raise ConfigError(
                "Cannot synthesize: no code review session found. Run CODE_REVIEW phase first."
            )

        # Load anonymized reviews from cache
        try:
            # Story 22.7: load_reviews_for_synthesis now returns (reviews, failed_reviewers)
            # TIER 2: Also loads pre-calculated evidence_score
            anonymized_reviews, failed_reviewers, _evidence_score = load_reviews_for_synthesis(
                session_id,
                self.project_path,
            )
        except CodeReviewError as e:
            raise ConfigError(f"Cannot load code reviews: {e}") from e

        if not anonymized_reviews:
            raise ConfigError("No code reviews found for synthesis. Run CODE_REVIEW phase first.")

        logger.info(
            "Compiling synthesis for story %s.%s with %d code reviews (%d failed)",
            epic_num,
            story_num,
            len(anonymized_reviews),
            len(failed_reviewers),
        )

        # Get configured paths
        paths = get_paths()

        # Build compiler context with reviews
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
                "anonymized_reviews": anonymized_reviews,
                "failed_reviewers": failed_reviewers,  # AC #4: Include failed reviewers for LLM context
            },
        )

        # Compile synthesis workflow
        compiled = compile_workflow("code-review-synthesis", context)

        logger.info(
            "Synthesis prompt compiled: ~%d tokens",
            compiled.token_estimate,
        )

        return compiled.context

    def execute(self, state: State) -> PhaseResult:
        """Execute code review synthesis phase.

        Compiles synthesis workflow with code reviews and invokes
        Master LLM to synthesize findings and apply changes.

        After successful synthesis, extracts metrics and saves synthesizer
        evaluation record (Story 13.10).

        Args:
            state: Current loop state.

        Returns:
            PhaseResult with synthesis output.

        """
        from bmad_assist.core.io import save_prompt
        from bmad_assist.core.loop.interactive import get_debugger

        try:
            # Get story info for report saving
            epic_num = state.current_epic
            story_num_str = self._extract_story_num(state.current_story)

            if epic_num is None or story_num_str is None:
                raise ConfigError("Cannot synthesize: missing epic_num or story_num in state")

            story_num = story_num_str  # Keep as str to support EpicId = int | str (TD-001)

            # Get session_id and load reviews for report saving
            session_id = self._get_session_id_from_cache()
            if session_id is None:
                raise ConfigError(
                    "Cannot synthesize: no code review session found. Run CODE_REVIEW phase first."
                )

            # Load reviews with proper error handling (AC10)
            try:
                # Story 22.7: load_reviews_for_synthesis now returns (reviews, failed_reviewers)
                # TIER 2: Also loads pre-calculated evidence_score for synthesis context
                anonymized_reviews, failed_reviewers, evidence_score_data = load_reviews_for_synthesis(
                    session_id,
                    self.project_path,
                )
            except CodeReviewError as e:
                raise ConfigError(f"Cannot load code reviews: {e}") from e

            reviewers_used = [v.validator_id for v in anonymized_reviews]

            if failed_reviewers:
                logger.info(
                    "Synthesis includes %d failed reviewers: %s",
                    len(failed_reviewers),
                    ", ".join(failed_reviewers),
                )

            # Render prompt with reviews
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
                check_for_edit_failures(result.stdout, target_hint="source files")

                # Extract synthesis report using priority-based extraction
                # 1. Markers, 2. Summary header, 3. Full content
                extracted_synthesis = extract_synthesis_report(
                    result.stdout, synthesis_type="code_review"
                )

                # Save synthesis report to code-reviews directory
                paths = get_paths()
                reviews_dir = paths.code_reviews_dir
                reviews_dir.mkdir(parents=True, exist_ok=True)

                model = self.get_model() or "unknown"
                master_reviewer_id = f"master-{model}"
                self._save_synthesis_report(
                    content=extracted_synthesis,
                    master_reviewer_id=master_reviewer_id,
                    session_id=session_id,
                    reviewers_used=reviewers_used,
                    epic=epic_num,
                    story=story_num,
                    duration_ms=result.duration_ms or 0,
                    reviews_dir=reviews_dir,
                    failed_reviewers=failed_reviewers,  # Story 22.7: Include failed reviewers
                )

                # Extract antipatterns for dev-story (best-effort, non-blocking)
                try:
                    from bmad_assist.antipatterns import extract_and_append_antipatterns

                    extract_and_append_antipatterns(
                        synthesis_content=extracted_synthesis,
                        epic_id=epic_num,
                        story_id=f"{epic_num}-{story_num}",
                        antipattern_type="code",
                        project_path=self.project_path,
                        config=self.config,
                    )
                except Exception as e:
                    logger.warning("Antipatterns extraction failed (non-blocking): %s", e)

                # Story 13.10: Extract metrics and save synthesizer record
                # Estimate tokens from char count (~4 chars per token)
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
                    reviewer_count=len(reviewers_used),
                )

                phase_result = PhaseResult.ok(
                    {
                        "response": result.stdout,
                        "model": result.model,
                        "duration_ms": result.duration_ms,
                    }
                )

            # Interactive debug mode
            debugger = get_debugger()
            if debugger.is_enabled:
                result_summary = (
                    f"{'SUCCESS' if phase_result.success else 'FAILED'} - "
                    f"{len(result.stdout)} chars output"
                )
                continue_execution = debugger.run_debug_loop(
                    phase_name=self.phase_name,
                    result_summary=result_summary,
                    provider=self.get_provider(),
                    model=self.get_model(),
                    timeout=get_phase_timeout(self.config, self.phase_name),
                )
                if not continue_execution:
                    return PhaseResult.fail("User interrupted execution")

            return phase_result

        except ConfigError as e:
            logger.error("Synthesis config error: %s", e)
            return PhaseResult.fail(str(e))

        except Exception as e:
            logger.error("Synthesis handler failed: %s", e, exc_info=True)
            return PhaseResult.fail(f"Synthesis failed: {e}")

    def _save_synthesis_report(
        self,
        content: str,
        master_reviewer_id: str,
        session_id: str,
        reviewers_used: list[str],
        epic: EpicId,
        story: int | str,  # Support string story IDs (Story 22.7)
        duration_ms: int,
        reviews_dir: Path,
        failed_reviewers: list[str] | None = None,
    ) -> None:
        """Save code review synthesis report with YAML frontmatter.

        Story 22.7: File path includes timestamp for traceability.
        Pattern: synthesis-{epic}-{story}-{timestamp}.md
        Also includes failed_reviewers in frontmatter for AC #4.

        Args:
            content: Synthesis output content.
            master_reviewer_id: Master LLM identifier.
            session_id: Anonymization session ID.
            reviewers_used: List of reviewer IDs that contributed.
            epic: Epic number.
            story: Story number.
            duration_ms: Synthesis duration in milliseconds.
            reviews_dir: Directory to save report.
            failed_reviewers: Optional list of failed reviewer IDs.

        """
        import yaml

        from bmad_assist.core.io import get_timestamp

        # Build frontmatter
        timestamp = datetime.now(UTC)
        frontmatter = {
            "session_id": session_id,
            "master_reviewer": master_reviewer_id,
            "reviewers_used": reviewers_used,
            "failed_reviewers": failed_reviewers or [],  # Story 22.7: Track failed reviewers
            "epic": epic,
            "story": story,
            "duration_ms": duration_ms,
            "generated_at": timestamp.isoformat(),
        }

        # Build full content with frontmatter
        frontmatter_yaml = yaml.dump(
            frontmatter,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        full_content = f"---\n{frontmatter_yaml}---\n\n{content}"

        # Use centralized atomic_write with PID collision protection (Story 22.7)
        from bmad_assist.core.io import atomic_write

        timestamp_str = get_timestamp(timestamp)
        report_path = reviews_dir / f"synthesis-{epic}-{story}-{timestamp_str}.md"

        atomic_write(report_path, full_content)
        logger.info("Saved code review synthesis report: %s", report_path)

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
        reviewer_count: int,
    ) -> None:
        """Extract metrics and save synthesizer evaluation record.

        Story 13.10: Code Review Benchmarking Integration

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
            reviewer_count: Number of reviewers (for sequence_position).

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
            # Create workflow info with code-review-synthesis workflow ID
            # Use config.workflow_variant for proper propagation (AC5)
            # Note: Config.workflow_variant defaults to "default" via Pydantic
            workflow_info = WorkflowInfo(
                id=CODE_REVIEW_SYNTHESIS_WORKFLOW_ID,
                version="1.0.0",
                variant=self.config.workflow_variant,
                patch=PatchInfo(applied=True),  # Synthesis always uses patch
            )

            # Create story info
            story_info = StoryInfo(
                epic_num=epic_num,
                story_num=story_num,
                title=story_title,
                complexity_flags={},
            )

            # Get provider name (stable string, not object repr)
            provider_obj = self.get_provider()
            provider_name = (
                provider_obj.provider_name
                if hasattr(provider_obj, "provider_name")
                else self.config.providers.master.provider
            )

            # output_tokens is already estimated (chars // 4), use directly
            estimated_output_tokens = output_tokens if output_tokens > 0 else 0

            # Create synthesizer record
            record = create_synthesizer_record(
                synthesis_output=synthesis_output,
                workflow_info=workflow_info,
                story_info=story_info,
                provider=provider_name,
                model=self.get_model() or "unknown",
                start_time=start_time,
                end_time=end_time,
                input_tokens=input_tokens,
                output_tokens=estimated_output_tokens,
                validator_count=reviewer_count,
            )

            # Add phase-specific custom metrics
            custom: dict[str, object] = {
                "phase": "code-review-synthesis",
                "reviewer_count": reviewer_count,
            }
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
