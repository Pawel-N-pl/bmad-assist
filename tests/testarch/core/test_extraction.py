"""Tests for testarch/core/extraction.py module.

This module tests centralized extraction functions for TEA workflows:
- extract_checklist_path: Extract ATDD checklist path from output
- extract_quality_score: Extract test quality score (0-100)
- extract_gate_decision: Extract gate decision (PASS/CONCERNS/FAIL/WAIVED)
"""

import pytest


# =============================================================================
# extract_checklist_path tests
# =============================================================================


class TestExtractChecklistPath:
    """Tests for extract_checklist_path function."""

    def test_extract_with_saved_prefix(self) -> None:
        """Extract path with 'saved' keyword."""
        from bmad_assist.testarch.core.extraction import extract_checklist_path

        output = "ATDD checklist saved to: /path/to/atdd-checklist-1.1.md"
        assert extract_checklist_path(output) == "/path/to/atdd-checklist-1.1.md"

    def test_extract_with_written_prefix(self) -> None:
        """Extract path with 'written' keyword."""
        from bmad_assist.testarch.core.extraction import extract_checklist_path

        output = "File written to: output/atdd-checklist-2.1.md"
        assert extract_checklist_path(output) == "output/atdd-checklist-2.1.md"

    def test_extract_with_created_prefix(self) -> None:
        """Extract path with 'created' keyword."""
        from bmad_assist.testarch.core.extraction import extract_checklist_path

        output = "Checklist created: tests/atdd-checklist-story.md"
        assert extract_checklist_path(output) == "tests/atdd-checklist-story.md"

    def test_extract_plain_path(self) -> None:
        """Extract plain path without context."""
        from bmad_assist.testarch.core.extraction import extract_checklist_path

        output = "Generated: /project/atdd-checklist-epic1.md and saved."
        assert extract_checklist_path(output) == "/project/atdd-checklist-epic1.md"

    def test_extract_with_output_keyword(self) -> None:
        """Extract path with 'output' keyword."""
        from bmad_assist.testarch.core.extraction import extract_checklist_path

        output = "Output file: results/atdd-checklist.md"
        assert extract_checklist_path(output) == "results/atdd-checklist.md"

    def test_returns_none_when_not_found(self) -> None:
        """Return None when no checklist path found."""
        from bmad_assist.testarch.core.extraction import extract_checklist_path

        output = "ATDD tests generated successfully."
        assert extract_checklist_path(output) is None

    def test_returns_none_for_empty_output(self) -> None:
        """Return None for empty output."""
        from bmad_assist.testarch.core.extraction import extract_checklist_path

        assert extract_checklist_path("") is None
        assert extract_checklist_path("   ") is None

    def test_extracts_first_valid_path(self) -> None:
        """Extract first valid path when multiple present."""
        from bmad_assist.testarch.core.extraction import extract_checklist_path

        output = "Saved to: first/atdd-checklist.md\nAlso at: second/atdd-checklist.md"
        # Should return first match
        result = extract_checklist_path(output)
        assert "atdd-checklist" in result


# =============================================================================
# extract_quality_score tests
# =============================================================================


class TestExtractQualityScore:
    """Tests for extract_quality_score function."""

    def test_extract_simple_format(self) -> None:
        """Extract score from 'Quality Score: 87/100'."""
        from bmad_assist.testarch.core.extraction import extract_quality_score

        output = "Test Quality Review\n\nQuality Score: 87/100 (A - Good)"
        assert extract_quality_score(output) == 87

    def test_extract_bold_format(self) -> None:
        """Extract score from '**Quality Score**: 78/100'."""
        from bmad_assist.testarch.core.extraction import extract_quality_score

        output = "## Summary\n\n**Quality Score**: 78/100 (B - Acceptable)"
        assert extract_quality_score(output) == 78

    def test_extract_with_parens(self) -> None:
        """Extract score from '92/100 ('."""
        from bmad_assist.testarch.core.extraction import extract_quality_score

        output = "Final verdict: 92/100 (A+ - Excellent)"
        assert extract_quality_score(output) == 92

    def test_extract_score_format(self) -> None:
        """Extract score from 'Score: 75/100'."""
        from bmad_assist.testarch.core.extraction import extract_quality_score

        output = "Score: 75/100 - needs improvement"
        assert extract_quality_score(output) == 75

    def test_returns_none_when_not_found(self) -> None:
        """Return None when no score found."""
        from bmad_assist.testarch.core.extraction import extract_quality_score

        output = "Test review completed successfully."
        assert extract_quality_score(output) is None

    def test_returns_none_for_out_of_range(self) -> None:
        """Return None for score > 100."""
        from bmad_assist.testarch.core.extraction import extract_quality_score

        output = "Quality Score: 150/100"
        assert extract_quality_score(output) is None

    def test_returns_none_for_negative(self) -> None:
        """Return None for negative score."""
        from bmad_assist.testarch.core.extraction import extract_quality_score

        # This is a malformed edge case
        output = "Score: -5/100"
        assert extract_quality_score(output) is None

    def test_extracts_first_valid_score(self) -> None:
        """Extract first valid score when multiple present."""
        from bmad_assist.testarch.core.extraction import extract_quality_score

        output = "Quality Score: 85/100\nOther Score: 90/100"
        assert extract_quality_score(output) == 85

    def test_returns_none_for_empty_output(self) -> None:
        """Return None for empty output."""
        from bmad_assist.testarch.core.extraction import extract_quality_score

        assert extract_quality_score("") is None
        assert extract_quality_score("   ") is None

    def test_case_insensitive(self) -> None:
        """Score extraction is case insensitive."""
        from bmad_assist.testarch.core.extraction import extract_quality_score

        output = "quality score: 80/100"
        assert extract_quality_score(output) == 80

    def test_boundary_values(self) -> None:
        """Test boundary values 0 and 100."""
        from bmad_assist.testarch.core.extraction import extract_quality_score

        assert extract_quality_score("Quality Score: 0/100") == 0
        assert extract_quality_score("Quality Score: 100/100") == 100


