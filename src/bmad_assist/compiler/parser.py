"""BMAD workflow file parsing.

This module provides functions for parsing BMAD workflow files:
- parse_workflow_config: Parse workflow.yaml configuration
- parse_workflow_md_frontmatter: Parse YAML frontmatter from workflow.md
- parse_workflow_instructions: Parse and validate instructions.xml
- parse_workflow: Unified parsing returning WorkflowIR

All parsing is STRUCTURAL only - variable resolution is handled by Story 10.3.
Placeholders like {config_source}:output_folder are preserved as raw strings.
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

from bmad_assist.compiler.types import WorkflowIR
from bmad_assist.core.exceptions import ParserError

logger = logging.getLogger(__name__)


def parse_workflow_md_frontmatter(workflow_md_path: Path) -> dict[str, Any]:
    """Parse YAML frontmatter from workflow.md file.

    Extracts YAML content between opening and closing --- markers.
    If no frontmatter exists, returns empty dict.

    Args:
        workflow_md_path: Path to workflow.md file.

    Returns:
        Parsed YAML frontmatter as dictionary, or empty dict if:
        - File does not exist
        - File has no frontmatter
        - Frontmatter is empty

    """
    if not workflow_md_path.exists():
        return {}

    try:
        content = workflow_md_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Cannot read workflow.md: %s", e)
        return {}

    # Check for frontmatter (content must start with ---)
    if not content.startswith("---"):
        return {}

    # Find the closing --- marker
    # Skip the first 3 characters (opening ---)
    end_marker_pos = content.find("---", 3)
    if end_marker_pos == -1:
        # No closing marker - invalid frontmatter
        return {}

    # Extract frontmatter content (between the markers)
    frontmatter = content[3:end_marker_pos].strip()
    if not frontmatter:
        return {}

    try:
        result = yaml.safe_load(frontmatter)
        if result is None:
            return {}
        if not isinstance(result, dict):
            logger.warning("workflow.md frontmatter is not a dict, ignoring")
            return {}
        return result
    except yaml.YAMLError as e:
        logger.warning("Invalid YAML in workflow.md frontmatter: %s", e)
        return {}


def parse_workflow_config(config_path: Path) -> dict[str, Any]:
    """Parse workflow.yaml configuration file.

    Parses YAML config and returns raw dictionary. All placeholders
    (e.g., {project-root}, {config_source}:) are preserved as strings.

    Args:
        config_path: Path to workflow.yaml file.

    Returns:
        Parsed YAML as dictionary. Empty dict for empty files.

    Raises:
        ParserError: If file not found or YAML syntax is invalid.

    """
    if not config_path.exists():
        raise ParserError(
            f"Configuration file not found: {config_path}\n"
            f"  Why it's needed: Contains workflow configuration and variable definitions\n"
            f"  How to fix: Ensure workflow.yaml exists in the workflow directory"
        )

    try:
        content = config_path.read_text(encoding="utf-8")
    except OSError as e:
        raise ParserError(
            f"Cannot read configuration file: {config_path}\n"
            f"  Error: {e}\n"
            f"  Suggestion: Check file permissions and ensure the file is accessible"
        ) from e

    # Empty file returns empty dict (AC6)
    if not content.strip():
        return {}

    try:
        result = yaml.safe_load(content)
        # yaml.safe_load returns None for empty/whitespace-only content
        if result is None:
            return {}
        if not isinstance(result, dict):
            raise ParserError(
                f"Invalid configuration in {config_path}:\n"
                f"  Root element must be a mapping (dict), got {type(result).__name__}\n"
                f"  Suggestion: Ensure workflow.yaml is key: value format, not a list or scalar"
            )
        return result
    except yaml.YAMLError as e:
        # Extract line number from YAML error if available
        line_info = ""
        if hasattr(e, "problem_mark") and e.problem_mark is not None:
            mark = e.problem_mark
            line_info = f"\n  Line {mark.line + 1}, column {mark.column + 1}"

        raise ParserError(
            f"Invalid YAML in {config_path}:{line_info}\n"
            f"  {e}\n"
            f"  Suggestion: Check YAML syntax (indentation, colons, quotes)"
        ) from e


def _detect_tri_modal(workflow_dir: Path) -> dict[str, Any]:
    """Detect tri-modal step directories and find first steps.

    Checks for steps-c/, steps-v/, steps-e/ directories and finds the
    first step file in each using natural sort order.

    Args:
        workflow_dir: Directory containing the workflow.

    Returns:
        Dictionary with tri-modal fields:
        - has_tri_modal: True if any step directory has .md files
        - workflow_type: "tri_modal" or "macro"
        - steps_c_dir, steps_v_dir, steps_e_dir: Path or None
        - first_step_c, first_step_v, first_step_e: Path or None

    """
    result: dict[str, Any] = {
        "has_tri_modal": False,
        "workflow_type": "macro",
        "steps_c_dir": None,
        "steps_v_dir": None,
        "steps_e_dir": None,
        "first_step_c": None,
        "first_step_v": None,
        "first_step_e": None,
    }

    mode_dirs = {
        "c": ("steps-c", "steps_c_dir", "first_step_c"),
        "v": ("steps-v", "steps_v_dir", "first_step_v"),
        "e": ("steps-e", "steps_e_dir", "first_step_e"),
    }

    for mode, (dir_name, dir_key, first_key) in mode_dirs.items():
        step_dir = workflow_dir / dir_name
        if not step_dir.is_dir():
            continue

        # Find .md files in the step directory
        step_files = list(step_dir.glob("step-*.md"))
        if not step_files:
            continue

        # Natural sort: step-01 before step-02 before step-10
        # Also handles substeps: step-04 before step-04a before step-04b
        step_files.sort(key=lambda p: _natural_sort_key(p.name))

        result[dir_key] = step_dir
        result[first_key] = step_files[0]
        result["has_tri_modal"] = True
        result["workflow_type"] = "tri_modal"

    return result


def _natural_sort_key(filename: str) -> tuple[int, str, str]:
    """Generate sort key for natural ordering of step files.

    Extracts numeric prefix from step-NN-name.md pattern.
    Handles substeps like step-04a, step-04b.

    Args:
        filename: Step file name (e.g., "step-01-preflight.md")

    Returns:
        Tuple (number, suffix, full_name) for sorting.

    """
    import re

    # Match step-NN or step-NNa/b/c pattern
    match = re.match(r"step-(\d+)([a-z])?", filename)
    if match:
        num = int(match.group(1))
        suffix = match.group(2) or ""  # Empty string for main step
        return (num, suffix, filename)

    # Fallback: treat as very high number to sort at end
    return (9999, "", filename)


def parse_workflow_instructions(instructions_path: Path) -> str:
    """Parse and validate instructions.xml file.

    Validates XML syntax using ElementTree, then returns raw XML content
    as string. The XML is NOT parsed into a tree - that happens in
    Story 10.5 (Instruction Filtering Engine).

    Args:
        instructions_path: Path to instructions.xml file.

    Returns:
        Raw XML content as string (validated for syntax).

    Raises:
        ParserError: If file not found or XML syntax is invalid.

    """
    if not instructions_path.exists():
        raise ParserError(
            f"Instructions file not found: {instructions_path}\n"
            f"  Why it's needed: Contains workflow execution steps and actions\n"
            f"  How to fix: Ensure instructions.xml exists in the workflow directory"
        )

    try:
        content = instructions_path.read_text(encoding="utf-8")
    except OSError as e:
        raise ParserError(
            f"Cannot read instructions file: {instructions_path}\n"
            f"  Error: {e}\n"
            f"  Suggestion: Check file permissions and ensure the file is accessible"
        ) from e

    # For .md files, skip XML validation (markdown may contain XML-like tags but isn't XML)
    if instructions_path.suffix.lower() == ".md":
        return content

    # Security: Reject XML with DOCTYPE/ENTITY declarations (XML bomb protection)
    if "<!DOCTYPE" in content or "<!ENTITY" in content:
        raise ParserError(
            f"Invalid XML in {instructions_path}:\n"
            f"  DOCTYPE and ENTITY declarations are not allowed\n"
            f"  Suggestion: Remove <!DOCTYPE> and <!ENTITY> declarations"
        )

    # Validate XML syntax by parsing (but we return the raw string)
    try:
        ET.fromstring(content)
    except ET.ParseError as e:
        # ParseError has position info: (msg, (line, column))
        line_info = ""
        if hasattr(e, "position") and e.position is not None:
            line, col = e.position
            line_info = f"\n  Line {line}, column {col}"

        raise ParserError(
            f"Invalid XML in {instructions_path}:{line_info}\n"
            f"  {e}\n"
            f"  Suggestion: Check XML syntax (tags, quotes, encoding)"
        ) from e

    return content


def parse_workflow(workflow_dir: Path) -> WorkflowIR:
    """Parse BMAD workflow directory into WorkflowIR.

    Loads and parses all workflow files from the directory:
    - workflow.yaml OR workflow.md (at least one required)
    - instructions.xml or instructions.md (required)
    - template path (optional, stored as raw string)

    For tri-modal workflows (TEA Enterprise):
    - workflow.md may exist without workflow.yaml
    - If both exist, workflow.yaml values take precedence for overlapping keys

    Args:
        workflow_dir: Directory containing workflow files.

    Returns:
        WorkflowIR with parsed content (placeholders preserved as strings).

    Raises:
        ParserError: If required files missing or parsing fails.

    """
    workflow_dir = workflow_dir.resolve()

    # Check for workflow.yaml and workflow.md
    yaml_path = workflow_dir / "workflow.yaml"
    md_path = workflow_dir / "workflow.md"

    yaml_exists = yaml_path.exists()
    md_exists = md_path.exists()

    # At least one must exist (AC1: tri-modal may have only workflow.md)
    if not yaml_exists and not md_exists:
        raise ParserError(
            f"workflow.yaml not found in: {workflow_dir}\n"
            f"  Why it's needed: Defines workflow configuration, variables, and file patterns\n"
            f"  How to fix: Ensure the workflow directory contains workflow.yaml or workflow.md"
        )

    # Parse configs and merge (workflow.md first, workflow.yaml overrides)
    raw_config: dict[str, Any] = {}

    # Start with workflow.md frontmatter if it exists
    if md_exists:
        md_config = parse_workflow_md_frontmatter(md_path)
        raw_config.update(md_config)

    # Override with workflow.yaml if it exists
    if yaml_exists:
        yaml_config = parse_workflow_config(yaml_path)
        raw_config.update(yaml_config)

    # Use whichever config file exists as the "main" config path
    config_path = yaml_path if yaml_exists else md_path

    # Detect tri-modal structure FIRST (AC2)
    tri_modal = _detect_tri_modal(workflow_dir)

    # Determine instructions path
    # If 'instructions' key contains placeholder like {installed_path},
    # assume instructions.xml in same directory (convention per AC4)
    instructions_key = raw_config.get("instructions", "")
    if isinstance(instructions_key, str) and "{" in instructions_key:
        # Placeholder present - use convention (try .xml first, then .md)
        instructions_path = workflow_dir / "instructions.xml"
        if not instructions_path.exists():
            instructions_path = workflow_dir / "instructions.md"
    elif isinstance(instructions_key, str) and instructions_key:
        # Explicit path (rare case - resolve relative to workflow_dir)
        # Security: Prevent path traversal attacks
        if ".." in instructions_key or instructions_key.startswith("/"):
            raise ParserError(
                f"Invalid instructions path in {config_path}:\n"
                f"  Path '{instructions_key}' contains path traversal\n"
                f"  Suggestion: Use relative path within workflow directory"
            )
        instructions_path = workflow_dir / instructions_key
    else:
        # No instructions key - use convention (try .xml first, then .md)
        instructions_path = workflow_dir / "instructions.xml"
        if not instructions_path.exists():
            instructions_path = workflow_dir / "instructions.md"

    # Check instructions file exists
    # For tri-modal workflows, instructions.md is optional (steps ARE the instructions)
    raw_instructions = ""
    if instructions_path.exists():
        raw_instructions = parse_workflow_instructions(instructions_path)
    elif not tri_modal["has_tri_modal"]:
        # Only require instructions for macro workflows
        raise ParserError(
            f"instructions file not found: {instructions_path}\n"
            f"  Why it's needed: Contains workflow execution steps and actions\n"
            f"  How to fix: Ensure the workflow directory contains instructions.xml or instructions.md" # noqa: E501
        )
    else:
        # Tri-modal without instructions.md: use first step as instructions path
        if tri_modal["first_step_c"]:
            instructions_path = tri_modal["first_step_c"]
        elif tri_modal["first_step_v"]:
            instructions_path = tri_modal["first_step_v"]
        elif tri_modal["first_step_e"]:
            instructions_path = tri_modal["first_step_e"]
        else:
            # Should not happen if has_tri_modal is True
            instructions_path = workflow_dir / "instructions.md"

    # Extract template path (AC3)
    template_value = raw_config.get("template")
    if template_value is False:
        # Explicit false means no template
        template_path: str | None = None
    elif isinstance(template_value, str):
        # Store as raw string with placeholders (NOT resolved)
        template_path = template_value
    else:
        # Key absent or other type - no template
        template_path = None

    # Extract validation/checklist path
    validation_value = raw_config.get("validation")
    if validation_value is False:
        # Explicit false means no validation
        validation_path: str | None = None
    elif isinstance(validation_value, str):
        # Store as raw string with placeholders (NOT resolved)
        validation_path = validation_value
    else:
        # Key absent or other type - no validation
        validation_path = None

    # Extract workflow name (AC4)
    # Priority: 'name' key in config, fallback to directory name
    name = raw_config.get("name")
    if not name or not isinstance(name, str):
        name = workflow_dir.name

    return WorkflowIR(
        name=name,
        config_path=config_path.resolve(),
        instructions_path=instructions_path.resolve(),
        template_path=template_path,
        validation_path=validation_path,
        raw_config=raw_config,
        raw_instructions=raw_instructions,
        # Tri-modal fields
        workflow_type=tri_modal["workflow_type"],
        has_tri_modal=tri_modal["has_tri_modal"],
        steps_c_dir=tri_modal["steps_c_dir"],
        steps_v_dir=tri_modal["steps_v_dir"],
        steps_e_dir=tri_modal["steps_e_dir"],
        first_step_c=tri_modal["first_step_c"],
        first_step_v=tri_modal["first_step_v"],
        first_step_e=tri_modal["first_step_e"],
    )
