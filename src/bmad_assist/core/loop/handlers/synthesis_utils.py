"""Shared utility functions for the synthesis compression pipeline.

Provides core functions used by both CodeReviewSynthesisHandler and
ValidateStorySynthesisHandler to implement adaptive synthesis prompt
compression. The pipeline has three steps:

- Step 0: Context trimming (drop source files when base context is large)
- Step 1: Batched pre-extraction (extract structured findings from raw reviews)
- Step 2: Progressive synthesis (synthesize in batches with meta-synthesis)

These utilities are agnostic to review vs. validation semantics -- handlers
pass in data and receive processed AnonymizedValidation instances back.

See tech-spec: adaptive-synthesis-prompt-compression for full design details.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.compiler.shared_utils import estimate_tokens
from bmad_assist.validation.anonymizer import AnonymizedValidation

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Placeholder token estimates for components that are dynamically loaded
# by the compiler but whose size we need to approximate for budgeting.
_SECURITY_PLACEHOLDER_TOKENS = 2000
_DV_PLACEHOLDER_TOKENS = 2000
_GIT_DIFF_CAP_TOKENS = 5000


def estimate_base_context_tokens(project_path: Path, config: Any, phase_name: str) -> int:
    """Estimate token count for base context (everything except reviews).

    Reads strategic doc files, antipattern files, and story file from
    configured project paths. Applies estimate_tokens() to each file's
    content and returns the total.

    For code_review_synthesis: includes strategic docs + antipatterns +
    story + security placeholder (~2K) + DV placeholder (~2K) + git diff
    cap (5K).

    For validate_story_synthesis: includes strategic docs + story + DV
    placeholder.

    Does NOT include source files (Step 0 target) or reviews (compression
    target).

    Args:
        project_path: Path to the project root directory.
        config: Application configuration (BmadAssistConfig or similar).
        phase_name: Phase name -- either "code_review_synthesis" or
            "validate_story_synthesis".

    Returns:
        Estimated token count for base context components.

    """
    total = 0

    # Read strategic context files from project_knowledge directory
    try:
        from bmad_assist.core.paths import get_paths

        paths = get_paths()
        project_knowledge = paths.project_knowledge
    except RuntimeError:
        project_knowledge = project_path / "docs"

    # Strategic docs: project-context.md and architecture.md
    for filename in ("project-context.md", "architecture.md"):
        filepath = project_knowledge / filename
        content = _safe_read(filepath)
        if content:
            total += estimate_tokens(content)

    # Story file -- try to find from state, but since we don't have state here,
    # use a heuristic estimate based on typical story file size (~3K tokens).
    # The actual story file path resolution depends on epic/story numbers
    # which are not available in this utility function's scope. We use
    # a conservative estimate instead.
    # In practice, story files are typically 8-15K chars (~2-4K tokens).
    total += 3000  # Conservative story file estimate

    if phase_name == "code_review_synthesis":
        # Antipatterns file
        antipatterns_path = project_path / ".bmad-assist" / "cache" / "antipatterns-code.md"
        content = _safe_read(antipatterns_path)
        if content:
            total += estimate_tokens(content)

        # Security findings placeholder
        total += _SECURITY_PLACEHOLDER_TOKENS

        # Deep Verify findings placeholder
        total += _DV_PLACEHOLDER_TOKENS

        # Git diff cap (compiler caps at 20K chars ~= 5K tokens)
        total += _GIT_DIFF_CAP_TOKENS

    elif phase_name == "validate_story_synthesis":
        # Deep Verify findings placeholder
        total += _DV_PLACEHOLDER_TOKENS

    return total


def estimate_synthesis_tokens(
    reviews: list[AnonymizedValidation],
    base_context_tokens: int,
    safety_factor: float,
) -> int:
    """Estimate total synthesis prompt tokens with safety factor.

    Args:
        reviews: List of anonymized reviews/validations.
        base_context_tokens: Pre-estimated base context token count.
        safety_factor: Multiplier on token estimates (e.g., 1.15).

    Returns:
        Total estimated token count after applying safety factor.

    """
    review_tokens = sum(estimate_tokens(r.content) for r in reviews)
    return int((review_tokens + base_context_tokens) * safety_factor)


def build_extraction_prompt(reviews: list[AnonymizedValidation], base_context_summary: str) -> str:
    """Build structured markdown extraction prompt for a single batch.

    Instructs the LLM to preserve all findings with severity and output
    structured markdown headings per reviewer. Output format follows
    ADR-4 (structured markdown, not JSON).

    Args:
        reviews: Batch of anonymized reviews to extract findings from.
        base_context_summary: Summary of base context for informed
            extraction (e.g., project description, key areas).

    Returns:
        Complete extraction prompt string.

    """
    lines = [
        "# Review Findings Extraction",
        "",
        "You are a technical review analyst. Extract ALL findings from the "
        "reviews below into a concise structured format.",
        "",
        "## Instructions",
        "",
        "For each reviewer's output:",
        "1. Preserve EVERY finding, issue, suggestion, and recommendation",
        "2. Maintain the original severity level (critical, error, warning, info)",
        "3. Keep code references (file paths, line numbers) intact",
        "4. Condense verbose explanations into concise descriptions",
        "5. Remove pleasantries, preambles, and repetitive context",
        "6. Do NOT add your own analysis or opinions",
        "7. Do NOT merge findings from different reviewers",
        "",
        "## Output Format",
        "",
        "Use this exact structure for each reviewer:",
        "",
        "```",
        "## {Reviewer ID}",
        "",
        "### Finding: {Title}",
        "**Severity:** {critical|error|warning|info}",
        "**File:** {path} (L{line})",
        "{Concise description of the finding}",
        "",
        "### Finding: {Title}",
        "...",
        "```",
        "",
    ]

    if base_context_summary:
        lines.extend(
            [
                "## Project Context",
                "",
                base_context_summary,
                "",
            ]
        )

    lines.extend(
        [
            "## Reviews to Extract",
            "",
        ]
    )

    for review in reviews:
        lines.extend(
            [
                f"### {review.validator_id}",
                "",
                review.content,
                "",
                "---",
                "",
            ]
        )

    return "\n".join(lines)


def validate_extraction_completeness(
    raw_reviews: list[AnonymizedValidation],
    extracted_reviews: list[AnonymizedValidation],
    log: logging.Logger,
) -> None:
    """Check extraction completeness using heading-count heuristic (FM-1).

    Counts markdown heading patterns (##, ###, **Issue**, **Finding**) in
    raw vs extracted content. Logs WARNING if extracted count < 80% of
    raw count.

    Does not raise -- this is an observability check only.

    Args:
        raw_reviews: Original unprocessed reviews.
        extracted_reviews: Reviews after LLM extraction.
        log: Logger instance for warning output.

    """
    raw_count = _count_heading_patterns(" ".join(r.content for r in raw_reviews))
    extracted_count = _count_heading_patterns(" ".join(r.content for r in extracted_reviews))

    if raw_count == 0:
        return

    ratio = extracted_count / raw_count
    if ratio < 0.8:
        log.warning(
            "Extraction completeness check: extracted %d/%d heading patterns "
            "(%.0f%%). Possible finding loss detected.",
            extracted_count,
            raw_count,
            ratio * 100,
        )
    else:
        log.info(
            "Extraction completeness check passed: %d/%d heading patterns (%.0f%%)",
            extracted_count,
            raw_count,
            ratio * 100,
        )


def pre_extract_reviews(
    reviews: list[AnonymizedValidation],
    batch_size: int,
    base_context_summary: str,
    invoke_fn: Callable[[str], str],
    log: logging.Logger,
    cache_dir: Path | None = None,
    session_id: str = "",
) -> list[AnonymizedValidation]:
    """Batch-extract structured findings from raw reviews via LLM (Step 1).

    Batches reviews into groups of batch_size and calls invoke_fn(prompt)
    per batch. Creates new AnonymizedValidation instances with extracted
    content for each review in successful batches.

    On batch failure: falls back to raw reviews for that batch with
    [RAW] prefix on validator_id (FM-4, FM-4a).

    Args:
        reviews: Raw anonymized reviews to extract from.
        batch_size: Number of reviews per extraction LLM call.
        base_context_summary: Project context summary for extraction prompt.
        invoke_fn: Callable that takes prompt string, returns LLM output.
            Raises RuntimeError on failure.
        log: Logger instance.
        cache_dir: Optional directory for saving prompts and results.
        session_id: Session identifier for cache file naming.

    Returns:
        List of AnonymizedValidation with extracted (or raw fallback)
        content. Same length as input.

    """
    result: list[AnonymizedValidation] = []

    # Split reviews into batches
    batches = _split_into_batches(reviews, batch_size)

    for batch_idx, batch in enumerate(batches):
        prompt = build_extraction_prompt(batch, base_context_summary)

        try:
            extracted_output = invoke_fn(prompt)

            # Save to cache if configured
            if cache_dir is not None:
                _save_cache_file(
                    cache_dir,
                    f"synthesis-extraction-{session_id}-batch-{batch_idx}.md",
                    prompt,
                    extracted_output,
                )

            # Parse extracted output and create new AnonymizedValidation instances
            extracted_batch = _parse_extraction_output(batch, extracted_output)

            # Validate extraction completeness (FM-1)
            validate_extraction_completeness(batch, extracted_batch, log)

            result.extend(extracted_batch)

            log.info(
                "Extraction batch %d: %d reviews processed successfully",
                batch_idx,
                len(batch),
            )

        except Exception as e:
            # FM-4: Fall back to raw reviews for failed batch
            log.warning(
                "Extraction batch %d failed, falling back to raw reviews: %s",
                batch_idx,
                e,
            )
            # FM-4a: Prefix failed reviews' validator_id with [RAW]
            for r in batch:
                result.append(dataclass_replace(r, validator_id=f"[RAW] {r.validator_id}"))

    return result


def progressive_synthesize(
    extracted_reviews: list[AnonymizedValidation],
    batch_size: int,
    base_context_summary: str,
    token_budget: int,
    invoke_fn: Callable[[str], str],
    log: logging.Logger,
    cache_dir: Path | None = None,
    session_id: str = "",
) -> list[AnonymizedValidation]:
    """Progressively synthesize extracted reviews in batches (Step 2).

    Synthesizes in batches, produces intermediates, and runs
    meta-synthesis if needed. Caps intermediates at token_budget * 0.4
    total (FM-6). Exactly two levels deep -- no recursion (ADR-5).

    Args:
        extracted_reviews: Pre-extracted reviews from Step 1.
        batch_size: Number of reviews per synthesis batch.
        base_context_summary: Project context summary.
        token_budget: Maximum token budget for final prompt.
        invoke_fn: Callable that takes prompt string, returns LLM output.
        log: Logger instance.
        cache_dir: Optional directory for saving prompts and results.
        session_id: Session identifier for cache file naming.

    Returns:
        Collapsed list of AnonymizedValidation:
        - Each batch produces one AnonymizedValidation with batch summary
        - If 2+ intermediates, runs meta-synthesis producing single result
        - On meta-synthesis failure (FM-10): returns intermediates directly

    """
    intermediate_cap = int(token_budget * 0.4)
    intermediates: list[AnonymizedValidation] = []

    batches = _split_into_batches(extracted_reviews, batch_size)

    for batch_idx, batch in enumerate(batches):
        # Build progressive synthesis prompt
        prompt = _build_progressive_prompt(batch, base_context_summary, batch_idx)

        try:
            batch_output = invoke_fn(prompt)

            # Save to cache if configured
            if cache_dir is not None:
                _save_cache_file(
                    cache_dir,
                    f"synthesis-progressive-{session_id}-batch-{batch_idx}.md",
                    prompt,
                    batch_output,
                )

            # Build reviewer range string (e.g., "A-E")
            reviewer_ids = [r.validator_id for r in batch]
            first_id = reviewer_ids[0].split()[-1] if reviewer_ids else "?"
            last_id = reviewer_ids[-1].split()[-1] if reviewer_ids else "?"

            intermediate = AnonymizedValidation(
                validator_id=f"Batch {batch_idx + 1} Findings (Reviewers {first_id}-{last_id})",
                content=batch_output,
                original_ref=f"progressive-batch-{batch_idx + 1}",
            )
            intermediates.append(intermediate)

            log.info(
                "Progressive batch %d: synthesized %d reviews",
                batch_idx,
                len(batch),
            )

        except Exception as e:
            log.warning(
                "Progressive synthesis batch %d failed: %s. Including extracted reviews directly.",
                batch_idx,
                e,
            )
            # On batch failure, include extracted reviews directly
            intermediates.extend(batch)

    # FM-6: Cap intermediates at token_budget * 0.4
    intermediates = _cap_intermediates(intermediates, intermediate_cap, log)

    # If only one intermediate, return it directly (no meta-synthesis needed)
    if len(intermediates) <= 1:
        return intermediates

    # Meta-synthesis: combine all intermediates
    total_reviewers = len(extracted_reviews)

    try:
        meta_prompt = _build_meta_synthesis_prompt(
            intermediates, base_context_summary, total_reviewers
        )

        meta_output = invoke_fn(meta_prompt)

        # Save to cache if configured
        if cache_dir is not None:
            _save_cache_file(
                cache_dir,
                f"synthesis-meta-{session_id}.md",
                meta_prompt,
                meta_output,
            )

        log.info(
            "Meta-synthesis completed: consolidated %d intermediates from %d reviewers",
            len(intermediates),
            total_reviewers,
        )

        return [
            AnonymizedValidation(
                validator_id=f"Consolidated Findings ({total_reviewers} reviewers)",
                content=meta_output,
                original_ref="meta-synthesis",
            )
        ]

    except Exception as e:
        # FM-10: Fall back to batch intermediates on meta-synthesis failure
        log.warning(
            "Meta-synthesis failed, returning %d batch intermediates: %s",
            len(intermediates),
            e,
        )
        return intermediates


def decide_compression_steps(
    total_tokens: int,
    base_tokens: int,
    token_budget: int,
    base_context_limit: int,
) -> list[str]:
    """Decide which compression steps to apply.

    Pure function that returns an ordered list of steps based on token
    estimates. Step 2 is NEVER pre-decided -- it is determined after
    Step 1 re-estimation.

    Args:
        total_tokens: Total estimated tokens (reviews + base context)
            with safety factor already applied.
        base_tokens: Estimated base context tokens.
        token_budget: Maximum allowed token budget.
        base_context_limit: Threshold for Step 0 (source file trimming).

    Returns:
        Ordered list of step identifiers: e.g., ["step0", "step1"],
        ["step1"], or [] (passthrough).

    """
    steps: list[str] = []

    # Step 0: source file trimming when base context is too large
    if base_tokens > base_context_limit:
        steps.append("step0")

    # Step 1: pre-extraction when total exceeds budget
    if total_tokens > token_budget:
        steps.append("step1")

    return steps


# =============================================================================
# Private Helper Functions
# =============================================================================


def _safe_read(filepath: Path) -> str:
    """Safely read file content, returning empty string on any error.

    Args:
        filepath: Path to the file.

    Returns:
        File content or empty string if file doesn't exist or can't be read.

    """
    try:
        return filepath.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""


def _count_heading_patterns(content: str) -> int:
    """Count markdown heading and finding patterns in content.

    Counts occurrences of:
    - ## and ### headings
    - **Issue** and **Finding** bold patterns

    Args:
        content: Text content to analyze.

    Returns:
        Total count of heading/finding patterns.

    """
    patterns = [
        r"^#{2,3}\s+",  # ## and ### headings
        r"\*\*Issue\*\*",  # **Issue** bold pattern
        r"\*\*Finding\*\*",  # **Finding** bold pattern
    ]
    count = 0
    for pattern in patterns:
        count += len(re.findall(pattern, content, re.MULTILINE))
    return count


def _split_into_batches(
    items: list[AnonymizedValidation], batch_size: int
) -> list[list[AnonymizedValidation]]:
    """Split a list into batches of specified size.

    Args:
        items: List to split.
        batch_size: Maximum items per batch.

    Returns:
        List of batches (each a list of AnonymizedValidation).

    """
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def _parse_extraction_output(
    original_reviews: list[AnonymizedValidation],
    extracted_output: str,
) -> list[AnonymizedValidation]:
    """Parse LLM extraction output and create new AnonymizedValidation instances.

    Attempts to split the extraction output by reviewer sections. If
    parsing fails, assigns the full output to each review proportionally.

    Args:
        original_reviews: Original reviews that were extracted.
        extracted_output: Raw LLM output with extracted findings.

    Returns:
        New AnonymizedValidation instances with extracted content.

    """
    # Try to split output by reviewer sections (## Validator/Reviewer X headers)
    sections = re.split(
        r"(?=^## (?:Validator|Reviewer)\s+)",
        extracted_output,
        flags=re.MULTILINE,
    )
    # Filter out empty sections
    sections = [s.strip() for s in sections if s.strip()]

    if len(sections) == len(original_reviews):
        # Clean split -- map sections to reviews
        return [
            dataclass_replace(review, content=section)
            for review, section in zip(original_reviews, sections, strict=True)
        ]

    # Fallback: assign entire extracted output to each review
    # This preserves all findings even if parsing couldn't split by reviewer
    per_review_content = extracted_output.strip()
    if len(original_reviews) == 1:
        return [dataclass_replace(original_reviews[0], content=per_review_content)]

    # Multiple reviews but couldn't parse sections: assign full output
    # to first review, empty extracted marker to others
    result = []
    for i, review in enumerate(original_reviews):
        if i == 0:
            result.append(dataclass_replace(review, content=per_review_content))
        else:
            result.append(
                dataclass_replace(
                    review,
                    content=f"(See {original_reviews[0].validator_id} for consolidated extraction)",
                )
            )
    return result


def _build_progressive_prompt(
    batch: list[AnonymizedValidation],
    base_context_summary: str,
    batch_idx: int,
) -> str:
    """Build prompt for progressive synthesis of a single batch.

    Args:
        batch: Reviews in this synthesis batch.
        base_context_summary: Project context summary.
        batch_idx: Zero-based batch index.

    Returns:
        Progressive synthesis prompt string.

    """
    lines = [
        "# Batch Synthesis",
        "",
        f"Synthesize the findings from the following {len(batch)} "
        "reviewer outputs into a consolidated summary.",
        "",
        "## Instructions",
        "",
        "1. Merge duplicate or overlapping findings across reviewers",
        "2. Preserve ALL unique findings with their severity levels",
        "3. Maintain code references (file paths, line numbers)",
        "4. Group findings by severity (critical > error > warning > info)",
        "5. For findings reported by multiple reviewers, note the consensus",
        "6. Output structured markdown with clear headings",
        "",
    ]

    if base_context_summary:
        lines.extend(
            [
                "## Project Context",
                "",
                base_context_summary,
                "",
            ]
        )

    lines.extend(
        [
            f"## Batch {batch_idx + 1} Reviews",
            "",
        ]
    )

    for review in batch:
        lines.extend(
            [
                f"### {review.validator_id}",
                "",
                review.content,
                "",
                "---",
                "",
            ]
        )

    return "\n".join(lines)


def _build_meta_synthesis_prompt(
    intermediates: list[AnonymizedValidation],
    base_context_summary: str,
    total_reviewers: int,
) -> str:
    """Build prompt for meta-synthesis of batch intermediates.

    Args:
        intermediates: Batch synthesis intermediates.
        base_context_summary: Project context summary.
        total_reviewers: Total number of original reviewers.

    Returns:
        Meta-synthesis prompt string.

    """
    lines = [
        "# Meta-Synthesis: Consolidated Review Findings",
        "",
        f"You are synthesizing findings from {total_reviewers} reviewers "
        f"that were pre-processed in {len(intermediates)} batches.",
        "",
        "## Instructions",
        "",
        "1. Merge matching issues that appear across batch summaries -- "
        "these represent multi-reviewer consensus and should be "
        "highlighted as high-confidence findings",
        "2. Preserve ALL unique findings from each batch",
        "3. Maintain severity levels (critical > error > warning > info)",
        "4. Group the final output by severity, then by topic/component",
        "5. For each finding, note how many reviewers flagged it",
        "6. Output structured markdown",
        "",
    ]

    if base_context_summary:
        lines.extend(
            [
                "## Project Context",
                "",
                base_context_summary,
                "",
            ]
        )

    lines.extend(
        [
            "## Batch Summaries",
            "",
        ]
    )

    for intermediate in intermediates:
        lines.extend(
            [
                f"### {intermediate.validator_id}",
                "",
                intermediate.content,
                "",
                "---",
                "",
            ]
        )

    return "\n".join(lines)


def _cap_intermediates(
    intermediates: list[AnonymizedValidation],
    cap_tokens: int,
    log: logging.Logger,
) -> list[AnonymizedValidation]:
    """Cap intermediate token total at the specified limit (FM-6).

    If intermediates exceed the cap, truncates oldest batch intermediates
    proportionally to fit within budget.

    Args:
        intermediates: List of batch intermediate results.
        cap_tokens: Maximum allowed tokens for all intermediates.
        log: Logger instance.

    Returns:
        Intermediates list, potentially with truncated content.

    """
    total = sum(estimate_tokens(i.content) for i in intermediates)

    if total <= cap_tokens or cap_tokens <= 0:
        return intermediates

    log.warning(
        "Intermediates total %d tokens exceeds cap %d. Truncating proportionally.",
        total,
        cap_tokens,
    )

    # Proportional truncation: each intermediate gets its fair share
    ratio = cap_tokens / total
    result = []
    for intermediate in intermediates:
        current_tokens = estimate_tokens(intermediate.content)
        allowed_tokens = int(current_tokens * ratio)
        # Convert back to approximate char count (tokens * 4)
        allowed_chars = allowed_tokens * 4
        if allowed_chars < len(intermediate.content):
            truncated_content = (
                intermediate.content[:allowed_chars] + "\n\n[... truncated to fit token budget ...]"
            )
            result.append(dataclass_replace(intermediate, content=truncated_content))
        else:
            result.append(intermediate)

    return result


def _save_cache_file(
    cache_dir: Path,
    filename: str,
    prompt: str,
    result: str,
) -> None:
    """Save extraction/synthesis prompt and result to cache file.

    Args:
        cache_dir: Directory to save the cache file in.
        filename: Name of the cache file.
        prompt: The prompt that was sent.
        result: The LLM result.

    """
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        filepath = cache_dir / filename
        content = f"# Prompt\n\n{prompt}\n\n---\n\n# Result\n\n{result}\n"
        filepath.write_text(content, encoding="utf-8")
        logger.debug("Saved cache file: %s", filepath)
    except OSError as e:
        logger.warning("Failed to save cache file %s: %s", filename, e)
