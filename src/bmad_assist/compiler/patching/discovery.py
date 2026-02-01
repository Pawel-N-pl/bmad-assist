"""Patch discovery and loading for BMAD workflow patches.

This module handles finding and loading workflow patch files from
project and global paths.

Functions:
    discover_patch: Find patch file for a workflow
    load_patch: Load and parse a patch file into WorkflowPatch
    load_defaults: Load shared defaults (post_process rules, etc.)
"""

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from bmad_assist.compiler.patching.types import (
    Compatibility,
    GitCommand,
    GitIntelligence,
    PatchConfig,
    PostProcessRule,
    Validation,
    WorkflowPatch,
)
from bmad_assist.core.exceptions import PatchError

logger = logging.getLogger(__name__)

# Default patch directory name
DEFAULT_PATCH_DIR = ".bmad-assist/patches"
DEFAULTS_FILENAME = "defaults.yaml"
DEFAULTS_TESTARCH_FILENAME = "defaults-testarch.yaml"

# TEA workflow prefix for detection
TEA_WORKFLOW_PREFIX = "testarch-"


def determine_patch_source_level(
    patch_path: Path,
    project_root: Path,
    cwd: Path | None = None,
) -> Path | None:
    """Determine which cache location corresponds to a patch's source.

    Maps patch discovery location to appropriate cache location:
    - Patch in project → cache in project
    - Patch in CWD → cache in CWD
    - Patch in home (global) → cache in home (None = global)

    Args:
        patch_path: Path to the discovered patch file.
        project_root: Project root directory.
        cwd: Current working directory (optional).

    Returns:
        Path for cache location (project_root or cwd), or None for global cache.

    """
    resolved_patch = patch_path.resolve()
    resolved_project = project_root.resolve()
    resolved_cwd = cwd.resolve() if cwd is not None else None

    # Check if patch is under project
    project_patches_dir = resolved_project / DEFAULT_PATCH_DIR
    try:
        if resolved_patch.is_relative_to(project_patches_dir):
            logger.debug("Patch source: project (%s)", project_root)
            return project_root
    except ValueError as e:
        logger.debug("Path comparison failed for project: %s", e)

    # Check if patch is under CWD (if different from project)
    if resolved_cwd is not None and resolved_cwd != resolved_project:
        cwd_patches_dir = resolved_cwd / DEFAULT_PATCH_DIR
        try:
            if resolved_patch.is_relative_to(cwd_patches_dir):
                logger.debug("Patch source: cwd (%s)", cwd)
                return cwd
        except ValueError as e:
            logger.debug("Path comparison failed for cwd: %s", e)

    # Check if patch is under home (global)
    home_patches_dir = Path.home() / DEFAULT_PATCH_DIR
    try:
        if resolved_patch.is_relative_to(home_patches_dir):
            logger.debug("Patch source: global (%s)", home_patches_dir)
            return None
    except ValueError as e:
        logger.debug("Path comparison failed for global: %s", e)

    # Fallback: unknown source, use project as default
    logger.debug("Patch source: unknown (%s), defaulting to project (%s)", patch_path, project_root)
    return project_root


