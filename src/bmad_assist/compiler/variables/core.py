"""Core variable resolution engine for BMAD workflow variables.

This module contains:
- resolve_variables(): Main orchestrator function
- Recursive resolution functions
- Variable placeholder substitution
- Circular reference detection
- Recursion depth limiting

Dependencies flow: core.py imports from paths.py, sprint_status.py, etc.
"""

import logging
import re
from pathlib import Path
from typing import Any

from bmad_assist.compiler.types import CompilerContext, WorkflowIR
from bmad_assist.compiler.variables.paths import (
    _load_external_config,
    _resolve_path_placeholders,
    _validate_config_path,
)
from bmad_assist.core.exceptions import VariableError

logger = logging.getLogger(__name__)

# Maximum recursion depth for variable resolution (prevents infinite loops)
MAX_RECURSION_DEPTH = 10

# Patterns for variable matching
# Single braces: {var_name} or {source}:key
_SINGLE_BRACE_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_-]*)\}")
# Double braces: {{var_name}}
_DOUBLE_BRACE_PATTERN = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_-]*)\}\}")

# Config source pattern: {config_source}:key_name
_CONFIG_SOURCE_PATTERN = re.compile(r"\{config_source\}:([a-zA-Z_][a-zA-Z0-9_-]*)")

# Known system variables that get special treatment
_SYSTEM_VARIABLES = frozenset(
    {
        "project-root",
        "installed_path",
        "config_source",
    }
)

# Computed variables (used for documentation/reference, may be extended later)
_COMPUTED_VARIABLES = frozenset(
    {
        "story_id",
        "story_key",
        "story_title",
        "date",
    }
)

__all__ = [
    "resolve_variables",
    "MAX_RECURSION_DEPTH",
    "_CONFIG_SOURCE_PATTERN",
    "_SINGLE_BRACE_PATTERN",
    "_DOUBLE_BRACE_PATTERN",
    "_SYSTEM_VARIABLES",
    "_COMPUTED_VARIABLES",
    "_resolve_dict_value_placeholders",
    "_resolve_all_recursive",
    "_resolve_recursive",
]


def _resolve_dict_value_placeholders(
    d: dict[str, Any],
    resolved: dict[str, Any],
    context: CompilerContext,
    workflow_ir: WorkflowIR,
) -> dict[str, Any]:
    """Resolve placeholders in dict string values using resolved variables.

    Recursively processes nested dicts. Non-string, non-dict values pass through.

    Args:
        d: Dict with potentially unresolved string values.
        resolved: Already resolved variables to use for substitution.
        context: Compiler context.
        workflow_ir: Workflow IR.

    Returns:
        New dict with placeholders resolved in string values.

    """
    result: dict[str, Any] = {}
    for key, value in d.items():
        if isinstance(value, str):
            result[key] = _resolve_recursive(value, resolved, set(), 0, key, context, workflow_ir)
        elif isinstance(value, dict):
            result[key] = _resolve_dict_value_placeholders(value, resolved, context, workflow_ir)
        else:
            result[key] = value
    return result


def _resolve_all_recursive(
    resolved: dict[str, Any],
    context: CompilerContext,
    workflow_ir: WorkflowIR,
) -> dict[str, Any]:
    """Recursively resolve all remaining variable placeholders.

    Processes each string value to resolve any {variable} or {{variable}}
    patterns that reference other resolved values.

    Args:
        resolved: Dictionary of currently resolved values.
        context: Compiler context.
        workflow_ir: Workflow IR.

    Returns:
        Dictionary with all recursive references resolved.

    Raises:
        VariableError: If circular reference detected or max depth exceeded.

    """
    result: dict[str, Any] = {}

    for key, value in resolved.items():
        if isinstance(value, str):
            result[key] = _resolve_recursive(value, resolved, set(), 0, key, context, workflow_ir)
        else:
            result[key] = value

    return result