# =============================================================================
# extract_gate_decision tests
# =============================================================================


class TestExtractGateDecision:
    """Tests for extract_gate_decision function."""

    def test_extract_pass(self) -> None:
        """Extract PASS from output."""
        from bmad_assist.testarch.core.extraction import extract_gate_decision

        output = "Analysis complete. Gate Decision: PASS\n\nMatrix generated."
        assert extract_gate_decision(output) == "PASS"

    def test_extract_fail(self) -> None:
        """Extract FAIL from output."""
        from bmad_assist.testarch.core.extraction import extract_gate_decision

        output = "Requirements missing. Gate Decision: FAIL"
        assert extract_gate_decision(output) == "FAIL"

    def test_extract_concerns(self) -> None:
        """Extract CONCERNS from output."""
        from bmad_assist.testarch.core.extraction import extract_gate_decision

        output = "Some issues found. Gate Decision: CONCERNS"
        assert extract_gate_decision(output) == "CONCERNS"

    def test_extract_waived(self) -> None:
        """Extract WAIVED from output."""
        from bmad_assist.testarch.core.extraction import extract_gate_decision

        output = "Manual override. Gate Decision: WAIVED"
        assert extract_gate_decision(output) == "WAIVED"

    def test_case_insensitive(self) -> None:
        """Extraction is case insensitive."""
        from bmad_assist.testarch.core.extraction import extract_gate_decision

        assert extract_gate_decision("gate: pass") == "PASS"
        assert extract_gate_decision("gate: Pass") == "PASS"
        assert extract_gate_decision("gate: PASS") == "PASS"

    def test_avoids_partial_matches(self) -> None:
        """Avoid partial matches like PASSED, FAILING."""
        from bmad_assist.testarch.core.extraction import extract_gate_decision

        # "PASSED" should not match "PASS" - requires word boundary
        output = "Tests PASSED successfully"
        assert extract_gate_decision(output) is None

    def test_priority_fail_over_pass(self) -> None:
        """FAIL has priority over PASS if both present."""
        from bmad_assist.testarch.core.extraction import extract_gate_decision

        output = "Result: PASS on module A, FAIL on module B"
        assert extract_gate_decision(output) == "FAIL"

    def test_priority_fail_over_concerns(self) -> None:
        """FAIL has priority over CONCERNS if both present."""
        from bmad_assist.testarch.core.extraction import extract_gate_decision

        output = "Some CONCERNS but critical FAIL detected"
        assert extract_gate_decision(output) == "FAIL"

    def test_priority_concerns_over_pass(self) -> None:
        """CONCERNS has priority over PASS if both present."""
        from bmad_assist.testarch.core.extraction import extract_gate_decision

        output = "Module A: PASS, Module B: CONCERNS"
        assert extract_gate_decision(output) == "CONCERNS"

    def test_returns_none_when_not_found(self) -> None:
        """Return None when no decision found."""
        from bmad_assist.testarch.core.extraction import extract_gate_decision

        output = "No decision in this output"
        assert extract_gate_decision(output) is None

    def test_returns_none_for_empty_output(self) -> None:
        """Return None for empty output."""
        from bmad_assist.testarch.core.extraction import extract_gate_decision

        assert extract_gate_decision("") is None
        assert extract_gate_decision("   ") is None


# =============================================================================
# Module-level tests
# =============================================================================