def discover_patch(
    workflow_name: str,
    project_root: Path,
    *,
    patch_path: str | None = None,
    cwd: Path | None = None,
) -> Path | None:
    """Discover patch file for a workflow.

    Searches for patch file in the following order:
    1. Custom patch_path (if provided)
    2. Project path: {project_root}/.bmad-assist/patches/{workflow}.patch.yaml
    3. CWD path: {cwd}/.bmad-assist/patches/{workflow}.patch.yaml (if different from project)
    4. Global path: ~/.bmad-assist/patches/{workflow}.patch.yaml

    First match wins (no merge).

    Args:
        workflow_name: Name of the workflow (e.g., "create-story").
        project_root: Root directory of the project.
        patch_path: Optional custom patch directory path (from config).
        cwd: Current working directory (for CWD-based patches).

    Returns:
        Path to patch file if found, None otherwise.

    """
    patch_filename = f"{workflow_name}.patch.yaml"

    # Check custom patch path first (from config compiler.patch_path)
    if patch_path:
        custom_path = Path(patch_path)
        if not custom_path.is_absolute():
            custom_path = project_root / custom_path
        # Security: Validate path is within project root to prevent path traversal
        try:
            resolved = custom_path.resolve()
            if not resolved.is_relative_to(project_root.resolve()):
                logger.warning(
                    "Custom patch path '%s' escapes project root, ignoring",
                    patch_path,
                )
            else:
                patch_file = custom_path / patch_filename
                if patch_file.exists() and patch_file.is_file():
                    logger.debug("Found patch at custom path: %s", patch_file)
                    return patch_file
        except (ValueError, OSError) as e:
            logger.warning("Invalid custom patch path '%s': %s", patch_path, e)

    # Check project path
    project_patch = project_root / DEFAULT_PATCH_DIR / patch_filename
    if project_patch.exists() and project_patch.is_file():
        logger.debug("Found patch at project path: %s", project_patch)
        return project_patch

    # Check CWD path (if different from project)
    if cwd is not None:
        resolved_cwd = cwd.resolve()
        resolved_project = project_root.resolve()
        if resolved_cwd != resolved_project:
            cwd_patch = cwd / DEFAULT_PATCH_DIR / patch_filename
            if cwd_patch.exists() and cwd_patch.is_file():
                logger.debug("Found patch at CWD path: %s", cwd_patch)
                return cwd_patch

    # Check global path
    global_patch = Path.home() / DEFAULT_PATCH_DIR / patch_filename
    if global_patch.exists() and global_patch.is_file():
        logger.debug("Found patch at global path: %s", global_patch)
        return global_patch

    # Check bmad-assist package directory (fallback for pip-installed patches)
    package_patch = Path(__file__).parent.parent.parent / "default_patches" / patch_filename
    if package_patch.exists() and package_patch.is_file():
        logger.debug("Found patch at package path: %s", package_patch)
        return package_patch

    # No patch found - this is OK for custom workflows that don't need patches
    logger.debug(
        "No patch found for '%s' - using workflow as-is (searched: project, global, package paths)",
        workflow_name,
    )
    return None


def _load_defaults_file(
    patch_dir: Path,
    filename: str,
    description: str,
) -> list[PostProcessRule]:
    """Load post_process rules from a defaults file.

    Args:
        patch_dir: Directory to search for defaults file.
        filename: Name of defaults file (e.g., "defaults.yaml").
        description: Description for logging (e.g., "defaults.yaml").

    Returns:
        List of PostProcessRule from file, empty list if not found or invalid.

    """
    defaults_path = patch_dir / filename

    # Fallback to global location
    if not defaults_path.exists():
        defaults_path = Path.home() / DEFAULT_PATCH_DIR / filename

    if not defaults_path.exists():
        logger.debug("No %s found", description)
        return []

    try:
        content = defaults_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except (yaml.YAMLError, OSError) as e:
        logger.warning("Failed to load %s: %s", description, e)
        return []

    if not isinstance(data, dict):
        logger.warning("%s must contain a YAML mapping", description)
        return []

    # Parse post_process section
    post_process_section = data.get("post_process")
    if post_process_section is None:
        return []

    if not isinstance(post_process_section, list):
        logger.warning("%s post_process must be a list", description)
        return []

    rules = []
    for i, rule_data in enumerate(post_process_section):
        if not isinstance(rule_data, dict):
            logger.warning("%s post_process[%d] must be a mapping", description, i)
            continue
        try:
            rules.append(
                PostProcessRule(
                    pattern=rule_data.get("pattern", ""),
                    replacement=rule_data.get("replacement", ""),
                    flags=rule_data.get("flags", ""),
                )
            )
        except ValidationError as e:
            logger.warning("Invalid rule in %s post_process[%d]: %s", description, i, e)
            continue

    logger.debug("Loaded %d post_process rules from %s", len(rules), defaults_path)
    return rules


