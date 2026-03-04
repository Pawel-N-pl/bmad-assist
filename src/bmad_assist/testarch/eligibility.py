"""Keyword-based and hybrid ATDD eligibility scoring.

This module provides scoring components for ATDD eligibility detection:
- KeywordScorer: Deterministic keyword-based scoring
- ATDDEligibilityDetector: Hybrid scoring combining keyword + LLM assessment
- ATDDEligibilityResult: Frozen dataclass for detection results

Usage:
    from bmad_assist.testarch.eligibility import KeywordScorer, ATDDEligibilityDetector
    from bmad_assist.testarch.config import EligibilityConfig

    # Keyword-only scoring
    scorer = KeywordScorer()
    score = scorer.score("Create a button component with form validation")

    # Hybrid scoring (keyword + LLM)
    config = EligibilityConfig()
    detector = ATDDEligibilityDetector(config)
    result = detector.detect("Create a button component with form validation")
    if result.eligible:
        print(f"ATDD eligible: {result.reasoning}")
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from bmad_assist.testarch.config import EligibilityConfig
    from bmad_assist.testarch.prompts import ATDDEligibilityOutput

__all__ = [
    "KeywordScorer",
    "UI_KEYWORDS",
    "API_KEYWORDS",
    "SKIP_KEYWORDS",
    "ATDDEligibilityResult",
    "ATDDEligibilityDetector",
]

logger = logging.getLogger(__name__)


# Keyword dictionaries with weights (Final is type-hint convention)
# UI keywords: positive weights (0.08-0.15)
UI_KEYWORDS: Final[dict[str, float]] = {
    "component": 0.12,
    "button": 0.12,
    "form": 0.15,
    "modal": 0.12,
    "dialog": 0.12,
    "page": 0.10,
    "screen": 0.10,
    "layout": 0.10,
    "css": 0.10,
    "style": 0.10,
    "render": 0.12,
    "display": 0.10,
    "ui": 0.15,
    "user interface": 0.15,
    "frontend": 0.12,
    "click": 0.10,
    "hover": 0.08,
    "focus": 0.08,
    "input": 0.10,
    "select": 0.10,
}

# API keywords: positive weights (0.08-0.15)
API_KEYWORDS: Final[dict[str, float]] = {
    "endpoint": 0.15,
    "rest": 0.12,
    "request": 0.10,
    "response": 0.10,
    "http": 0.10,
    "payload": 0.12,
    "json": 0.08,
    "validation": 0.08,
    "contract": 0.10,
    "api": 0.15,
    "get": 0.08,
    "post": 0.10,
    "put": 0.08,
    "delete": 0.08,
    "patch": 0.08,
    "authentication": 0.12,
    "authorization": 0.12,
    "header": 0.08,
}

# Skip keywords: negative weights (-0.25 to -0.15)
SKIP_KEYWORDS: Final[dict[str, float]] = {
    "config": -0.15,
    "configuration": -0.15,
    "documentation": -0.20,
    "doc": -0.15,
    "refactor": -0.20,
    "rename": -0.18,
    "cleanup": -0.18,
    "internal": -0.15,
    "schema only": -0.25,
    "no tests": -0.25,
    "technical debt": -0.20,
    "infrastructure": -0.18,
    "devops": -0.18,
    "deployment": -0.15,
}


class KeywordScorer:
    """Keyword-based ATDD eligibility scorer.

    Analyzes text for UI, API, and skip keywords to calculate
    a deterministic ATDD suitability score using word boundary matching.

    The score is calculated as sum of all matched keyword weights,
    clamped to [0.0, 1.0]. Higher scores indicate better ATDD fit.

    Word boundary matching prevents false positives:
    - "api" matches "API endpoint" but NOT "capital" or "rapid"
    - Multi-word keywords like "schema only" match as complete phrases

    Attributes:
        ui_keywords: UI keyword to weight mapping.
        api_keywords: API keyword to weight mapping.
        skip_keywords: Skip keyword to weight mapping (negative).

    """

    def __init__(
        self,
        ui_keywords: dict[str, float] | None = None,
        api_keywords: dict[str, float] | None = None,
        skip_keywords: dict[str, float] | None = None,
    ) -> None:
        """Initialize scorer with keyword dictionaries.

        Args:
            ui_keywords: Custom UI keywords. Defaults to UI_KEYWORDS if None.
            api_keywords: Custom API keywords. Defaults to API_KEYWORDS if None.
            skip_keywords: Custom skip keywords. Defaults to SKIP_KEYWORDS if None.

        """
        self.ui_keywords = ui_keywords if ui_keywords is not None else UI_KEYWORDS
        self.api_keywords = api_keywords if api_keywords is not None else API_KEYWORDS
        self.skip_keywords = skip_keywords if skip_keywords is not None else SKIP_KEYWORDS

    def _matches_keyword(self, keyword: str, text: str) -> bool:
        """Check if keyword matches in text using word boundaries.

        Args:
            keyword: Keyword to search for (may be multi-word).
            text: Text to search in.

        Returns:
            True if keyword found with word boundaries.

        """
        # Escape regex special chars, use word boundaries
        pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
        return bool(re.search(pattern, text, re.IGNORECASE))

    def score(self, text: str) -> float:
        """Calculate ATDD eligibility score from text.

        Uses word boundary matching to prevent false positives.
        Each unique keyword is counted only once.

        Args:
            text: Story acceptance criteria or description text.

        Returns:
            Score clamped to [0.0, 1.0], where:
            - 0.0 = no ATDD suitability evidence
            - 1.0 = high ATDD suitability

        Raises:
            TypeError: If text is not a string.

        """
        if not isinstance(text, str):
            raise TypeError(f"Expected str, got {type(text).__name__}")

        if not text or not text.strip():
            return 0.0

        text_lower = text.lower()
        raw_score = 0.0

        # Sum UI keyword weights (word boundary matching)
        for keyword, weight in self.ui_keywords.items():
            if self._matches_keyword(keyword, text_lower):
                raw_score += weight

        # Sum API keyword weights (word boundary matching)
        for keyword, weight in self.api_keywords.items():
            if self._matches_keyword(keyword, text_lower):
                raw_score += weight

        # Sum skip keyword weights (negative, word boundary matching)
        for keyword, weight in self.skip_keywords.items():
            if self._matches_keyword(keyword, text_lower):
                raw_score += weight

        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, raw_score))


@dataclass(frozen=True)
class ATDDEligibilityResult:
    """Result of hybrid ATDD eligibility detection.

    Combines keyword-based and LLM-based scoring for final eligibility.
    All scores are in range [0.0, 1.0].

    Attributes:
        keyword_score: Score from KeywordScorer (deterministic).
        llm_score: Composite score from LLM assessment.
        final_score: Weighted combination of keyword and LLM scores.
        eligible: True if final_score > threshold.
        reasoning: Human-readable explanation of decision.
        ui_score: UI involvement score from LLM.
        api_score: API involvement score from LLM.
        testability_score: General testability score from LLM.
        skip_score: Skip indicator score from LLM.

    Raises:
        ValueError: If any score is outside [0.0, 1.0] range.

    """

    keyword_score: float
    llm_score: float
    final_score: float
    eligible: bool
    reasoning: str
    ui_score: float
    api_score: float
    testability_score: float
    skip_score: float

    def __post_init__(self) -> None:
        """Validate all scores are in [0.0, 1.0] range."""
        for name in (
            "keyword_score",
            "llm_score",
            "final_score",
            "ui_score",
            "api_score",
            "testability_score",
            "skip_score",
        ):
            value = getattr(self, name)
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be in [0.0, 1.0], got {value}")


class ATDDEligibilityDetector:
    """Hybrid ATDD eligibility detector combining keyword and LLM scoring.

    Uses configurable weights to combine deterministic keyword matching
    with intelligent LLM assessment for accurate ATDD decisions.

    Attributes:
        config: EligibilityConfig with weights, threshold, provider settings.
        keyword_scorer: KeywordScorer instance for deterministic scoring.

    """

    def __init__(self, config: "EligibilityConfig") -> None:
        """Initialize detector with configuration.

        Args:
            config: EligibilityConfig with scoring parameters.

        """
        self.config = config
        self.keyword_scorer = KeywordScorer()

    def _compute_llm_composite_score(self, output: "ATDDEligibilityOutput") -> float:
        """Compute composite LLM score from individual scores.

        Formula: max(testability_score, (ui_score + api_score) / 2) - skip_score
        Clamped to [0.0, 1.0].

        Args:
            output: Validated LLM output with ui/api/testability/skip scores.

        Returns:
            Composite score in [0.0, 1.0].

        """
        ui_api_avg = (output.ui_score + output.api_score) / 2
        raw = max(output.testability_score, ui_api_avg) - output.skip_score
        return max(0.0, min(1.0, raw))

    def _invoke_llm(self, text: str) -> tuple["ATDDEligibilityOutput | None", str | None]:
        """Invoke LLM for eligibility assessment.

        Args:
            text: Story content to assess.

        Returns:
            Tuple of (ATDDEligibilityOutput, None) if successful,
            or (None, error_type) on failure.

        """
        from pydantic import ValidationError

        from bmad_assist.core import get_config
        from bmad_assist.core.exceptions import (
            ConfigError,
            ProviderError,
            ProviderTimeoutError,
        )
        from bmad_assist.providers.registry import get_provider
        from bmad_assist.testarch.prompts import (
            get_eligibility_prompt,
            parse_eligibility_response,
        )

        try:
            # Use helper provider config for LLM eligibility assessment
            config = get_config()
            provider = get_provider(config.providers.helper.provider)
            prompt = get_eligibility_prompt().format(story_content=text)

            result = provider.invoke(
                prompt,
                model=config.providers.helper.model,
                timeout=60,
                disable_tools=True,
                no_cache=True,
            )

            response_text = provider.parse_output(result)
            return parse_eligibility_response(response_text), None

        except (ConfigError, ProviderError, ProviderTimeoutError, ValidationError) as e:
            error_type = type(e).__name__
            logger.warning("LLM eligibility assessment failed (%s): %s", error_type, e)
            return None, error_type

    def detect(self, text: str) -> ATDDEligibilityResult:
        """Detect ATDD eligibility using hybrid scoring.

        Args:
            text: Story acceptance criteria or description.

        Returns:
            ATDDEligibilityResult with all scoring components.

        Raises:
            TypeError: If text is not a string.

        """
        # Keyword scoring (raises TypeError if not string)
        keyword_score = self.keyword_scorer.score(text)

        # LLM scoring (with fallback)
        llm_output, error_type = self._invoke_llm(text)

        if llm_output is not None:
            llm_score = self._compute_llm_composite_score(llm_output)
            ui_score = llm_output.ui_score
            api_score = llm_output.api_score
            testability_score = llm_output.testability_score
            skip_score = llm_output.skip_score
            llm_reasoning = llm_output.reasoning

            # Hybrid calculation: max of keyword and LLM scores
            final_score = max(keyword_score, llm_score)
        else:
            # Fallback: keyword-only scoring (ignore weights per AC#6)
            llm_score = 0.0
            ui_score = 0.0
            api_score = 0.0
            testability_score = 0.0
            skip_score = 0.0
            llm_reasoning = f"LLM assessment failed ({error_type}), using keyword-only scoring"
            final_score = keyword_score  # Direct use, no weight multiplication

        eligible = final_score > self.config.threshold

        # Combined reasoning with final decision explanation (AC#8)
        decision = "Eligible for ATDD." if eligible else "Not eligible for ATDD."
        reasoning = (
            f"Keyword: {keyword_score:.2f}, LLM: {llm_score:.2f}. {llm_reasoning} {decision}"
        )

        return ATDDEligibilityResult(
            keyword_score=keyword_score,
            llm_score=llm_score,
            final_score=final_score,
            eligible=eligible,
            reasoning=reasoning,
            ui_score=ui_score,
            api_score=api_score,
            testability_score=testability_score,
            skip_score=skip_score,
        )
