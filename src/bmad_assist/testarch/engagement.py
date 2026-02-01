"""TEA engagement model logic.

This module provides functions to determine whether TEA workflows should run
based on the configured engagement model.

Story 25.12: Loop Configuration & Phase Registration.

Usage:
    from bmad_assist.testarch.engagement import should_run_workflow

    # In a handler's execute() method:
    if not should_run_workflow("atdd", config.testarch):
        return PhaseResult.ok({"skipped": True, "reason": "..."})

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bmad_assist.testarch.config import TestarchConfig

logger = logging.getLogger(__name__)


# Workflows that run standalone (not requiring full story loop integration)
STANDALONE_WORKFLOWS: set[str] = {
    "framework",
    "ci",
    "automate",
    "test-design",
    "nfr-assess",
}


# Workflow to mode field mapping (matches TestarchConfig field names)
# Keys use kebab-case (e.g., "test-review") for consistency with legacy config field names
WORKFLOW_MODE_FIELDS: dict[str, str] = {
    "atdd": "atdd_mode",
    "test-review": "test_review_on_code_complete",  # Legacy field name
    "trace": "trace_on_epic_complete",  # Legacy field name
    "framework": "framework_mode",
    "ci": "ci_mode",
    "test-design": "test_design_mode",
    "automate": "automate_mode",
    "nfr-assess": "nfr_assess_mode",
}


def should_run_workflow(
    workflow_id: str,
    config: TestarchConfig | None,
) -> bool:
    """Determine if a TEA workflow should run based on engagement model.

    This function is the central decision point for TEA workflow execution.
    It evaluates the engagement model and individual workflow mode settings.

    Priority:
        1. If config is None → return True (backwards compatible)
        2. If engagement_model == "off" → return False for all workflows
        3. If engagement_model == "lite" → return True only for "automate"
        4. If engagement_model == "solo" → return True for standalone workflows
        5. If engagement_model == "integrated" → return True for all workflows
        6. If engagement_model == "auto" → defer to individual workflow mode

    Args:
        workflow_id: Workflow identifier using kebab-case for legacy workflows.
            Valid values: "atdd", "test-review", "trace", "framework", "ci",
            "test-design", "automate", "nfr-assess"
        config: TestarchConfig instance (can be None for backwards compatibility).

    Returns:
        True if workflow should execute, False otherwise.

    Examples:
        >>> from bmad_assist.testarch.config import TestarchConfig

        >>> # No config means run (backwards compatible)
        >>> should_run_workflow("atdd", None)
        True

        >>> # engagement_model="off" disables all workflows
        >>> config = TestarchConfig(engagement_model="off")
        >>> should_run_workflow("atdd", config)
        False

        >>> # engagement_model="lite" only enables automate
        >>> config = TestarchConfig(engagement_model="lite")
        >>> should_run_workflow("automate", config)
        True
        >>> should_run_workflow("atdd", config)
        False

        >>> # engagement_model="solo" enables standalone workflows
        >>> config = TestarchConfig(engagement_model="solo")
        >>> should_run_workflow("framework", config)
        True
        >>> should_run_workflow("atdd", config)  # Not standalone
        False

        >>> # engagement_model="integrated" enables all workflows
        >>> config = TestarchConfig(engagement_model="integrated")
        >>> should_run_workflow("atdd", config)
        True

    """
    if config is None:
        logger.debug("No testarch config, allowing workflow %s", workflow_id)
        return True  # Backwards compatible - no config means run

    # Master switch - if disabled, all workflows are blocked
    if not config.enabled:
        logger.debug("Workflow %s blocked by testarch.enabled=false", workflow_id)
        return False

    model = config.engagement_model

    # engagement_model overrides
    if model == "off":
        logger.debug("Workflow %s blocked by engagement_model=off", workflow_id)
        return False

    if model == "lite":
        # Only automate workflow enabled in lite mode
        result = workflow_id == "automate"
        logger.debug(
            "Workflow %s %s by engagement_model=lite",
            workflow_id,
            "allowed" if result else "blocked",
        )
        return result

    if model == "solo":
        # Only standalone workflows enabled
        result = workflow_id in STANDALONE_WORKFLOWS
        logger.debug(
            "Workflow %s %s by engagement_model=solo (standalone=%s)",
            workflow_id,
            "allowed" if result else "blocked",
            result,
        )
        return result

    if model == "integrated":
        logger.debug("Workflow %s allowed by engagement_model=integrated", workflow_id)
        return True

    # model == "auto" - defer to handler's individual mode check
    # Just return True and let the handler's _execute_with_mode_check handle it
    logger.debug("Workflow %s allowed by engagement_model=auto (defers to handler mode check)", workflow_id)
    return True


__all__ = [
    "STANDALONE_WORKFLOWS",
    "WORKFLOW_MODE_FIELDS",
    "should_run_workflow",
]
