"""Bundled workflow templates for bmad-assist."""

import sys
from importlib.resources import files
from pathlib import Path

# Python 3.14+ moved Traversable to importlib.resources.abc
if sys.version_info >= (3, 14):
    from importlib.resources.abc import Traversable
else:
    from importlib.abc import Traversable


def get_bundled_workflow_dir(workflow_name: str) -> Path | None:
    """Get path to bundled workflow directory.

    Args:
        workflow_name: Workflow name (e.g., 'dev-story', 'create-story').

    Returns:
        Path to workflow directory, or None if not bundled.

    Note:
        importlib.resources.files() returns Traversable, not Path.
        We validate with Traversable methods, then convert to Path.
    """
    try:
        # Get package resources path (returns Traversable)
        package_path: Traversable = files("bmad_assist.workflows")
        workflow_path: Traversable = package_path / workflow_name

        # Validate using Traversable methods
        if not workflow_path.is_dir():
            return None

        workflow_yaml = workflow_path / "workflow.yaml"
        if not workflow_yaml.is_file():
            return None

        # Convert Traversable to Path for return
        # str(Traversable) gives the filesystem path
        return Path(str(workflow_path))
    except Exception:
        return None


def list_bundled_workflows() -> list[str]:
    """List all bundled workflow names.

    Returns:
        List of workflow directory names that contain workflow.yaml.
    """
    try:
        package_path: Traversable = files("bmad_assist.workflows")
        workflows = []
        for item in package_path.iterdir():
            # item is Traversable, use its methods
            if item.is_dir() and (item / "workflow.yaml").is_file():
                workflows.append(item.name)
        return sorted(workflows)
    except Exception:
        return []
