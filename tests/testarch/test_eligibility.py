"""Unit tests for the KeywordScorer and eligibility module.

Tests cover:
- Empty/whitespace input handling
- UI keyword positive contributions
- API keyword positive contributions
- Skip keyword negative contributions
- Mixed keyword scenarios
- Score clamping bounds
- Case-insensitive matching
- Custom keyword dictionary injection
- Word boundary matching (no false positives)
- Multi-word keyword phrase matching
- Duplicate keyword counted once
"""

from unittest.mock import MagicMock, patch

import pytest


class TestEligibilityModuleExports:
    """Test AC1 and AC9: Module structure and exports."""

    def test_module_exports_keyword_scorer(self) -> None:
        """KeywordScorer class is exported from eligibility module."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        assert KeywordScorer is not None

    def test_module_exports_ui_keywords(self) -> None:
        """UI_KEYWORDS constant is exported from eligibility module."""
        from bmad_assist.testarch.eligibility import UI_KEYWORDS

        assert isinstance(UI_KEYWORDS, dict)
        assert len(UI_KEYWORDS) > 0

    def test_module_exports_api_keywords(self) -> None:
        """API_KEYWORDS constant is exported from eligibility module."""
        from bmad_assist.testarch.eligibility import API_KEYWORDS

        assert isinstance(API_KEYWORDS, dict)
        assert len(API_KEYWORDS) > 0

    def test_module_exports_skip_keywords(self) -> None:
        """SKIP_KEYWORDS constant is exported from eligibility module."""
        from bmad_assist.testarch.eligibility import SKIP_KEYWORDS

        assert isinstance(SKIP_KEYWORDS, dict)
        assert len(SKIP_KEYWORDS) > 0

    def test_module_all_exports(self) -> None:
        """__all__ contains expected exports."""
        from bmad_assist.testarch import eligibility

        assert hasattr(eligibility, "__all__")
        assert "KeywordScorer" in eligibility.__all__
        assert "UI_KEYWORDS" in eligibility.__all__
        assert "API_KEYWORDS" in eligibility.__all__
        assert "SKIP_KEYWORDS" in eligibility.__all__

    def test_testarch_module_exports_eligibility(self) -> None:
        """Testarch __init__ exports eligibility symbols."""
        from bmad_assist.testarch import (
            API_KEYWORDS,
            SKIP_KEYWORDS,
            UI_KEYWORDS,
            KeywordScorer,
        )

        assert KeywordScorer is not None
        assert UI_KEYWORDS is not None
        assert API_KEYWORDS is not None
        assert SKIP_KEYWORDS is not None


class TestKeywordDictionaries:
    """Test AC3, AC4, AC5: Keyword dictionaries with proper weights."""

    def test_ui_keywords_have_positive_weights(self) -> None:
        """UI keywords have positive weights in range 0.08-0.15."""
        from bmad_assist.testarch.eligibility import UI_KEYWORDS

        for keyword, weight in UI_KEYWORDS.items():
            assert 0.08 <= weight <= 0.15, f"UI keyword '{keyword}' has invalid weight {weight}"

    def test_api_keywords_have_positive_weights(self) -> None:
        """API keywords have positive weights in range 0.08-0.15."""
        from bmad_assist.testarch.eligibility import API_KEYWORDS

        for keyword, weight in API_KEYWORDS.items():
            assert 0.08 <= weight <= 0.15, f"API keyword '{keyword}' has invalid weight {weight}"

    def test_skip_keywords_have_negative_weights(self) -> None:
        """Skip keywords have negative weights in range -0.25 to -0.15."""
        from bmad_assist.testarch.eligibility import SKIP_KEYWORDS

        for keyword, weight in SKIP_KEYWORDS.items():
            assert -0.25 <= weight <= -0.15, f"Skip keyword '{keyword}' has invalid weight {weight}"

    def test_ui_keywords_contains_expected_terms(self) -> None:
        """UI keywords include expected UI-related terms."""
        from bmad_assist.testarch.eligibility import UI_KEYWORDS

        expected = ["component", "button", "form", "modal", "page", "css", "render", "display"]
        for term in expected:
            assert term in UI_KEYWORDS, f"Expected UI keyword '{term}' not found"

    def test_api_keywords_contains_expected_terms(self) -> None:
        """API keywords include expected API-related terms."""
        from bmad_assist.testarch.eligibility import API_KEYWORDS

        expected = ["endpoint", "rest", "request", "response", "http", "json", "api", "payload"]
        for term in expected:
            assert term in API_KEYWORDS, f"Expected API keyword '{term}' not found"

    def test_skip_keywords_contains_expected_terms(self) -> None:
        """Skip keywords include expected skip-related terms."""
        from bmad_assist.testarch.eligibility import SKIP_KEYWORDS

        expected = [
            "config",
            "documentation",
            "refactor",
            "rename",
            "cleanup",
            "schema only",
            "no tests",
        ]
        for term in expected:
            assert term in SKIP_KEYWORDS, f"Expected skip keyword '{term}' not found"


class TestKeywordScorerEmptyInput:
    """Test AC7: Empty and edge cases."""

    def test_score_empty_text_returns_zero(self) -> None:
        """Empty string returns 0.0."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        assert scorer.score("") == 0.0

    def test_score_whitespace_only_returns_zero(self) -> None:
        """Whitespace-only text returns 0.0."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        assert scorer.score("   ") == 0.0
        assert scorer.score("\t\t") == 0.0
        assert scorer.score("\n\n") == 0.0
        assert scorer.score("  \t\n  ") == 0.0

    def test_score_no_matching_keywords_returns_zero(self) -> None:
        """Text with no matching keywords returns 0.0 (base score)."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        result = scorer.score("This is just random text without any relevant keywords")
        assert result == 0.0

    def test_score_raises_typeerror_for_none(self) -> None:
        """TypeError raised for None input."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        with pytest.raises(TypeError, match="Expected str, got NoneType"):
            scorer.score(None)  # type: ignore[arg-type]

    def test_score_raises_typeerror_for_int(self) -> None:
        """TypeError raised for int input."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        with pytest.raises(TypeError, match="Expected str, got int"):
            scorer.score(0)  # type: ignore[arg-type]

    def test_score_raises_typeerror_for_list(self) -> None:
        """TypeError raised for list input."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        with pytest.raises(TypeError, match="Expected str, got list"):
            scorer.score([])  # type: ignore[arg-type]


class TestKeywordScorerPositiveKeywords:
    """Test AC3 and AC4: UI and API keywords add positive weight."""

    def test_score_ui_keywords_positive(self) -> None:
        """UI keywords add positive weight to score."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        result = scorer.score("Create a button component with modal dialog")
        assert result > 0.0

    def test_score_api_keywords_positive(self) -> None:
        """API keywords add positive weight to score."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        result = scorer.score("Create REST endpoint with JSON response")
        assert result > 0.0

    def test_single_ui_keyword_contributes_correct_weight(self) -> None:
        """Single UI keyword contributes its exact weight."""
        from bmad_assist.testarch.eligibility import UI_KEYWORDS, KeywordScorer

        scorer = KeywordScorer()
        result = scorer.score("Create a button")
        expected = UI_KEYWORDS["button"]
        assert abs(result - expected) < 0.001

    def test_single_api_keyword_contributes_correct_weight(self) -> None:
        """Single API keyword contributes its exact weight."""
        from bmad_assist.testarch.eligibility import API_KEYWORDS, KeywordScorer

        scorer = KeywordScorer()
        result = scorer.score("Create an endpoint")
        expected = API_KEYWORDS["endpoint"]
        assert abs(result - expected) < 0.001


class TestKeywordScorerNegativeKeywords:
    """Test AC5: Skip keywords subtract weight."""

    def test_score_skip_keywords_negative(self) -> None:
        """Skip keywords subtract from score."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        # Only skip keywords, no positive keywords
        result = scorer.score("refactor the internal config")
        # Should be clamped to 0.0 since negative
        assert result == 0.0

    def test_skip_keywords_reduce_positive_score(self) -> None:
        """Skip keywords reduce a positive score."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        positive_only = scorer.score("Create a button component")
        with_skip = scorer.score("Create a button component, just refactor")
        assert with_skip < positive_only

    def test_skip_keyword_with_positive_baseline_schema_only(self) -> None:
        """Positive baseline: 'schema only' keyword demonstrably subtracts weight.

        This test proves the skip keyword actually matched by showing the delta
        between a positive score and positive + skip keyword.
        """
        from bmad_assist.testarch.eligibility import (
            SKIP_KEYWORDS,
            UI_KEYWORDS,
            KeywordScorer,
        )

        scorer = KeywordScorer()
        # Baseline: just "form" (0.15)
        baseline = scorer.score("create a form")
        assert abs(baseline - UI_KEYWORDS["form"]) < 0.001

        # With skip keyword: "form" + "schema only" (0.15 - 0.25 = -0.10 → clamped to 0.0)
        with_skip = scorer.score("create a form schema only")
        expected_raw = UI_KEYWORDS["form"] + SKIP_KEYWORDS["schema only"]
        expected = max(0.0, expected_raw)
        assert abs(with_skip - expected) < 0.001
        assert with_skip < baseline  # Proves skip keyword had effect

    def test_skip_keyword_with_positive_baseline_technical_debt(self) -> None:
        """Positive baseline: 'technical debt' multi-word keyword demonstrably subtracts.

        This test covers the multi-word skip keyword 'technical debt' which was
        identified as missing coverage in code review.
        """
        from bmad_assist.testarch.eligibility import (
            SKIP_KEYWORDS,
            UI_KEYWORDS,
            KeywordScorer,
        )

        scorer = KeywordScorer()
        # Baseline: "endpoint" (0.15) + "button" (0.12) = 0.27
        from bmad_assist.testarch.eligibility import API_KEYWORDS

        baseline = scorer.score("endpoint button")
        expected_baseline = API_KEYWORDS["endpoint"] + UI_KEYWORDS["button"]
        assert abs(baseline - expected_baseline) < 0.001

        # With "technical debt": 0.15 + 0.12 - 0.20 = 0.07
        with_skip = scorer.score("endpoint button technical debt")
        expected = expected_baseline + SKIP_KEYWORDS["technical debt"]
        assert abs(with_skip - expected) < 0.001
        assert with_skip < baseline  # Proves technical debt keyword matched


class TestKeywordScorerMixedKeywords:
    """Test mixed keyword scenarios."""

    def test_score_mixed_keywords(self) -> None:
        """Mixed keywords produce expected weighted sum."""
        from bmad_assist.testarch.eligibility import (
            API_KEYWORDS,
            SKIP_KEYWORDS,
            UI_KEYWORDS,
            KeywordScorer,
        )

        scorer = KeywordScorer()
        text = "Create a form with endpoint and config"
        result = scorer.score(text)
        expected = UI_KEYWORDS["form"] + API_KEYWORDS["endpoint"] + SKIP_KEYWORDS["config"]
        expected_clamped = max(0.0, min(1.0, expected))
        assert abs(result - expected_clamped) < 0.001


class TestKeywordScorerClamping:
    """Test AC6: Score clamping to [0.0, 1.0]."""

    def test_score_clamping_lower_bound(self) -> None:
        """Many skip keywords clamp score to 0.0."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        text = "refactor cleanup rename config documentation schema only no tests"
        result = scorer.score(text)
        assert result == 0.0

    def test_score_clamping_upper_bound(self) -> None:
        """Many UI/API keywords clamp score to 1.0."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        # Pack many keywords to exceed 1.0
        text = (
            "component button form modal dialog page screen layout css style "
            "render display ui frontend click hover focus input select "
            "endpoint rest request response http payload json validation api"
        )
        result = scorer.score(text)
        assert result == 1.0

    def test_score_returns_valid_float_in_range(self) -> None:
        """Score always returns valid float in [0.0, 1.0]."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        for text in ["", "button", "refactor", "endpoint api form config"]:
            result = scorer.score(text)
            assert isinstance(result, float)
            assert 0.0 <= result <= 1.0


