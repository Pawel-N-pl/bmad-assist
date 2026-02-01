"""Centralized output extraction for TEA workflows.

This module provides extraction functions for parsing LLM output from TEA workflows.
Each function uses regex patterns optimized for common output formats from LLM providers.

Functions:
    extract_checklist_path: Extract ATDD checklist path from output
    extract_quality_score: Extract test quality score (0-100)
    extract_gate_decision: Extract gate decision (PASS/CONCERNS/FAIL/WAIVED)

Usage:
    from bmad_assist.testarch.core.extraction import (
        extract_checklist_path,
        extract_quality_score,
        extract_gate_decision,
    )

    # Extract from LLM output
    checklist = extract_checklist_path(output)
    score = extract_quality_score(output)
    decision = extract_gate_decision(output)

"""

from __future__ import annotations

import re

__all__ = [
    "ATDD_CHECKLIST_PATTERNS",
    "QUALITY_SCORE_PATTERNS",
    "GATE_DECISION_OPTIONS",
    "FRAMEWORK_TYPE_OPTIONS",
    "CI_PLATFORM_OPTIONS",
    "DESIGN_LEVEL_OPTIONS",
    "AUTOMATION_STATUS_OPTIONS",
    "NFR_STATUS_OPTIONS",
    "NFR_DOMAIN_OPTIONS",
    "extract_checklist_path",
    "extract_quality_score",
    "extract_gate_decision",
    "extract_framework_type",
    "extract_ci_platform",
    "extract_design_level",
    "extract_risk_count",
    "extract_automation_status",
    "extract_test_count",
    "extract_nfr_overall_status",
    "extract_nfr_blocked_domains",
]


# =============================================================================
# Pattern Constants
# =============================================================================

# Patterns for extracting ATDD checklist paths
# Priority: explicit "saved/written/created" patterns first, then generic
ATDD_CHECKLIST_PATTERNS: list[str] = [
    r"(?:saved|written|created|checklist).*?[:\s]+([^\s]+atdd-checklist[^\s]*\.md)",
    r"([^\s]+atdd-checklist[^\s]*\.md)",
    r"(?:output|file)[:\s]+([^\s]+\.md)",
]

# Patterns for extracting quality scores (0-100)
# Handles markdown bold, optional colon, slash notation
QUALITY_SCORE_PATTERNS: list[str] = [
    r"\*?\*?[Qq]uality [Ss]core\*?\*?:?\s*(\d{1,3})\s*/\s*100",  # Quality Score: 87/100
    r"\*?\*?[Ss]core\*?\*?:?\s*(\d{1,3})\s*/\s*100",  # Score: 87/100
    r"(\d{1,3})\s*/\s*100\s*\(",  # 87/100 (
]

# Gate decision options in priority order (strictest first)
# FAIL > CONCERNS > PASS > WAIVED
GATE_DECISION_OPTIONS: list[str] = ["FAIL", "CONCERNS", "PASS", "WAIVED"]

# Framework type options for testarch-framework workflow (Story 25.9)
FRAMEWORK_TYPE_OPTIONS: list[str] = ["playwright", "cypress"]

# CI platform options for testarch-ci workflow (Story 25.9)
# Priority order: github > gitlab > circleci > azure > jenkins
CI_PLATFORM_OPTIONS: list[str] = ["github", "gitlab", "circleci", "azure", "jenkins"]

# Design level options for testarch-test-design workflow (Story 25.10)
DESIGN_LEVEL_OPTIONS: list[str] = ["system", "epic"]

# Patterns for design level detection (system vs epic)
# System-level patterns (more specific, checked first)
DESIGN_LEVEL_SYSTEM_PATTERNS: list[str] = [
    r"(?:system[- ]?level|architecture review|testability assessment)",
    r"(?:test-design-architecture|test-design-qa)",
    r"(?:architectural concerns|NFR requirements)",
]

