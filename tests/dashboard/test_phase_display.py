"""Tests for phase name resolution - Story 24.3: Phase Name Resolution from LoopConfig.

Tests verify:
- AC1: Phase display names from PHASE_DISPLAY_NAMES mapping
- AC2: Fallback pattern for unknown phases
- AC3: All standard phases match documented convention
"""


from bmad_assist.dashboard.server import PHASE_DISPLAY_NAMES, _build_phases_from_config

# =============================================================================
# Test: PHASE_DISPLAY_NAMES Mapping - AC1, AC3
# =============================================================================


class TestPhaseDisplayNamesAC1AC3:
    """Tests for PHASE_DISPLAY_NAMES mapping (AC1, AC3)."""

    def test_validate_story_uses_full_name(self) -> None:
        """GIVEN PHASE_DISPLAY_NAMES mapping
        WHEN looking up validate_story
        THEN it returns 'Validate Story' (not 'Validate').
        """
        # AC1: validate_story → "Validate Story"
        assert PHASE_DISPLAY_NAMES["validate_story"] == "Validate Story"

    def test_dev_story_uses_full_name(self) -> None:
        """GIVEN PHASE_DISPLAY_NAMES mapping
        WHEN looking up dev_story
        THEN it returns 'Develop Story' (not 'Develop').
        """
        # AC1: dev_story → "Develop Story"
        assert PHASE_DISPLAY_NAMES["dev_story"] == "Develop Story"

    def test_code_review_uses_full_name(self) -> None:
        """GIVEN PHASE_DISPLAY_NAMES mapping
        WHEN looking up code_review
        THEN it returns 'Code Review' (not 'Review').
        """
        # AC1: code_review → "Code Review"
        assert PHASE_DISPLAY_NAMES["code_review"] == "Code Review"

    def test_create_story_unchanged(self) -> None:
        """GIVEN PHASE_DISPLAY_NAMES mapping
        WHEN looking up create_story
        THEN it returns 'Create Story' (unchanged from before).
        """
        # AC3: create_story → "Create Story"
        assert PHASE_DISPLAY_NAMES["create_story"] == "Create Story"

    def test_synthesis_phases_use_shortcuts(self) -> None:
        """GIVEN PHASE_DISPLAY_NAMES mapping
        WHEN looking up synthesis phases
        THEN they use shortcuts for space constraints.
        """
        # AC3: Synthesis phases use shortcuts
        assert PHASE_DISPLAY_NAMES["validate_story_synthesis"] == "Val Synth"
        assert PHASE_DISPLAY_NAMES["code_review_synthesis"] == "Rev Synth"

    def test_retrospective_unchanged(self) -> None:
        """GIVEN PHASE_DISPLAY_NAMES mapping
        WHEN looking up retrospective
        THEN it returns 'Retrospective' (unchanged).
        """
        # AC3: retrospective → "Retrospective"
        assert PHASE_DISPLAY_NAMES["retrospective"] == "Retrospective"

    def test_all_standard_phases_mapped(self) -> None:
        """GIVEN PHASE_DISPLAY_NAMES mapping
        WHEN checking all standard phases from project_context.md
        THEN they are all present in the mapping.
        """
        # AC3: All standard phases from unified convention table
        standard_phases = [
            "create_story",
            "validate_story",
            "validate_story_synthesis",
            "dev_story",
            "code_review",
            "code_review_synthesis",
            "retrospective",
        ]
        for phase_id in standard_phases:
            assert phase_id in PHASE_DISPLAY_NAMES, f"Missing phase: {phase_id}"


# =============================================================================
# Test: Fallback Behavior - AC2
# =============================================================================


