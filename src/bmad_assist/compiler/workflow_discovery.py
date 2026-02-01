"""Multi-location workflow discovery for compiler.

Hybrid discovery strategy:
- CUSTOM workflows (validate-story, *-synthesis, code-review): Always use bundled
- STANDARD workflows (create-story, dev-story, retrospective): Prefer user's BMAD,
  fallback to bundled
"""

import logging
from pathlib import Path

from bmad_assist.workflows import get_bundled_workflow_dir

logger = logging.getLogger(__name__)

# Workflows that are custom/modified by bmad-assist - ALWAYS use bundled
CUSTOM_WORKFLOWS = {
    "validate-story",  # Not in standard BMAD
    "validate-story-synthesis",  # Multi-LLM consolidation
    "code-review",  # Modified (2x larger than original)
    "code-review-synthesis",  # Multi-LLM consolidation
    "qa-plan-generate",  # QA module - not in standard BMAD
    "qa-plan-execute",  # QA module - not in standard BMAD
}

# Standard BMAD workflows - prefer user's installation, fallback to bundled
STANDARD_WORKFLOWS = {
    "create-story",
    "dev-story",
    "retrospective",
    # Testarch module (standard BMAD, not custom) - all 8 TEA workflows
    "testarch-atdd",
    "testarch-trace",
    "testarch-test-review",
    "testarch-automate",
    "testarch-ci",
    "testarch-framework",
    "testarch-nfr-assess",
    "testarch-test-design",
}

# Search locations for user's BMAD installation (checked in order)
# Note: .bmad-assist/workflows is checked separately as override, not here
BMAD_SEARCH_PATHS = [
    "_bmad/bmm/workflows/4-implementation",
    "_bmad/bmm/workflows/testarch",
]

# Mapping from workflow name to BMAD directory structure
# testarch workflows use different naming in BMAD (without 'testarch-' prefix)
WORKFLOW_TO_BMAD_DIR = {
    "testarch-atdd": "atdd",
    "testarch-trace": "trace",
    "testarch-test-review": "test-review",
    "testarch-automate": "automate",
    "testarch-ci": "ci",
    "testarch-framework": "framework",
    "testarch-nfr-assess": "nfr-assess",
    "testarch-test-design": "test-design",
}


def discover_workflow_dir(
    workflow_name: str,
    project_root: Path,
) -> Path | None:
    """Discover workflow directory using hybrid strategy.

    For CUSTOM workflows (validate-story, *-synthesis, code-review):
    - Always use bundled (user's BMAD doesn't have these)

    For STANDARD workflows (create-story, dev-story, retrospective):
    1. Check user's BMAD installation first
    2. Fallback to bundled if no BMAD

    Args:
        workflow_name: Workflow name (e.g., 'dev-story').
        project_root: Project root directory.

    Returns:
        Path to workflow directory, or None if not found.

    """
    # Always check project-level override first (for any workflow)
    override = project_root / ".bmad-assist/workflows" / workflow_name
    if _is_valid_workflow_dir(override):
        logger.debug("Using project override: %s", override)
        return override

    # CUSTOM workflows: Always use bundled
    if workflow_name in CUSTOM_WORKFLOWS:
        bundled = get_bundled_workflow_dir(workflow_name)
        if bundled:
            logger.debug("Using bundled custom workflow: %s", workflow_name)
            return bundled
        logger.error("Bundled workflow missing: %s", workflow_name)
        return None

    # STANDARD workflows: Check user's BMAD first
    bmad_dir_name = WORKFLOW_TO_BMAD_DIR.get(workflow_name, workflow_name)
    for search_path in BMAD_SEARCH_PATHS:
        candidate = project_root / search_path / bmad_dir_name
        if _is_valid_workflow_dir(candidate):
            logger.debug("Using user's BMAD workflow: %s", candidate)
            return candidate

    # STANDARD workflows: Fallback to bundled
    bundled = get_bundled_workflow_dir(workflow_name)
    if bundled:
        logger.info(
            "Using bundled fallback for %s (no BMAD installation found)",
            workflow_name,
        )
        return bundled

    return None


def _is_valid_workflow_dir(path: Path) -> bool:
    """Check if path is a valid workflow directory.

    Valid if directory contains workflow.yaml OR workflow.md (or both).
    Tri-modal workflows may have only workflow.md without workflow.yaml.
    """
    if not path.is_dir():
        return False

    # Either workflow.yaml or workflow.md (or both) makes it valid
    has_yaml = (path / "workflow.yaml").is_file()
    has_md = (path / "workflow.md").is_file()

    return has_yaml or has_md


def get_workflow_not_found_message(workflow_name: str, project_root: Path) -> str:
    """Generate helpful error message when workflow not found."""
    is_custom = workflow_name in CUSTOM_WORKFLOWS

    if is_custom:
        return (
            f"Bundled workflow '{workflow_name}' not found!\n\n"
            f"This is a bmad-assist custom workflow that should be bundled.\n"
            f"Please reinstall: pip install -e .\n"
        )

    bmad_dir_name = WORKFLOW_TO_BMAD_DIR.get(workflow_name, workflow_name)
    checked = [str(project_root / p / bmad_dir_name) for p in BMAD_SEARCH_PATHS]
    checked.append("(bundled package fallback)")

    return (
        f"Workflow '{workflow_name}' not found!\n\n"
        f"Checked locations:\n"
        + "\n".join(f"  - {loc}" for loc in checked)
        + "\n\n"
        f"To fix:\n"
        f"  1. Reinstall bmad-assist: pip install -e .\n"
        f"  2. Or install BMAD: Copy _bmad/ from github.com/bmad-code-org/BMAD-METHOD\n"
        f"  3. Or create override: .bmad-assist/workflows/{workflow_name}/"
    )