# Epic-level patterns
DESIGN_LEVEL_EPIC_PATTERNS: list[str] = [
    r"(?:epic[- ]?level|epic \d+|test design for epic)",
    r"(?:test-design-epic-\d+)",
    r"(?:per[- ]?epic test plan)",
]

# Risk count extraction pattern
RISK_COUNT_PATTERN: str = r"(?:total risks?|risks? identified)[:\s]*(\d+)"

# Story 25.11: Automation status options (priority order: strictest first)
AUTOMATION_STATUS_OPTIONS: list[str] = ["CONCERNS", "PARTIAL", "PASS"]

# Story 25.11: NFR overall status options (priority order: strictest first)
NFR_STATUS_OPTIONS: list[str] = ["FAIL", "CONCERNS", "PASS"]

# Story 25.11: NFR domain options (aligned with epic-25 specification)
NFR_DOMAIN_OPTIONS: list[str] = ["security", "performance", "reliability", "maintainability"]

# Story 25.11: Test count extraction pattern
TEST_COUNT_PATTERN: str = r"(?:total tests?|tests? (?:created|generated))[:\s]*(\d+)"

# Story 25.11: Blocked domains extraction pattern
BLOCKED_DOMAINS_PATTERN: str = r"(?:blocked|failed)[- ]?(?:domains?|categories?)[:\s]*([^\n]+)"


# =============================================================================
# Extraction Functions
# =============================================================================


def extract_checklist_path(output: str) -> str | None:
    """Extract ATDD checklist file path from workflow output.

    Searches for common patterns indicating where the checklist was saved.
    Uses multiple patterns to handle different output formats.

    Args:
        output: Raw workflow output from provider.

    Returns:
        Path to checklist file or None if not found.

    Examples:
        >>> extract_checklist_path("Saved to: /path/atdd-checklist.md")
        '/path/atdd-checklist.md'
        >>> extract_checklist_path("Tests generated successfully")
        None

    """
    if not output or not output.strip():
        return None

    for pattern in ATDD_CHECKLIST_PATTERNS:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            path = match.group(1).strip()
            # Basic sanity check - path should contain path separator or extension
            if "/" in path or "\\" in path or "." in path:
                return path

    return None


def extract_quality_score(output: str) -> int | None:
    """Extract quality score (0-100) from test review workflow output.

    Searches for patterns like "Quality Score: 87/100" or "**Score**: 78/100".
    Validates that the score is within the 0-100 range.

    Args:
        output: Raw workflow output from provider.

    Returns:
        Quality score as integer (0-100) or None if not found or invalid.

    Examples:
        >>> extract_quality_score("Quality Score: 87/100 (A - Good)")
        87
        >>> extract_quality_score("**Quality Score**: 78/100")
        78
        >>> extract_quality_score("Quality Score: 150/100")  # Out of range
        None

    """
    if not output or not output.strip():
        return None

    for pattern in QUALITY_SCORE_PATTERNS:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            try:
                score = int(match.group(1))
                if 0 <= score <= 100:
                    return score
            except (ValueError, IndexError):
                continue

    return None


def extract_gate_decision(output: str) -> str | None:
    """Extract gate decision from trace workflow output.

    Searches for PASS, FAIL, CONCERNS, or WAIVED using word boundaries
    to avoid partial matches (e.g., "PASSED" won't match "PASS").

    Returns the highest priority match:
    - FAIL (highest priority)
    - CONCERNS
    - PASS
    - WAIVED (lowest priority)

    Args:
        output: Raw workflow output from provider.

    Returns:
        Gate decision string or None if not found.

    Examples:
        >>> extract_gate_decision("Gate Decision: PASS")
        'PASS'
        >>> extract_gate_decision("Result: PASS on A, FAIL on B")
        'FAIL'  # FAIL has priority
        >>> extract_gate_decision("Tests PASSED successfully")
        None  # "PASSED" != "PASS"

    """
    if not output or not output.strip():
        return None

    # Check options in priority order (FAIL > CONCERNS > PASS > WAIVED)
    for option in GATE_DECISION_OPTIONS:
        # Use word boundary to avoid partial matches
        pattern = rf"\b{re.escape(option)}\b"
        if re.search(pattern, output, re.IGNORECASE):
            return option

    return None