def _resolve_recursive(
    value: str,
    resolved: dict[str, Any],
    visiting: set[str],
    depth: int,
    current_key: str,
    context: CompilerContext,
    workflow_ir: WorkflowIR,
) -> str:
    """Recursively resolve a single string value.

    Args:
        value: String to resolve.
        resolved: Dictionary of resolved values to look up.
        visiting: Set of variables currently being resolved (cycle detection).
        depth: Current recursion depth.
        current_key: Key of the variable being resolved (for error messages).
        context: Compiler context.
        workflow_ir: Workflow IR.

    Returns:
        Fully resolved string.

    Raises:
        VariableError: If circular reference or max depth exceeded.

    """
    if depth > MAX_RECURSION_DEPTH:
        max_depth = MAX_RECURSION_DEPTH
        raise VariableError(
            f"Cannot resolve '{current_key}': max recursion depth ({max_depth}) exceeded\n"
            f"  Sources checked: variable definitions in workflow.yaml\n"
            f"  Suggestion: Simplify nesting or check for indirect circular references",
            variable_name=current_key,
            sources_checked=["workflow.yaml"],
            suggestion="Simplify variable nesting or check for indirect circular references",
        )

    result = value

    # Find all variable references in the value
    # Process double braces first (they are more specific), then single braces
    # Double braces {{var}} should be treated same as single braces {var}
    for pattern in [_DOUBLE_BRACE_PATTERN, _SINGLE_BRACE_PATTERN]:
        # Keep resolving until no more matches (handles overlapping replacements)
        prev_result = None
        while prev_result != result:
            prev_result = result
            for match in pattern.finditer(result):
                var_name = match.group(1)
                full_match = match.group(0)

                # Skip system variables that were already resolved
                if var_name in _SYSTEM_VARIABLES:
                    continue

                # Check for circular reference
                if var_name in visiting:
                    cycle_path = " → ".join(visiting) + f" → {var_name}"
                    raise VariableError(
                        f"Cannot resolve variable '{var_name}': circular reference detected\n"
                        f"  Cycle path: {cycle_path}\n"
                        f"  Sources checked: variable definitions in workflow.yaml\n"
                        f"  Suggestion: Remove circular dependency in variable definitions",
                        variable_name=var_name,
                        sources_checked=["workflow.yaml"],
                        suggestion="Remove circular dependency in variable definitions",
                    )

                # Look up the variable value
                if var_name in resolved:
                    var_value = resolved[var_name]

                    # Convert to string for substitution
                    if not isinstance(var_value, str):
                        var_value = str(var_value)

                    # Add to visiting set for cycle detection
                    visiting.add(var_name)

                    # Recursively resolve the value
                    resolved_value = _resolve_recursive(
                        var_value, resolved, visiting, depth + 1, var_name, context, workflow_ir
                    )

                    visiting.discard(var_name)

                    # Replace in result
                    result = result.replace(full_match, resolved_value, 1)
                    break  # Re-scan after replacement
                else:
                    # Unknown variable - leave as-is (may be handled later by Jinja2)
                    logger.debug("Unknown variable pattern '%s' - leaving as-is", full_match)

    # Resolve any remaining path placeholders
    result = _resolve_path_placeholders(result, context, workflow_ir)

    return result


