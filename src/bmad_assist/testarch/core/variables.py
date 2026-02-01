"""TEA Variable Resolution for all TEA workflows.

This module provides centralized variable resolution for all 8 TEA workflows,
including CI platform detection, review scope resolution, and caching.

Usage:
    from bmad_assist.testarch.core.variables import (
        TEAVariableResolver,
        detect_ci_platform,
        resolve_review_scope,
    )

    # Create resolver instance
    resolver = TEAVariableResolver()

    # Resolve all TEA variables for a workflow
    resolved = resolver.resolve_all(context, "testarch-atdd")

    # Detect CI platform
    platform = detect_ci_platform(project_root)

    # Resolve review scope
    scope = resolve_review_scope(context)
"""

import hashlib
import logging
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from bmad_assist.testarch.core.types import CIPlatform, ReviewScope

if TYPE_CHECKING:
    from bmad_assist.compiler.types import CompilerContext
    from bmad_assist.testarch.config import TestarchConfig

logger = logging.getLogger(__name__)


# Duplicate is_tea_workflow here to avoid circular import with compiler package
# (testarch -> compiler -> core.config -> testarch)
def is_tea_workflow(workflow_name: str) -> bool:
    """Check if workflow is a TEA workflow.

    TEA workflows are identified by the "testarch-" prefix.

    Args:
        workflow_name: Workflow name.

    Returns:
        True if workflow is a TEA workflow.

    """
    return workflow_name.startswith("testarch-") if workflow_name else False


def detect_ci_platform(project_root: Path) -> str:
    """Detect CI platform from project structure.

    Searches for CI configuration files in the following order:
    1. `.github/workflows/*.yml` or `*.yaml` → "github"
    2. `.gitlab-ci.yml` → "gitlab"
    3. `.circleci/config.yml` → "circleci"
    4. `azure-pipelines.yml` → "azure"
    5. `Jenkinsfile` → "jenkins"
    6. None found → "unknown"

    Args:
        project_root: Project root directory.

    Returns:
        CI platform identifier string (e.g., "github", "gitlab", "unknown").

    """
    # Check for GitHub Actions (must have actual workflow files)
    workflows_dir = project_root / ".github/workflows"
    if workflows_dir.is_dir():
        yml_files = list(workflows_dir.glob("*.yml"))
        yaml_files = list(workflows_dir.glob("*.yaml"))
        if yml_files or yaml_files:
            logger.debug("Detected GitHub Actions CI")
            return CIPlatform.GITHUB.value

    # Check for GitLab CI
    if (project_root / ".gitlab-ci.yml").exists():
        logger.debug("Detected GitLab CI")
        return CIPlatform.GITLAB.value

    # Check for CircleCI
    circleci_config = project_root / ".circleci/config.yml"
    if circleci_config.exists():
        logger.debug("Detected CircleCI")
        return CIPlatform.CIRCLECI.value

    # Check for Azure Pipelines
    if (project_root / "azure-pipelines.yml").exists():
        logger.debug("Detected Azure Pipelines")
        return CIPlatform.AZURE.value

    # Check for Jenkins
    if (project_root / "Jenkinsfile").exists():
        logger.debug("Detected Jenkins")
        return CIPlatform.JENKINS.value

    logger.debug("No CI platform detected")
    return CIPlatform.UNKNOWN.value


def resolve_review_scope(
    context: "CompilerContext",
    test_dir: str | None = None,
) -> str:
    """Resolve review scope from context.

    Determines the review scope based on available context:
    1. If `story_file` is provided → "single" (single story review)
    2. If `test_dir` points to a subdirectory of tests/ → "directory"
    3. Default → "suite" (full test suite review)

    Args:
        context: Compiler context with resolved variables.
        test_dir: Optional explicit test directory path.

    Returns:
        Review scope identifier string ("single", "directory", or "suite").

    """
    # If story_file is provided, it's a single story review
    if context.resolved_variables.get("story_file"):
        return ReviewScope.SINGLE.value

    # Check test_dir for directory-level review
    # Use pathlib for robust path analysis
    dir_to_check = test_dir or context.resolved_variables.get("test_dir")
    if dir_to_check:
        test_path = Path(dir_to_check)
        # Check if it's a subdirectory of tests/ (not tests/ itself)
        parts = test_path.parts
        if "tests" in parts and test_path.name != "tests":
            return ReviewScope.DIRECTORY.value

    # Default: full suite review
    return ReviewScope.SUITE.value