class TestModuleExports:
    """Test module exports and documentation."""

    def test_all_functions_exported(self) -> None:
        """All extraction functions are exported."""
        from bmad_assist.testarch.core import extraction

        assert hasattr(extraction, "extract_checklist_path")
        assert hasattr(extraction, "extract_quality_score")
        assert hasattr(extraction, "extract_gate_decision")

    def test_functions_are_callable(self) -> None:
        """All exported functions are callable."""
        from bmad_assist.testarch.core.extraction import (
            extract_checklist_path,
            extract_gate_decision,
            extract_quality_score,
        )

        assert callable(extract_checklist_path)
        assert callable(extract_quality_score)
        assert callable(extract_gate_decision)

    def test_patterns_constants_available(self) -> None:
        """Pattern constants are available for reference."""
        from bmad_assist.testarch.core.extraction import (
            ATDD_CHECKLIST_PATTERNS,
            CI_PLATFORM_OPTIONS,
            FRAMEWORK_TYPE_OPTIONS,
            GATE_DECISION_OPTIONS,
            QUALITY_SCORE_PATTERNS,
        )

        assert isinstance(ATDD_CHECKLIST_PATTERNS, list)
        assert isinstance(QUALITY_SCORE_PATTERNS, list)
        assert isinstance(GATE_DECISION_OPTIONS, list)
        assert isinstance(FRAMEWORK_TYPE_OPTIONS, list)
        assert isinstance(CI_PLATFORM_OPTIONS, list)


# =============================================================================
# extract_framework_type tests (Story 25.9)
# =============================================================================


class TestExtractFrameworkType:
    """Tests for extract_framework_type function."""

    def test_extract_playwright(self) -> None:
        """Extract playwright from output."""
        from bmad_assist.testarch.core.extraction import extract_framework_type

        output = "Initialized Playwright framework successfully."
        assert extract_framework_type(output) == "playwright"

    def test_extract_cypress(self) -> None:
        """Extract cypress from output."""
        from bmad_assist.testarch.core.extraction import extract_framework_type

        output = "Cypress configuration created and saved."
        assert extract_framework_type(output) == "cypress"

    def test_case_insensitive_playwright(self) -> None:
        """Extraction is case insensitive for playwright."""
        from bmad_assist.testarch.core.extraction import extract_framework_type

        assert extract_framework_type("PLAYWRIGHT config ready") == "playwright"
        assert extract_framework_type("Playwright tests setup") == "playwright"
        assert extract_framework_type("playwright initialized") == "playwright"

    def test_case_insensitive_cypress(self) -> None:
        """Extraction is case insensitive for cypress."""
        from bmad_assist.testarch.core.extraction import extract_framework_type

        assert extract_framework_type("CYPRESS config ready") == "cypress"
        assert extract_framework_type("Cypress tests setup") == "cypress"
        assert extract_framework_type("cypress initialized") == "cypress"

    def test_playwright_priority_over_cypress(self) -> None:
        """playwright has priority over cypress if both present."""
        from bmad_assist.testarch.core.extraction import extract_framework_type

        output = "Considered Cypress but chose Playwright for E2E."
        assert extract_framework_type(output) == "playwright"

    def test_uses_word_boundaries(self) -> None:
        """Extraction uses word boundaries."""
        from bmad_assist.testarch.core.extraction import extract_framework_type

        # 'playwrighter' should not match 'playwright'
        output = "Using playwrighter library"
        assert extract_framework_type(output) is None

    def test_returns_none_when_not_found(self) -> None:
        """Return None when no framework type found."""
        from bmad_assist.testarch.core.extraction import extract_framework_type

        output = "Framework setup complete."
        assert extract_framework_type(output) is None

    def test_returns_none_for_empty_output(self) -> None:
        """Return None for empty output."""
        from bmad_assist.testarch.core.extraction import extract_framework_type

        assert extract_framework_type("") is None
        assert extract_framework_type("   ") is None

    def test_extract_from_markdown_output(self) -> None:
        """Extract framework type from markdown formatted output."""
        from bmad_assist.testarch.core.extraction import extract_framework_type

        output = """
## Framework Setup Complete

The **Playwright** framework has been configured with:
- chromium browser
- 30s timeout
"""
        assert extract_framework_type(output) == "playwright"

    def test_extract_from_plain_text_output(self) -> None:
        """Extract framework type from plain text output."""
        from bmad_assist.testarch.core.extraction import extract_framework_type

        output = "Created cypress.config.ts and e2e/ directory structure"
        assert extract_framework_type(output) == "cypress"


# =============================================================================
# extract_ci_platform tests (Story 25.9)
# =============================================================================