class TestKeywordScorerCaseInsensitive:
    """Test case-insensitive matching."""

    def test_case_insensitive_matching(self) -> None:
        """Keywords match regardless of case."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        lower = scorer.score("button")
        upper = scorer.score("BUTTON")
        mixed = scorer.score("BuTtOn")
        assert lower == upper == mixed


class TestKeywordScorerCustomDictionaries:
    """Test AC8: Custom keyword dictionaries."""

    def test_custom_keyword_dictionaries(self) -> None:
        """Custom dictionaries override defaults."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        custom_ui = {"custom": 0.10}
        custom_api = {"special": 0.12}
        custom_skip = {"ignore": -0.20}
        scorer = KeywordScorer(
            ui_keywords=custom_ui,
            api_keywords=custom_api,
            skip_keywords=custom_skip,
        )
        # Default keywords should not match
        assert scorer.score("button endpoint refactor") == 0.0
        # Custom keywords should match
        result = scorer.score("custom special ignore")
        expected = 0.10 + 0.12 - 0.20
        assert abs(result - expected) < 0.001

    def test_none_uses_defaults(self) -> None:
        """None parameter uses default dictionaries."""
        from bmad_assist.testarch.eligibility import (
            API_KEYWORDS,
            SKIP_KEYWORDS,
            UI_KEYWORDS,
            KeywordScorer,
        )

        scorer = KeywordScorer(ui_keywords=None, api_keywords=None, skip_keywords=None)
        assert scorer.ui_keywords == UI_KEYWORDS
        assert scorer.api_keywords == API_KEYWORDS
        assert scorer.skip_keywords == SKIP_KEYWORDS

    def test_empty_dict_uses_empty(self) -> None:
        """Empty dict {} uses that empty dict, not defaults."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer(ui_keywords={}, api_keywords={}, skip_keywords={})
        assert scorer.ui_keywords == {}
        assert scorer.api_keywords == {}
        assert scorer.skip_keywords == {}
        # No keywords match
        assert scorer.score("button endpoint refactor") == 0.0

    def test_partial_custom_dictionaries(self) -> None:
        """Partial custom dictionaries: custom for one, default for others."""
        from bmad_assist.testarch.eligibility import (
            API_KEYWORDS,
            SKIP_KEYWORDS,
            KeywordScorer,
        )

        custom_ui = {"custom": 0.10}
        scorer = KeywordScorer(ui_keywords=custom_ui)
        assert scorer.ui_keywords == custom_ui
        assert scorer.api_keywords == API_KEYWORDS
        assert scorer.skip_keywords == SKIP_KEYWORDS


class TestKeywordScorerWordBoundary:
    """Test AC2: Word boundary matching (CRITICAL)."""

    def test_word_boundary_no_false_positives(self) -> None:
        """Word boundary matching prevents false positives."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        # "api" should not match in "capital" or "rapid"
        assert scorer.score("capital investments") == 0.0
        assert scorer.score("rapid development") == 0.0

    def test_api_matches_standalone(self) -> None:
        """'api' matches 'API endpoint' as standalone word."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        result = scorer.score("API endpoint")
        assert result > 0.0

    def test_form_not_in_platform(self) -> None:
        """'form' does not match in 'platform'."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        assert scorer.score("platform") == 0.0
        assert scorer.score("performance") == 0.0

    def test_form_matches_standalone(self) -> None:
        """'form' matches 'create a form' as standalone word."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        result = scorer.score("create a form")
        assert result > 0.0

    def test_ui_not_in_build(self) -> None:
        """'ui' does not match in 'build' or 'fruit'."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        assert scorer.score("build the application") == 0.0
        assert scorer.score("fruit salad") == 0.0

    def test_ui_matches_standalone(self) -> None:
        """'ui' matches 'UI component' as standalone word."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        result = scorer.score("UI component")
        assert result > 0.0


class TestKeywordScorerMultiWord:
    """Test multi-word keyword phrase matching."""

    def test_multi_word_keyword_matching(self) -> None:
        """Multi-word keywords like 'schema only' match as complete phrases."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        # "schema only" should match as phrase
        result = scorer.score("this is schema only change")
        # Clamped to 0.0 since negative (see test_skip_keyword_with_positive_baseline_schema_only)
        assert result == 0.0

    def test_multi_word_partial_no_match(self) -> None:
        """Partial multi-word keyword does not match."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        # Just "schema" without "only" should not trigger "schema only"
        # (but "schema" itself is not a keyword)
        assert scorer.score("schema changes") == 0.0

    def test_no_tests_multi_word(self) -> None:
        """'no tests' matches as complete phrase."""
        from bmad_assist.testarch.eligibility import KeywordScorer

        scorer = KeywordScorer()
        result = scorer.score("this change needs no tests")
        # Since "no tests" is negative, clamped to 0.0
        assert result == 0.0

    def test_user_interface_multi_word(self) -> None:
        """'user interface' matches as complete phrase."""
        from bmad_assist.testarch.eligibility import UI_KEYWORDS, KeywordScorer

        scorer = KeywordScorer()
        result = scorer.score("build the user interface")
        expected = UI_KEYWORDS["user interface"]
        assert abs(result - expected) < 0.001


class TestKeywordScorerDuplicates:
    """Test duplicate keyword handling."""

    def test_duplicate_keyword_counted_once(self) -> None:
        """Each unique keyword is counted only once."""
        from bmad_assist.testarch.eligibility import UI_KEYWORDS, KeywordScorer

        scorer = KeywordScorer()
        single = scorer.score("button")
        duplicate = scorer.score("button button button")
        assert single == duplicate
        assert single == UI_KEYWORDS["button"]

    def test_multiple_different_keywords_all_count(self) -> None:
        """Different keywords are all counted."""
        from bmad_assist.testarch.eligibility import UI_KEYWORDS, KeywordScorer

        scorer = KeywordScorer()
        single = scorer.score("button")
        multiple = scorer.score("button form modal")
        expected = UI_KEYWORDS["button"] + UI_KEYWORDS["form"] + UI_KEYWORDS["modal"]
        assert abs(multiple - expected) < 0.001
        assert multiple > single


# =============================================================================
# ATDDEligibilityResult Tests (Story testarch-4)
# =============================================================================


class TestATDDEligibilityResultDataclass:
    """Test AC2: ATDDEligibilityResult dataclass structure."""

    def test_result_dataclass_exists(self) -> None:
        """ATDDEligibilityResult class is importable."""
        from bmad_assist.testarch.eligibility import ATDDEligibilityResult

        assert ATDDEligibilityResult is not None

    def test_result_dataclass_frozen(self) -> None:
        """ATDDEligibilityResult is frozen (immutable)."""
        from dataclasses import FrozenInstanceError

        from bmad_assist.testarch.eligibility import ATDDEligibilityResult

        result = ATDDEligibilityResult(
            keyword_score=0.5,
            llm_score=0.6,
            final_score=0.55,
            eligible=True,
            reasoning="Test reasoning",
            ui_score=0.7,
            api_score=0.5,
            skip_score=0.1,
        )
        with pytest.raises(FrozenInstanceError):
            result.eligible = False  # type: ignore[misc]

    def test_result_has_all_required_fields(self) -> None:
        """ATDDEligibilityResult has all required fields."""
        from bmad_assist.testarch.eligibility import ATDDEligibilityResult

        result = ATDDEligibilityResult(
            keyword_score=0.5,
            llm_score=0.6,
            final_score=0.55,
            eligible=True,
            reasoning="Test reasoning",
            ui_score=0.7,
            api_score=0.5,
            skip_score=0.1,
        )
        assert result.keyword_score == 0.5
        assert result.llm_score == 0.6
        assert result.final_score == 0.55
        assert result.eligible is True
        assert result.reasoning == "Test reasoning"
        assert result.ui_score == 0.7
        assert result.api_score == 0.5
        assert result.skip_score == 0.1

    def test_result_scores_in_valid_range(self) -> None:
        """All float scores are in [0.0, 1.0] range."""
        from bmad_assist.testarch.eligibility import ATDDEligibilityResult

        # Valid range
        result = ATDDEligibilityResult(
            keyword_score=0.0,
            llm_score=1.0,
            final_score=0.5,
            eligible=True,
            reasoning="Boundary test",
            ui_score=0.0,
            api_score=1.0,
            skip_score=0.5,
        )
        assert 0.0 <= result.keyword_score <= 1.0
        assert 0.0 <= result.llm_score <= 1.0
        assert 0.0 <= result.final_score <= 1.0
        assert 0.0 <= result.ui_score <= 1.0
        assert 0.0 <= result.api_score <= 1.0
        assert 0.0 <= result.skip_score <= 1.0

    def test_result_post_init_validation_rejects_invalid_scores(self) -> None:
        """__post_init__ rejects scores outside [0.0, 1.0] range."""
        from bmad_assist.testarch.eligibility import ATDDEligibilityResult

        # Test keyword_score > 1.0
        with pytest.raises(ValueError, match="keyword_score must be in"):
            ATDDEligibilityResult(
                keyword_score=1.5,
                llm_score=0.5,
                final_score=0.5,
                eligible=True,
                reasoning="Test",
                ui_score=0.5,
                api_score=0.5,
                skip_score=0.5,
            )

        # Test negative llm_score
        with pytest.raises(ValueError, match="llm_score must be in"):
            ATDDEligibilityResult(
                keyword_score=0.5,
                llm_score=-0.1,
                final_score=0.5,
                eligible=True,
                reasoning="Test",
                ui_score=0.5,
                api_score=0.5,
                skip_score=0.5,
            )

        # Test final_score > 1.0
        with pytest.raises(ValueError, match="final_score must be in"):
            ATDDEligibilityResult(
                keyword_score=0.5,
                llm_score=0.5,
                final_score=2.0,
                eligible=True,
                reasoning="Test",
                ui_score=0.5,
                api_score=0.5,
                skip_score=0.5,
            )


class TestATDDEligibilityResultExports:
    """Test AC1: Module exports for ATDDEligibilityResult."""

    def test_eligibility_module_exports_result(self) -> None:
        """ATDDEligibilityResult in eligibility.__all__."""
        from bmad_assist.testarch import eligibility

        assert "ATDDEligibilityResult" in eligibility.__all__

    def test_testarch_module_exports_result(self) -> None:
        """ATDDEligibilityResult exported from testarch.__init__."""
        from bmad_assist.testarch import ATDDEligibilityResult

        assert ATDDEligibilityResult is not None


# =============================================================================
# ATDDEligibilityDetector Tests (Story testarch-4)
# =============================================================================


class TestATDDEligibilityDetectorClass:
    """Test AC1: ATDDEligibilityDetector class structure."""

    def test_detector_class_exists(self) -> None:
        """ATDDEligibilityDetector class is importable."""
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        assert ATDDEligibilityDetector is not None

    def test_detector_accepts_eligibility_config(self) -> None:
        """Detector accepts EligibilityConfig in constructor."""
        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        config = EligibilityConfig()
        detector = ATDDEligibilityDetector(config)
        assert detector.config == config

    def test_detector_has_keyword_scorer(self) -> None:
        """Detector has internal KeywordScorer instance."""
        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector, KeywordScorer

        config = EligibilityConfig()
        detector = ATDDEligibilityDetector(config)
        assert hasattr(detector, "keyword_scorer")
        assert isinstance(detector.keyword_scorer, KeywordScorer)


class TestATDDEligibilityDetectorExports:
    """Test AC1: Module exports for ATDDEligibilityDetector."""

    def test_eligibility_module_exports_detector(self) -> None:
        """ATDDEligibilityDetector in eligibility.__all__."""
        from bmad_assist.testarch import eligibility

        assert "ATDDEligibilityDetector" in eligibility.__all__

    def test_testarch_module_exports_detector(self) -> None:
        """ATDDEligibilityDetector exported from testarch.__init__."""
        from bmad_assist.testarch import ATDDEligibilityDetector

        assert ATDDEligibilityDetector is not None


class TestCompositeLLMScoreFormula:
    """Test AC4: LLM composite score calculation."""

    def test_composite_score_formula(self) -> None:
        """Composite LLM score = max(0, (ui + api) / 2 - skip)."""
        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector
        from bmad_assist.testarch.prompts import ATDDEligibilityOutput

        config = EligibilityConfig()
        detector = ATDDEligibilityDetector(config)

        # Test formula: (0.8 + 0.6) / 2 - 0.3 = 0.7 - 0.3 = 0.4
        output = ATDDEligibilityOutput(
            ui_score=0.8, api_score=0.6, skip_score=0.3, reasoning="Test"
        )
        result = detector._compute_llm_composite_score(output)
        expected = (0.8 + 0.6) / 2 - 0.3
        assert abs(result - expected) < 0.001

    def test_composite_score_clamped_to_zero(self) -> None:
        """Composite score floors at 0.0 when negative."""
        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector
        from bmad_assist.testarch.prompts import ATDDEligibilityOutput

        config = EligibilityConfig()
        detector = ATDDEligibilityDetector(config)

        # Test formula: (0.2 + 0.2) / 2 - 0.9 = 0.2 - 0.9 = -0.7 → 0.0
        output = ATDDEligibilityOutput(
            ui_score=0.2, api_score=0.2, skip_score=0.9, reasoning="Skip-heavy"
        )
        result = detector._compute_llm_composite_score(output)
        assert result == 0.0

    def test_composite_score_clamped_to_one(self) -> None:
        """Composite score capped at 1.0 (edge case)."""
        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector
        from bmad_assist.testarch.prompts import ATDDEligibilityOutput

        config = EligibilityConfig()
        detector = ATDDEligibilityDetector(config)

        # Test formula: (1.0 + 1.0) / 2 - 0.0 = 1.0 (exactly at cap)
        output = ATDDEligibilityOutput(ui_score=1.0, api_score=1.0, skip_score=0.0, reasoning="Max")
        result = detector._compute_llm_composite_score(output)
        assert result == 1.0


class TestHybridScoreCalculation:
    """Test AC3: Hybrid score calculation with weights."""

    @pytest.fixture(autouse=True)
    def mock_get_config(self):
        """Mock get_config for all tests in this class."""
        mock_config = MagicMock()
        mock_config.providers.helper.provider = "claude"
        mock_config.providers.helper.model = "haiku"
        with patch("bmad_assist.core.get_config", return_value=mock_config):
            yield

    def test_hybrid_score_weights_applied(self) -> None:
        """Final score = (keyword_weight * keyword) + (llm_weight * llm)."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        # Custom weights: keyword=0.3, llm=0.7
        config = EligibilityConfig(keyword_weight=0.3, llm_weight=0.7, threshold=0.5)

        # Mock provider to return controlled LLM output
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.invoke.return_value = MagicMock(
            stdout='{"ui_score": 0.8, "api_score": 0.6, "skip_score": 0.0, "reasoning": "Test"}',
            stderr="",
            exit_code=0,
        )
        mock_provider.parse_output.return_value = (
            '{"ui_score": 0.8, "api_score": 0.6, "skip_score": 0.0, "reasoning": "Test"}'
        )

        with patch("bmad_assist.providers.registry.get_provider", return_value=mock_provider):
            detector = ATDDEligibilityDetector(config)
            # "button" = 0.12 keyword score
            result = detector.detect("button")

        # keyword_score = 0.12, llm_score = (0.8 + 0.6) / 2 - 0.0 = 0.7
        # final_score = 0.3 * 0.12 + 0.7 * 0.7 = 0.036 + 0.49 = 0.526
        expected_final = 0.3 * 0.12 + 0.7 * 0.7
        assert abs(result.final_score - expected_final) < 0.001

    def test_detect_threshold_boundary_not_eligible(self) -> None:
        """Score == threshold → NOT eligible (strict > required)."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        # Set up scenario where final_score exactly equals threshold
        config = EligibilityConfig(keyword_weight=1.0, llm_weight=0.0, threshold=0.12)

        # Mock LLM to not be called (weight=0.0 means keyword only in practice)
        # but we still mock it since detect() calls it
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.invoke.return_value = MagicMock(
            stdout='{"ui_score": 0.0, "api_score": 0.0, "skip_score": 0.0, "reasoning": "Test"}',
            stderr="",
            exit_code=0,
        )
        mock_provider.parse_output.return_value = (
            '{"ui_score": 0.0, "api_score": 0.0, "skip_score": 0.0, "reasoning": "Test"}'
        )

        with patch("bmad_assist.providers.registry.get_provider", return_value=mock_provider):
            detector = ATDDEligibilityDetector(config)
            result = detector.detect("button")  # 0.12 keyword score

        # final_score = 1.0 * 0.12 + 0.0 * 0.0 = 0.12, threshold = 0.12
        # eligible = 0.12 > 0.12 → False
        assert result.final_score == pytest.approx(0.12, abs=0.001)
        assert result.eligible is False

    def test_detect_mixed_scores(self) -> None:
        """Balanced scores → threshold determines eligibility (AC#10)."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        # Balanced: keyword=0.5, llm=0.5, equal weights
        config = EligibilityConfig(keyword_weight=0.5, llm_weight=0.5, threshold=0.4)

        # LLM returns balanced scores: ui=0.5, api=0.5, skip=0.3
        # llm_composite = (0.5 + 0.5) / 2 - 0.3 = 0.2
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.invoke.return_value = MagicMock(
            stdout='{"ui_score": 0.5, "api_score": 0.5, "skip_score": 0.3, "reasoning": "Balanced"}',
            stderr="",
            exit_code=0,
        )
        mock_provider.parse_output.return_value = (
            '{"ui_score": 0.5, "api_score": 0.5, "skip_score": 0.3, "reasoning": "Balanced"}'
        )

        with patch("bmad_assist.providers.registry.get_provider", return_value=mock_provider):
            detector = ATDDEligibilityDetector(config)
            # "form endpoint" = 0.15 + 0.15 = 0.30 keyword score
            result = detector.detect("form endpoint")

        # keyword_score ~= 0.30, llm_score = 0.2
        # final = 0.5 * 0.30 + 0.5 * 0.2 = 0.15 + 0.10 = 0.25
        # threshold = 0.4, so NOT eligible
        assert result.keyword_score == pytest.approx(0.30, abs=0.01)
        assert result.llm_score == pytest.approx(0.2, abs=0.001)
        assert result.final_score == pytest.approx(0.25, abs=0.01)
        assert result.eligible is False  # 0.25 < 0.4

        # Now test with lower threshold where it WOULD be eligible
        config_low = EligibilityConfig(keyword_weight=0.5, llm_weight=0.5, threshold=0.2)
        with patch("bmad_assist.providers.registry.get_provider", return_value=mock_provider):
            detector_low = ATDDEligibilityDetector(config_low)
            result_low = detector_low.detect("form endpoint")

        # Same scores, but threshold = 0.2
        # 0.25 > 0.2 → eligible
        assert result_low.eligible is True  # Threshold is deciding factor

    def test_detect_high_ui_score_eligible(self) -> None:
        """High UI score → eligible."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        config = EligibilityConfig()  # defaults: 0.5/0.5/0.5

        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.invoke.return_value = MagicMock(
            stdout='{"ui_score": 0.9, "api_score": 0.7, "skip_score": 0.0, "reasoning": "UI-heavy story"}',
            stderr="",
            exit_code=0,
        )
        mock_provider.parse_output.return_value = (
            '{"ui_score": 0.9, "api_score": 0.7, "skip_score": 0.0, "reasoning": "UI-heavy story"}'
        )

        with patch("bmad_assist.providers.registry.get_provider", return_value=mock_provider):
            detector = ATDDEligibilityDetector(config)
            result = detector.detect("Create a button component with form validation")

        # keyword_score > 0 (button, component, form)
        # llm_score = (0.9 + 0.7) / 2 - 0.0 = 0.8
        # final_score should be > 0.5
        assert result.eligible is True
        assert result.ui_score == 0.9
        assert result.api_score == 0.7
        assert result.skip_score == 0.0

    def test_detect_high_skip_score_not_eligible(self) -> None:
        """High skip score → not eligible."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        config = EligibilityConfig()  # defaults

        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.invoke.return_value = MagicMock(
            stdout='{"ui_score": 0.1, "api_score": 0.1, "skip_score": 0.9, "reasoning": "Config only"}',
            stderr="",
            exit_code=0,
        )
        mock_provider.parse_output.return_value = (
            '{"ui_score": 0.1, "api_score": 0.1, "skip_score": 0.9, "reasoning": "Config only"}'
        )

        with patch("bmad_assist.providers.registry.get_provider", return_value=mock_provider):
            detector = ATDDEligibilityDetector(config)
            result = detector.detect("Update configuration schema")

        # keyword_score low (config is negative)
        # llm_score = (0.1 + 0.1) / 2 - 0.9 = -0.8 → clamped to 0.0
        assert result.eligible is False
        assert result.skip_score == 0.9


class TestLLMFallback:
    """Test AC6: Graceful LLM failure handling."""

    @pytest.fixture(autouse=True)
    def mock_get_config(self):
        """Mock get_config for all tests in this class."""
        mock_config = MagicMock()
        mock_config.providers.helper.provider = "claude"
        mock_config.providers.helper.model = "haiku"
        with patch("bmad_assist.core.get_config", return_value=mock_config):
            yield

    def test_llm_timeout_fallback(self) -> None:
        """ProviderTimeoutError → keyword-only scoring with error type in reasoning."""
        from unittest.mock import patch

        from bmad_assist.core.exceptions import ProviderTimeoutError
        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        config = EligibilityConfig(threshold=0.1)  # Low threshold

        with patch(
            "bmad_assist.providers.registry.get_provider",
            side_effect=ProviderTimeoutError("Timeout"),
        ):
            detector = ATDDEligibilityDetector(config)
            result = detector.detect("button")  # 0.12 keyword score

        # Fallback: final_score = keyword_score (direct, no weights)
        assert result.llm_score == 0.0
        assert result.ui_score == 0.0
        assert result.api_score == 0.0
        assert result.skip_score == 0.0
        assert result.final_score == pytest.approx(0.12, abs=0.001)
        # AC#6: reasoning must include error type
        assert "ProviderTimeoutError" in result.reasoning
        assert "failed" in result.reasoning.lower()

    def test_llm_provider_error_fallback(self) -> None:
        """ProviderError → keyword-only scoring with error type in reasoning."""
        from unittest.mock import patch

        from bmad_assist.core.exceptions import ProviderError
        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        config = EligibilityConfig(threshold=0.1)

        with patch(
            "bmad_assist.providers.registry.get_provider",
            side_effect=ProviderError("Provider failed"),
        ):
            detector = ATDDEligibilityDetector(config)
            result = detector.detect("button")

        assert result.llm_score == 0.0
        assert result.final_score == pytest.approx(0.12, abs=0.001)
        # AC#6: reasoning must include error type
        assert "ProviderError" in result.reasoning
        assert "failed" in result.reasoning.lower()

    def test_llm_config_error_fallback(self) -> None:
        """ConfigError → keyword-only scoring with error type in reasoning."""
        from unittest.mock import patch

        from bmad_assist.core.exceptions import ConfigError
        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        config = EligibilityConfig(threshold=0.1)

        with patch(
            "bmad_assist.providers.registry.get_provider",
            side_effect=ConfigError("Config invalid"),
        ):
            detector = ATDDEligibilityDetector(config)
            result = detector.detect("button")

        assert result.llm_score == 0.0
        assert result.final_score == pytest.approx(0.12, abs=0.001)
        # AC#6: reasoning must include error type
        assert "ConfigError" in result.reasoning
        assert "failed" in result.reasoning.lower()

    def test_llm_validation_error_fallback(self) -> None:
        """pydantic.ValidationError → keyword-only scoring with error type in reasoning."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        config = EligibilityConfig(threshold=0.1)

        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.invoke.return_value = MagicMock(
            stdout='{"invalid": "json"}',  # Missing required fields
            stderr="",
            exit_code=0,
        )
        mock_provider.parse_output.return_value = '{"invalid": "json"}'

        with patch("bmad_assist.providers.registry.get_provider", return_value=mock_provider):
            detector = ATDDEligibilityDetector(config)
            result = detector.detect("button")

        # Validation error from parse_eligibility_response → fallback
        assert result.llm_score == 0.0
        assert result.final_score == pytest.approx(0.12, abs=0.001)
        # AC#6: reasoning must include error type
        assert "ValidationError" in result.reasoning
        assert "failed" in result.reasoning.lower()


class TestEdgeCases:
    """Test AC9: Edge case handling."""

    @pytest.fixture(autouse=True)
    def mock_get_config(self):
        """Mock get_config for all tests in this class."""
        mock_config = MagicMock()
        mock_config.providers.helper.provider = "claude"
        mock_config.providers.helper.model = "haiku"
        with patch("bmad_assist.core.get_config", return_value=mock_config):
            yield

    def test_empty_text_invokes_llm(self) -> None:
        """Empty text still invokes LLM (may provide insight)."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        config = EligibilityConfig()

        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.invoke.return_value = MagicMock(
            stdout='{"ui_score": 0.0, "api_score": 0.0, "skip_score": 0.5, "reasoning": "Empty"}',
            stderr="",
            exit_code=0,
        )
        mock_provider.parse_output.return_value = (
            '{"ui_score": 0.0, "api_score": 0.0, "skip_score": 0.5, "reasoning": "Empty"}'
        )

        with patch("bmad_assist.providers.registry.get_provider", return_value=mock_provider):
            detector = ATDDEligibilityDetector(config)
            result = detector.detect("")

        # LLM was called (not skipped)
        mock_provider.invoke.assert_called_once()
        assert result.keyword_score == 0.0

    def test_non_string_input_raises_typeerror(self) -> None:
        """Non-string input raises TypeError (from KeywordScorer)."""
        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        config = EligibilityConfig()
        detector = ATDDEligibilityDetector(config)

        with pytest.raises(TypeError, match="Expected str"):
            detector.detect(None)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="Expected str"):
            detector.detect(123)  # type: ignore[arg-type]


