"""Workflow-specific knowledge fragment defaults.

This module defines default fragment IDs for each TEA workflow,
enabling automatic loading of relevant knowledge.

Usage:
    from bmad_assist.testarch.knowledge.defaults import WORKFLOW_KNOWLEDGE_MAP

    fragment_ids = WORKFLOW_KNOWLEDGE_MAP.get("atdd", [])
"""

from typing import Final

# Workflow to default fragment IDs mapping
# Source: docs/epics/epic-25-tea-enterprise-integration.md#Story-25.A3
WORKFLOW_KNOWLEDGE_MAP: Final[dict[str, list[str]]] = {
    # ATDD workflow: fixture patterns, network handling, test levels, component TDD
    "atdd": [
        "fixture-architecture",
        "network-first",
        "test-levels",
        "component-tdd",
    ],
    # Test review workflow: quality criteria, risk governance, healing patterns
    "test-review": [
        "test-quality",
        "risk-governance",
        "test-healing-patterns",
    ],
    # Trace workflow: risk governance, probability/impact, priorities
    "trace": [
        "risk-governance",
        "probability-impact",
        "test-priorities",
    ],
    # Framework setup workflow: fixtures, Playwright config, overview
    "framework": [
        "fixture-architecture",
        "playwright-config",
        "overview",
    ],
    # NFR assessment workflow: NFR criteria, probability/impact, risk
    "nfr-assess": [
        "nfr-criteria",
        "probability-impact",
        "risk-governance",
    ],
    # Test design workflow: risk, priorities, test levels
    "test-design": [
        "risk-governance",
        "test-priorities",
        "test-levels",
    ],
    # Test automation workflow: data factories, network, fixtures
    "automate": [
        "data-factories",
        "network-first",
        "fixture-architecture",
    ],
    # CI workflow: burn-in, selective testing
    "ci": [
        "ci-burn-in",
        "selective-testing",
        "burn-in",
    ],
    # Testarch ATDD workflow (tri-modal compiler) - same as atdd
    "testarch-atdd": [
        "fixture-architecture",
        "network-first",
        "test-levels",
        "component-tdd",
    ],
}


def get_workflow_defaults(workflow_id: str) -> list[str]:
    """Get default fragment IDs for a workflow.

    Args:
        workflow_id: Workflow identifier (e.g., "atdd", "test-review").

    Returns:
        List of fragment IDs for the workflow, or empty list if unknown.
        Returns a copy to prevent mutation of global state.

    """
    defaults = WORKFLOW_KNOWLEDGE_MAP.get(workflow_id, [])
    return list(defaults)  # Return shallow copy to prevent mutation