class TestExtractCIPlatform:
    """Tests for extract_ci_platform function."""

    def test_extract_github(self) -> None:
        """Extract github from output."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        output = "Created GitHub Actions workflow in .github/workflows/"
        assert extract_ci_platform(output) == "github"

    def test_extract_gitlab(self) -> None:
        """Extract gitlab from output."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        output = "GitLab CI configuration saved to .gitlab-ci.yml"
        assert extract_ci_platform(output) == "gitlab"

    def test_extract_circleci(self) -> None:
        """Extract circleci from output."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        output = "CircleCI config created at .circleci/config.yml"
        assert extract_ci_platform(output) == "circleci"

    def test_extract_azure(self) -> None:
        """Extract azure from output."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        output = "Azure Pipelines YAML created"
        assert extract_ci_platform(output) == "azure"

    def test_extract_jenkins(self) -> None:
        """Extract jenkins from output."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        output = "Jenkins pipeline Jenkinsfile created"
        assert extract_ci_platform(output) == "jenkins"

    def test_case_insensitive(self) -> None:
        """Extraction is case insensitive."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        assert extract_ci_platform("GITHUB actions ready") == "github"
        assert extract_ci_platform("Github workflow created") == "github"
        assert extract_ci_platform("GITLAB ci configured") == "gitlab"

    def test_priority_order_github_over_gitlab(self) -> None:
        """github has priority over gitlab if both present."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        output = "Both GitHub and GitLab configured for CI/CD"
        assert extract_ci_platform(output) == "github"

    def test_priority_order_gitlab_over_circleci(self) -> None:
        """gitlab has priority over circleci if both present."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        output = "GitLab and CircleCI configs generated"
        assert extract_ci_platform(output) == "gitlab"

    def test_uses_word_boundaries(self) -> None:
        """Extraction uses word boundaries."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        # 'githubber' should not match 'github'
        output = "Using githubber tool"
        assert extract_ci_platform(output) is None

    def test_returns_none_when_not_found(self) -> None:
        """Return None when no CI platform found."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        output = "CI/CD pipeline configured."
        assert extract_ci_platform(output) is None

    def test_returns_none_for_empty_output(self) -> None:
        """Return None for empty output."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        assert extract_ci_platform("") is None
        assert extract_ci_platform("   ") is None

    def test_extract_from_markdown_output(self) -> None:
        """Extract CI platform from markdown formatted output."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        output = """
## CI Pipeline Setup

The **GitHub** Actions workflow has been configured with:
- test job
- build job
- deploy job
"""
        assert extract_ci_platform(output) == "github"

    def test_extract_from_plain_text_output(self) -> None:
        """Extract CI platform from plain text output."""
        from bmad_assist.testarch.core.extraction import extract_ci_platform

        output = "Created .gitlab-ci.yml with test stages"
        assert extract_ci_platform(output) == "gitlab"


class TestFrameworkCIConstantsValues:
    """Test that constants have correct values."""

    def test_framework_type_options_values(self) -> None:
        """FRAMEWORK_TYPE_OPTIONS has correct values."""
        from bmad_assist.testarch.core.extraction import FRAMEWORK_TYPE_OPTIONS

        assert FRAMEWORK_TYPE_OPTIONS == ["playwright", "cypress"]

    def test_ci_platform_options_values(self) -> None:
        """CI_PLATFORM_OPTIONS has correct priority order."""
        from bmad_assist.testarch.core.extraction import CI_PLATFORM_OPTIONS

        assert CI_PLATFORM_OPTIONS == ["github", "gitlab", "circleci", "azure", "jenkins"]

    def test_design_level_options_values(self) -> None:
        """DESIGN_LEVEL_OPTIONS has correct values."""
        from bmad_assist.testarch.core.extraction import DESIGN_LEVEL_OPTIONS

        assert DESIGN_LEVEL_OPTIONS == ["system", "epic"]


# =============================================================================
# extract_design_level tests (Story 25.10)
# =============================================================================


class TestExtractDesignLevel:
    """Tests for extract_design_level function."""

    def test_extract_system_level_from_assessment(self) -> None:
        """Extract system from 'testability assessment' output."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        output = "Performing system-level testability assessment for the project."
        assert extract_design_level(output) == "system"

    def test_extract_system_level_from_architecture_review(self) -> None:
        """Extract system from 'architecture review' output."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        output = "This architecture review identified several testability concerns."
        assert extract_design_level(output) == "system"

    def test_extract_system_level_from_filename(self) -> None:
        """Extract system from test-design-architecture filename."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        output = "Created test-design-architecture.md and test-design-qa.md"
        assert extract_design_level(output) == "system"

    def test_extract_system_level_from_nfr(self) -> None:
        """Extract system from 'NFR requirements' output."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        output = "NFR requirements have been analyzed for testability."
        assert extract_design_level(output) == "system"

    def test_extract_system_level_case_insensitive(self) -> None:
        """Extraction is case insensitive for system level."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        assert extract_design_level("SYSTEM-LEVEL design complete") == "system"
        assert extract_design_level("System Level testability done") == "system"
        assert extract_design_level("system level review") == "system"

    def test_extract_epic_level_from_text(self) -> None:
        """Extract epic from 'epic-level' output."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        output = "This epic-level test plan covers stories 1-5."
        assert extract_design_level(output) == "epic"

    def test_extract_epic_level_from_epic_number(self) -> None:
        """Extract epic from 'Epic 25' output."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        output = "Test design for Epic 25 completed."
        assert extract_design_level(output) == "epic"

    def test_extract_epic_level_from_filename(self) -> None:
        """Extract epic from test-design-epic filename."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        output = "Created test-design-epic-25.md with risk matrix."
        assert extract_design_level(output) == "epic"

    def test_extract_epic_level_from_per_epic_plan(self) -> None:
        """Extract epic from 'per-epic test plan' output."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        output = "Generated per-epic test plan for implementation phase."
        assert extract_design_level(output) == "epic"

    def test_extract_epic_level_case_insensitive(self) -> None:
        """Extraction is case insensitive for epic level."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        assert extract_design_level("EPIC-LEVEL design complete") == "epic"
        assert extract_design_level("Epic Level planning done") == "epic"
        assert extract_design_level("Test design for epic 10") == "epic"

    def test_system_priority_over_epic(self) -> None:
        """System-level has priority over epic-level if both present."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        output = "System-level review for Epic 25 architecture."
        assert extract_design_level(output) == "system"

    def test_returns_none_when_not_found(self) -> None:
        """Return None when no design level found."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        output = "Test plan generated successfully."
        assert extract_design_level(output) is None

    def test_returns_none_for_empty_output(self) -> None:
        """Return None for empty output."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        assert extract_design_level("") is None
        assert extract_design_level("   ") is None

    def test_extract_from_markdown_output(self) -> None:
        """Extract design level from markdown formatted output."""
        from bmad_assist.testarch.core.extraction import extract_design_level

        output = """
## Test Design Complete

The **system-level** testability assessment has been completed:
- Architecture review: PASS
- NFR analysis: CONCERNS
"""
        assert extract_design_level(output) == "system"