def resolve_variables(
    context: CompilerContext,
    invocation_params: dict[str, Any],
    sprint_status_path: Path | None = None,
    epics_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve all variables in workflow configuration.

    Resolution order (priority low to high):
    1. config_source values (user config.yaml - lowest priority defaults)
    2. workflow.yaml raw_config values
    3. invocation_params (CLI arguments)
    4. Computed story variables (story_id, story_key, date, timestamp)
    5. Recursive resolution of placeholders
    6. Flattened 'variables' dict
    7. project_context resolution (dual-name detection with token estimate)
    8. input_file_patterns resolution (directory-based - overrides earlier)
    9. sprint_status resolution (docs/ or docs/sprint-artifacts/)
    10. Hard overrides (user_skill_level, communication_language, etc.)
    11. Remove internal/unused variables

    Args:
        context: Compiler context with workflow_ir set.
        invocation_params: Parameters from CLI invocation (epic_num, story_num, etc.).
        sprint_status_path: Optional path to sprint-status.yaml for story_title lookup.
        epics_path: Optional path to epics file for story_title extraction fallback.

    Returns:
        Dictionary of resolved variable names to values.

    Raises:
        VariableError: If required variable cannot be resolved,
            circular reference detected, or config file issues.

    """
    # Import here to avoid circular imports
    from bmad_assist.compiler.variables.epic_story import _compute_story_variables
    from bmad_assist.compiler.variables.patterns import _resolve_input_file_patterns
    from bmad_assist.compiler.variables.project_context import _resolve_project_context
    from bmad_assist.compiler.variables.sprint_status import _resolve_sprint_status

    if context.workflow_ir is None:
        raise VariableError(
            "Cannot resolve variables: workflow_ir not set in context",
            suggestion="Ensure parse_workflow() was called before resolve_variables()",
        )

    workflow_ir = context.workflow_ir
    raw_config = workflow_ir.raw_config.copy()

    # Initialize resolved variables (will be populated in priority order)
    resolved: dict[str, Any] = {}

    # Step 1: Load config_source and merge ALL values as defaults (lowest priority)
    if "config_source" in raw_config:
        config_source_raw = raw_config["config_source"]
        if isinstance(config_source_raw, str):
            config_source_path = _resolve_path_placeholders(config_source_raw, context, workflow_ir)

            # Validate and load external config
            config_path = Path(config_source_path)
            _validate_config_path(config_path, context.project_root)

            if not config_path.exists():
                raise VariableError(
                    f"Config source file not found: {config_path}\n"
                    f"  Variable: config_source\n"
                    f"  Suggestion: Ensure config file exists at {config_path}",
                    variable_name="config_source",
                    sources_checked=["workflow.yaml"],
                    suggestion=f"Ensure config file exists at {config_path}",
                )

            external_config = _load_external_config(config_path)
            logger.info("Loaded external config from %s", config_path)

            # Merge all config values as defaults
            for key, value in external_config.items():
                if isinstance(value, str):
                    value = _resolve_path_placeholders(value, context, workflow_ir)
                resolved[key] = value
                logger.debug("Merged from config_source: %s", key)

    # Step 2: Process workflow.yaml raw_config values (overrides config_source)
    for key, value in raw_config.items():
        if key == "config_source":
            # Already handled above
            continue

        if not isinstance(value, str):
            # Non-string values pass through unchanged
            resolved[key] = value
            logger.debug("Set from workflow.yaml: %s (%s)", key, type(value).__name__)
            continue

        # Skip {config_source}:key patterns (now redundant - all config merged)
        if _CONFIG_SOURCE_PATTERN.match(value):
            logger.debug("Skipping legacy {config_source}:key pattern for %s", key)
            continue

        # Regular string - resolve path placeholders
        resolved[key] = _resolve_path_placeholders(value, context, workflow_ir)

    # Step 3: Apply invocation params (highest priority from CLI)
    for key, value in invocation_params.items():
        resolved[key] = value
        logger.debug("Set from invocation params: %s", key)

    # Step 4: Compute story variables if epic_num and story_num are available
    epic_num = resolved.get("epic_num")
    story_num = resolved.get("story_num")

    if epic_num is not None and story_num is not None:
        # Get date override for deterministic builds (NFR11)
        # Only use override if it looks like an actual date (YYYY-MM-DD)
        date_val = resolved.get("date")
        date_override = None
        if isinstance(date_val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", date_val):
            date_override = date_val

        story_vars = _compute_story_variables(
            int(epic_num),
            int(story_num),
            sprint_status_path,
            epics_path,
            resolved.get("story_title"),
            date_override,
        )
        # Add computed values, overwriting date/timestamp (they're always computed)
        for k, v in story_vars.items():
            if k in ("date", "timestamp"):
                resolved[k] = v  # Always use computed date/timestamp
            elif k not in resolved:
                resolved[k] = v

    # Step 5: Recursive resolution for remaining placeholders
    resolved = _resolve_all_recursive(resolved, context, workflow_ir)

    # Step 6: Resolve placeholders in dict values (like 'variables' key)
    # This handles nested dicts where string values contain {placeholder} patterns
    for key, value in list(resolved.items()):
        if isinstance(value, dict):
            resolved_dict = _resolve_dict_value_placeholders(value, resolved, context, workflow_ir)
            # Flatten 'variables' dict - merge into main resolved, skip duplicates
            if key == "variables":
                for var_name, var_value in resolved_dict.items():
                    if var_name not in resolved:
                        resolved[var_name] = var_value
                        logger.debug("Merged variable from 'variables': %s", var_name)
                    else:
                        logger.debug("Skipped duplicate variable: %s", var_name)
                # Remove the 'variables' key itself after flattening
                del resolved[key]
                logger.debug("Flattened 'variables' dict into main resolved")
            else:
                resolved[key] = resolved_dict

    # Step 7: Resolve project_context (dual-name detection with token estimate)
    resolved = _resolve_project_context(resolved, context)

    # Step 8: Resolve input_file_patterns to variables with attributes
    # (directory-based detection overrides earlier values)
    resolved = _resolve_input_file_patterns(resolved, context)

    # Step 9: Resolve sprint_status path (docs/ or docs/sprint-artifacts/)
    resolved = _resolve_sprint_status(resolved, context)

    # Step 9.5: TEA variable resolution for testarch-* workflows
    # Only applies if workflow name starts with "testarch-"
    workflow_name = workflow_ir.name if workflow_ir else None
    if workflow_name and workflow_name.startswith("testarch-"):
        from bmad_assist.testarch.core.variables import TEAVariableResolver

        tea_resolver = TEAVariableResolver()
        tea_vars = tea_resolver.resolve_all(context, workflow_name)

        # Merge TEA variables (don't override existing)
        for key, value in tea_vars.items():
            if key not in resolved:
                resolved[key] = value
                logger.debug("Set from TEA resolver: %s", key)

    # Step 10: Apply hard overrides (always enforced regardless of config)
    resolved["user_skill_level"] = "expert"
    resolved["communication_language"] = "English"
    resolved["document_output_language"] = "English"

    # Step 11: Remove internal/unused variables
    # - standalone: unused workflow flag, conflicts with future "standalone story" feature
    for key in ["standalone"]:
        resolved.pop(key, None)

    # Step 12: Store in context and return
    context.resolved_variables = resolved
    logger.debug("Resolved %d variables", len(resolved))

    return resolved
