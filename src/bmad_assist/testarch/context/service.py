"""TEA Context Service for collecting and injecting TEA artifacts.

This module provides the main service class for TEA context loading.
It orchestrates resolver execution, manages token budgets, and
returns collected artifacts for injection into compiled prompts.

Addresses:
- ADR-3: Return API (dict[str, str] like StrategicContextService)
- ADR-7: Proportional budget allocation (F1 Fix)
- ADR-9: Config access strategy (F5 Fix: constructor injection)
- F6 Fix: Engagement model check before collection
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bmad_assist.compiler.shared_utils import estimate_tokens
from bmad_assist.testarch.context.config import TEAContextConfig
from bmad_assist.testarch.context.resolvers import RESOLVER_REGISTRY
from bmad_assist.testarch.context.resolvers.atdd import ATDDResolver

if TYPE_CHECKING:
    from pathlib import Path

    from bmad_assist.compiler.types import CompilerContext
    from bmad_assist.core.types import EpicId
    from bmad_assist.testarch.config import TestarchConfig

logger = logging.getLogger(__name__)

# Minimum budget allocation per resolver (prevents starvation)
MIN_BUDGET_ALLOCATION = 500


class TEAContextService:
    """Collect TEA artifacts for workflow context injection.

    This service mirrors StrategicContextService in API design:
    - collect() returns dict[str, str] (path -> content)
    - Token budget management with intelligent truncation
    - Can be completely disabled via config

    Usage in workflow compilers:
        testarch_config = getattr(context.config, "testarch", None)
        if testarch_config and testarch_config.context and testarch_config.context.enabled:
            tea_service = TEAContextService(context, "dev_story", testarch_config)
            files.update(tea_service.collect())

    Attributes:
        _context: Compiler context with paths and variables.
        _workflow_name: Current workflow identifier.
        _testarch_config: TEA configuration.

    """

    def __init__(
        self,
        context: CompilerContext,
        workflow_name: str,
        testarch_config: TestarchConfig | None = None,
        resolved: dict[str, object] | None = None,
    ) -> None:
        """Initialize TEA context service.

        Args:
            context: Compiler context with paths and variables.
            workflow_name: Current workflow identifier (e.g., "dev_story").
            testarch_config: TEA configuration (optional, F5 Fix).
            resolved: Resolved variables containing epic_num, story_id, etc.

        """
        self._context = context
        self._workflow_name = workflow_name
        self._testarch_config = testarch_config
        self._resolved = resolved or {}

    @property
    def _tea_context_config(self) -> TEAContextConfig | None:
        """Get TEA context config (lazy, cached)."""
        if self._testarch_config is None:
            return None
        return self._testarch_config.context

    def _check_engagement_model(self) -> bool:
        """Check if TEA is engaged.

        Returns:
            False if engagement_model=off, True otherwise.

        Note (F6 Fix):
            When engagement_model is "off", all TEA features are disabled
            regardless of individual workflow configs.

        """
        if self._testarch_config is None:
            return True  # No testarch config = default behavior

        engagement = getattr(self._testarch_config, "engagement_model", "auto")
        if engagement == "off":
            logger.info("TEA context skipped: engagement_model=off")
            return False
        return True

    def _allocate_budgets(self, artifact_types: list[str]) -> dict[str, int]:
        """Allocate budget proportionally across artifact types.

        Args:
            artifact_types: List of artifact types to allocate budget for.

        Returns:
            Dict mapping artifact type to allocated budget.

        Note (F1 Fix):
            Proportional allocation prevents first resolver from
            consuming entire budget. Each resolver gets fair share
            with minimum floor to prevent starvation.

        """
        config = self._tea_context_config
        if not config:
            return {}

        total_budget = config.budget
        max_per_artifact = config.max_tokens_per_artifact

        # Filter to valid types that have resolvers
        valid_types = [t for t in artifact_types if t in RESOLVER_REGISTRY]
        if not valid_types:
            return {}

        # Simple equal allocation (can be enhanced with size estimation)
        per_type = total_budget // len(valid_types)

        # Apply min floor and max cap
        result: dict[str, int] = {}
        for artifact_type in valid_types:
            allocation = max(MIN_BUDGET_ALLOCATION, min(per_type, max_per_artifact))
            result[artifact_type] = allocation

        return result

    def _get_base_path(self) -> Path:
        """Get base path for TEA artifacts.

        Returns:
            Path to implementation_artifacts (output_folder).
            Resolvers handle subdirectory navigation themselves.

        """
        # Try paths singleton first
        try:
            from bmad_assist.core.paths import get_paths

            path = get_paths().implementation_artifacts
            logger.debug("TEA base path (from paths singleton): %s", path)
            return path
        except RuntimeError:
            # Paths not initialized - use context output_folder as fallback
            logger.debug(
                "TEA base path (fallback to output_folder): %s",
                self._context.output_folder,
            )
            return self._context.output_folder

    def _get_epic_id(self) -> EpicId:
        """Get current epic ID from resolved variables."""
        epic_id = self._resolved.get("epic_num")
        if epic_id is None:
            # Fallback to context resolved variables
            epic_id = self._context.resolved_variables.get("epic_num")
        # Default to empty string if still not found (will result in no matches)
        if epic_id is None:
            return ""
        # Cast to EpicId (int | str)
        if isinstance(epic_id, int):
            return epic_id
        return str(epic_id)

    def _get_story_id(self) -> str | None:
        """Get current story ID from resolved variables."""
        story_id = self._resolved.get("story_id")
        if story_id is None:
            story_id = self._context.resolved_variables.get("story_id")
        return str(story_id) if story_id is not None else None

    def collect(self) -> dict[str, str]:
        """Collect TEA artifacts for the configured workflow.

        Returns:
            Dict mapping file paths to content (same API as StrategicContextService).
            Empty dict if:
            - No config
            - enabled=false
            - budget=0
            - engagement_model=off
            - No artifacts configured for this workflow

        """
        result: dict[str, str] = {}

        # Early returns (ordered by check cost)
        config = self._tea_context_config
        if config is None:
            logger.debug("TEA context: no config")
            return result

        if not config.enabled:
            logger.debug("TEA context: disabled")
            return result

        if config.budget == 0:
            logger.debug("TEA context: zero budget")
            return result

        # F6: Check engagement model
        if not self._check_engagement_model():
            return result

        # Get workflow config
        wf_config = config.get_workflow_config(self._workflow_name)
        if wf_config is None or not wf_config.include:
            logger.debug(
                "TEA context: no artifacts configured for %s",
                self._workflow_name,
            )
            return result

        # F1: Allocate budgets proportionally
        budgets = self._allocate_budgets(wf_config.include)

        # Get context variables (F2: handles int|str epic IDs)
        epic_id = self._get_epic_id()
        story_id = self._get_story_id()
        base_path = self._get_base_path()

        # Track total tokens used
        total_tokens = 0

        # Resolve each artifact type
        for artifact_type in wf_config.include:
            if artifact_type not in RESOLVER_REGISTRY:
                logger.warning("Unknown artifact type: %s", artifact_type)
                continue

            artifact_budget = budgets.get(artifact_type, 0)
            if artifact_budget == 0:
                continue

            resolver_cls = RESOLVER_REGISTRY[artifact_type]

            # ATDDResolver needs special handling for max_files
            if resolver_cls is ATDDResolver:
                resolver = ATDDResolver(
                    base_path,
                    artifact_budget,
                    max_files=config.max_files_per_resolver,
                )
            else:
                resolver = resolver_cls(base_path, artifact_budget)

            try:
                artifacts = resolver.resolve(epic_id, story_id)
                for path, content in artifacts.items():
                    content_tokens = estimate_tokens(content)
                    if total_tokens + content_tokens > config.budget:
                        logger.info(
                            "TEA context: budget exhausted, stopping (%d tokens used)",
                            total_tokens,
                        )
                        return result
                    result[path] = content
                    total_tokens += content_tokens
            except (OSError, ValueError, RuntimeError) as e:
                # F15: Don't let resolver failure block workflow
                # Catch specific exceptions - let KeyboardInterrupt/SystemExit propagate
                logger.error(
                    "TEA resolver %s failed: %s",
                    artifact_type,
                    e,
                )
                continue

        if result:
            logger.info(
                "TEA context collected: %d artifacts, ~%d tokens",
                len(result),
                total_tokens,
            )
        else:
            logger.debug("TEA context: no artifacts collected")

        return result