# =============================================================================
# extract_risk_count tests (Story 25.10)
# =============================================================================


class TestExtractRiskCount:
    """Tests for extract_risk_count function."""

    def test_extract_total_risks(self) -> None:
        """Extract count from 'Total Risks: 5'."""
        from bmad_assist.testarch.core.extraction import extract_risk_count

        output = "## Risk Summary\n\nTotal Risks: 5 (2 high, 2 medium, 1 low)"
        assert extract_risk_count(output) == 5

    def test_extract_risks_identified(self) -> None:
        """Extract count from 'Risks identified: 12'."""
        from bmad_assist.testarch.core.extraction import extract_risk_count

        output = "Risks identified: 12"
        assert extract_risk_count(output) == 12

    def test_extract_risk_singular(self) -> None:
        """Extract count from 'Risk identified: 1'."""
        from bmad_assist.testarch.core.extraction import extract_risk_count

        output = "Risk identified: 1"
        assert extract_risk_count(output) == 1

    def test_case_insensitive(self) -> None:
        """Extraction is case insensitive."""
        from bmad_assist.testarch.core.extraction import extract_risk_count

        assert extract_risk_count("TOTAL RISKS: 8") == 8
        assert extract_risk_count("total risks: 3") == 3
        assert extract_risk_count("Risks Identified: 7") == 7

    def test_extract_with_spaces(self) -> None:
        """Extract count with various spacing."""
        from bmad_assist.testarch.core.extraction import extract_risk_count

        assert extract_risk_count("Total Risks:  10") == 10
        assert extract_risk_count("Total Risks : 15") == 15
        assert extract_risk_count("Risks identified   25") == 25

    def test_extract_first_match(self) -> None:
        """Extract first risk count when multiple present."""
        from bmad_assist.testarch.core.extraction import extract_risk_count

        output = "Total Risks: 5\nRisks Identified: 10"
        assert extract_risk_count(output) == 5

    def test_returns_none_when_not_found(self) -> None:
        """Return None when no risk count found."""
        from bmad_assist.testarch.core.extraction import extract_risk_count

        output = "Risk assessment complete. No issues."
        assert extract_risk_count(output) is None

    def test_returns_none_for_empty_output(self) -> None:
        """Return None for empty output."""
        from bmad_assist.testarch.core.extraction import extract_risk_count

        assert extract_risk_count("") is None
        assert extract_risk_count("   ") is None

    def test_extract_zero_risks(self) -> None:
        """Extract zero risk count."""
        from bmad_assist.testarch.core.extraction import extract_risk_count

        output = "Total Risks: 0 - No risks identified."
        assert extract_risk_count(output) == 0

    def test_extract_from_markdown_output(self) -> None:
        """Extract risk count from markdown formatted output."""
        from bmad_assist.testarch.core.extraction import extract_risk_count

        output = """
## Risk Matrix

| Category | Count |
|----------|-------|
| High     | 2     |
| Medium   | 5     |
| Low      | 3     |

**Total Risks: 10**
"""
        assert extract_risk_count(output) == 10


# =============================================================================
# extract_automation_status tests (Story 25.11)
# =============================================================================


