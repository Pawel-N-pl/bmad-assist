"""Variable resolution engine for BMAD workflow compilation.

This package resolves all variable placeholders in workflow configurations.
See core.py for the main resolve_variables() function and detailed documentation.

Public API:
- resolve_variables(): Main entry point for variable resolution
- MAX_RECURSION_DEPTH: Recursion limit constant

Internal functions are re-exported for backward compatibility with existing tests.
New code should import internal functions directly from submodules.
"""

# Public API
# Re-exports for backward compatibility with tests (will be deprecated)
# Tests should import directly from submodules, e.g.:
#   from bmad_assist.compiler.variables.paths import _validate_config_path
from bmad_assist.compiler.variables.core import (  # noqa: F401
    _COMPUTED_VARIABLES,
    _CONFIG_SOURCE_PATTERN,
    _DOUBLE_BRACE_PATTERN,
    _SINGLE_BRACE_PATTERN,
    _SYSTEM_VARIABLES,
    MAX_RECURSION_DEPTH,
    _resolve_all_recursive,
    _resolve_dict_value_placeholders,
    _resolve_recursive,
    resolve_variables,
)
from bmad_assist.compiler.variables.epic_story import (  # noqa: F401
    _compute_story_variables,
    _extract_story_title_from_epics,
)
from bmad_assist.compiler.variables.paths import (  # noqa: F401
    _load_external_config,
    _resolve_path_placeholders,
    _validate_config_path,
)
from bmad_assist.compiler.variables.patterns import (  # noqa: F401
    _find_epic_file_in_sharded_dir,
    _find_sharded_index,
    _find_whole_file,
    _resolve_input_file_patterns,
)
from bmad_assist.compiler.variables.project_context import (  # noqa: F401
    _estimate_tokens,
    _resolve_project_context,
)
from bmad_assist.compiler.variables.sprint_status import (  # noqa: F401
    _extract_story_title,
    _resolve_sprint_status,
)
from bmad_assist.compiler.variables.tea import (  # noqa: F401
    resolve_knowledge_index,
    resolve_next_step_file,
    resolve_tea_config_flags,
    resolve_tea_variables,
)

__all__ = [
    "resolve_variables",
    "MAX_RECURSION_DEPTH",
    "resolve_tea_variables",
    "resolve_knowledge_index",
]
