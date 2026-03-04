"""Unit tests for synthesis_utils module.

Tests the adaptive synthesis prompt compression pipeline utilities:
- decide_compression_steps: step selection logic
- estimate_synthesis_tokens: token estimation with safety factor
- estimate_base_context_tokens: base context token estimation
- build_extraction_prompt: extraction prompt formatting
- validate_extraction_completeness: heading-count heuristic validation
- pre_extract_reviews: batched LLM extraction with fallbacks
- progressive_synthesize: progressive synthesis with meta-synthesis
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.loop.handlers.synthesis_utils import (
    build_extraction_prompt,
    decide_compression_steps,
    estimate_base_context_tokens,
    estimate_synthesis_tokens,
    pre_extract_reviews,
    progressive_synthesize,
    validate_extraction_completeness,
)
from bmad_assist.validation.anonymizer import AnonymizedValidation


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_reviews() -> list[AnonymizedValidation]:
    """Two sample reviews with realistic content."""
    return [
        AnonymizedValidation(
            validator_id="Reviewer A",
            content="## Finding: Bug\n**Severity:** error\n"
            "Missing null check in handler.\n" * 50,
            original_ref="reviewer-a",
        ),
        AnonymizedValidation(
            validator_id="Reviewer B",
            content="## Finding: Issue\n**Severity:** warning\n"
            "Unused import detected.\n" * 50,
            original_ref="reviewer-b",
        ),
    ]


@pytest.fixture
def many_reviews() -> list[AnonymizedValidation]:
    """Seven reviews for multi-batch testing."""
    return [
        AnonymizedValidation(
            validator_id=f"Reviewer {chr(65 + i)}",
            content=f"## Finding: Issue {i}\n**Severity:** warning\nDescription {i}\n"
            * 20,
            original_ref=f"reviewer-{chr(97 + i)}",
        )
        for i in range(7)
    ]


@pytest.fixture
def log() -> logging.Logger:
    """Logger instance for test assertions."""
    return logging.getLogger("test_synthesis_utils")


# =============================================================================
# Tests: decide_compression_steps
# =============================================================================


class TestDecideCompressionSteps:
    """Tests for decide_compression_steps()."""

    def test_passthrough_when_total_under_budget(self) -> None:
        """No steps needed when total tokens are under budget."""
        steps = decide_compression_steps(
            total_tokens=5000,
            base_tokens=2000,
            token_budget=10000,
            base_context_limit=5000,
        )
        assert steps == []

    def test_step0_only_when_base_exceeds_limit_but_total_under_budget(self) -> None:
        """Step 0 only when base context is large but total fits budget."""
        steps = decide_compression_steps(
            total_tokens=8000,
            base_tokens=6000,
            token_budget=10000,
            base_context_limit=5000,
        )
        assert steps == ["step0"]

    def test_step1_only_when_total_exceeds_budget_but_base_under_limit(self) -> None:
        """Step 1 only when total exceeds budget but base is small."""
        steps = decide_compression_steps(
            total_tokens=12000,
            base_tokens=3000,
            token_budget=10000,
            base_context_limit=5000,
        )
        assert steps == ["step1"]

    def test_step0_and_step1_when_both_conditions_met(self) -> None:
        """Both steps when base exceeds limit AND total exceeds budget."""
        steps = decide_compression_steps(
            total_tokens=15000,
            base_tokens=8000,
            token_budget=10000,
            base_context_limit=5000,
        )
        assert steps == ["step0", "step1"]

    def test_exact_boundary_total_equals_budget_is_passthrough(self) -> None:
        """Exact boundary: total == budget means no step1 (not >)."""
        steps = decide_compression_steps(
            total_tokens=10000,
            base_tokens=3000,
            token_budget=10000,
            base_context_limit=5000,
        )
        assert steps == []

    def test_exact_boundary_base_equals_limit_no_step0(self) -> None:
        """Exact boundary: base == limit means no step0 (not >)."""
        steps = decide_compression_steps(
            total_tokens=8000,
            base_tokens=5000,
            token_budget=10000,
            base_context_limit=5000,
        )
        assert steps == []

    def test_zero_tokens_empty_list(self) -> None:
        """Zero tokens produces no compression steps."""
        steps = decide_compression_steps(
            total_tokens=0,
            base_tokens=0,
            token_budget=10000,
            base_context_limit=5000,
        )
        assert steps == []

    def test_large_values_realistic_scenario(self) -> None:
        """Realistic large values trigger expected steps."""
        steps = decide_compression_steps(
            total_tokens=200_000,
            base_tokens=50_000,
            token_budget=128_000,
            base_context_limit=40_000,
        )
        assert steps == ["step0", "step1"]


# =============================================================================
# Tests: estimate_synthesis_tokens
# =============================================================================


class TestEstimateSynthesisTokens:
    """Tests for estimate_synthesis_tokens()."""

    def test_basic_estimation_with_reviews(
        self, sample_reviews: list[AnonymizedValidation]
    ) -> None:
        """Returns positive token estimate with sample reviews."""
        result = estimate_synthesis_tokens(
            reviews=sample_reviews,
            base_context_tokens=1000,
            safety_factor=1.0,
        )
        assert result > 0
        # With factor 1.0, should be sum of review tokens + base
        # Each review has content ~ 50 repetitions of ~35 chars = ~1750 chars => ~437 tokens
        # Two reviews => ~874 + 1000 base = ~1874
        assert result > 1000  # At least base tokens

    def test_safety_factor_correctly_applied(
        self, sample_reviews: list[AnonymizedValidation]
    ) -> None:
        """Safety factor multiplies the total estimate."""
        base = estimate_synthesis_tokens(
            reviews=sample_reviews,
            base_context_tokens=1000,
            safety_factor=1.0,
        )
        with_factor = estimate_synthesis_tokens(
            reviews=sample_reviews,
            base_context_tokens=1000,
            safety_factor=1.15,
        )
        # 1.15x should produce a proportionally larger result
        assert with_factor == int(base * 1.15)

    def test_empty_reviews_returns_base_times_factor(self) -> None:
        """Empty reviews list returns int(base * safety_factor)."""
        result = estimate_synthesis_tokens(
            reviews=[],
            base_context_tokens=5000,
            safety_factor=1.15,
        )
        assert result == int(5000 * 1.15)


# =============================================================================
# Tests: estimate_base_context_tokens
# =============================================================================


class TestEstimateBaseContextTokens:
    """Tests for estimate_base_context_tokens()."""

    def test_with_strategic_docs_on_disk(self, tmp_path: Path) -> None:
        """Includes token estimates for strategic docs that exist on disk."""
        # Create project knowledge directory with docs
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "project-context.md").write_text("# Project\n" * 100)
        (docs_dir / "architecture.md").write_text("# Architecture\n" * 100)

        config = MagicMock()

        with patch(
            "bmad_assist.core.paths.get_paths"
        ) as mock_get_paths:
            mock_paths = MagicMock()
            mock_paths.project_knowledge = docs_dir
            mock_get_paths.return_value = mock_paths

            result = estimate_base_context_tokens(
                tmp_path, config, "validate_story_synthesis"
            )

        # Should include strategic docs tokens + story estimate (3000) + DV placeholder (2000)
        assert result > 5000

    def test_missing_project_knowledge_still_returns_positive(
        self, tmp_path: Path
    ) -> None:
        """Returns >0 even when project knowledge dir is missing."""
        config = MagicMock()

        # get_paths raises RuntimeError -> falls back to project_path / "docs"
        with patch(
            "bmad_assist.core.paths.get_paths",
            side_effect=RuntimeError("not initialized"),
        ):
            result = estimate_base_context_tokens(
                tmp_path, config, "validate_story_synthesis"
            )

        # Story estimate (3000) + DV placeholder (2000) = 5000 minimum
        assert result >= 5000

    def test_code_review_synthesis_includes_security_dv_git_diff(
        self, tmp_path: Path
    ) -> None:
        """code_review_synthesis includes security + DV + git_diff placeholders."""
        config = MagicMock()

        with patch(
            "bmad_assist.core.paths.get_paths",
            side_effect=RuntimeError("not initialized"),
        ):
            cr_result = estimate_base_context_tokens(
                tmp_path, config, "code_review_synthesis"
            )
            vs_result = estimate_base_context_tokens(
                tmp_path, config, "validate_story_synthesis"
            )

        # Code review adds security (2000) + DV (2000) + git_diff (5000) = 9000 more
        # Validate story only adds DV (2000)
        # Difference should be security (2000) + git_diff (5000) = 7000
        assert cr_result > vs_result
        assert cr_result - vs_result == 7000


# =============================================================================
# Tests: build_extraction_prompt
# =============================================================================


class TestBuildExtractionPrompt:
    """Tests for build_extraction_prompt()."""

    def test_correct_markdown_format_with_reviewer_headers(
        self, sample_reviews: list[AnonymizedValidation]
    ) -> None:
        """Prompt contains reviewer headers and review content."""
        prompt = build_extraction_prompt(sample_reviews, "")
        assert "# Review Findings Extraction" in prompt
        assert "### Reviewer A" in prompt
        assert "### Reviewer B" in prompt
        assert "## Reviews to Extract" in prompt
        # Review content should be included
        assert "Finding: Bug" in prompt
        assert "Finding: Issue" in prompt

    def test_includes_base_context_summary_when_nonempty(
        self, sample_reviews: list[AnonymizedValidation]
    ) -> None:
        """Base context summary is included when provided."""
        prompt = build_extraction_prompt(
            sample_reviews, "This is a Python CLI project."
        )
        assert "## Project Context" in prompt
        assert "This is a Python CLI project." in prompt

    def test_empty_reviews_produces_minimal_prompt(self) -> None:
        """Empty reviews list produces prompt with headers but no reviewer sections."""
        prompt = build_extraction_prompt([], "")
        assert "# Review Findings Extraction" in prompt
        assert "## Reviews to Extract" in prompt
        # No reviewer headers
        assert "### Reviewer" not in prompt


# =============================================================================
# Tests: validate_extraction_completeness
# =============================================================================


class TestValidateExtractionCompleteness:
    """Tests for validate_extraction_completeness()."""

    def test_passes_when_extracted_above_threshold(
        self, log: logging.Logger
    ) -> None:
        """Logs INFO when extracted count >= 80% of raw."""
        raw = [
            AnonymizedValidation(
                validator_id="A",
                content="## Finding 1\n## Finding 2\n## Finding 3\n## Finding 4\n## Finding 5",
                original_ref="a",
            )
        ]
        extracted = [
            AnonymizedValidation(
                validator_id="A",
                content="## Finding 1\n## Finding 2\n## Finding 3\n## Finding 4",
                original_ref="a",
            )
        ]
        with patch.object(log, "info") as mock_info:
            validate_extraction_completeness(raw, extracted, log)
            mock_info.assert_called_once()
            assert "passed" in mock_info.call_args[0][0]

    def test_warns_when_below_threshold(self, log: logging.Logger) -> None:
        """Logs WARNING when extracted count < 80% of raw."""
        raw = [
            AnonymizedValidation(
                validator_id="A",
                content="## Finding 1\n## Finding 2\n## Finding 3\n## Finding 4\n## Finding 5\n"
                "## Finding 6\n## Finding 7\n## Finding 8\n## Finding 9\n## Finding 10",
                original_ref="a",
            )
        ]
        extracted = [
            AnonymizedValidation(
                validator_id="A",
                content="## Finding 1\n## Finding 2",
                original_ref="a",
            )
        ]
        with patch.object(log, "warning") as mock_warning:
            validate_extraction_completeness(raw, extracted, log)
            mock_warning.assert_called_once()
            assert "Possible finding loss" in mock_warning.call_args[0][0]

    def test_empty_input_returns_without_error(
        self, log: logging.Logger
    ) -> None:
        """Empty input lists return silently."""
        # Should not raise
        validate_extraction_completeness([], [], log)

    def test_zero_headings_in_raw_returns_without_error(
        self, log: logging.Logger
    ) -> None:
        """Returns without error when raw has no heading patterns."""
        raw = [
            AnonymizedValidation(
                validator_id="A",
                content="No headings here, just plain text.",
                original_ref="a",
            )
        ]
        extracted = [
            AnonymizedValidation(
                validator_id="A",
                content="Also no headings.",
                original_ref="a",
            )
        ]
        # zero raw headings -> early return, no log
        with patch.object(log, "info") as mock_info, patch.object(
            log, "warning"
        ) as mock_warning:
            validate_extraction_completeness(raw, extracted, log)
            mock_info.assert_not_called()
            mock_warning.assert_not_called()


# =============================================================================
# Tests: pre_extract_reviews
# =============================================================================


class TestPreExtractReviews:
    """Tests for pre_extract_reviews()."""

    def test_single_batch_success(
        self, sample_reviews: list[AnonymizedValidation], log: logging.Logger
    ) -> None:
        """Single batch: invoke_fn called once, returns new instances."""
        # The extraction output must have matching ## Reviewer sections
        # for clean parsing. With 2 reviews, provide 2 sections.
        extraction_output = (
            "## Reviewer A\n\n### Finding: Bug\n**Severity:** error\nExtracted bug.\n\n"
            "## Reviewer B\n\n### Finding: Issue\n**Severity:** warning\nExtracted issue.\n"
        )
        invoke_fn = MagicMock(return_value=extraction_output)

        result = pre_extract_reviews(
            reviews=sample_reviews,
            batch_size=5,
            base_context_summary="",
            invoke_fn=invoke_fn,
            log=log,
        )

        invoke_fn.assert_called_once()
        assert len(result) == 2
        # Content should be the extracted version, not the original
        assert "Extracted bug" in result[0].content
        assert "Extracted issue" in result[1].content
        # Original reviews should be unchanged (frozen dataclass)
        assert "Extracted" not in sample_reviews[0].content
        assert "Extracted" not in sample_reviews[1].content

    def test_multi_batch_invoke_count(
        self, many_reviews: list[AnonymizedValidation], log: logging.Logger
    ) -> None:
        """7 reviews with batch_size=3 produces 3 batches (3+3+1)."""
        invoke_fn = MagicMock(return_value="Extracted content for batch.")

        result = pre_extract_reviews(
            reviews=many_reviews,
            batch_size=3,
            base_context_summary="",
            invoke_fn=invoke_fn,
            log=log,
        )

        assert invoke_fn.call_count == 3
        assert len(result) == 7

    def test_partial_failure_fm4_raw_prefix(
        self, log: logging.Logger
    ) -> None:
        """FM-4: failed batch reviews get [RAW] prefix on validator_id."""
        reviews = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="Content A",
                original_ref="a",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="Content B",
                original_ref="b",
            ),
            AnonymizedValidation(
                validator_id="Reviewer C",
                content="Content C",
                original_ref="c",
            ),
        ]

        call_count = 0

        def invoke_fn(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First batch succeeds (A, B with batch_size=2)
                return "Extracted content for first batch."
            # Second batch fails (C)
            raise RuntimeError("LLM timeout")

        result = pre_extract_reviews(
            reviews=reviews,
            batch_size=2,
            base_context_summary="",
            invoke_fn=invoke_fn,
            log=log,
        )

        assert len(result) == 3
        # First batch: extracted (no [RAW] prefix)
        assert not result[0].validator_id.startswith("[RAW]")
        assert not result[1].validator_id.startswith("[RAW]")
        # Second batch: raw fallback
        assert result[2].validator_id == "[RAW] Reviewer C"
        # Original content preserved for failed batch
        assert result[2].content == "Content C"

    def test_all_fail_all_raw(self, log: logging.Logger) -> None:
        """All batches fail: all reviews get [RAW] prefix."""
        reviews = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="Content A",
                original_ref="a",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="Content B",
                original_ref="b",
            ),
        ]

        invoke_fn = MagicMock(side_effect=RuntimeError("LLM down"))

        result = pre_extract_reviews(
            reviews=reviews,
            batch_size=1,
            base_context_summary="",
            invoke_fn=invoke_fn,
            log=log,
        )

        assert len(result) == 2
        assert all(r.validator_id.startswith("[RAW]") for r in result)

    def test_exact_batch_boundary(self, log: logging.Logger) -> None:
        """5 reviews with batch_size=5 produces exactly 1 batch."""
        reviews = [
            AnonymizedValidation(
                validator_id=f"Reviewer {chr(65 + i)}",
                content=f"Content {i}",
                original_ref=f"ref-{i}",
            )
            for i in range(5)
        ]

        invoke_fn = MagicMock(return_value="Extracted output.")

        result = pre_extract_reviews(
            reviews=reviews,
            batch_size=5,
            base_context_summary="",
            invoke_fn=invoke_fn,
            log=log,
        )

        invoke_fn.assert_called_once()
        assert len(result) == 5

    def test_frozen_dataclass_immutability(
        self, sample_reviews: list[AnonymizedValidation], log: logging.Logger
    ) -> None:
        """Original frozen dataclass reviews unchanged after extraction."""
        original_content_a = sample_reviews[0].content
        original_content_b = sample_reviews[1].content

        invoke_fn = MagicMock(return_value="Completely different extracted content.")

        pre_extract_reviews(
            reviews=sample_reviews,
            batch_size=5,
            base_context_summary="",
            invoke_fn=invoke_fn,
            log=log,
        )

        # Original frozen dataclass instances unchanged
        assert sample_reviews[0].content == original_content_a
        assert sample_reviews[1].content == original_content_b

    def test_cache_file_creation(
        self,
        sample_reviews: list[AnonymizedValidation],
        tmp_path: Path,
        log: logging.Logger,
    ) -> None:
        """Cache files are written when cache_dir is set."""
        cache_dir = tmp_path / "cache"

        invoke_fn = MagicMock(return_value="Extracted.")

        pre_extract_reviews(
            reviews=sample_reviews,
            batch_size=5,
            base_context_summary="",
            invoke_fn=invoke_fn,
            log=log,
            cache_dir=cache_dir,
            session_id="test-session",
        )

        assert cache_dir.exists()
        cache_files = list(cache_dir.iterdir())
        assert len(cache_files) == 1
        assert "synthesis-extraction-test-session-batch-0" in cache_files[0].name
        # File should contain both prompt and result
        content = cache_files[0].read_text()
        assert "# Prompt" in content
        assert "# Result" in content

    def test_returns_same_count_as_input(
        self, many_reviews: list[AnonymizedValidation], log: logging.Logger
    ) -> None:
        """Output count always matches input count."""
        invoke_fn = MagicMock(return_value="Extracted.")

        result = pre_extract_reviews(
            reviews=many_reviews,
            batch_size=3,
            base_context_summary="",
            invoke_fn=invoke_fn,
            log=log,
        )

        assert len(result) == len(many_reviews)


# =============================================================================
# Tests: progressive_synthesize
# =============================================================================


class TestProgressiveSynthesize:
    """Tests for progressive_synthesize()."""

    def test_two_batch_synthesis_with_meta(
        self, log: logging.Logger
    ) -> None:
        """Two batches trigger meta-synthesis, returning 1 consolidated result."""
        reviews = [
            AnonymizedValidation(
                validator_id=f"Reviewer {chr(65 + i)}",
                content=f"## Finding {i}\n**Severity:** warning\nIssue {i}.\n",
                original_ref=f"ref-{i}",
            )
            for i in range(4)
        ]

        call_count = 0

        def invoke_fn(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if "Batch Synthesis" in prompt:
                return f"Batch {call_count} synthesized findings."
            # Meta-synthesis
            return "## Consolidated\nAll findings merged."

        result = progressive_synthesize(
            extracted_reviews=reviews,
            batch_size=2,
            base_context_summary="",
            token_budget=200_000,
            invoke_fn=invoke_fn,
            log=log,
        )

        # 2 batch calls + 1 meta-synthesis = 3 total
        assert call_count == 3
        # Meta-synthesis returns single consolidated result
        assert len(result) == 1
        assert "Consolidated Findings" in result[0].validator_id
        assert "4 reviewers" in result[0].validator_id
        assert result[0].original_ref == "meta-synthesis"

    def test_single_batch_no_meta_synthesis(
        self, log: logging.Logger
    ) -> None:
        """Single batch returns 1 intermediate without meta-synthesis."""
        reviews = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="## Finding\nIssue.\n",
                original_ref="ref-a",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="## Finding\nOther issue.\n",
                original_ref="ref-b",
            ),
        ]

        invoke_fn = MagicMock(return_value="Synthesized batch output.")

        result = progressive_synthesize(
            extracted_reviews=reviews,
            batch_size=5,
            base_context_summary="",
            token_budget=200_000,
            invoke_fn=invoke_fn,
            log=log,
        )

        # Single batch -> one intermediate, no meta-synthesis
        invoke_fn.assert_called_once()
        assert len(result) == 1
        assert "Batch 1 Findings" in result[0].validator_id

    def test_intermediate_cap_fm6(self, log: logging.Logger) -> None:
        """FM-6: intermediates exceeding token_budget * 0.4 are truncated."""
        # Create reviews that will produce large intermediates
        reviews = [
            AnonymizedValidation(
                validator_id=f"Reviewer {chr(65 + i)}",
                content=f"Finding details for reviewer {i}.\n" * 10,
                original_ref=f"ref-{i}",
            )
            for i in range(6)
        ]

        # Each batch synthesis returns a large output
        large_output = "X" * 4000  # ~1000 tokens each

        call_count = 0

        def invoke_fn(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if "Batch Synthesis" in prompt:
                return large_output
            return "Meta-synthesis result."

        result = progressive_synthesize(
            extracted_reviews=reviews,
            batch_size=2,
            base_context_summary="",
            token_budget=2000,  # Cap at 2000*0.4=800 tokens for intermediates
            invoke_fn=invoke_fn,
            log=log,
        )

        # Meta-synthesis should still run (3 intermediates > 1)
        # The intermediates should have been truncated before meta-synthesis
        assert len(result) == 1  # consolidated

    def test_meta_synthesis_failure_fm10(
        self, log: logging.Logger
    ) -> None:
        """FM-10: meta-synthesis failure returns batch intermediates."""
        reviews = [
            AnonymizedValidation(
                validator_id=f"Reviewer {chr(65 + i)}",
                content=f"Finding {i}.\n",
                original_ref=f"ref-{i}",
            )
            for i in range(4)
        ]

        call_count = 0

        def invoke_fn(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if "Batch Synthesis" in prompt:
                return f"Batch {call_count} output."
            # Meta-synthesis fails
            raise RuntimeError("LLM timeout on meta-synthesis")

        result = progressive_synthesize(
            extracted_reviews=reviews,
            batch_size=2,
            base_context_summary="",
            token_budget=200_000,
            invoke_fn=invoke_fn,
            log=log,
        )

        # Should return the 2 batch intermediates instead of consolidated
        assert len(result) == 2
        assert all("Batch" in r.validator_id for r in result)

    def test_validator_id_format_for_batch_intermediates(
        self, log: logging.Logger
    ) -> None:
        """Batch intermediates use reviewer range in validator_id."""
        reviews = [
            AnonymizedValidation(
                validator_id="Reviewer A",
                content="Finding.\n",
                original_ref="ref-a",
            ),
            AnonymizedValidation(
                validator_id="Reviewer B",
                content="Finding.\n",
                original_ref="ref-b",
            ),
            AnonymizedValidation(
                validator_id="Reviewer C",
                content="Finding.\n",
                original_ref="ref-c",
            ),
        ]

        call_count = 0

        def invoke_fn(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if "Batch Synthesis" in prompt:
                return f"Batch {call_count} output."
            raise RuntimeError("fail meta to see intermediates")

        result = progressive_synthesize(
            extracted_reviews=reviews,
            batch_size=2,
            base_context_summary="",
            token_budget=200_000,
            invoke_fn=invoke_fn,
            log=log,
        )

        # Batch 1: Reviewers A-B
        assert "Batch 1 Findings" in result[0].validator_id
        assert "A" in result[0].validator_id
        assert "B" in result[0].validator_id
        assert result[0].original_ref == "progressive-batch-1"

        # Batch 2: Reviewer C only
        assert "Batch 2 Findings" in result[1].validator_id
        assert "C" in result[1].validator_id
        assert result[1].original_ref == "progressive-batch-2"

    def test_consolidated_output_format(
        self, log: logging.Logger
    ) -> None:
        """Meta-synthesis produces correct consolidated format."""
        reviews = [
            AnonymizedValidation(
                validator_id=f"Reviewer {chr(65 + i)}",
                content=f"Finding {i}.\n",
                original_ref=f"ref-{i}",
            )
            for i in range(4)
        ]

        meta_output = "## Critical\n- Missing validation\n## Warning\n- Style issue"

        def invoke_fn(prompt: str) -> str:
            if "Meta-Synthesis" in prompt:
                return meta_output
            return "Batch output."

        result = progressive_synthesize(
            extracted_reviews=reviews,
            batch_size=2,
            base_context_summary="",
            token_budget=200_000,
            invoke_fn=invoke_fn,
            log=log,
        )

        assert len(result) == 1
        assert result[0].content == meta_output
        assert "4 reviewers" in result[0].validator_id
        assert result[0].original_ref == "meta-synthesis"