class TestExtractAutomationStatus:
    """Tests for extract_automation_status function."""

    def test_extract_pass(self) -> None:
        """Extract PASS from automation output."""
        from bmad_assist.testarch.core.extraction import extract_automation_status

        output = "Automation complete. Status: PASS - all tests generated."
        assert extract_automation_status(output) == "PASS"

    def test_extract_partial(self) -> None:
        """Extract PARTIAL from automation output."""
        from bmad_assist.testarch.core.extraction import extract_automation_status

        output = "Some tests created. Automation Status: PARTIAL"
        assert extract_automation_status(output) == "PARTIAL"

    def test_extract_concerns(self) -> None:
        """Extract CONCERNS from automation output."""
        from bmad_assist.testarch.core.extraction import extract_automation_status

        output = "Issues found during automation. Status: CONCERNS"
        assert extract_automation_status(output) == "CONCERNS"

    def test_case_insensitive(self) -> None:
        """Extraction is case insensitive."""
        from bmad_assist.testarch.core.extraction import extract_automation_status

        assert extract_automation_status("status: pass") == "PASS"
        assert extract_automation_status("status: Pass") == "PASS"
        assert extract_automation_status("status: PASS") == "PASS"

    def test_priority_concerns_over_partial(self) -> None:
        """CONCERNS has priority over PARTIAL if both present."""
        from bmad_assist.testarch.core.extraction import extract_automation_status

        output = "PARTIAL success but CONCERNS about coverage"
        assert extract_automation_status(output) == "CONCERNS"

    def test_priority_partial_over_pass(self) -> None:
        """PARTIAL has priority over PASS if both present."""
        from bmad_assist.testarch.core.extraction import extract_automation_status

        output = "Module A: PASS, Module B: PARTIAL"
        assert extract_automation_status(output) == "PARTIAL"

    def test_uses_word_boundaries(self) -> None:
        """Extraction uses word boundaries."""
        from bmad_assist.testarch.core.extraction import extract_automation_status

        # 'PASSING' should not match 'PASS'
        output = "Tests are PASSING"
        assert extract_automation_status(output) is None

    def test_returns_none_when_not_found(self) -> None:
        """Return None when no status found."""
        from bmad_assist.testarch.core.extraction import extract_automation_status

        output = "Automation completed successfully."
        assert extract_automation_status(output) is None

    def test_returns_none_for_empty_output(self) -> None:
        """Return None for empty output."""
        from bmad_assist.testarch.core.extraction import extract_automation_status

        assert extract_automation_status("") is None
        assert extract_automation_status("   ") is None

    def test_extract_from_markdown_output(self) -> None:
        """Extract automation status from markdown formatted output."""
        from bmad_assist.testarch.core.extraction import extract_automation_status

        output = """
## Automation Summary

**Status**: PASS

Tests generated: 25
Coverage: 85%
"""
        assert extract_automation_status(output) == "PASS"


# =============================================================================
# extract_test_count tests (Story 25.11)
# =============================================================================


class TestExtractTestCount:
    """Tests for extract_test_count function."""

    def test_extract_total_tests(self) -> None:
        """Extract count from 'Total Tests: 25'."""
        from bmad_assist.testarch.core.extraction import extract_test_count

        output = "## Summary\n\nTotal Tests: 25 generated."
        assert extract_test_count(output) == 25

    def test_extract_tests_created(self) -> None:
        """Extract count from 'Tests created: 15'."""
        from bmad_assist.testarch.core.extraction import extract_test_count

        output = "Tests created: 15 for component A."
        assert extract_test_count(output) == 15

    def test_extract_tests_generated(self) -> None:
        """Extract count from 'tests generated: 30'."""
        from bmad_assist.testarch.core.extraction import extract_test_count

        output = "Successfully tests generated: 30"
        assert extract_test_count(output) == 30

    def test_case_insensitive(self) -> None:
        """Extraction is case insensitive."""
        from bmad_assist.testarch.core.extraction import extract_test_count

        assert extract_test_count("TOTAL TESTS: 10") == 10
        assert extract_test_count("Total Tests: 20") == 20
        assert extract_test_count("tests created: 5") == 5

    def test_extract_with_colon_variations(self) -> None:
        """Extract count with various spacing around colon."""
        from bmad_assist.testarch.core.extraction import extract_test_count

        assert extract_test_count("Total Tests:  15") == 15
        assert extract_test_count("Total Tests : 20") == 20
        assert extract_test_count("Total Tests:25") == 25

    def test_extract_first_match(self) -> None:
        """Extract first test count when multiple present."""
        from bmad_assist.testarch.core.extraction import extract_test_count

        output = "Total Tests: 10\nTests created: 20"
        assert extract_test_count(output) == 10

    def test_returns_none_when_not_found(self) -> None:
        """Return None when no test count found."""
        from bmad_assist.testarch.core.extraction import extract_test_count

        output = "Tests have been created successfully."
        assert extract_test_count(output) is None

    def test_returns_none_for_empty_output(self) -> None:
        """Return None for empty output."""
        from bmad_assist.testarch.core.extraction import extract_test_count

        assert extract_test_count("") is None
        assert extract_test_count("   ") is None

    def test_extract_zero_tests(self) -> None:
        """Extract zero test count."""
        from bmad_assist.testarch.core.extraction import extract_test_count

        output = "Total Tests: 0 - no tests needed."
        assert extract_test_count(output) == 0

    def test_extract_from_markdown_output(self) -> None:
        """Extract test count from markdown formatted output."""
        from bmad_assist.testarch.core.extraction import extract_test_count

        output = """
## Automation Report

**Total Tests: 42**

| Metric     | Value |
|------------|-------|
| Pass Rate  | 100%  |
"""
        assert extract_test_count(output) == 42