def extract_framework_type(output: str) -> str | None:
    """Extract framework type from testarch-framework workflow output.

    Searches for "playwright" or "cypress" using word boundaries.
    Returns the first match found (priority: playwright > cypress).

    Args:
        output: Raw workflow output from provider.

    Returns:
        Framework type string ("playwright" or "cypress") or None if not found.

    Examples:
        >>> extract_framework_type("Initialized Playwright framework")
        'playwright'
        >>> extract_framework_type("Cypress config created successfully")
        'cypress'
        >>> extract_framework_type("No framework specified")
        None

    """
    if not output or not output.strip():
        return None

    # Check options in priority order (playwright > cypress)
    for option in FRAMEWORK_TYPE_OPTIONS:
        pattern = rf"\b{re.escape(option)}\b"
        if re.search(pattern, output, re.IGNORECASE):
            return option

    return None


def extract_ci_platform(output: str) -> str | None:
    """Extract CI platform from testarch-ci workflow output.

    Searches for CI platform names using word boundaries.
    Returns the first match found with priority: github > gitlab > circleci > azure > jenkins.

    Args:
        output: Raw workflow output from provider.

    Returns:
        CI platform string or None if not found.

    Examples:
        >>> extract_ci_platform("Created GitHub Actions workflow")
        'github'
        >>> extract_ci_platform("GitLab CI configuration saved")
        'gitlab'
        >>> extract_ci_platform("Both GitHub and GitLab configured")
        'github'  # github has priority
        >>> extract_ci_platform("No CI platform detected")
        None

    """
    if not output or not output.strip():
        return None

    # Check options in priority order (github > gitlab > circleci > azure > jenkins)
    for option in CI_PLATFORM_OPTIONS:
        pattern = rf"\b{re.escape(option)}\b"
        if re.search(pattern, output, re.IGNORECASE):
            return option

    return None


def extract_design_level(output: str) -> str | None:
    """Extract design level from testarch-test-design workflow output.

    Searches for patterns indicating system-level or epic-level test design.
    System-level patterns are checked first as they are more specific.

    Args:
        output: Raw workflow output from provider.

    Returns:
        Design level string ("system" or "epic") or None if not found.

    Examples:
        >>> extract_design_level("Performing system-level testability assessment")
        'system'
        >>> extract_design_level("Created test-design-architecture.md")
        'system'
        >>> extract_design_level("Test design for Epic 25")
        'epic'
        >>> extract_design_level("Generated test-design-epic-25.md")
        'epic'
        >>> extract_design_level("No design context")
        None

    """
    if not output or not output.strip():
        return None

    # Check system-level patterns first (more specific)
    for pattern in DESIGN_LEVEL_SYSTEM_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            return "system"

    # Check epic-level patterns
    for pattern in DESIGN_LEVEL_EPIC_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            return "epic"

    return None


