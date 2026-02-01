"""TEA Core module for centralized variable resolution and output extraction.

This module provides the core TEA infrastructure for all 8 TEA workflows:
- Variable resolution (CI platform detection, review scope)
- Output extraction (checklist paths, quality scores, gate decisions)

Usage:
    from bmad_assist.testarch.core import (
        TEAVariableResolver,
        detect_ci_platform,
        resolve_review_scope,
        CIPlatform,
        ReviewScope,
        # Extraction functions
        extract_checklist_path,
        extract_quality_score,
        extract_gate_decision,
    )

    # Create resolver instance
    resolver = TEAVariableResolver()

    # Resolve all TEA variables for a workflow
    resolved = resolver.resolve_all(context, "testarch-atdd")

    # Detect CI platform
    platform = detect_ci_platform(project_root)

    # Resolve review scope
    scope = resolve_review_scope(context)

    # Extract from LLM output
    checklist = extract_checklist_path(output)
    score = extract_quality_score(output)
    decision = extract_gate_decision(output)
"""

from bmad_assist.testarch.core.extraction import (
    ATDD_CHECKLIST_PATTERNS,
    AUTOMATION_STATUS_OPTIONS,
    CI_PLATFORM_OPTIONS,
    DESIGN_LEVEL_OPTIONS,
    FRAMEWORK_TYPE_OPTIONS,
    GATE_DECISION_OPTIONS,
    NFR_DOMAIN_OPTIONS,
    NFR_STATUS_OPTIONS,
    QUALITY_SCORE_PATTERNS,
    extract_automation_status,
    extract_checklist_path,
    extract_ci_platform,
    extract_design_level,
    extract_framework_type,
    extract_gate_decision,
    extract_nfr_blocked_domains,
    extract_nfr_overall_status,
    extract_quality_score,
    extract_risk_count,
    extract_test_count,
)
from bmad_assist.testarch.core.types import CIPlatform, ReviewScope
from bmad_assist.testarch.core.variables import (
    TEAVariableResolver,
    detect_ci_platform,
    resolve_review_scope,
)

__all__ = [
    # Types
    "CIPlatform",
    "ReviewScope",
    # Variable resolution
    "TEAVariableResolver",
    "detect_ci_platform",
    "resolve_review_scope",
    # Extraction functions
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
    # Extraction patterns
    "ATDD_CHECKLIST_PATTERNS",
    "QUALITY_SCORE_PATTERNS",
    "GATE_DECISION_OPTIONS",
    "FRAMEWORK_TYPE_OPTIONS",
    "CI_PLATFORM_OPTIONS",
    "DESIGN_LEVEL_OPTIONS",
    "AUTOMATION_STATUS_OPTIONS",
    "NFR_STATUS_OPTIONS",
    "NFR_DOMAIN_OPTIONS",
]