# =============================================================================
# extract_nfr_overall_status tests (Story 25.11)
# =============================================================================


class TestExtractNFROverallStatus:
    """Tests for extract_nfr_overall_status function."""

    def test_extract_pass(self) -> None:
        """Extract PASS from NFR assessment output."""
        from bmad_assist.testarch.core.extraction import extract_nfr_overall_status

        output = "NFR Assessment complete. Overall Status: PASS"
        assert extract_nfr_overall_status(output) == "PASS"

    def test_extract_concerns(self) -> None:
        """Extract CONCERNS from NFR assessment output."""
        from bmad_assist.testarch.core.extraction import extract_nfr_overall_status

        output = "Some issues found. NFR Status: CONCERNS"
        assert extract_nfr_overall_status(output) == "CONCERNS"

    def test_extract_fail(self) -> None:
        """Extract FAIL from NFR assessment output."""
        from bmad_assist.testarch.core.extraction import extract_nfr_overall_status

        output = "Critical issues. NFR Assessment: FAIL"
        assert extract_nfr_overall_status(output) == "FAIL"

    def test_case_insensitive(self) -> None:
        """Extraction is case insensitive."""
        from bmad_assist.testarch.core.extraction import extract_nfr_overall_status

        assert extract_nfr_overall_status("status: pass") == "PASS"
        assert extract_nfr_overall_status("status: Pass") == "PASS"
        assert extract_nfr_overall_status("status: FAIL") == "FAIL"

    def test_priority_fail_over_concerns(self) -> None:
        """FAIL has priority over CONCERNS if both present."""
        from bmad_assist.testarch.core.extraction import extract_nfr_overall_status

        output = "Security: CONCERNS, Performance: FAIL"
        assert extract_nfr_overall_status(output) == "FAIL"

    def test_priority_concerns_over_pass(self) -> None:
        """CONCERNS has priority over PASS if both present."""
        from bmad_assist.testarch.core.extraction import extract_nfr_overall_status

        output = "Reliability: PASS, Security: CONCERNS"
        assert extract_nfr_overall_status(output) == "CONCERNS"

    def test_uses_word_boundaries(self) -> None:
        """Extraction uses word boundaries."""
        from bmad_assist.testarch.core.extraction import extract_nfr_overall_status

        # 'PASSED' should not match 'PASS'
        output = "All tests PASSED successfully"
        assert extract_nfr_overall_status(output) is None

    def test_returns_none_when_not_found(self) -> None:
        """Return None when no status found."""
        from bmad_assist.testarch.core.extraction import extract_nfr_overall_status

        output = "NFR assessment completed."
        assert extract_nfr_overall_status(output) is None

    def test_returns_none_for_empty_output(self) -> None:
        """Return None for empty output."""
        from bmad_assist.testarch.core.extraction import extract_nfr_overall_status

        assert extract_nfr_overall_status("") is None
        assert extract_nfr_overall_status("   ") is None

    def test_extract_from_markdown_output(self) -> None:
        """Extract NFR status from markdown formatted output."""
        from bmad_assist.testarch.core.extraction import extract_nfr_overall_status

        output = """
## NFR Assessment Summary

**Overall Status**: CONCERNS

- Performance: PASS
- Security: CONCERNS
- Reliability: PASS
"""
        assert extract_nfr_overall_status(output) == "CONCERNS"


# =============================================================================
# extract_nfr_blocked_domains tests (Story 25.11)
# =============================================================================