def is_tea_workflow(workflow_name: str) -> bool:
    """Check if workflow is a TEA workflow.

    TEA workflows are identified by the "testarch-" prefix.

    Args:
        workflow_name: Workflow name.

    Returns:
        True if workflow is a TEA workflow.

    """
    return workflow_name.startswith(TEA_WORKFLOW_PREFIX) if workflow_name else False


def load_defaults(
    patch_path: Path,
    workflow_name: str | None = None,
) -> list[PostProcessRule]:
    """Load shared post_process rules from defaults files.

    For TEA workflows (testarch-*), applies merge order:
    1. defaults.yaml (global base)
    2. defaults-testarch.yaml (TEA overlay)

    For non-TEA workflows, only loads defaults.yaml.

    Args:
        patch_path: Path to the patch file (used to find sibling defaults).
        workflow_name: Optional workflow name for TEA detection.

    Returns:
        List of PostProcessRule from defaults, empty list if not found.

    """
    patch_dir = patch_path.parent

    # Load base defaults.yaml
    base_rules = _load_defaults_file(patch_dir, DEFAULTS_FILENAME, "defaults.yaml")

    # For TEA workflows, also load defaults-testarch.yaml
    if workflow_name and is_tea_workflow(workflow_name):
        tea_rules = _load_defaults_file(
            patch_dir, DEFAULTS_TESTARCH_FILENAME, "defaults-testarch.yaml"
        )
        if tea_rules:
            logger.debug(
                "Merging TEA defaults: %d base + %d TEA = %d total",
                len(base_rules),
                len(tea_rules),
                len(base_rules) + len(tea_rules),
            )
            return base_rules + tea_rules

    return base_rules


