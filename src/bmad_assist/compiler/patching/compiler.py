"""Patch compilation logic for BMAD workflow patches.

This module contains the core business logic for patch compilation,
moved from CLI to allow use from any entry point (CLI, orchestrator, etc.).

Public API:
    compile_patch: Compile a workflow patch into a template
    ensure_template_compiled: Ensure cached template exists for a workflow
    load_workflow_ir: Load workflow IR from cache or original files
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

from bmad_assist.compiler.parser import parse_workflow
from bmad_assist.compiler.patching.cache import (
    CacheMeta,
    TemplateCache,
    compute_file_hash,
)
from bmad_assist.compiler.patching.discovery import (
    determine_patch_source_level,
    discover_patch,
    load_patch,
)
from bmad_assist.compiler.patching.output import TemplateMetadata, generate_template
from bmad_assist.compiler.patching.session import PatchSession
from bmad_assist.compiler.patching.transforms import post_process_compiled
from bmad_assist.compiler.patching.validation import check_threshold, validate_output
from bmad_assist.compiler.types import WorkflowIR
from bmad_assist.core.exceptions import CompilerError, PatchError

logger = logging.getLogger(__name__)

# Standard workflow locations in BMAD folder structure
# Supports both legacy (.bmad/) and new (_bmad/) directory structures
_WORKFLOW_LOCATIONS = [
    # New BMAD v6 structure (_bmad/)
    "_bmad/bmm/workflows/4-implementation",  # Implementation workflows
    "_bmad/bmm/workflows/testarch",  # TEA workflows
    "_bmad/bmm/workflows/3-solutioning",  # Solutioning workflows
    "_bmad/bmm/workflows/testarch",  # Testarch module
    "_bmad/bmm/workflows/qa",  # QA module (Beta)
    "_bmad/bmm/workflows",  # Generic workflows
    "_bmad/core/workflows",  # Core workflows
    "_bmad/tea/workflows/testarch",  # TEA external module
    "_bmad/sdet/workflows",  # SDET module
    # Legacy structure (.bmad/)
    ".bmad/bmm/workflows/4-implementation",  # Implementation workflows
    ".bmad/bmm/workflows/3-solutioning",  # Solutioning workflows
    ".bmad/bmm/workflows",  # Generic workflows
    ".bmad/core/workflows",  # Core workflows
]

# Mapping from workflow name to BMAD directory structure
# testarch workflows use different naming in BMAD (without 'testarch-' prefix)
_WORKFLOW_TO_BMAD_DIR = {
    "testarch-atdd": "atdd",
    "testarch-trace": "trace",
    "testarch-test-review": "test-review",
    "testarch-automate": "automate",
    "testarch-ci": "ci",
    "testarch-framework": "framework",
    "testarch-nfr-assess": "nfr-assess",
    "testarch-test-design": "test-design",
}


def _find_workflow_files(
    workflow: str,
    project_root: Path,
) -> tuple[Path, Path]:
    """Find workflow.yaml and instructions file for a workflow.

    Searches in standard BMAD locations within the project.
    Supports both .xml and .md instruction file formats.

    Args:
        workflow: Workflow name (e.g., 'create-story').
        project_root: Project root directory.

    Returns:
        Tuple of (workflow_yaml_path, instructions_path).
        Instructions path may be .xml or .md depending on what exists.

    Raises:
        PatchError: If workflow files not found.

    """
    # Use mapping for testarch workflows (testarch-ci -> ci)
    bmad_dir_name = _WORKFLOW_TO_BMAD_DIR.get(workflow, workflow)

    for location in _WORKFLOW_LOCATIONS:
        workflow_dir = project_root / location / bmad_dir_name
        workflow_yaml = workflow_dir / "workflow.yaml"

        if not workflow_yaml.exists():
            continue

        # Try instructions.xml first, then .md as fallback
        instructions_xml = workflow_dir / "instructions.xml"
        if instructions_xml.exists():
            return workflow_yaml, instructions_xml

        instructions_md = workflow_dir / "instructions.md"
        if instructions_md.exists():
            return workflow_yaml, instructions_md

    # Not found in project - try global ~/.bmad/
    for location in _WORKFLOW_LOCATIONS:
        workflow_dir = Path.home() / location / bmad_dir_name
        workflow_yaml = workflow_dir / "workflow.yaml"

        if not workflow_yaml.exists():
            continue

        instructions_xml = workflow_dir / "instructions.xml"
        if instructions_xml.exists():
            return workflow_yaml, instructions_xml

        instructions_md = workflow_dir / "instructions.md"
        if instructions_md.exists():
            return workflow_yaml, instructions_md

    # Not found in project or global - try bundled workflows
    from bmad_assist.workflows import get_bundled_workflow_dir

    bundled_dir = get_bundled_workflow_dir(workflow)
    if bundled_dir is not None:
        workflow_yaml = bundled_dir / "workflow.yaml"
        if workflow_yaml.exists():
            instructions_xml = bundled_dir / "instructions.xml"
            if instructions_xml.exists():
                return workflow_yaml, instructions_xml

            instructions_md = bundled_dir / "instructions.md"
            if instructions_md.exists():
                return workflow_yaml, instructions_md

    raise PatchError(
        f"Workflow not found: {workflow}\n"
        f"  Searched in: {project_root}/_bmad/**/workflows/{bmad_dir_name}/\n"
        f"  Suggestion: Ensure BMAD is installed in the project or use bundled workflows"
    )


def compile_patch(
    workflow: str,
    project_root: Path,
    cwd: Path | None = None,
    debug: bool = False,
) -> tuple[str, Path, int]:
    """Compile a workflow patch into a template.

    This is the core business logic for patch compilation.

    Args:
        workflow: Workflow name to compile.
        project_root: Project root directory.
        cwd: Current working directory (for CWD-based patch/cache discovery).
        debug: Whether to enable debug logging.

    Returns:
        Tuple of (compiled_content, output_path, warning_count).

    Raises:
        PatchError: If compilation fails.
        CompilerError: If workflow files not found.

    """
    from bmad_assist.core.config import get_config
    from bmad_assist.providers.registry import get_provider

    # Discover patch file
    patch_path = discover_patch(workflow, project_root, cwd=cwd)
    if patch_path is None:
        raise PatchError(f"No patch found for {workflow}")

    # Load patch
    patch = load_patch(patch_path)

    # Find workflow source files
    workflow_yaml_path, instructions_path = _find_workflow_files(workflow, project_root)
    workflow_dir = workflow_yaml_path.parent

    # Load workflow content (combine yaml + xml/md + template)
    workflow_yaml_content = workflow_yaml_path.read_text(encoding="utf-8")
    instructions_content = instructions_path.read_text(encoding="utf-8")

    # Load template if exists (template.md in workflow dir)
    template_content = ""
    template_path = workflow_dir / "template.md"
    if template_path.exists():
        template_content = template_path.read_text(encoding="utf-8")
        logger.debug("Loaded template from %s", template_path)

    workflow_content = f"""<workflow-source>