class TEAVariableResolver:
    """Centralized TEA variable resolution with caching.

    Resolves all TEA-specific variables for any TEA workflow, using a
    priority-ordered cascade and thread-safe caching.

    Resolution priority (highest to lowest):
    1. Handler context (runtime values)
    2. Workflow-specific patch variables
    3. defaults-testarch.yaml variables
    4. TestarchConfig values
    5. PathsConfig / BmadConfig values (lowest priority)

    Usage:
        resolver = TEAVariableResolver()
        resolved = resolver.resolve_all(context, "testarch-atdd")

    """

    def __init__(self) -> None:
        """Initialize the resolver with empty cache.

        Cache stores tuples of (config_hash, resolved_variables) to support
        per-entry invalidation when TestarchConfig changes.
        """
        self._cache: dict[tuple[Path, str], tuple[str, dict[str, Any]]] = {}
        self._cache_lock = Lock()

    def clear_cache(self) -> None:
        """Clear the resolution cache.

        Thread-safe: Uses lock to prevent race conditions.
        """
        with self._cache_lock:
            self._cache.clear()
            logger.debug("TEAVariableResolver cache cleared")

    def _compute_config_hash(self, testarch_config: "TestarchConfig | None") -> str:
        """Compute hash of TestarchConfig for cache invalidation.

        Args:
            testarch_config: TestarchConfig instance, or None.

        Returns:
            SHA256 hash of config JSON, or empty string if no config.

        """
        if testarch_config is None:
            return ""
        try:
            config_json = testarch_config.model_dump_json()
            return hashlib.sha256(config_json.encode()).hexdigest()[:16]
        except Exception as e:
            logger.warning("Failed to compute config hash: %s", e)
            return ""

    def _get_testarch_config(
        self, context: "CompilerContext"
    ) -> "TestarchConfig | None":
        """Get TestarchConfig from bmad-assist config.

        Args:
            context: Compiler context.

        Returns:
            TestarchConfig instance, or None if not configured.

        """
        try:
            from bmad_assist.core.config import get_config

            config = get_config()
            return config.testarch
        except Exception as e:
            logger.debug("Failed to get TestarchConfig: %s", e)
            return None

    def _resolve_universal_variables(
        self,
        context: "CompilerContext",
        testarch_config: "TestarchConfig | None",
    ) -> dict[str, Any]:
        """Resolve universal TEA variables.

        Universal variables are used by all TEA workflows:
        - {project-root}: Project root path
        - {communication_language}: Communication language
        - {knowledgeIndex}: Path to TEA knowledge index CSV
        - {config_source}: bmad-assist.yaml
        - {test_dir}: Test directory location
        - {implementation_artifacts}: Implementation artifacts path
        - {tea_use_playwright_utils}: Playwright utils flag
        - {tea_use_mcp_enhancements}: MCP enhancements flag

        Args:
            context: Compiler context.
            testarch_config: TestarchConfig instance.

        Returns:
            Dictionary of resolved universal variables.

        """
        resolved: dict[str, Any] = {}

        # project-root from context or PathsConfig
        resolved["project-root"] = str(context.project_root)

        # communication_language from config or default
        resolved["communication_language"] = context.resolved_variables.get(
            "communication_language", "English"
        )

        # config_source is always bmad-assist.yaml
        resolved["config_source"] = "bmad-assist.yaml"

        # test_dir from TestarchConfig or default
        if testarch_config is not None:
            resolved["test_dir"] = testarch_config.test_dir
        else:
            resolved["test_dir"] = "tests/"

        # implementation_artifacts from context
        resolved["implementation_artifacts"] = str(context.output_folder)

        # TEA feature flags from TestarchConfig.knowledge or defaults
        if testarch_config is not None and testarch_config.knowledge is not None:
            knowledge = testarch_config.knowledge
            resolved["tea_use_playwright_utils"] = knowledge.playwright_utils
            resolved["tea_use_mcp_enhancements"] = knowledge.mcp_enhancements
        else:
            resolved["tea_use_playwright_utils"] = True
            resolved["tea_use_mcp_enhancements"] = True

        # knowledgeIndex - resolved via existing TEA variable resolution
        from bmad_assist.compiler.variables.tea import resolve_knowledge_index

        ki_path = resolve_knowledge_index(context.project_root)
        if ki_path:
            resolved["knowledgeIndex"] = ki_path

        return resolved

    def _resolve_workflow_variables(
        self,
        context: "CompilerContext",
        workflow_id: str,
        testarch_config: "TestarchConfig | None",
    ) -> dict[str, Any]:
        """Resolve workflow-specific TEA variables.

        Workflow-specific variables vary by workflow:
        - testarch-atdd: {story_file}
        - testarch-test-review: {review_scope}
        - testarch-ci: {ci_platform}
        - testarch-trace: {story_file}

        Args:
            context: Compiler context.
            workflow_id: Workflow identifier.
            testarch_config: TestarchConfig instance.

        Returns:
            Dictionary of resolved workflow-specific variables.

        """
        resolved: dict[str, Any] = {}

        # story_file from context (used by atdd, trace)
        if workflow_id in ("testarch-atdd", "testarch-trace"):
            story_file = context.resolved_variables.get("story_file")
            if story_file:
                resolved["story_file"] = story_file

        # review_scope for test-review workflow
        if workflow_id == "testarch-test-review":
            test_dir = None
            if testarch_config is not None:
                test_dir = testarch_config.test_dir
            resolved["review_scope"] = resolve_review_scope(context, test_dir)

        # ci_platform for ci workflow
        if workflow_id == "testarch-ci":
            # Check TestarchConfig for override (if ci_platform field exists)
            # For now, just use auto-detection
            resolved["ci_platform"] = detect_ci_platform(context.project_root)

        return resolved

    def resolve_all(
        self,
        context: "CompilerContext",
        workflow_id: str,
    ) -> dict[str, Any]:
        """Resolve all TEA variables for a workflow.

        Uses priority-ordered cascade:
        1. Handler context (runtime values) - highest priority
        2. Workflow-specific patch variables
        3. defaults-testarch.yaml variables
        4. TestarchConfig values
        5. PathsConfig / BmadConfig values - lowest priority

        Results are cached per (project_root, workflow_id, config_hash) tuple.
        Cache is invalidated when config changes.

        Args:
            context: Compiler context with project_root and resolved_variables.
            workflow_id: Workflow identifier (e.g., "testarch-atdd").

        Returns:
            Dictionary of resolved TEA variables.

        """
        testarch_config = self._get_testarch_config(context)
        current_hash = self._compute_config_hash(testarch_config)

        # Check cache - includes config_hash in key for proper invalidation
        cache_key = (context.project_root.resolve(), workflow_id)
        with self._cache_lock:
            if cache_key in self._cache:
                cached_hash, cached_data = self._cache[cache_key]
                if cached_hash == current_hash:
                    logger.debug("TEA variable cache hit for %s", workflow_id)
                    return dict(cached_data)  # Return copy

        # Resolve variables
        resolved: dict[str, Any] = {}

        # Step 1: Start with existing resolved variables from context
        # This includes values from PathsConfig, BmadConfig, etc.
        # We only copy TEA-relevant keys, not all variables
        for key in [
            "project_root",
            "project-root",
            "communication_language",
            "test_dir",
            "implementation_artifacts",
            "story_file",
        ]:
            if key in context.resolved_variables:
                resolved[key] = context.resolved_variables[key]

        # Step 2: Add universal TEA variables (lower priority)
        universal = self._resolve_universal_variables(context, testarch_config)
        for key, value in universal.items():
            if key not in resolved:
                resolved[key] = value

        # Step 3: Add workflow-specific variables (higher priority)
        workflow_vars = self._resolve_workflow_variables(
            context, workflow_id, testarch_config
        )
        resolved.update(workflow_vars)

        # Step 4: Existing tea.py resolution for additional variables
        from bmad_assist.compiler.variables.tea import resolve_tea_variables

        resolve_tea_variables(
            resolved,
            context.project_root,
            workflow_id=workflow_id,
        )

        # Update cache - store hash with data for proper invalidation
        with self._cache_lock:
            self._cache[cache_key] = (current_hash, dict(resolved))

        logger.debug("Resolved %d TEA variables for %s", len(resolved), workflow_id)
        return resolved