class TestExtractNFRBlockedDomains:
    """Tests for extract_nfr_blocked_domains function."""

    def test_extract_single_domain(self) -> None:
        """Extract single blocked domain."""
        from bmad_assist.testarch.core.extraction import extract_nfr_blocked_domains

        output = "Blocked Domains: security"
        assert extract_nfr_blocked_domains(output) == ["security"]

    def test_extract_multiple_domains(self) -> None:
        """Extract multiple blocked domains."""
        from bmad_assist.testarch.core.extraction import extract_nfr_blocked_domains

        output = "Blocked Domains: security, performance"
        result = extract_nfr_blocked_domains(output)
        assert "security" in result
        assert "performance" in result

    def test_extract_failed_categories(self) -> None:
        """Extract from 'Failed Categories:' format."""
        from bmad_assist.testarch.core.extraction import extract_nfr_blocked_domains

        output = "Failed Categories: reliability, maintainability"
        result = extract_nfr_blocked_domains(output)
        assert "reliability" in result
        assert "maintainability" in result

    def test_extract_all_domains(self) -> None:
        """Extract all four domain types."""
        from bmad_assist.testarch.core.extraction import extract_nfr_blocked_domains

        output = "Blocked domains: security, performance, reliability, maintainability"
        result = extract_nfr_blocked_domains(output)
        assert len(result) == 4
        assert "security" in result
        assert "performance" in result
        assert "reliability" in result
        assert "maintainability" in result

    def test_case_insensitive(self) -> None:
        """Extraction is case insensitive."""
        from bmad_assist.testarch.core.extraction import extract_nfr_blocked_domains

        output = "BLOCKED DOMAINS: SECURITY, Performance"
        result = extract_nfr_blocked_domains(output)
        assert "security" in result
        assert "performance" in result

    def test_filters_invalid_domains(self) -> None:
        """Only return valid domain names."""
        from bmad_assist.testarch.core.extraction import extract_nfr_blocked_domains

        output = "Blocked domains: security, unknown, performance"
        result = extract_nfr_blocked_domains(output)
        assert "security" in result
        assert "performance" in result
        assert "unknown" not in result

    def test_returns_empty_list_when_not_found(self) -> None:
        """Return empty list when no blocked domains found."""
        from bmad_assist.testarch.core.extraction import extract_nfr_blocked_domains

        output = "NFR assessment: all domains passed."
        assert extract_nfr_blocked_domains(output) == []

    def test_returns_empty_list_for_empty_output(self) -> None:
        """Return empty list for empty output."""
        from bmad_assist.testarch.core.extraction import extract_nfr_blocked_domains

        assert extract_nfr_blocked_domains("") == []
        assert extract_nfr_blocked_domains("   ") == []

    def test_extract_from_markdown_output(self) -> None:
        """Extract blocked domains from markdown formatted output."""
        from bmad_assist.testarch.core.extraction import extract_nfr_blocked_domains

        output = """
## NFR Assessment

Blocked Domains: security, performance
These domains require attention before release.
"""
        result = extract_nfr_blocked_domains(output)
        assert "security" in result
        assert "performance" in result

    def test_handles_hyphenated_format(self) -> None:
        """Handle 'blocked-domains:' hyphenated format."""
        from bmad_assist.testarch.core.extraction import extract_nfr_blocked_domains

        output = "blocked-domains: security"
        assert extract_nfr_blocked_domains(output) == ["security"]


# =============================================================================
# Story 25.11 Constants tests
# =============================================================================


class TestStory2511Constants:
    """Test that Story 25.11 constants have correct values."""

    def test_automation_status_options_values(self) -> None:
        """AUTOMATION_STATUS_OPTIONS has correct priority order."""
        from bmad_assist.testarch.core.extraction import AUTOMATION_STATUS_OPTIONS

        # Priority: CONCERNS > PARTIAL > PASS (strictest first)
        assert AUTOMATION_STATUS_OPTIONS == ["CONCERNS", "PARTIAL", "PASS"]

    def test_nfr_status_options_values(self) -> None:
        """NFR_STATUS_OPTIONS has correct priority order."""
        from bmad_assist.testarch.core.extraction import NFR_STATUS_OPTIONS

        # Priority: FAIL > CONCERNS > PASS (strictest first)
        assert NFR_STATUS_OPTIONS == ["FAIL", "CONCERNS", "PASS"]

    def test_nfr_domain_options_values(self) -> None:
        """NFR_DOMAIN_OPTIONS has correct domain values."""
        from bmad_assist.testarch.core.extraction import NFR_DOMAIN_OPTIONS

        assert NFR_DOMAIN_OPTIONS == [
            "security",
            "performance",
            "reliability",
            "maintainability",
        ]

    def test_test_count_pattern_available(self) -> None:
        """TEST_COUNT_PATTERN constant is available."""
        from bmad_assist.testarch.core.extraction import TEST_COUNT_PATTERN

        assert isinstance(TEST_COUNT_PATTERN, str)
        assert "tests?" in TEST_COUNT_PATTERN.lower()

    def test_blocked_domains_pattern_available(self) -> None:
        """BLOCKED_DOMAINS_PATTERN constant is available."""
        from bmad_assist.testarch.core.extraction import BLOCKED_DOMAINS_PATTERN

        assert isinstance(BLOCKED_DOMAINS_PATTERN, str)
        assert "blocked" in BLOCKED_DOMAINS_PATTERN.lower()
