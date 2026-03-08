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

import json
import logging
import re
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
from bmad_assist.core.exceptions import ConfigError
from bmad_assist.core.io import get_original_cwd
from bmad_assist.core.loop.handlers.base import BaseHandler, check_for_edit_failures
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State
from bmad_assist.core.types import EpicId
from bmad_assist.security.integration import load_security_findings_from_cache
from bmad_assist.core.loop.synthesis_contract import (
    ExtractionQuality,
    SynthesisDecision,
    make_synthesis_decision,
)
from bmad_assist.validation.reports import extract_synthesis_report

logger = logging.getLogger(__name__)

# Markers for structured resolution block in synthesis output
_RESOLUTION_START = "<!-- SYNTHESIS_RESOLUTION_START -->"
_RESOLUTION_END = "<!-- SYNTHESIS_RESOLUTION_END -->"

# Valid resolution values
VALID_RESOLUTIONS = frozenset({"resolved", "rework", "halt"})

# Integer count fields in the resolution block
_COUNT_FIELDS = (
    "verified_critical",
    "verified_high",
    "fixed_critical",
    "fixed_high",
    "remaining_critical",
    "remaining_high",
)

# Regex patterns for layered extraction (Layer 2 and 3)
_HEADER_RESOLUTION_RE = re.compile(
    r"^\s*resolution\s*:\s*(resolved|rework|halt)\s*$", re.IGNORECASE | re.MULTILINE
)
_HEADER_INT_RE = re.compile(
    r"^\s*(remaining_critical|remaining_high|fixed_critical|fixed_high"
    r"|verified_critical|verified_high)\s*:\s*(\d+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Semantic signals for Layer 3 (kept deliberately broad to catch paraphrases)
_SEMANTIC_RESOLVED_RE = re.compile(
    r"no remaining critical|all critical issues (have been )?fixed|"
    r"all issues (have been )?addressed|no remaining issues",
    re.IGNORECASE,
)
_SEMANTIC_REWORK_RE = re.compile(
    r"remaining critical issue|recommend rework|requires? rework|needs? rework|"
    r"critical issues? remain",
    re.IGNORECASE,
)
_SEMANTIC_HALT_RE = re.compile(
    r"cannot (reliably )?determine|unable to (reliably )?determine",
    re.IGNORECASE,
)


def _parse_marker_block(block: str) -> dict[str, Any] | None:
    """Parse key: value lines from a resolution block string.

    Returns validated dict or None on validation failure.
    """
    parsed: dict[str, Any] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key and value:
            parsed[key] = value

    resolution = parsed.get("resolution")
    if resolution not in VALID_RESOLUTIONS:
        logger.warning(
            "Invalid or missing resolution value in block: %r (valid: %s)",
            resolution,
            ", ".join(sorted(VALID_RESOLUTIONS)),
        )
        return None

    for field in _COUNT_FIELDS:
        raw = parsed.get(field)
        if raw is not None:
            try:
                val = int(raw)
                if val < 0:
                    logger.warning("Negative count for %s: %d", field, val)
                    return None
                parsed[field] = val
            except (ValueError, TypeError):
                logger.warning("Non-integer count for %s: %r", field, raw)
                return None

    # Cross-validate: override "resolved" if remaining counts contradict
    if parsed.get("resolution") == "resolved":
        remaining_critical = parsed.get("remaining_critical", 0)
        remaining_high = parsed.get("remaining_high", 0)
        if isinstance(remaining_critical, int) and remaining_critical > 0:
            logger.info(
                "Cross-validation override: resolution 'resolved' but "
                "remaining_critical=%d, overriding to 'rework'",
                remaining_critical,
            )
            parsed["resolution"] = "rework"
        elif isinstance(remaining_high, int) and remaining_high > 0:
            logger.info(
                "Cross-validation override: resolution 'resolved' but "
                "remaining_high=%d, overriding to 'rework'",
                remaining_high,
            )
            parsed["resolution"] = "rework"

    return parsed


def _extract_resolution_layered(
    stdout: str,
) -> tuple[dict[str, Any] | None, ExtractionQuality]:
    """Extract synthesis resolution using a three-layer strategy.

    Layer 1 — Exact markers (STRICT): search for SYNTHESIS_RESOLUTION_START/END.
    Layer 2 — Section header fallback (DEGRADED): scan for bare "resolution: X" lines.
    Layer 3 — Semantic fallback (DEGRADED): keyword signals → inferred resolution.

    Returns:
        (parsed_dict_or_None, ExtractionQuality)
    """
    # Layer 1: exact markers
    pattern = re.compile(
        re.escape(_RESOLUTION_START) + r"\s*(.*?)\s*" + re.escape(_RESOLUTION_END),
        re.DOTALL,
    )
    matches = pattern.findall(stdout)
    if matches:
        # Markers found — if the block is invalid, do NOT fall through to Layer 2.
        # Falling through when markers exist but have bad data would silently accept
        # garbage (e.g., negative counts) via the header scan.
        block = matches[-1].strip()
        if block:
            parsed = _parse_marker_block(block)
            if parsed is not None:
                return parsed, ExtractionQuality.STRICT
        logger.warning(
            "SYNTHESIS_RESOLUTION markers found but block is empty or invalid; "
            "treating as FAILED (not falling through to header fallback)"
        )
        return None, ExtractionQuality.FAILED

    # Layer 2: section header fallback (bare "resolution: X" key-value lines)
    res_match = _HEADER_RESOLUTION_RE.search(stdout)
    if res_match:
        resolution_str = res_match.group(1).lower()
        partial: dict[str, Any] = {"resolution": resolution_str}
        for m in _HEADER_INT_RE.finditer(stdout):
            partial[m.group(1).lower()] = int(m.group(2))

        # Apply same cross-validation as marker path
        if partial.get("resolution") == "resolved":
            remaining_critical = partial.get("remaining_critical", 0)
            remaining_high = partial.get("remaining_high", 0)
            if isinstance(remaining_critical, int) and remaining_critical > 0:
                partial["resolution"] = "rework"
            elif isinstance(remaining_high, int) and remaining_high > 0:
                partial["resolution"] = "rework"

        logger.info(
            "Resolution extracted via section header fallback: %s", partial.get("resolution")
        )
        return partial, ExtractionQuality.DEGRADED

    # Layer 3: semantic keyword fallback
    if _SEMANTIC_HALT_RE.search(stdout):
        logger.info("Resolution inferred via semantic fallback: halt")
        return {"resolution": "halt"}, ExtractionQuality.DEGRADED

    if _SEMANTIC_REWORK_RE.search(stdout):
        logger.info("Resolution inferred via semantic fallback: rework")
        return {"resolution": "rework"}, ExtractionQuality.DEGRADED

    if _SEMANTIC_RESOLVED_RE.search(stdout):
        logger.info("Resolution inferred via semantic fallback: resolved")
        return {"resolution": "resolved"}, ExtractionQuality.DEGRADED

    logger.warning(
        "All extraction layers failed: no markers, no key-value lines, no semantic signals "
        "(stdout_len=%d, preview=%.200s)",
        len(stdout),
        stdout[:200] if stdout else "(empty)",
    )
    return None, ExtractionQuality.FAILED


def extract_resolution(stdout: str) -> dict[str, Any] | None:
    """Extract structured resolution block from synthesis LLM output.

    Backward-compatible wrapper around the layered extraction.
    Callers that need ExtractionQuality should call _extract_resolution_layered() directly.

    Returns:
        Parsed dict with resolution and counts, or None if all layers fail.
    """
    parsed, _ = _extract_resolution_layered(stdout)
    return parsed


def compute_resolution(
    parsed: dict[str, Any] | None,
    evidence_verdict: str,
    evidence_score_data: dict[str, Any] | None = None,
) -> str:
    """Compute canonical resolution string (backward-compatible wrapper).

    Delegates to make_synthesis_decision() with STRICT quality assumption
    when parsed is not None (the old callers always called extract_resolution first,
    which only returned valid markers-based results).

    New code should call make_synthesis_decision() directly with ExtractionQuality.

    Returns:
        One of "resolved", "rework", or "halt".
    """
    quality = ExtractionQuality.STRICT if parsed is not None else ExtractionQuality.FAILED
    decision = make_synthesis_decision(parsed, quality, evidence_verdict, evidence_score_data)
    return decision.resolution.value


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

    def _get_dv_findings_from_cache(self, session_id: str) -> dict[str, Any] | None:
        """Load Deep Verify findings from cache with file_path injection.

        Story 26.20: Load DV findings for inclusion in synthesis prompt.

        Reads cache JSON files directly (same glob pattern as
        load_dv_findings_from_cache) to preserve the file_path metadata
        that would otherwise be discarded during deserialization. Injects
        file_path into each finding dict for grouped rendering.

        Args:
            session_id: The code review session ID.

        Returns:
            Dict with DV findings data (including file_path per finding)
            or None if not found/error.

        """
        try:
            cache_dir = self.project_path / ".bmad-assist" / "cache"
            if not cache_dir.exists():
                return None

            pattern = f"deep-verify-{session_id}-*.json"
            cache_files = list(cache_dir.glob(pattern))
            if not cache_files:
                logger.debug("DV findings cache not found for session: %s", session_id)
                return None

            all_findings: list[dict[str, Any]] = []
            all_domains: list[dict[str, Any]] = []
            all_methods: set[str] = set()
            worst_verdict: str | None = None
            min_score = 100.0
            verdict_rank = {"REJECT": 0, "UNCERTAIN": 1, "ACCEPT": 2}

            for cache_file in cache_files:
                with open(cache_file, encoding="utf-8") as f:
                    data = json.load(f)

                file_path = data.get("file_path")
                verdict = data.get("verdict", "ACCEPT")
                score = data.get("score", 100.0)

                # Track worst verdict (REJECT > UNCERTAIN > ACCEPT)
                if worst_verdict is None or verdict_rank.get(verdict, 2) < verdict_rank.get(
                    worst_verdict, 2
                ):
                    worst_verdict = verdict

                min_score = min(min_score, score)

                # Collect domains
                for d in data.get("domains_detected", []):
                    if isinstance(d, dict):
                        all_domains.append(d)

                # Collect methods
                for m in data.get("methods_executed", []):
                    all_methods.add(str(m))

                # Inject file_path into each finding
                for finding in data.get("findings", []):
                    if not isinstance(finding, dict):
                        continue
                    finding["file_path"] = file_path
                    all_findings.append(finding)

            if not all_findings and worst_verdict is None:
                return None

            findings_count = len(all_findings)
            critical_count = sum(1 for f in all_findings if f.get("severity") == "critical")
            error_count = sum(1 for f in all_findings if f.get("severity") == "error")

            return {
                "verdict": worst_verdict or "ACCEPT",
                "score": min_score,
                "findings_count": findings_count,
                "critical_count": critical_count,
                "error_count": error_count,
                "domains": all_domains,
                "methods": sorted(all_methods),
                "findings": all_findings,
            }
        except (OSError, json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.warning("Failed to load DV findings: %s", e)
            return None

    def _get_security_findings_from_cache(self, session_id: str) -> dict[str, Any] | None:
        """Load security findings from cache if available.

        Applies confidence filtering per config.security_agent.max_findings.

        Args:
            session_id: The code review session ID.

        Returns:
            Dict with security findings data or None if not found/error.

        """
        try:
            report = load_security_findings_from_cache(session_id, self.project_path)
            if report is None:
                return None

            # Apply confidence filtering
            max_findings = self.config.security_agent.max_findings
            filtered = report.filter_for_synthesis(
                min_confidence=0.5,
                max_findings=max_findings,
            )

            if not filtered and not report.timed_out and report.analysis_quality == "full":
                logger.debug("No security findings passed confidence filter")
                return None

            # Log severity breakdown
            high = sum(1 for f in filtered if f.severity.upper() == "HIGH")
            medium = sum(1 for f in filtered if f.severity.upper() == "MEDIUM")
            low = sum(1 for f in filtered if f.severity.upper() == "LOW")
            logger.info(
                "Security findings for synthesis: %d HIGH, %d MEDIUM, %d LOW "
                "(filtered from %d total)",
                high,
                medium,
                low,
                len(report.findings),
            )

            return {
                "findings": [
                    {
                        "id": f.id,
                        "file_path": f.file_path,
                        "line_number": f.line_number,
                        "cwe_id": f.cwe_id,
                        "severity": f.severity,
                        "title": f.title,
                        "description": f.description,
                        "remediation": f.remediation,
                        "confidence": f.confidence,
                    }
                    for f in filtered
                ],
                "languages_detected": report.languages_detected,
                "timed_out": report.timed_out,
                "analysis_quality": report.analysis_quality,
                "total_findings": len(report.findings),
                "filtered_count": len(filtered),
            }
        except (OSError, json.JSONDecodeError, KeyError, AttributeError, ValueError) as e:
            logger.warning("Failed to load security findings: %s", e)
            return None

    def _get_session_id_from_story_reports(
        self,
        epic_num: EpicId | None,
        story_num: str | None,
    ) -> str | None:
        """Find code review session from persisted report files for a story.

        This is resilient when `.bmad-assist/cache/code-reviews-*.json` is missing.
        """
        if epic_num is None or story_num is None:
            return None

        try:
            import frontmatter
        except Exception:
            return None

        review_dirs = [
            self.project_path / "_bmad-output" / "implementation-artifacts" / "code-reviews",
            self.project_path / "docs" / "sprint-artifacts" / "code-reviews",
            self.project_path / "docs" / "code-reviews",
        ]

        report_files: list[Path] = []
        pattern = f"code-review-{epic_num}-{story_num}-*.md"
        for review_dir in review_dirs:
            if review_dir.exists():
                report_files.extend(review_dir.glob(pattern))

        if not report_files:
            return None

        def safe_mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except (OSError, FileNotFoundError):
                return 0.0

        for report_path in sorted(report_files, key=safe_mtime, reverse=True):
            try:
                post = frontmatter.load(report_path, handler=frontmatter.YAMLHandler())
            except Exception:
                continue
            metadata = post.metadata if isinstance(post.metadata, dict) else {}
            session_id = str(metadata.get("session_id") or "").strip()
            if session_id:
                logger.debug(
                    "Recovered code review session from report for %s.%s: %s",
                    epic_num,
                    story_num,
                    session_id,
                )
                return session_id

        return None

    def _get_session_id_from_cache(
        self,
        epic_num: EpicId | None = None,
        story_num: str | None = None,
    ) -> str | None:
        """Find code review session id for synthesis.

        Resolution order:
        1. Story-specific persisted code-review reports (if epic/story provided)
        2. Most recent code-reviews cache JSON

        Returns:
            Session ID string or None if not found.

        """
        session_from_reports = self._get_session_id_from_story_reports(epic_num, story_num)
        if session_from_reports:
            return session_from_reports

        cache_dir = self.project_path / ".bmad-assist" / "cache"
        if not cache_dir.exists():
            return None

        # Find most recent code-reviews cache file
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
        session_id = self._get_session_id_from_cache(epic_num, story_num)
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

        # Load DV findings if available (Story 26.20)
        dv_findings = self._get_dv_findings_from_cache(session_id)
        if dv_findings:
            logger.info(
                "Including DV findings in synthesis: verdict=%s, findings=%d",
                dv_findings["verdict"],
                dv_findings["findings_count"],
            )

        # Load security findings if available
        security_findings = self._get_security_findings_from_cache(session_id)
        if security_findings:
            logger.info(
                "Including security findings in synthesis: %d findings (timed_out=%s)",
                security_findings["filtered_count"],
                security_findings["timed_out"],
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
            self.project_path, self.config, "code_review_synthesis"
        )
        total_tokens = estimate_synthesis_tokens(
            anonymized_reviews, base_tokens, synthesis_config.safety_factor
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
        reviews_to_use = anonymized_reviews

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
                    anonymized_reviews, base_tokens, synthesis_config.safety_factor
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
                    math.ceil(len(anonymized_reviews) / synthesis_config.extraction_batch_size) + 2
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
                reviews_to_use = pre_extract_reviews(
                    reviews=anonymized_reviews,
                    batch_size=synthesis_config.extraction_batch_size,
                    base_context_summary=f"Project at {self.project_path.name}",
                    invoke_fn=invoke_fn,
                    log=logger,
                    cache_dir=cache_dir,
                    session_id=session_id,
                )
                extraction_llm_calls = math.ceil(
                    len(anonymized_reviews) / synthesis_config.extraction_batch_size
                )

                total_tokens = estimate_synthesis_tokens(
                    reviews_to_use, base_tokens, synthesis_config.safety_factor
                )
                logger.info(
                    "Step 1: %d reviews in %d batches, revised total=%d",
                    len(reviews_to_use),
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
                    reviews_to_use = progressive_synthesize(
                        extracted_reviews=reviews_to_use,
                        batch_size=synthesis_config.progressive_batch_size,
                        base_context_summary=f"Project at {self.project_path.name}",
                        token_budget=synthesis_config.token_budget,
                        invoke_fn=invoke_fn,
                        log=logger,
                        cache_dir=cache_dir,
                        session_id=session_id,
                    )
                    prog_calls = (
                        math.ceil(len(anonymized_reviews) / synthesis_config.progressive_batch_size)
                        + 1
                    )
                    extraction_llm_calls += prog_calls
                    total_tokens = estimate_synthesis_tokens(
                        reviews_to_use, base_tokens, synthesis_config.safety_factor
                    )
                    logger.info("Step 2: progressive synthesis, final=%d", total_tokens)
        else:
            logger.info(
                "Compression: passthrough (total=%d <= budget=%d)",
                total_tokens,
                synthesis_config.token_budget,
            )

        compression_end = time.monotonic()
        self._compressed_reviews = reviews_to_use
        self._compression_metrics: dict[str, object] = {
            "compression_steps_applied": steps,
            "original_token_estimate": original_token_estimate,
            "compressed_token_estimate": total_tokens,
            "extraction_llm_calls": extraction_llm_calls,
            "extraction_duration_ms": int((compression_end - compression_start) * 1000),
        }

        # Get configured paths
        paths = get_paths()

        # Build compiler context with (possibly compressed) reviews
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
                "anonymized_reviews": reviews_to_use,
                "failed_reviewers": failed_reviewers,  # AC #4: Include failed reviewers for LLM context # noqa: E501
                "deep_verify_findings": dv_findings,  # Story 26.20: Include DV findings
                "security_findings": security_findings,  # Security agent findings
                "security_review_status": "TIMEOUT"
                if (security_findings and security_findings.get("timed_out"))
                else "",
                "skip_source_files": skip_source_files,
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

        try:
            # Get story info for report saving
            epic_num = state.current_epic
            story_num_str = self._extract_story_num(state.current_story)

            if epic_num is None or story_num_str is None:
                raise ConfigError("Cannot synthesize: missing epic_num or story_num in state")

            story_num = story_num_str  # Keep as str to support EpicId = int | str (TD-001)

            # Get session_id and load reviews for report saving
            session_id = self._get_session_id_from_cache(epic_num, story_num)
            if session_id is None:
                raise ConfigError(
                    "Cannot synthesize: no code review session found. Run CODE_REVIEW phase first."
                )

            # Load reviews with proper error handling (AC10)
            try:
                # Story 22.7: load_reviews_for_synthesis now returns (reviews, failed_reviewers)
                # TIER 2: Also loads pre-calculated evidence_score for synthesis context
                anonymized_reviews, failed_reviewers, evidence_score_data = (
                    load_reviews_for_synthesis(  # noqa: E501
                        session_id,
                        self.project_path,
                    )
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

            # Invoke Master LLM with restricted tools (file manipulation only)
            result = self.invoke_provider(
                prompt, allowed_tools=["Read", "Edit", "Write", "Bash"]
            )

            # Record end time for benchmarking
            end_time = datetime.now(UTC)

            # Check for errors
            if result.exit_code != 0:
                # Classify ToolCallGuard terminations as RETRYABLE so the runner
                # can attempt a bounded retry rather than hard-failing the phase.
                from bmad_assist.core.loop.synthesis_contract import FailureClass

                is_guard_termination = bool(
                    result.termination_reason
                    and result.termination_reason.startswith("guard:")
                )
                if is_guard_termination:
                    logger.warning(
                        "Synthesis terminated by ToolCallGuard: %s — classifying as RETRYABLE",
                        result.termination_reason,
                    )
                    phase_result = PhaseResult.ok(
                        {
                            "response": result.stdout or "",
                            "model": result.model,
                            "duration_ms": result.duration_ms,
                            "verdict": (
                                evidence_score_data.get("verdict", "UNKNOWN")
                                if evidence_score_data
                                else "UNKNOWN"
                            ),
                            "resolution": "halt",
                            "extraction_quality": ExtractionQuality.FAILED.value,
                            "failure_class": FailureClass.RETRYABLE.value,
                            "resolution_data": None,
                            "synthesis_report_path": None,
                        }
                    )
                else:
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

                # Guard against silent provider failure: if provider returns
                # exit_code=0 but empty/minimal output, synthesis is useless.
                min_synthesis_chars = 200
                if len(extracted_synthesis.strip()) < min_synthesis_chars:
                    logger.error(
                        "Code review synthesis output too short (%d chars, min %d). "
                        "Provider returned exit_code=0 but produced no meaningful synthesis. "
                        "Raw stdout (%d chars): %.500s",
                        len(extracted_synthesis.strip()),
                        min_synthesis_chars,
                        len(result.stdout),
                        result.stdout[:500] if result.stdout else "(empty)",
                    )
                    return PhaseResult.fail(
                        f"Code review synthesis failed: provider returned empty/minimal output "
                        f"({len(extracted_synthesis.strip())} chars, "
                        f"duration={result.duration_ms}ms). "
                        f"Check provider config and model availability."
                    )

                # Save synthesis report to code-reviews directory
                paths = get_paths()
                reviews_dir = paths.code_reviews_dir
                reviews_dir.mkdir(parents=True, exist_ok=True)

                model = self.get_model() or "unknown"
                master_reviewer_id = f"master-{model}"
                synthesis_report_path = self._save_synthesis_report(
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

                # Include evidence score verdict in outputs for rework loop decision
                verdict = (
                    evidence_score_data.get("verdict", "UNKNOWN")
                    if evidence_score_data
                    else "UNKNOWN"
                )

                # Extract synthesis-authoritative resolution from LLM output
                # using layered extraction (exact markers → headers → semantic)
                resolution_data, extraction_quality = _extract_resolution_layered(result.stdout)
                decision: SynthesisDecision = make_synthesis_decision(
                    resolution_data, extraction_quality, verdict, evidence_score_data
                )
                logger.info(
                    "Synthesis resolution: %s (quality=%s, evidence_verdict=%s, from_llm=%s)",
                    decision.resolution.value,
                    decision.extraction_quality.value,
                    verdict,
                    resolution_data is not None,
                )

                phase_result = PhaseResult.ok(
                    {
                        "response": result.stdout,
                        "model": result.model,
                        "duration_ms": result.duration_ms,
                        "verdict": verdict,
                        "resolution": decision.resolution.value,
                        "extraction_quality": decision.extraction_quality.value,
                        "failure_class": (
                            decision.failure_class.value if decision.failure_class else None
                        ),
                        "resolution_data": resolution_data,
                        "synthesis_report_path": str(synthesis_report_path),
                    }
                )

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
    ) -> Path:
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

        Returns:
            Path to the saved synthesis report file.

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
        return report_path

    def _save_synthesizer_record(
        self,
        synthesis_output: str,
        epic_num: EpicId,
        story_num: int | str,
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
            # Add compression metrics if available
            compression_metrics = getattr(self, "_compression_metrics", None)
            if compression_metrics:
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
