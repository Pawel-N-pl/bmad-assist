"""TEA Context Loader package.

This package provides TEA artifact context injection for workflow compilers.
It loads TEA-generated artifacts (test-design, ATDD checklists, test-review,
trace matrix) and injects them into compiled prompts.

Usage:
    from bmad_assist.testarch.context import collect_tea_context

    # In workflow compiler's _build_context_files():
    files.update(collect_tea_context(context, "dev_story", resolved))

Configuration:
    testarch:
      context:
        enabled: true
        budget: 8000
        max_tokens_per_artifact: 4000
        max_files_per_resolver: 10
        workflows:
          dev_story:
            include: [test-design, atdd]
          code_review:
            include: [test-design]
          code_review_synthesis:
            include: [test-review]
          retrospective:
            include: [trace]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bmad_assist.testarch.context.config import (
    TEAContextConfig,
    TEAContextWorkflowConfig,
)

if TYPE_CHECKING:
    from bmad_assist.compiler.types import CompilerContext

# Lazy import TEAContextService to break circular dependency:
# testarch/config.py -> testarch/context/__init__.py -> service.py -> compiler/__init__.py
# -> core/__init__.py -> core/config/__init__.py -> core/config/models/main.py -> testarch/config.py
# Note: This breaks IDE autocompletion for TEAContextService but is necessary for import order.


def __getattr__(name: str) -> object:
    """Lazy load TEAContextService to avoid circular import."""
    if name == "TEAContextService":
        from bmad_assist.testarch.context.service import TEAContextService

        return TEAContextService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def is_tea_context_enabled(context: CompilerContext) -> bool:
    """Check if TEA context is configured and enabled (F1 Fix: DRY helper).

    Args:
        context: Compiler context with config and paths.

    Returns:
        True if TEA context is configured and enabled, False otherwise.

    """
    testarch_config = getattr(context, "config", None)
    if testarch_config:
        testarch_config = getattr(testarch_config, "testarch", None)

    return (
        testarch_config is not None
        and testarch_config.context is not None
        and testarch_config.context.enabled
    )


def collect_tea_context(
    context: CompilerContext,
    workflow_name: str,
    resolved: dict[str, object] | None = None,
) -> dict[str, str]:
    """Collect TEA context artifacts for a workflow (F1 Fix: DRY helper).

    This helper encapsulates the common pattern for TEA context collection
    used across workflow compilers. It handles:
    - Config access (context.config.testarch.context)
    - Enabled check
    - Service instantiation and collection

    Args:
        context: Compiler context with config and paths.
        workflow_name: Workflow identifier (e.g., "dev_story", "code_review").
        resolved: Resolved variables containing epic_num, story_id, etc.

    Returns:
        Dict mapping file paths to content. Empty dict if TEA context
        is not configured or disabled.

    Example:
        # In workflow compiler's _build_context_files():
        files.update(collect_tea_context(context, "dev_story", resolved))

    """
    if not is_tea_context_enabled(context):
        return {}

    # Get testarch config for service
    testarch_config = getattr(context, "config", None)
    if testarch_config:
        testarch_config = getattr(testarch_config, "testarch", None)

    # Import service here to avoid circular import at module level
    from bmad_assist.testarch.context.service import TEAContextService

    tea_service = TEAContextService(context, workflow_name, testarch_config, resolved)
    return tea_service.collect()


__all__ = [
    "TEAContextConfig",
    "TEAContextWorkflowConfig",
    "TEAContextService",
    "collect_tea_context",
    "is_tea_context_enabled",
]
