"""Project tree generator for workflow prompts.

This module generates a directory structure in an XML <project-tree> tag,
respects .gitignore, limits the number of files per directory, and enforces
a configurable token budget. The tree provides structural context without
the overhead of full file content.

Usage:
    from bmad_assist.core.project_tree import ProjectTreeService
    from bmad_assist.core.config import get_config
    from bmad_assist.core.paths import get_paths

    config = get_config()
    paths = get_paths()
    service = ProjectTreeService(config, paths)
    tree_xml = service.generate_tree(workflow_name="dev_story")
"""

from bmad_assist.core.project_tree.config import ProjectTreeConfig
from bmad_assist.core.project_tree.service import ProjectTreeService

__all__ = ["ProjectTreeService", "ProjectTreeConfig"]