class TestFallbackBehaviorAC2:
    """Tests for fallback pattern when phase not in PHASE_DISPLAY_NAMES (AC2)."""

    def test_unknown_phase_uses_title_case_fallback(self) -> None:
        """GIVEN a phase ID not in PHASE_DISPLAY_NAMES
        WHEN _build_phases_from_config is called
        THEN it applies phase_id.replace('_', ' ').title() fallback.
        """
        # AC2: my_custom_phase → "My Custom Phase"
        result = _build_phases_from_config(["my_custom_phase"])

        assert len(result) == 1
        assert result[0]["id"] == "my_custom_phase"
        assert result[0]["name"] == "My Custom Phase"
        assert result[0]["status"] == "pending"

    def test_single_word_unknown_phase(self) -> None:
        """GIVEN a single-word phase ID not in PHASE_DISPLAY_NAMES
        WHEN _build_phases_from_config is called
        THEN it applies title case.
        """
        # AC2: Fallback for single word
        result = _build_phases_from_config(["testing"])

        assert result[0]["name"] == "Testing"

    def test_multiple_underscores_fallback(self) -> None:
        """GIVEN a phase ID with multiple underscores
        WHEN _build_phases_from_config is called
        THEN it replaces all underscores with spaces.
        """
        # AC2: deep_nested_phase_name → "Deep Nested Phase Name"
        result = _build_phases_from_config(["deep_nested_phase_name"])

        assert result[0]["name"] == "Deep Nested Phase Name"

    def test_mixed_known_and_unknown_phases(self) -> None:
        """GIVEN a mix of known and unknown phases
        WHEN _build_phases_from_config is called
        THEN known phases use mapping, unknown use fallback.
        """
        phases = ["create_story", "custom_phase", "dev_story"]
        result = _build_phases_from_config(phases)

        assert len(result) == 3
        # Known phases use mapping
        assert result[0]["name"] == "Create Story"
        assert result[2]["name"] == "Develop Story"
        # Unknown phase uses fallback
        assert result[1]["name"] == "Custom Phase"


# =============================================================================
# Test: _build_phases_from_config Function
# =============================================================================


class TestBuildPhasesFromConfig:
    """Tests for _build_phases_from_config() function."""

    def test_returns_list_of_phase_dicts(self) -> None:
        """GIVEN a list of phase IDs
        WHEN _build_phases_from_config is called
        THEN it returns list of dicts with id, name, status keys.
        """
        result = _build_phases_from_config(["create_story"])

        assert isinstance(result, list)
        assert len(result) == 1
        assert "id" in result[0]
        assert "name" in result[0]
        assert "status" in result[0]

    def test_status_is_always_pending(self) -> None:
        """GIVEN any list of phase IDs
        WHEN _build_phases_from_config is called
        THEN all phases have status 'pending'.
        """
        phases = ["create_story", "validate_story", "dev_story"]
        result = _build_phases_from_config(phases)

        for phase in result:
            assert phase["status"] == "pending"

    def test_preserves_phase_order(self) -> None:
        """GIVEN an ordered list of phase IDs
        WHEN _build_phases_from_config is called
        THEN the output order matches input order.
        """
        phases = ["code_review", "create_story", "dev_story"]
        result = _build_phases_from_config(phases)

        assert [p["id"] for p in result] == phases

    def test_empty_list_returns_empty_list(self) -> None:
        """GIVEN an empty list
        WHEN _build_phases_from_config is called
        THEN it returns an empty list.
        """
        result = _build_phases_from_config([])

        assert result == []

    def test_full_story_phase_sequence(self) -> None:
        """GIVEN the standard story phase sequence from LoopConfig
        WHEN _build_phases_from_config is called
        THEN all phases have correct display names.
        """
        # Standard story phases from LoopConfig
        story_phases = [
            "create_story",
            "validate_story",
            "validate_story_synthesis",
            "dev_story",
            "code_review",
            "code_review_synthesis",
        ]
        result = _build_phases_from_config(story_phases)

        expected_names = [
            "Create Story",
            "Validate Story",
            "Val Synth",
            "Develop Story",
            "Code Review",
            "Rev Synth",
        ]

        assert [p["name"] for p in result] == expected_names
