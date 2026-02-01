"""Step chain building for tri-modal workflows.

This module provides functions for parsing step files and building step chains
for TEA Enterprise tri-modal workflows.

Public API:
    parse_step_file: Parse a single step file into StepIR
    build_step_chain: Build chain following nextStepFile references
    concatenate_step_chain: Concatenate steps into single instructions string
    compile_step_chain: Build chain and resolve variables in content
"""

import logging
from pathlib import Path
from typing import Any

import yaml

from bmad_assist.compiler.types import StepIR
from bmad_assist.core.exceptions import CompilerError

logger = logging.getLogger(__name__)

# Maximum chain depth to prevent infinite loops
MAX_CHAIN_DEPTH = 20


def parse_step_file(step_path: Path) -> StepIR:
    """Parse a tri-modal step file into StepIR.

    Extracts YAML frontmatter and markdown content from a step file.
    Validates that nextStepFile paths are relative and don't escape
    the workflow directory.

    Args:
        step_path: Path to the step file.

    Returns:
        StepIR with parsed frontmatter and content.

    Raises:
        CompilerError: If nextStepFile contains path traversal.

    """
    try:
        content = step_path.read_text(encoding="utf-8")
    except OSError as e:
        raise CompilerError(
            f"Cannot read step file: {step_path}\n"
            f"  Error: {e}"
        ) from e

    # Parse frontmatter
    frontmatter: dict = {}
    raw_content = content

    if content.startswith("---"):
        # Find closing ---
        end_pos = content.find("---", 3)
        if end_pos != -1:
            frontmatter_str = content[3:end_pos].strip()
            raw_content = content[end_pos + 3:].lstrip("\n")

            if frontmatter_str:
                try:
                    parsed = yaml.safe_load(frontmatter_str)
                    if isinstance(parsed, dict):
                        frontmatter = parsed
                    else:
                        logger.warning(
                            "Step file %s has non-dict frontmatter, ignoring",
                            step_path,
                        )
                except yaml.YAMLError as e:
                    logger.warning(
                        "Invalid YAML in step file %s frontmatter: %s",
                        step_path,
                        e,
                    )

    # Extract fields from frontmatter
    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    next_step_file = frontmatter.get("nextStepFile")
    knowledge_index = frontmatter.get("knowledgeIndex")

    # Security: Validate nextStepFile
    if next_step_file:
        if not isinstance(next_step_file, str):
            next_step_file = str(next_step_file)

        # Check for path traversal
        if ".." in next_step_file:
            raise CompilerError(
                f"Path traversal detected in step file {step_path}:\n"
                f"  nextStepFile: '{next_step_file}' contains '..'\n"
                f"  Suggestion: Use relative path within workflow directory"
            )

        # Check for absolute path
        if next_step_file.startswith("/"):
            raise CompilerError(
                f"Absolute path not allowed in step file {step_path}:\n"
                f"  nextStepFile: '{next_step_file}' is an absolute path\n"
                f"  Suggestion: Use relative path like './step-02.md'"
            )

    return StepIR(
        path=step_path,
        name=name if isinstance(name, str) else "",
        description=description if isinstance(description, str) else "",
        next_step_file=next_step_file,
        knowledge_index=knowledge_index if isinstance(knowledge_index, str) else None,
        raw_content=raw_content,
    )


def build_step_chain(
    first_step: Path,
    max_depth: int = MAX_CHAIN_DEPTH,
) -> list[StepIR]:
    """Build step chain by following nextStepFile references.

    Starting from the first step, follows nextStepFile references to build
    the complete chain. Detects circular references and enforces maximum
    depth to prevent infinite loops.

    Args:
        first_step: Path to the first step file.
        max_depth: Maximum chain length (default: 20).

    Returns:
        List of StepIR objects in chain order.

    Raises:
        CompilerError: If circular reference detected or max depth exceeded.

    """
    chain: list[StepIR] = []
    visited: set[Path] = set()
    current_path = first_step.resolve()

    while current_path is not None:
        # Check for circular reference
        if current_path in visited:
            cycle_path = " -> ".join(s.name or str(s.path.name) for s in chain)
            cycle_path += f" -> {current_path.name}"
            raise CompilerError(
                f"Circular reference detected in step chain:\n"
                f"  Cycle: {cycle_path}\n"
                f"  Suggestion: Check nextStepFile references in your step files"
            )

        # Check max depth
        if len(chain) >= max_depth:
            chain_path = " -> ".join(s.name or str(s.path.name) for s in chain)
            raise CompilerError(
                f"Step chain exceeds maximum depth (20). Chain: {chain_path}"
            )

        # Parse current step
        visited.add(current_path)
        step = parse_step_file(current_path)
        chain.append(step)

        # Determine next step
        if not step.next_step_file:
            break

        # Resolve next step path relative to current step's directory
        next_path = (current_path.parent / step.next_step_file).resolve()

        if not next_path.exists():
            logger.warning(
                "Next step not found: %s (from %s). Chain truncated.",
                step.next_step_file,
                current_path.name,
            )
            break

        current_path = next_path

    return chain