<workflow-yaml>
{workflow_yaml_content}
</workflow-yaml>
<instructions-xml>
{instructions_content}
</instructions-xml>
<output-template>
{template_content}
</output-template>
</workflow-source>"""

    # Get Master provider from config
    config = get_config()
    if not config.providers or not config.providers.master:
        raise PatchError(
            "Master provider required for patch compilation. "
            "Configure in bmad-assist.yaml: providers.master"
        )

    # Create provider instance from config
    master_provider = get_provider(config.providers.master.provider)
    master_model = config.providers.master.model

    # Run LLM session with validation retries (3 total attempts)
    from bmad_assist.compiler.patching.types import TransformResult

    max_validation_retries = 3
    compiled_workflow: str | None = None
    results: list[TransformResult] = []

    for validation_attempt in range(max_validation_retries):
        # Add retry hint to instructions on subsequent attempts
        retry_instructions = list(patch.transforms)
        if validation_attempt > 0:
            retry_hint = (
                f"RETRY ATTEMPT {validation_attempt + 1}: Previous attempt failed validation. "
                "Pay extra attention to preserving ALL content that should be kept, especially "
                "INVEST validation, step numbering, and any CRITICAL instructions. "
                "Double-check your output before submitting."
            )
            retry_instructions.insert(0, retry_hint)

        # Create and run session
        session = PatchSession(
            workflow_content=workflow_content,
            instructions=retry_instructions,
            provider=master_provider,
            model=master_model,
        )

        try:
            compiled_workflow, results = session.run()
        except PatchError:
            if validation_attempt == max_validation_retries - 1:
                raise
            logger.warning(
                "Session failed, retry %d/%d",
                validation_attempt + 1,
                max_validation_retries,
            )
            continue

        # Post-process: apply deterministic rules from patch config
        compiled_workflow = post_process_compiled(compiled_workflow, patch.post_process)

        # Validate output
        if patch.validation:
            errors = validate_output(compiled_workflow, patch.validation)
            if errors:
                logger.warning(
                    "Validation failed: %s. Retry %d/%d",
                    errors,
                    validation_attempt + 1,
                    max_validation_retries,
                )
                if validation_attempt == max_validation_retries - 1:
                    msg = f"Validation failed after {max_validation_retries} attempts: {errors}"
                    raise PatchError(msg)
                continue

        # Validation passed
        break

    if compiled_workflow is None:
        raise PatchError("Compilation failed: no output produced")

    # Check success threshold (75%)
    if not check_threshold(results):
        successful = sum(1 for r in results if r.success)
        total = len(results)
        rate = (successful * 100) // total if total > 0 else 0
        raise PatchError(
            f"Patch compilation failed: {successful}/{total} transforms succeeded "
            f"({rate}%, minimum 75% required)"
        )

    # Count warnings (failed transforms that didn't block compilation)
    warning_count = sum(1 for r in results if not r.success)

    # Determine cache location based on patch source
    # Cache is stored where the patch comes from to maintain consistency:
    # - Project patch → project cache
    # - CWD patch → CWD cache
    # - Global patch → global cache
    cache = TemplateCache()
    cache_location = determine_patch_source_level(patch_path, project_root, cwd)

    cache_path = cache.get_cache_path(workflow, cache_location)

    # Generate template with metadata
    compiled_at = datetime.now(UTC).isoformat()
    patch_hash = compute_file_hash(patch_path)
    workflow_hash = compute_file_hash(workflow_yaml_path)
    instructions_hash = compute_file_hash(instructions_path)

    meta = TemplateMetadata(
        workflow=workflow,
        patch_name=patch.config.name,
        patch_version=patch.config.version,
        bmad_version=patch.compatibility.bmad_version,
        compiled_at=compiled_at,
        source_hash=patch_hash,
    )

    template = generate_template(compiled_workflow, meta)

    # Save cache to location matching patch source
    cache_meta = CacheMeta(
        compiled_at=compiled_at,
        bmad_version=patch.compatibility.bmad_version,
        source_hashes={
            "workflow.yaml": workflow_hash,
            instructions_path.name: instructions_hash,  # Use actual filename
        },
        patch_hash=patch_hash,
    )
    cache.save(workflow, template, cache_meta, cache_location)

    logger.info("Compiled patch for %s → %s", workflow, cache_path)
    return template, cache_path, warning_count


def ensure_template_compiled(
    workflow: str,
    project_root: Path,
    cwd: Path | None = None,
) -> Path | None:
    """Ensure cached template exists for a workflow if patch exists.

    Checks cache validity and auto-compiles if needed. This is the pure
    business logic version - CLI adds UI output on top.

    Flow:
    1. Check for cached template (project → CWD → global)
    2. If valid cache found, return its path
    3. If no cache, check for patch (project → CWD → global)
    4. If patch exists, compile it and save to cache
    5. If no patch, return None (use original workflow)

    Args:
        workflow: Workflow name (e.g., 'create-story').
        project_root: Project root directory.
        cwd: Current working directory (for CWD-based discovery).

    Returns:
        Path to valid cached template, or None if no patch exists.

    Raises:
        PatchError: If patch exists but compilation fails.
        CompilerError: If workflow files not found.

    """
    cache = TemplateCache()

    # Step 1: Check if patch exists
    patch_path = discover_patch(workflow, project_root, cwd=cwd)
    if patch_path is None:
        # No patch → use original workflow
        logger.debug("No patch for %s, using original workflow", workflow)
        return None

    # Step 2: Find workflow source files for cache validation
    try:
        workflow_yaml_path, instructions_path = _find_workflow_files(workflow, project_root)
        source_files = {
            "workflow.yaml": workflow_yaml_path,
            instructions_path.name: instructions_path,  # Use actual filename (.xml or .md)
        }
    except PatchError as e:
        # Can't find workflow files
        raise CompilerError(str(e)) from e

    # Step 3: Check cache locations in priority order
    # Project cache
    if cache.is_valid(workflow, project_root, source_files=source_files, patch_path=patch_path):
        cache_path = cache.get_cache_path(workflow, project_root)
        logger.debug("Using project cache: %s", cache_path)
        return cache_path

    # CWD cache (if different from project)
    if (
        cwd is not None
        and cwd.resolve() != project_root.resolve()
        and cache.is_valid(workflow, cwd, source_files=source_files, patch_path=patch_path)
    ):
        cache_path = cache.get_cache_path(workflow, cwd)
        logger.debug("Using CWD cache: %s", cache_path)
        return cache_path

    # Global cache
    if cache.is_valid(workflow, None, source_files=source_files, patch_path=patch_path):
        cache_path = cache.get_cache_path(workflow, None)
        logger.debug("Using global cache: %s", cache_path)
        return cache_path

    # Step 4: No valid cache - try auto-compile
    # If compilation fails (e.g., no LLM config), return None to use original files
    try:
        logger.info("Auto-compiling patch for %s", workflow)
        _, cache_path, warning_count = compile_patch(workflow, project_root, cwd=cwd, debug=False)

        if warning_count > 0:
            logger.warning("Patch compiled with %d warnings", warning_count)

        return cache_path

    except (PatchError, CompilerError) as e:
        # Compilation failed (likely no LLM config or other issue)
        # Return None to fall back to original files with post_process
        logger.warning(
            "Patch compilation failed for %s, using original files + post_process: %s",
            workflow,
            str(e)[:100],
        )
        return None


def load_workflow_ir(
    workflow: str,
    project_root: Path,
    cwd: Path | None = None,
    workflow_dir: Path | None = None,
) -> tuple[WorkflowIR, Path | None]:
    """Load workflow IR from cache or original files.

    Unified loading logic that:
    1. Ensures patch is compiled if it exists
    2. Loads from cached template if available
    3. Falls back to original workflow files

    Args:
        workflow: Workflow name (e.g., 'create-story').
        project_root: Project root directory.
        cwd: Current working directory for patch discovery.
        workflow_dir: Explicit workflow directory (optional, for workflow-specific paths).

    Returns:
        Tuple of (WorkflowIR, patch_path or None).
        patch_path is set if using patched template.

    Raises:
        CompilerError: If workflow cannot be loaded.

    """
    import re

    import yaml

    # Ensure template is compiled (auto-compiles if patch exists but no cache)
    cache_path = ensure_template_compiled(workflow, project_root, cwd=cwd)

    if cache_path is not None:
        # Load directly from the verified cache path
        # (avoid re-deriving cache_location - we already have the valid path)
        try:
            cached_content = cache_path.read_text(encoding="utf-8")
        except OSError as e:
            raise CompilerError(f"Failed to load cached template: {cache_path}\n  Error: {e}") from e # noqa: E501

        # Parse cached template into WorkflowIR
        # NOTE: Use ^tag to match tags at line start, not as text in comments
        # (e.g., workflow.yaml may contain "# template: embedded in <output-template>")
        try:
            yaml_match = re.search(
                r"^<workflow-yaml>\s*(.*?)\s*^</workflow-yaml>",
                cached_content,
                re.DOTALL | re.MULTILINE,
            )
            instructions_match = re.search(
                r"^<instructions-xml>\s*(.*?)\s*^</instructions-xml>",
                cached_content,
                re.DOTALL | re.MULTILINE,
            )
            # Extract embedded output template (optional)
            template_match = re.search(
                r"^<output-template>\s*(.*?)\s*^</output-template>",
                cached_content,
                re.DOTALL | re.MULTILINE,
            )

            if not yaml_match or not instructions_match:
                raise CompilerError(f"Cached template missing required sections: {cache_path}")

            config = yaml.safe_load(yaml_match.group(1))

            # Extract output template content (may be empty string)
            output_template = template_match.group(1).strip() if template_match else None
            if output_template == "":
                output_template = None

            # Find original workflow dir for {installed_path} resolution
            # config_path must point to original workflow.yaml, not cache file
            if workflow_dir is None:
                workflow_yaml_path, _ = _find_workflow_files(workflow, project_root)
                workflow_dir = workflow_yaml_path.parent
            else:
                workflow_yaml_path = workflow_dir / "workflow.yaml"

            workflow_ir = WorkflowIR(
                name=config.get("name", workflow),
                config_path=workflow_yaml_path,  # Original workflow.yaml for {installed_path}
                instructions_path=cache_path,  # Cache file for instructions content
                template_path=config.get("template"),
                validation_path=config.get("validation"),
                raw_config=config,
                raw_instructions=instructions_match.group(1),
                output_template=output_template,  # Embedded template content from cache
            )

            # Cached templates have post_process already applied, no patch_path needed
            logger.info("Loaded workflow %s from cached template", workflow)
            return workflow_ir, None

        except Exception as e:
            raise CompilerError(
                f"Failed to parse cached template: {cache_path}\n  Error: {e}"
            ) from e

    else:
        # No cache - load from original workflow files
        # But check if patch exists - if so, return patch_path for post_process
        try:
            if workflow_dir is None:
                workflow_yaml_path, _ = _find_workflow_files(workflow, project_root)
                workflow_dir = workflow_yaml_path.parent
            workflow_ir = parse_workflow(workflow_dir)

            # Check if patch exists (for post_process application by compiler)
            patch_path = discover_patch(workflow, project_root, cwd=cwd)
            if patch_path:
                logger.info(
                    "Loaded workflow %s from original files (patch post_process will apply)",
                    workflow,
                )
            else:
                logger.debug("Loaded workflow %s from original files", workflow)

            return workflow_ir, patch_path
        except PatchError as e:
            raise CompilerError(str(e)) from e