def extract_risk_count(output: str) -> int | None:
    """Extract total risk count from test design workflow output.

    Searches for patterns like "Total Risks: 5" or "Risks Identified: 12".

    Args:
        output: Raw workflow output from provider.

    Returns:
        Risk count as integer or None if not found.

    Examples:
        >>> extract_risk_count("Total Risks: 5")
        5
        >>> extract_risk_count("Risks identified: 12 (3 high, 5 medium, 4 low)")
        12
        >>> extract_risk_count("No risks documented")
        None

    """
    if not output or not output.strip():
        return None

    match = re.search(RISK_COUNT_PATTERN, output, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except (ValueError, IndexError):
            pass

    return None


# =============================================================================
# Story 25.11: Automation and NFR Assessment Extraction Functions
# =============================================================================


def extract_automation_status(output: str) -> str | None:
    """Extract automation status from testarch-automate workflow output.

    Uses word boundary matching with priority: CONCERNS > PARTIAL > PASS.
    Returns first match found by priority order.

    Args:
        output: Raw workflow output from provider.

    Returns:
        Automation status string ("CONCERNS", "PARTIAL", or "PASS") or None.

    Examples:
        >>> extract_automation_status("Automation Status: PASS")
        'PASS'
        >>> extract_automation_status("Results: PASS on API, CONCERNS on E2E")
        'CONCERNS'  # CONCERNS has priority
        >>> extract_automation_status("No automation results")
        None

    """
    if not output or not output.strip():
        return None

    # Check options in priority order (strictest first: CONCERNS > PARTIAL > PASS)
    for option in AUTOMATION_STATUS_OPTIONS:
        pattern = rf"\b{re.escape(option)}\b"
        if re.search(pattern, output, re.IGNORECASE):
            return option

    return None


def extract_test_count(output: str) -> int | None:
    """Extract total test count from automation workflow output.

    Searches for patterns like "Total Tests: 15" or "Tests Created: 42".

    Args:
        output: Raw workflow output from provider.

    Returns:
        Test count as integer or None if not found.

    Examples:
        >>> extract_test_count("Total Tests: 15")
        15
        >>> extract_test_count("Tests generated: 42 (20 E2E, 22 API)")
        42
        >>> extract_test_count("No tests created")
        None

    """
    if not output or not output.strip():
        return None

    match = re.search(TEST_COUNT_PATTERN, output, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except (ValueError, IndexError):
            pass

    return None


def extract_nfr_overall_status(output: str) -> str | None:
    """Extract NFR overall status from assessment workflow output.

    Uses word boundary matching with priority: FAIL > CONCERNS > PASS.
    Returns first match found by priority order.

    Args:
        output: Raw workflow output from provider.

    Returns:
        NFR status string ("FAIL", "CONCERNS", or "PASS") or None.

    Examples:
        >>> extract_nfr_overall_status("Overall Status: PASS")
        'PASS'
        >>> extract_nfr_overall_status("Result: PASS on security, FAIL on performance")
        'FAIL'  # FAIL has priority
        >>> extract_nfr_overall_status("No NFR assessment results")
        None

    """
    if not output or not output.strip():
        return None

    # Check options in priority order (strictest first: FAIL > CONCERNS > PASS)
    for option in NFR_STATUS_OPTIONS:
        pattern = rf"\b{re.escape(option)}\b"
        if re.search(pattern, output, re.IGNORECASE):
            return option

    return None


def extract_nfr_blocked_domains(output: str) -> list[str]:
    """Extract blocked NFR domains from assessment output.

    Searches for patterns like "Blocked domains: security, performance"
    or "Failed categories: reliability and maintainability".

    Returns list of valid domain names (lowercase, trimmed).
    Handles comma, semicolon, and "and" separators.
    Filters against NFR_DOMAIN_OPTIONS for validity.

    Args:
        output: Raw workflow output from provider.

    Returns:
        List of valid blocked domain names. Empty list if none found.

    Examples:
        >>> extract_nfr_blocked_domains("Blocked domains: security, performance")
        ['security', 'performance']
        >>> extract_nfr_blocked_domains("Failed categories: reliability and maintainability")
        ['reliability', 'maintainability']
        >>> extract_nfr_blocked_domains("No blocked domains")
        []

    """
    if not output or not output.strip():
        return []

    match = re.search(BLOCKED_DOMAINS_PATTERN, output, re.IGNORECASE)
    if match:
        domains_str = match.group(1)
        # Split by comma, semicolon, or "and"
        domains = re.split(r"[,;]|\band\b", domains_str)
        # Clean and filter against valid options
        valid_domains = []
        for d in domains:
            cleaned = d.strip().lower()
            if cleaned and cleaned in NFR_DOMAIN_OPTIONS:
                valid_domains.append(cleaned)
        return valid_domains
    return []
