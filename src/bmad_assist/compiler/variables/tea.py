"""TEA (Test Engineer Architect) specific variable resolution.

This module provides variable resolution for TEA Enterprise tri-modal workflows,
including knowledge index resolution, TEA config flags, step-specific variables,
and knowledge base fragment loading.

Public API:
    resolve_tea_variables: Resolve TEA-specific variables for step content
    resolve_knowledge_index: Resolve knowledgeIndex to actual file path
    resolve_knowledge_base: Load workflow-specific knowledge fragments
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default TEA knowledge index location (relative to project root)
DEFAULT_KNOWLEDGE_INDEX_PATH = "_bmad/tea/testarch/tea-index.csv"

# Fallback location for knowledge index
FALLBACK_KNOWLEDGE_INDEX_PATH = "_bmad/bmm/testarch/tea-index.csv"


def resolve_knowledge_index(
    project_root: Path,
    explicit_path: str | None = None,
) -> str | None:
    """Resolve knowledgeIndex to actual file path.

    Searches for the TEA knowledge index file in order:
    1. If explicit_path provided, resolve relative to project root
    2. Default location: _bmad/tea/testarch/tea-index.csv
    3. Fallback location: _bmad/bmm/testarch/tea-index.csv

    Args:
        project_root: Project root directory.
        explicit_path: Optional explicit path from step frontmatter.

    Returns:
        Absolute path to knowledge index file as string, or None if not found.

    """
    # If explicit path provided, resolve it
    if explicit_path:
        # Security: Reject absolute paths
        if Path(explicit_path).is_absolute():
            logger.warning(
                "Absolute knowledge index path rejected: %s (security)",
                explicit_path,
            )
            return None

        # Security: Reject path traversal
        if ".." in explicit_path:
            logger.warning(
                "Knowledge index path with traversal rejected: %s (security)",
                explicit_path,
            )
            return None

        candidate = (project_root / explicit_path).resolve()

        # Security: Validate resolved path is within project root
        try:
            candidate.relative_to(project_root.resolve())
        except ValueError:
            logger.warning(
                "Knowledge index path escapes project root: %s",
                explicit_path,
            )
            return None

        if candidate.exists():
            logger.debug("Using explicit knowledge index: %s", candidate)
            return str(candidate)
        else:
            logger.warning(
                "Explicit knowledge index not found: %s (continuing without it)",
                candidate,
            )
            return None

    # Check default location
    default_path = project_root / DEFAULT_KNOWLEDGE_INDEX_PATH
    if default_path.exists():
        logger.debug("Using default knowledge index: %s", default_path)
        return str(default_path)

    # Check fallback location
    fallback_path = project_root / FALLBACK_KNOWLEDGE_INDEX_PATH
    if fallback_path.exists():
        logger.debug("Using fallback knowledge index: %s", fallback_path)
        return str(fallback_path)

    logger.debug("No knowledge index found (not a blocker)")
    return None


def resolve_tea_config_flags(
    project_root: Path,
) -> dict[str, Any]:
    """Resolve TEA config flags from module.yaml.

    Loads TEA module configuration and extracts feature flags.
    Falls back to defaults if module.yaml not found.

    Args:
        project_root: Project root directory.

    Returns:
        Dictionary with TEA config flags.

    """
    # Default values if config not found
    flags: dict[str, Any] = {
        "tea_use_playwright_utils": True,
        "tea_use_mcp_enhancements": True,
    }

    # Try to load TEA module config
    module_yaml_path = project_root / "_bmad/tea/module.yaml"
    if not module_yaml_path.exists():
        logger.debug("TEA module.yaml not found, using defaults")
        return flags

    try:
        import yaml

        with open(module_yaml_path, encoding="utf-8") as f:
            module_config = yaml.safe_load(f) or {}

        # Extract feature flags (handle both dict format and simple values)
        for flag_name in ["tea_use_playwright_utils", "tea_use_mcp_enhancements"]:
            if flag_name in module_config:
                value = module_config[flag_name]
                # Handle dict format with 'default' key
                if isinstance(value, dict):
                    flags[flag_name] = value.get("default", True)
                elif isinstance(value, bool):
                    flags[flag_name] = value
                else:
                    logger.warning(
                        "Invalid type for %s: expected bool, got %s. Using default.",
                        flag_name,
                        type(value).__name__,
                    )
                    # Keep default value

        logger.debug("Loaded TEA config flags: %s", flags)

    except Exception as e:
        logger.warning("Failed to load TEA module.yaml: %s (using defaults)", e)

    return flags


def resolve_next_step_file(
    next_step_ref: str | None,
    current_step_path: Path,
) -> str | None:
    """Resolve nextStepFile reference to absolute path.

    Args:
        next_step_ref: Relative path from step frontmatter (e.g., './step-02.md').
        current_step_path: Absolute path to current step file.

    Returns:
        Absolute path to next step file as string, or None if not provided.

    """
    if not next_step_ref:
        return None

    # Resolve relative to current step's directory
    step_dir = current_step_path.parent
    next_path = (step_dir / next_step_ref).resolve()

    return str(next_path)


def resolve_knowledge_base(
    project_root: Path,
    workflow_id: str,
    tea_flags: dict[str, Any] | None = None,
) -> str:
    """Load workflow-specific knowledge fragments.

    Loads relevant knowledge fragments for the workflow and returns
    concatenated markdown content with headers.

    Args:
        project_root: Project root directory.
        workflow_id: Workflow identifier (e.g., "atdd", "test-review").
        tea_flags: Optional TEA config flags for conditional loading.

    Returns:
        Concatenated markdown content with <!-- KNOWLEDGE: name --> headers.
        Empty string if index missing or no fragments found.

    """
    try:
        from bmad_assist.testarch.knowledge import get_knowledge_loader

        loader = get_knowledge_loader(project_root)
        content = loader.load_for_workflow(workflow_id, tea_flags)
        if content:
            logger.debug("Loaded knowledge base for workflow %s", workflow_id)
        return content
    except (
        ImportError,
        ModuleNotFoundError,
        OSError,
        ValueError,
    ) as e:
        logger.warning("Failed to load knowledge base: %s (continuing)", e)
        return ""


def resolve_tea_variables(
    resolved: dict[str, Any],
    project_root: Path,
    knowledge_index_path: str | None = None,
    workflow_id: str | None = None,
    context_files: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve all TEA-specific variables.

    Adds TEA variables to the resolved variables dict:
    - knowledgeIndex: Path to TEA knowledge index CSV
    - tea_use_playwright_utils: Playwright utils feature flag
    - tea_use_mcp_enhancements: MCP enhancements feature flag
    - knowledge_base: Workflow-specific knowledge fragments (if workflow_id provided)

    Args:
        resolved: Existing resolved variables dict (modified in place).
        project_root: Project root directory.
        knowledge_index_path: Optional explicit knowledge index path.
        workflow_id: Optional workflow identifier for knowledge base loading.
        context_files: Optional dict to add knowledge fragments as context.

    Returns:
        Updated resolved variables dict with TEA variables.

    """
    # Resolve knowledge index
    ki_path = resolve_knowledge_index(project_root, knowledge_index_path)
    if ki_path:
        resolved["knowledgeIndex"] = ki_path
        logger.debug("Set knowledgeIndex: %s", ki_path)

    # Resolve TEA config flags
    tea_flags = resolve_tea_config_flags(project_root)
    for key, value in tea_flags.items():
        # Only set if not already set (allow overrides)
        if key not in resolved:
            resolved[key] = value

    # Load knowledge base for workflow (AC8)
    if workflow_id:
        knowledge_content = resolve_knowledge_base(project_root, workflow_id, tea_flags)
        if knowledge_content:
            resolved["knowledge_base"] = knowledge_content
            # Also add to context_files if provided
            if context_files is not None:
                context_files["knowledge_base"] = knowledge_content
            logger.debug("Set knowledge_base variable for workflow %s", workflow_id)
        else:
            logger.debug("No knowledge base content for workflow %s", workflow_id)

    return resolved
