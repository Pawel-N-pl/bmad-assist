"""Tests for workflow-specific knowledge defaults."""

from bmad_assist.testarch.knowledge.defaults import (
    WORKFLOW_KNOWLEDGE_MAP,
    get_workflow_defaults,
)


class TestWorkflowKnowledgeMap:
    """Tests for WORKFLOW_KNOWLEDGE_MAP constant."""

    def test_map_has_expected_workflows(self) -> None:
        """Test that map contains all expected workflows."""
        expected_workflows = {
            "atdd",
            "test-review",
            "trace",
            "framework",
            "nfr-assess",
            "test-design",
            "automate",
            "ci",
            "testarch-atdd",  # Tri-modal compiler workflow
        }
        assert set(WORKFLOW_KNOWLEDGE_MAP.keys()) == expected_workflows

    def test_atdd_workflow_defaults(self) -> None:
        """Test atdd workflow default fragments."""
        defaults = WORKFLOW_KNOWLEDGE_MAP["atdd"]
        assert "fixture-architecture" in defaults
        assert "network-first" in defaults
        assert "test-levels" in defaults
        assert "component-tdd" in defaults

    def test_test_review_workflow_defaults(self) -> None:
        """Test test-review workflow default fragments."""
        defaults = WORKFLOW_KNOWLEDGE_MAP["test-review"]
        assert "test-quality" in defaults
        assert "risk-governance" in defaults
        assert "test-healing-patterns" in defaults

    def test_trace_workflow_defaults(self) -> None:
        """Test trace workflow default fragments."""
        defaults = WORKFLOW_KNOWLEDGE_MAP["trace"]
        assert "risk-governance" in defaults
        assert "probability-impact" in defaults
        assert "test-priorities" in defaults

    def test_framework_workflow_defaults(self) -> None:
        """Test framework workflow default fragments."""
        defaults = WORKFLOW_KNOWLEDGE_MAP["framework"]
        assert "fixture-architecture" in defaults
        assert "playwright-config" in defaults
        assert "overview" in defaults

    def test_nfr_assess_workflow_defaults(self) -> None:
        """Test nfr-assess workflow default fragments."""
        defaults = WORKFLOW_KNOWLEDGE_MAP["nfr-assess"]
        assert "nfr-criteria" in defaults
        assert "probability-impact" in defaults
        assert "risk-governance" in defaults

    def test_test_design_workflow_defaults(self) -> None:
        """Test test-design workflow default fragments."""
        defaults = WORKFLOW_KNOWLEDGE_MAP["test-design"]
        assert "risk-governance" in defaults
        assert "test-priorities" in defaults
        assert "test-levels" in defaults

    def test_automate_workflow_defaults(self) -> None:
        """Test automate workflow default fragments."""
        defaults = WORKFLOW_KNOWLEDGE_MAP["automate"]
        assert "data-factories" in defaults
        assert "network-first" in defaults
        assert "fixture-architecture" in defaults

    def test_ci_workflow_defaults(self) -> None:
        """Test ci workflow default fragments."""
        defaults = WORKFLOW_KNOWLEDGE_MAP["ci"]
        assert "ci-burn-in" in defaults
        assert "selective-testing" in defaults
        assert "burn-in" in defaults


class TestGetWorkflowDefaults:
    """Tests for get_workflow_defaults function."""

    def test_known_workflow(self) -> None:
        """Test getting defaults for known workflow."""
        defaults = get_workflow_defaults("atdd")
        assert defaults == WORKFLOW_KNOWLEDGE_MAP["atdd"]

    def test_unknown_workflow(self) -> None:
        """Test getting defaults for unknown workflow returns empty list."""
        defaults = get_workflow_defaults("unknown-workflow")
        assert defaults == []

    def test_empty_workflow_id(self) -> None:
        """Test getting defaults for empty workflow id returns empty list."""
        defaults = get_workflow_defaults("")
        assert defaults == []

    def test_case_sensitive(self) -> None:
        """Test that workflow lookup is case-sensitive."""
        defaults = get_workflow_defaults("ATDD")
        assert defaults == []

    def test_returns_list_not_reference(self) -> None:
        """Test that returned list is a copy, not the original reference."""
        defaults1 = get_workflow_defaults("atdd")
        defaults2 = get_workflow_defaults("atdd")
        # Should return a copy (different object), not same reference
        assert defaults1 is not defaults2
        # But contents should be equal
        assert defaults1 == defaults2
        # Modifying returned list should not affect global constant
        defaults1.append("test-fragment")
        defaults3 = get_workflow_defaults("atdd")
        assert "test-fragment" not in defaults3
