"""Tri-modal workflow utilities.

This module provides utilities for working with TEA Enterprise tri-modal workflows:
- Mode selection (create, validate, edit)
- Mode validation
- Available modes discovery

Public API:
    get_workflow_mode: Get the selected mode for a tri-modal workflow
    validate_workflow_mode: Validate mode is available for workflow
    get_available_modes: Get list of available modes for a workflow
"""

import logging
from typing import TYPE_CHECKING

from bmad_assist.compiler.types import WorkflowIR
from bmad_assist.core.exceptions import CompilerError

if TYPE_CHECKING:
    from bmad_assist.compiler.types import CompilerContext

logger = logging.getLogger(__name__)

# Valid mode identifiers
VALID_MODES = {"c", "v", "e"}

# Mode full names for normalization
MODE_NAMES = {
    "c": "c",
    "create": "c",
    "v": "v",
    "validate": "v",
    "e": "e",
    "edit": "e",
}


def normalize_mode(mode: str) -> str:
    """Normalize mode name to single character.

    Args:
        mode: Mode name (c, v, e, create, validate, edit).

    Returns:
        Normalized mode ('c', 'v', or 'e').

    Raises:
        CompilerError: If mode is not recognized.

    """
    normalized = MODE_NAMES.get(mode.lower())
    if normalized is None:
        raise CompilerError(
            f"Unknown workflow mode: '{mode}'\n"
            f"  Valid modes: c (create), v (validate), e (edit)"
        )
    return normalized


def get_available_modes(workflow_ir: WorkflowIR) -> list[str]:
    """Get list of available modes for a workflow.

    Args:
        workflow_ir: Parsed workflow intermediate representation.

    Returns:
        List of available mode identifiers (e.g., ['c', 'v', 'e']).

    """
    modes: list[str] = []

    if workflow_ir.steps_c_dir is not None:
        modes.append("c")
    if workflow_ir.steps_v_dir is not None:
        modes.append("v")
    if workflow_ir.steps_e_dir is not None:
        modes.append("e")

    return modes


def validate_workflow_mode(workflow_ir: WorkflowIR, mode: str) -> None:
    """Validate that mode is available for the workflow.

    Args:
        workflow_ir: Parsed workflow intermediate representation.
        mode: Mode to validate ('c', 'v', 'e', or full names).

    Raises:
        CompilerError: If mode is not available for this workflow.

    """
    # Normalize mode name
    normalized = normalize_mode(mode)

    # Check if workflow is tri-modal
    if not workflow_ir.has_tri_modal:
        raise CompilerError(
            f"Mode '{mode}' not available for workflow '{workflow_ir.name}'.\n"
            f"  This is a macro workflow without tri-modal step directories.\n"
            f"  Suggestion: Remove --mode flag for macro workflows"
        )

    # Get available modes
    available = get_available_modes(workflow_ir)

    # Check if requested mode is available
    if normalized not in available:
        available_str = ", ".join(available)
        raise CompilerError(
            f"Mode '{mode}' not available for workflow '{workflow_ir.name}'. Available modes: {available_str}"
        )


def get_workflow_mode(context: "CompilerContext") -> str | None:
    """Get the selected mode for a tri-modal workflow.

    Checks context.resolved_variables['workflow_mode'] for override,
    otherwise returns 'c' (create) as default for tri-modal workflows.

    Args:
        context: Compiler context with workflow_ir and resolved_variables.

    Returns:
        Mode identifier ('c', 'v', 'e') or None for macro workflows.

    """
    workflow_ir = context.workflow_ir
    if workflow_ir is None:
        return None

    # Macro workflows don't have modes
    if not workflow_ir.has_tri_modal:
        return None

    # Check for override in context
    mode_override = context.resolved_variables.get("workflow_mode")
    if mode_override:
        # Normalize and return (validation happens separately)
        return normalize_mode(str(mode_override))

    # Default to 'c' (create) mode
    return "c"