def concatenate_step_chain(steps: list[StepIR]) -> str:
    """Concatenate step chain into single instructions string.

    Combines all step content with boundary markers for each step.

    Args:
        steps: List of StepIR objects from build_step_chain.

    Returns:
        Single string with all step content, separated by markers.

    """
    if not steps:
        return ""

    parts: list[str] = []

    for step in steps:
        step_name = step.name or step.path.name
        marker = f"<!-- STEP: {step_name} -->"
        parts.append(marker)
        parts.append(step.raw_content)

    return "\n".join(parts)


def compile_step_chain(
    first_step: Path,
    resolved_variables: dict[str, Any],
    project_root: Path,
    max_depth: int = MAX_CHAIN_DEPTH,
    workflow_id: str | None = None,
) -> tuple[str, list[str]]:
    """Build step chain and resolve variables in content.

    This is the high-level function for tri-modal workflow compilation.
    It builds the step chain, concatenates content, and resolves variables
    including TEA-specific variables.

    Args:
        first_step: Path to the first step file.
        resolved_variables: Dict of resolved variables for substitution.
        project_root: Project root directory.
        max_depth: Maximum chain length (default: 20).
        workflow_id: Optional workflow identifier for knowledge base loading
            (e.g., "testarch-atdd"). If provided and starts with "testarch-",
            knowledge fragments will be loaded and injected.

    Returns:
        Tuple of (compiled_content, context_files):
        - compiled_content: Step chain with variables resolved
        - context_files: List of file paths to include in context (e.g., knowledge index)

    Raises:
        CompilerError: If chain building fails.

    """
    from bmad_assist.compiler.variable_utils import substitute_variables
    from bmad_assist.compiler.variables.tea import (
        resolve_knowledge_index,
        resolve_next_step_file,
        resolve_tea_variables,
    )

    # Build the step chain
    steps = build_step_chain(first_step, max_depth)

    if not steps:
        return "", []

    # Collect context files (like knowledge index)
    context_files: list[str] = []

    # Check first step for knowledge index
    first_step_ir = steps[0]
    if first_step_ir.knowledge_index:
        ki_path = resolve_knowledge_index(
            project_root, first_step_ir.knowledge_index
        )
        if ki_path:
            context_files.append(ki_path)
            # Add to resolved variables for substitution
            resolved_variables["knowledgeIndex"] = ki_path
    else:
        # Try to find default knowledge index
        ki_path = resolve_knowledge_index(project_root)
        if ki_path:
            context_files.append(ki_path)
            resolved_variables["knowledgeIndex"] = ki_path

    # Check if this is a TEA workflow requiring knowledge injection
    is_tea = workflow_id and workflow_id.startswith("testarch-")

    # Log warning if knowledge index missing for TEA workflow (AC7)
    if is_tea and "knowledgeIndex" not in resolved_variables:
        logger.warning(
            "Knowledge index not found for TEA workflow %s "
            "(knowledge fragments may not load correctly)",
            workflow_id,
        )

    # Create context_files dict for knowledge base injection (AC7)
    knowledge_context: dict[str, str] = {}

    # Resolve TEA config variables with workflow_id for knowledge loading
    # Pass knowledge_context to capture loaded knowledge fragments
    resolve_tea_variables(
        resolved_variables,
        project_root,
        workflow_id=workflow_id,
        context_files=knowledge_context,
    )

    # Resolve nextStepFile paths for each step (for any inline references)
    for step in steps:
        if step.next_step_file:
            abs_next = resolve_next_step_file(step.next_step_file, step.path)
            # Add step-specific variable for this step
            # Using step name as key prefix for scoped variables
            step_key = step.name.replace("-", "_") if step.name else step.path.stem
            resolved_variables[f"{step_key}_nextStepFile"] = abs_next

    # Concatenate all step content
    raw_content = concatenate_step_chain(steps)

    # Inject knowledge base content before step content (AC7)
    if knowledge_context.get("knowledge_base"):
        knowledge_section = (
            "<!-- KNOWLEDGE BASE -->\n"
            f"{knowledge_context['knowledge_base']}\n"
            "<!-- END KNOWLEDGE BASE -->\n\n"
        )
        raw_content = knowledge_section + raw_content
        logger.debug(
            "Injected knowledge base content for workflow %s",
            workflow_id,
        )

    # Apply variable substitution
    compiled_content = substitute_variables(raw_content, resolved_variables)

    return compiled_content, context_files