def load_patch(patch_path: Path) -> WorkflowPatch:
    """Load and parse a patch file into WorkflowPatch.

    Args:
        patch_path: Path to the patch YAML file.

    Returns:
        Validated WorkflowPatch object.

    Raises:
        PatchError: If file not found, YAML is malformed, or validation fails.
            Error message includes line number when available from YAML parser.

    """
    if not patch_path.exists():
        raise PatchError(f"Patch file not found: {patch_path}")

    if not patch_path.is_file():
        raise PatchError(f"Patch path is not a file: {patch_path}")

    try:
        content = patch_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        # YAML errors include line/column info in the exception
        raise PatchError(f"Invalid patch YAML in {patch_path}: {e}") from e
    except OSError as e:
        raise PatchError(f"Cannot read patch file {patch_path}: {e}") from e

    if not isinstance(data, dict):
        raise PatchError(
            f"Patch file {patch_path} must contain a YAML mapping, got {type(data).__name__}"
        )

    # Extract and validate patch config section
    patch_section = data.get("patch", {})
    if not isinstance(patch_section, dict):
        raise PatchError(f"'patch' section must be a mapping in {patch_path}")

    try:
        config = PatchConfig(
            name=patch_section.get("name", ""),
            version=patch_section.get("version", ""),
            author=patch_section.get("author"),
            description=patch_section.get("description"),
        )
    except ValidationError as e:
        raise PatchError(f"Invalid patch config in {patch_path}: {e}") from e

    # Extract and validate compatibility section
    compat_section = data.get("compatibility", {})
    if not isinstance(compat_section, dict):
        raise PatchError(f"'compatibility' section must be a mapping in {patch_path}")

    try:
        compatibility = Compatibility(
            bmad_version=compat_section.get("bmad_version", ""),
            workflow=compat_section.get("workflow", ""),
        )
    except ValidationError as e:
        raise PatchError(f"Invalid compatibility in {patch_path}: {e}") from e

    # Extract and validate transforms (simple instruction strings)
    transforms_section = data.get("transforms", [])
    if not isinstance(transforms_section, list):
        raise PatchError(f"'transforms' section must be a list in {patch_path}")

    transforms: list[str] = []
    for i, instruction in enumerate(transforms_section):
        if not isinstance(instruction, str):
            raise PatchError(
                f"Transform at index {i} must be a string instruction in {patch_path}, "
                f"got {type(instruction).__name__}"
            )
        if not instruction.strip():
            raise PatchError(f"Transform at index {i} cannot be empty in {patch_path}")
        transforms.append(instruction.strip())

    # Extract and validate optional validation section
    validation_section = data.get("validation")
    validation = None
    if validation_section is not None:
        if not isinstance(validation_section, dict):
            raise PatchError(f"'validation' section must be a mapping in {patch_path}")
        try:
            validation = Validation(
                must_contain=validation_section.get("must_contain", []),
                must_not_contain=validation_section.get("must_not_contain", []),
            )
        except ValidationError as e:
            raise PatchError(f"Invalid validation in {patch_path}: {e}") from e

    # Extract and validate optional git_intelligence section
    git_section = data.get("git_intelligence")
    git_intelligence = None
    if git_section is not None:
        if not isinstance(git_section, dict):
            raise PatchError(f"'git_intelligence' section must be a mapping in {patch_path}")
        try:
            # Parse commands list
            commands_data = git_section.get("commands", [])
            if not isinstance(commands_data, list):
                raise PatchError(f"'git_intelligence.commands' must be a list in {patch_path}")

            commands = []
            for i, cmd_data in enumerate(commands_data):
                if not isinstance(cmd_data, dict):
                    raise PatchError(
                        f"git_intelligence.commands[{i}] must be a mapping in {patch_path}"
                    )
                commands.append(
                    GitCommand(
                        name=cmd_data.get("name", ""),
                        command=cmd_data.get("command", ""),
                    )
                )

            git_intelligence = GitIntelligence(
                enabled=git_section.get("enabled", True),
                commands=commands,
                embed_marker=git_section.get("embed_marker", "git-intelligence"),
                no_git_message=git_section.get(
                    "no_git_message",
                    GitIntelligence.model_fields["no_git_message"].default,
                ),
            )
        except ValidationError as e:
            raise PatchError(f"Invalid git_intelligence in {patch_path}: {e}") from e

    # Load default post_process rules from defaults.yaml (and defaults-testarch.yaml for TEA)
    # Defaults are applied first, patch-specific rules extend them
    # Use workflow name from compatibility section for TEA detection
    workflow_name = compatibility.workflow
    default_rules = load_defaults(patch_path, workflow_name)

    # Extract and validate optional post_process section (patch-specific)
    post_process_section = data.get("post_process")
    patch_rules: list[PostProcessRule] = []
    if post_process_section is not None:
        if not isinstance(post_process_section, list):
            raise PatchError(f"'post_process' section must be a list in {patch_path}")
        try:
            for i, rule_data in enumerate(post_process_section):
                if not isinstance(rule_data, dict):
                    raise PatchError(f"post_process[{i}] must be a mapping in {patch_path}")
                patch_rules.append(
                    PostProcessRule(
                        pattern=rule_data.get("pattern", ""),
                        replacement=rule_data.get("replacement", ""),
                        flags=rule_data.get("flags", ""),
                    )
                )
        except ValidationError as e:
            raise PatchError(f"Invalid post_process in {patch_path}: {e}") from e

    # Merge: defaults first, then patch-specific rules
    post_process: list[PostProcessRule] | None = None
    if default_rules or patch_rules:
        post_process = default_rules + patch_rules
        logger.debug(
            "Post-process rules: %d from defaults + %d from patch = %d total",
            len(default_rules),
            len(patch_rules),
            len(post_process),
        )

    try:
        return WorkflowPatch(
            config=config,
            compatibility=compatibility,
            transforms=transforms,
            validation=validation,
            git_intelligence=git_intelligence,
            post_process=post_process,
        )
    except ValidationError as e:
        raise PatchError(f"Invalid patch in {patch_path}: {e}") from e