class TestProviderInvocation:
    """Test AC5: Provider integration parameters."""

    def test_provider_invocation_parameters(self) -> None:
        """Provider invoke() called with correct parameters."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        config = EligibilityConfig()

        mock_provider = MagicMock()
        mock_provider.provider_name = "claude"
        mock_provider.invoke.return_value = MagicMock(
            stdout='{"ui_score": 0.5, "api_score": 0.5, "skip_score": 0.0, "reasoning": "Test"}',
            stderr="",
            exit_code=0,
        )
        mock_provider.parse_output.return_value = (
            '{"ui_score": 0.5, "api_score": 0.5, "skip_score": 0.0, "reasoning": "Test"}'
        )

        # Mock helper config
        mock_helper_config = MagicMock()
        mock_helper_config.providers.helper.provider = "claude"
        mock_helper_config.providers.helper.model = "haiku"

        with (
            patch(
                "bmad_assist.providers.registry.get_provider", return_value=mock_provider
            ) as mock_get,
            patch("bmad_assist.core.get_config", return_value=mock_helper_config),
        ):
            detector = ATDDEligibilityDetector(config)
            detector.detect("button component")

        # Verify get_provider was called with correct provider name
        mock_get.assert_called_once_with("claude")

        # Verify invoke parameters
        invoke_call = mock_provider.invoke.call_args
        assert invoke_call.kwargs["model"] == "haiku"
        assert invoke_call.kwargs["timeout"] == 60
        assert invoke_call.kwargs["disable_tools"] is True
        assert invoke_call.kwargs["no_cache"] is True


class TestCombinedReasoning:
    """Test AC8: Combined reasoning output."""

    def test_reasoning_includes_source_attribution(self) -> None:
        """Reasoning includes 'Keyword: X, LLM: Y' format and final decision (AC#8)."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        config = EligibilityConfig()

        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.invoke.return_value = MagicMock(
            stdout='{"ui_score": 0.7, "api_score": 0.5, "skip_score": 0.1, "reasoning": "UI-heavy story"}',
            stderr="",
            exit_code=0,
        )
        mock_provider.parse_output.return_value = (
            '{"ui_score": 0.7, "api_score": 0.5, "skip_score": 0.1, "reasoning": "UI-heavy story"}'
        )

        # Mock helper config
        mock_helper_config = MagicMock()
        mock_helper_config.providers.helper.provider = "claude"
        mock_helper_config.providers.helper.model = "haiku"

        with (
            patch("bmad_assist.providers.registry.get_provider", return_value=mock_provider),
            patch("bmad_assist.core.get_config", return_value=mock_helper_config),
        ):
            detector = ATDDEligibilityDetector(config)
            result = detector.detect("button")

        # Check reasoning format (AC#8)
        assert "Keyword:" in result.reasoning
        assert "LLM:" in result.reasoning
        assert "UI-heavy story" in result.reasoning
        # AC#8: Must include final decision explanation
        assert (
            "Eligible for ATDD" in result.reasoning or "Not eligible for ATDD" in result.reasoning
        )


# =============================================================================
# Integration Tests with Mock Provider (Story testarch-4)
# =============================================================================


class TestIntegrationWithMockProvider:
    """Test AC11: Integration tests with mocked provider."""

    def test_detect_with_mock_provider_full_flow(self) -> None:
        """Full detection flow with mocked LLM."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        json_response = (
            '{"ui_score": 0.7, "api_score": 0.5, "skip_score": 0.1, "reasoning": "UI-heavy story"}'
        )

        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.invoke.return_value = MagicMock(
            stdout=json_response,
            stderr="",
            exit_code=0,
        )
        mock_provider.parse_output.return_value = json_response

        # Mock helper config
        mock_config = MagicMock()
        mock_config.providers.helper.provider = "claude"
        mock_config.providers.helper.model = "haiku"

        with (
            patch("bmad_assist.providers.registry.get_provider", return_value=mock_provider),
            patch("bmad_assist.core.get_config", return_value=mock_config),
        ):
            config = EligibilityConfig()
            detector = ATDDEligibilityDetector(config)
            result = detector.detect("Create a button component")

        # Verify all result fields populated correctly
        assert result.keyword_score > 0  # "button", "component" matched
        assert result.llm_score == pytest.approx((0.7 + 0.5) / 2 - 0.1, abs=0.001)
        assert result.ui_score == 0.7
        assert result.api_score == 0.5
        assert result.skip_score == 0.1
        assert isinstance(result.eligible, bool)
        assert isinstance(result.final_score, float)
        assert isinstance(result.reasoning, str)

        # Verify provider was called
        mock_provider.invoke.assert_called_once()

    def test_full_flow_eligibility_decision(self) -> None:
        """Verify eligibility decision in full flow."""
        from unittest.mock import MagicMock, patch

        from bmad_assist.testarch.config import EligibilityConfig
        from bmad_assist.testarch.eligibility import ATDDEligibilityDetector

        # Scenario: High UI/API, low skip → eligible
        json_response = '{"ui_score": 0.9, "api_score": 0.8, "skip_score": 0.0, "reasoning": "Great ATDD candidate"}'

        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.invoke.return_value = MagicMock(
            stdout=json_response,
            stderr="",
            exit_code=0,
        )
        mock_provider.parse_output.return_value = json_response

        with patch("bmad_assist.providers.registry.get_provider", return_value=mock_provider):
            config = EligibilityConfig(threshold=0.5)
            detector = ATDDEligibilityDetector(config)
            result = detector.detect("Build a form with button and modal dialog")

        # High keyword score (form, button, modal, dialog) + high LLM score
        # Should definitely be eligible
        assert result.eligible is True
        assert result.final_score > 0.5
