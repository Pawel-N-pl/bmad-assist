"""XML output generation module for BMAD workflow compiler.

This module transforms CompiledWorkflow data into a well-formed XML string
following recency-bias ordering principles where the most relevant content
(instructions, output template) appears at the end.

Public API:
    generate_output: Generate XML output from compiled workflow
    GeneratedOutput: Return type containing XML string and metadata

IMPORTANT: This module builds XML manually (not via ElementTree) to avoid
automatic escaping of < > characters in content. Instructions contain XML
that must be embedded literally, and context files may contain code.
"""

import json
import logging
import xml.etree.ElementTree as ET  # Only used for validation, not building
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bmad_assist.compiler.types import CompiledWorkflow
from bmad_assist.core.exceptions import CompilerError, TokenBudgetError

logger = logging.getLogger(__name__)

# Size threshold for INFO-level logging (100KB)
LARGE_OUTPUT_THRESHOLD: int = 100 * 1024

# Characters per token estimate (English text approximation)
CHARS_PER_TOKEN_ESTIMATE: int = 4

# Token budget limits (per NFR10: ~20k tokens max)
DEFAULT_SOFT_LIMIT_TOKENS: int = 15_000
DEFAULT_HARD_LIMIT_TOKENS: int = 20_000
SOFT_LIMIT_RATIO: float = 0.75  # Warn at 75% of custom hard limit

__all__ = [
    "generate_output",
    "GeneratedOutput",
    "validate_token_budget",
    "DEFAULT_SOFT_LIMIT_TOKENS",
    "DEFAULT_HARD_LIMIT_TOKENS",
    "SOFT_LIMIT_RATIO",
]


def _escape_xml_attr(value: str) -> str:
    """Escape string for use in XML attribute value.

    Only escapes characters that are invalid in attribute values.
    Does NOT escape < > in content (use CDATA for that).

    Args:
        value: String to escape.

    Returns:
        Escaped string safe for XML attribute.

    """
    return (
        value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _sanitize_xml_content(content: str) -> str:
    """Remove invalid XML characters from content.

    XML 1.0 spec only allows these control characters:
    - 0x09 (TAB)
    - 0x0A (LF)
    - 0x0D (CR)

    All other chars in range 0x00-0x1F are invalid even inside CDATA.
    This commonly occurs in minified JS, binary diffs, or build artifacts.

    Args:
        content: Raw content to sanitize.

    Returns:
        Content with invalid control chars removed.

    """
    if not content:
        return ""
    # Remove invalid control chars (keep tab, newline, carriage return)
    return "".join(ch for ch in content if ord(ch) >= 0x20 or ord(ch) in (0x09, 0x0A, 0x0D))


def _wrap_cdata(content: str) -> str:
    """Wrap content in CDATA section to preserve < > characters.

    Handles the edge case where content contains ']]>' by splitting
    into multiple CDATA sections.

    Adds two newlines after <![CDATA[ and before ]]> for readability.

    Sanitizes content to remove invalid XML control characters (0x00-0x1F
    except tab/LF/CR) that can appear in minified JS or binary diffs.

    Args:
        content: Raw content to wrap.

    Returns:
        CDATA-wrapped sanitized string.

    """
    if not content:
        return ""
    # Sanitize first to remove invalid XML control chars
    content = _sanitize_xml_content(content)
    # Handle ]]> in content by splitting CDATA sections
    # "foo]]>bar" becomes "<![CDATA[\n\nfoo\n\n]]]]><![CDATA[\n\n>\n\n]]>"
    if "]]>" in content:
        parts = content.split("]]>")
        return "<![CDATA[\n\n" + "\n\n]]]]><![CDATA[\n\n".join(parts) + "\n\n]]>"
    return "<![CDATA[\n\n" + content + "\n\n]]>"


def _get_file_label(path_str: str) -> str:
    """Get human-readable label for a file based on its path pattern.

    Args:
        path_str: File path (can be absolute, relative, or virtual like "[Validator A]").

    Returns:
        Uppercase label describing the file type (e.g., "PROJECT CONTEXT", "STORY FILE").

    """
    path_lower = path_str.lower()

    # Virtual paths (validation outputs, DV findings, etc.)
    if path_str.startswith("[") and path_str.endswith("]"):
        if "validator" in path_lower:
            return "VALIDATION OUTPUT"
        if "reviewer" in path_lower:
            return "CODE REVIEW OUTPUT"
        if "deep verify" in path_lower:
            return "DEEP VERIFY FINDINGS"
        if "security" in path_lower:
            return "SECURITY ANALYSIS"
        return "VIRTUAL CONTENT"

    # Strategic docs
    if "project_context" in path_lower or "project-context" in path_lower:
        return "PROJECT CONTEXT"
    if path_lower.endswith("prd.md"):
        return "PRD"
    if "architecture" in path_lower and path_lower.endswith(".md"):
        return "ARCHITECTURE"
    if "ux" in path_lower and path_lower.endswith(".md"):
        return "UX DESIGN"
    if "epic" in path_lower and path_lower.endswith(".md"):
        return "EPIC"
    if "epics" in path_lower:
        return "EPIC"
    if "modules" in path_lower and path_lower.endswith(".md"):
        return "MODULE DOCUMENTATION"

    # Story files
    if "sprint-artifacts" in path_lower or "implementation-artifacts" in path_lower:
        import re

        if re.search(r"/\d+-\d+-[^/]+\.md$", path_lower):
            return "STORY FILE"
        if "sprint-status" in path_lower:
            return "SPRINT STATUS"

    # Source code
    if path_str.endswith(
        (".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cpp", ".c", ".h")
    ):
        return "SOURCE CODE"
    if path_str.endswith((".yaml", ".yml", ".toml", ".json", ".xml")):
        return "CONFIG FILE"
    if path_str.endswith((".md", ".rst", ".txt")):
        return "DOCUMENTATION"
    if path_str.endswith((".css", ".scss", ".sass", ".less")):
        return "STYLESHEET"
    if path_str.endswith((".html", ".htm")):
        return "HTML TEMPLATE"
    if path_str.endswith(".sql"):
        return "SQL QUERY"

    # Test files
    if "test" in path_lower:
        return "TEST FILE"

    # Default
    return "FILE"


@dataclass(frozen=True)
class GeneratedOutput:
    """Final generated XML output with metadata.

    Attributes:
        xml: The generated XML string.
        token_estimate: Estimated token count (len(xml) // 4).
        size_bytes: Byte size of XML output in UTF-8 encoding.

    """

    xml: str
    token_estimate: int
    size_bytes: int


# File ordering patterns for recency-bias optimization.
#
# Files are ordered from general (early) to specific (late) in the output.
# Each tuple contains pattern strings matched against file paths (case-insensitive).
# Earlier matches appear first in the context section.
#
# Order is CRITICAL for LLM attention mechanisms:
# - General content (project_context) appears early (lower attention weight)
# - Specific content (epics, stories) appears late (higher attention weight)
#
# IMPORTANT: Story files (matching "-story" or "-\d-\d" pattern) must appear LAST
# for dev-story workflow recency-bias requirements.
#
# DO NOT REORDER without updating tests and validating LLM performance.
FILE_ORDER_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("project_context", "project-context"),  # Step 1: General project rules and patterns
    ("prd",),  # Step 2: Product requirements and features
    ("ux",),  # Step 3: UX design specifications
    ("architecture",),  # Step 4: Technical constraints and patterns
    ("epics", "epic-"),  # Step 5: Epic content
    # Files not matching any pattern get index = len(patterns), placing them after epics
    # This includes source files from File List, which is correct behavior
)


def _serialize_value(value: Any) -> str:
    """Serialize value for XML variable element.

    Args:
        value: Value to serialize.

    Returns:
        String representation of the value.

    Raises:
        CompilerError: If value is not JSON-serializable.

    """
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    # Complex types: serialize as JSON with sorted keys for determinism
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as e:
        raise CompilerError(
            f"Variable has non-JSON-serializable type: {type(value).__name__}\n"
            f"  Error: {e}\n"
            f"  Why it's needed: All variables must be serializable for XML output\n"
            f"  How to fix: Convert to primitive type (str, int, float, bool, list, dict)"
        ) from e


def _get_file_order_key(path: str) -> tuple[int, str]:
    """Get ordering key for a file path.

    Args:
        path: File path to get ordering key for.

    Returns:
        Tuple of (order_index, path) for sorting.
        Lower index = appears earlier in output (general content).
        Higher index = appears later (more specific content).

    Story files in sprint-artifacts (matching {epic}-{story}-*.md pattern)
    get the highest index to appear LAST per recency-bias requirements.

    """
    import re

    path_lower = path.lower()

    # Story files MUST appear LAST for recency-bias (dev-story AC1 requirement)
    # Pattern: sprint-artifacts/{epic}-{story}-*.md (e.g., "14-1-dev-story-compiler.md")
    if "sprint-artifacts" in path_lower and re.search(r"/\d+-\d+-[^/]+\.md$", path_lower):
        # Story files get highest priority (last in output)
        return (len(FILE_ORDER_PATTERNS) + 1, path)

    for idx, patterns in enumerate(FILE_ORDER_PATTERNS):
        for pattern in patterns:
            if pattern in path_lower:
                return (idx, path)
    # Files not matching any pattern go after epics but before story files
    return (len(FILE_ORDER_PATTERNS), path)


def _normalize_path(path: Path) -> str:
    """Normalize path to absolute path string with forward slashes.

    Always returns absolute path with forward slashes for:
    - Cross-platform determinism (NFR11)
    - Matching with variable values that use absolute paths
    - Avoiding LLM confusion about file locations

    Args:
        path: Path to normalize.

    Returns:
        Absolute path string with forward slashes.

    """
    # Resolve to absolute and normalize slashes
    return str(path.resolve()).replace("\\", "/")


def _generate_file_id(path_str: str) -> str:
    """Generate deterministic short ID from file path.

    Uses first 8 characters of SHA-256 hash for:
    - Determinism: same path = same ID across compilations
    - Brevity: 8 hex chars is enough for uniqueness in typical projects
    - Readability: easy to reference in LLM output

    Args:
        path_str: Absolute file path string.

    Returns:
        8-character hex string (e.g., "6db78f3a").

    """
    import hashlib

    return hashlib.sha256(path_str.encode("utf-8")).hexdigest()[:8]


@dataclass(frozen=True)
class ContextSectionResult:
    """Result of building context section.

    Attributes:
        xml: The XML string for <context> section.
        path_to_id: Mapping of absolute file paths to their short IDs.

    """

    xml: str
    path_to_id: dict[str, str]


def _build_context_section(
    context_files: dict[str, str],
    project_root: Path,
    links_only: bool = False,
) -> ContextSectionResult:
    """Build the <context> section with ordered files and IDs.

    Uses CDATA to preserve < > characters in file contents.
    Each file gets a deterministic short ID (hash of path) for cross-referencing.

    Paths in XML are relative to project_root to reduce noise.
    Each file gets a label attribute indicating its type.

    Args:
        context_files: Dict mapping file paths to content.
        project_root: Project root for generating relative paths.
        links_only: If True, only include file paths without content (debug mode).

    Returns:
        ContextSectionResult with XML string and relative path-to-ID mapping.

    """
    file_elements: list[str] = []
    path_to_id: dict[str, str] = {}

    # Sort files by recency-bias order (general -> specific)
    sorted_paths = sorted(context_files.keys(), key=_get_file_order_key)

    for path_str in sorted_paths:
        # Validate path is non-empty
        if not path_str:
            logger.warning("Skipping empty path in context_files")
            continue

        content = context_files[path_str]
        # Skip empty content
        if not content:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Skipping empty file: {path_str}")
            continue

        # Special handling for project-tree: insert raw XML (not wrapped in <file>)
        if path_str == "[PROJECT-TREE]":
            file_elements.append(content)
            continue

        # Get label for this file type
        label = _get_file_label(path_str)

        # For virtual paths (starting with [), use as-is
        # For real paths, compute relative path from project root
        if path_str.startswith("["):
            display_path = path_str
            # Hash the virtual path for ID
            file_id = _generate_file_id(path_str)
        else:
            path = Path(path_str)
            try:
                # Try to make path relative to project root
                abs_path = path.resolve()
                display_path = str(abs_path.relative_to(project_root.resolve()))
            except (ValueError, OSError):
                # If path is outside project_root, use basename or full path
                display_path = path.name
                abs_path = path
            # Generate deterministic ID from absolute path for uniqueness
            file_id = _generate_file_id(str(abs_path))

        path_to_id[display_path] = file_id

        if links_only:
            # Debug mode: show only path and token estimate from actual file
            try:
                actual_size = Path(path_str).stat().st_size
                token_approx = actual_size // 4  # ~4 chars per token
            except (OSError, FileNotFoundError):
                # Fallback to content length if file doesn't exist
                token_approx = len(content) // 4
            file_elements.append(
                f'<file id="{file_id}" path="{_escape_xml_attr(display_path)}" '
                f'label="{_escape_xml_attr(label)}" token_approx="{token_approx}" />'
            )
        else:
            # Normal mode: include full content in CDATA
            file_elements.append(
                f'<file id="{file_id}" path="{_escape_xml_attr(display_path)}" '
                f'label="{_escape_xml_attr(label)}">{_wrap_cdata(content)}</file>'
            )

    xml = "<context>\n" + "\n".join(file_elements) + "\n</context>"
    return ContextSectionResult(xml=xml, path_to_id=path_to_id)


def _escape_xml_text(value: str) -> str:
    """Escape string for use as XML text content.

    Args:
        value: String to escape.

    Returns:
        Escaped string safe for XML text content.

    """
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _is_attributed_var(value: Any) -> bool:
    """Check if value is a variable with attributes (special dict format).

    Attributed variables have keys starting with underscore:
    - _value: the actual value (optional - if missing, var has no value)
    - _description: description text
    - _load_strategy: load strategy
    - _sharded: "true" if sharded
    - _token_approx: estimated token count

    """
    if not isinstance(value, dict):
        return False
    # Check if all keys start with underscore
    return all(k.startswith("_") for k in value)


def _find_file_id_for_value(
    value: str | None,
    path_to_id: dict[str, str],
    project_root: Path | None = None,
) -> str | None:
    """Find file ID if value matches an embedded file path.

    Normalizes the value path and checks against the path_to_id mapping.
    Handles both absolute and relative paths in path_to_id.

    Args:
        value: Variable value (possibly a file path).
        path_to_id: Mapping of file paths to their IDs (now relative paths).
        project_root: Project root for converting absolute to relative paths.

    Returns:
        File ID if value matches an embedded file, None otherwise.

    """
    if not value or not path_to_id:
        return None

    # First try exact match (for virtual paths like [Validator A])
    if value in path_to_id:
        return path_to_id[value]

    # Try absolute path normalization
    try:
        abs_path = str(Path(value).resolve()).replace("\\", "/")
        # Try direct match with absolute path
        if abs_path in path_to_id:
            return path_to_id[abs_path]

        # Try converting to relative path if project_root is available
        if project_root is not None:
            try:
                rel_path = str(Path(abs_path).relative_to(project_root.resolve()))
                if rel_path in path_to_id:
                    return path_to_id[rel_path]
            except (ValueError, OSError):
                # Path is outside project_root, skip
                pass
    except (OSError, ValueError):
        # Not a valid path
        pass

    return None


def _build_attributed_var(
    name: str,
    attrs: dict[str, Any],
    path_to_id: dict[str, str] | None = None,
    project_root: Path | None = None,
) -> str:
    """Build XML element for variable with attributes.

    Args:
        name: Variable name.
        attrs: Dict with attribute keys (prefixed with _).
        path_to_id: Optional mapping of file paths to IDs for cross-referencing.
        project_root: Project root for converting absolute to relative paths.

    Returns:
        XML string for the variable element.

    """
    # Build attribute string
    attr_parts = [f'name="{_escape_xml_attr(name)}"']

    # Check if value matches an embedded file
    var_value = attrs.get("_value")
    file_id = None
    display_value = var_value  # Default: show original value

    if path_to_id and var_value is not None:
        file_id = _find_file_id_for_value(str(var_value), path_to_id, project_root)
        if file_id:
            attr_parts.append(f'file_id="{file_id}"')
            # When embedded, show "embedded in prompt, file id: {id}" as value
            display_value = f"embedded in prompt, file id: {file_id}"
        elif project_root is not None:
            # For non-embedded files, convert to relative path from project root
            try:
                abs_path = Path(str(var_value)).resolve()
                rel_path = str(abs_path.relative_to(project_root.resolve()))
                display_value = rel_path
            except (ValueError, OSError):
                # Keep original value if path is outside project_root
                display_value = str(var_value)

    # Add description if present
    if "_description" in attrs:
        attr_parts.append(f'description="{_escape_xml_attr(str(attrs["_description"]))}"')

    # Add load_strategy - override to EMBEDDED if file is in context
    if file_id:
        attr_parts.append('load_strategy="EMBEDDED"')
    elif "_load_strategy" in attrs:
        attr_parts.append(f'load_strategy="{_escape_xml_attr(str(attrs["_load_strategy"]))}"')

    # Add sharded if present
    if "_sharded" in attrs:
        attr_parts.append(f'sharded="{_escape_xml_attr(str(attrs["_sharded"]))}"')

    # Add token_approx if present
    if "_token_approx" in attrs:
        attr_parts.append(f'token_approx="{_escape_xml_attr(str(attrs["_token_approx"]))}"')

    attr_str = " ".join(attr_parts)

    # Check if has value
    if "_value" in attrs and attrs["_value"] is not None:
        value = _escape_xml_text(str(display_value))
        return f"<var {attr_str}>{value}</var>"
    else:
        # Self-closing tag - no value
        return f"<var {attr_str} />"


def _is_garbage_variable(name: str) -> bool:
    """Check if variable name is garbage that should be filtered out.

    Args:
        name: Variable name to check.

    Returns:
        True if variable should be filtered out.

    """
    if not name:
        return True
    return bool(name.startswith("(") or name.endswith(")"))


def _build_variables_section(
    variables: dict[str, Any],
    path_to_id: dict[str, str] | None = None,
    project_root: Path | None = None,
) -> str:
    """Build the <variables> section with sorted variables.

    Supports two variable formats:
    1. Simple: name -> value (rendered as <var name="...">value</var>)
    2. Attributed: name -> {_value, _description, ...} (rendered with attributes)

    When a variable value matches an embedded file path, adds file_id attribute
    for easy cross-referencing.

    Filters out garbage variables (empty names, names with parentheses).

    Args:
        variables: Dict of variable names to values.
        path_to_id: Optional mapping of file paths to IDs for cross-referencing.
        project_root: Project root for converting absolute to relative paths.

    Returns:
        XML string for the <variables> section.

    Raises:
        CompilerError: If a variable value is not JSON-serializable.

    """
    var_elements: list[str] = []

    # Sort variables alphabetically for determinism (NFR11)
    # Filter out garbage variables at output time
    for name in sorted(variables.keys()):
        if _is_garbage_variable(name):
            logger.debug("Filtering garbage variable from output: %s", name)
            continue
        value = variables[name]

        if _is_attributed_var(value):
            # Variable with attributes
            var_elements.append(_build_attributed_var(name, value, path_to_id, project_root))
        else:
            # Simple variable - check if it matches a file path
            serialized = _serialize_value(value)
            file_id = None
            display_value = serialized  # Default: show original value

            if path_to_id and isinstance(value, str):
                file_id = _find_file_id_for_value(value, path_to_id, project_root)
                if file_id:
                    # When embedded, show "embedded in prompt, file id: {id}" as value
                    display_value = f"embedded in prompt, file id: {file_id}"
                    var_elements.append(
                        f'<var name="{_escape_xml_attr(name)}" file_id="{file_id}">'
                        f"{_escape_xml_text(display_value)}</var>"
                    )
                elif project_root is not None:
                    # For non-embedded files, try to show relative path
                    try:
                        abs_path = Path(value).resolve()
                        rel_path = str(abs_path.relative_to(project_root.resolve()))
                        display_value = rel_path
                    except (ValueError, OSError):
                        display_value = serialized
                    var_elements.append(
                        f'<var name="{_escape_xml_attr(name)}">{_escape_xml_text(display_value)}</var>'
                    )
                else:
                    var_elements.append(
                        f'<var name="{_escape_xml_attr(name)}">{_escape_xml_text(serialized)}</var>'
                    )
            else:
                var_elements.append(
                    f'<var name="{_escape_xml_attr(name)}">{_escape_xml_text(serialized)}</var>'
                )

    return "<variables>\n" + "\n".join(var_elements) + "\n</variables>"


def generate_output(
    compiled: CompiledWorkflow,
    project_root: Path | None = None,
    context_files: dict[str, str] | None = None,
    links_only: bool = False,
) -> GeneratedOutput:
    """Generate XML output from compiled workflow.

    Transforms the CompiledWorkflow data structure into a well-formed XML string
    following recency-bias ordering principles:
    1. <mission> - task description (least context-dependent)
    2. <context> - project files with IDs (background -> specific)
    3. <variables> - resolved variable values (with file_id when matching embedded file)
    4. <instructions> - filtered execution steps (embedded as raw XML)
    5. <output-template> - expected output template (most relevant for generation)

    IMPORTANT: This function builds XML manually to avoid ElementTree's automatic
    escaping of < > characters. Instructions contain XML tags that must be
    preserved literally.

    File paths in <context> are relative to project_root to reduce noise.
    Each file has a label attribute indicating its type (e.g., "PROJECT CONTEXT", "STORY FILE").

    Args:
        compiled: CompiledWorkflow data to transform.
        project_root: Project root for generating relative paths.
            Defaults to current working directory if not provided.
        context_files: Optional dict mapping file paths to content.
            If provided, overrides compiled.context for file ordering.
            Keys should be file paths (absolute or relative).
        links_only: If True, only include file paths in context section,
            without file contents (debug mode for inspecting file ordering).

    Returns:
        GeneratedOutput containing XML string, token estimate, and size.

    Raises:
        CompilerError: If variable values are not JSON-serializable.

    """
    if project_root is None:
        project_root = Path.cwd()

    parts: list[str] = []
    path_to_id: dict[str, str] = {}

    # XML declaration
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append("<compiled-workflow>")

    # 1. Mission section (least context-dependent) - use CDATA, inline
    parts.append(f"<mission>{_wrap_cdata(compiled.mission)}</mission>")

    # 2. Context section (background -> specific) with file IDs
    if context_files is not None:
        context_result = _build_context_section(context_files, project_root, links_only)
        parts.append(context_result.xml)
        path_to_id = context_result.path_to_id
    else:
        # Use compiled.context as raw text if no structured files provided
        parts.append(f"<context>{_wrap_cdata(compiled.context)}</context>")

    # 3. Variables section (sorted alphabetically, with file_id cross-references)
    parts.append(_build_variables_section(compiled.variables, path_to_id, project_root))

    # 4. Instructions section
    # For XML instructions, embed raw (they're already valid XML from filter_instructions())
    # For markdown instructions, wrap in CDATA to prevent parsing issues
    if compiled.instructions:
        # Detect if instructions are markdown (starts with # heading after comments)
        stripped = compiled.instructions.strip()
        while stripped.startswith("<!--"):
            end = stripped.find("-->")
            if end == -1:
                break
            stripped = stripped[end + 3 :].strip()

        is_markdown = stripped.startswith("#") or not stripped.startswith("<")
        if is_markdown:
            # Wrap markdown in CDATA to preserve special chars like &
            parts.append(f"<instructions>{_wrap_cdata(compiled.instructions)}</instructions>")
        else:
            # XML instructions - embed raw
            parts.append(f"<instructions>{compiled.instructions}</instructions>")
    else:
        parts.append("<instructions></instructions>")

    # 6. Output template section (most relevant for generation) - use CDATA, inline
    parts.append(f"<output-template>{_wrap_cdata(compiled.output_template)}</output-template>")

    parts.append("</compiled-workflow>")

    # Join all parts with newlines between sections
    xml_str = "\n".join(parts)

    # Validate XML well-formedness (AC6: fail-fast on malformed output)
    try:
        ET.fromstring(xml_str)
    except ET.ParseError as e:
        # Extract position info from ParseError
        line_info = ""
        if hasattr(e, "position") and e.position is not None:
            line, col = e.position
            line_info = f"\n  Line {line}, column {col}"
        raise CompilerError(
            f"Generated XML is malformed - output validation failed{line_info}\n"
            f"  Error: {e}\n"
            f"  Why it's needed: Compiled workflow must be valid XML for downstream processing\n"
            f"  How to fix: Check for invalid characters in context files or variables"
        ) from e

    # Calculate size and token estimate
    size_bytes = len(xml_str.encode("utf-8"))
    token_estimate = len(xml_str) // CHARS_PER_TOKEN_ESTIMATE

    # Log token estimate at DEBUG level
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"Generated XML output: {token_estimate} tokens (estimated)")

    # Log large output at INFO level
    if size_bytes > LARGE_OUTPUT_THRESHOLD:
        logger.info(f"Generated large XML output: {size_bytes} bytes")

    return GeneratedOutput(
        xml=xml_str,
        token_estimate=token_estimate,
        size_bytes=size_bytes,
    )


def validate_token_budget(
    token_estimate: int,
    hard_limit: int = DEFAULT_HARD_LIMIT_TOKENS,
) -> list[str]:
    """Validate token count against budget limits.

    Args:
        token_estimate: Estimated token count from CompiledWorkflow.
        hard_limit: Maximum allowed tokens. Use 0 to disable validation.

    Returns:
        List of warning messages (empty if none).

    Raises:
        TokenBudgetError: If token_estimate exceeds hard_limit.

    """
    if hard_limit == 0:
        return []  # Validation disabled

    warnings: list[str] = []

    # Calculate soft limit
    if hard_limit == DEFAULT_HARD_LIMIT_TOKENS:
        soft_limit = DEFAULT_SOFT_LIMIT_TOKENS
    else:
        soft_limit = int(hard_limit * SOFT_LIMIT_RATIO)

    if token_estimate > hard_limit:
        raise TokenBudgetError(
            f"Token budget exceeded\n"
            f"  Tokens: ~{token_estimate:,} (estimated)\n"
            f"  Hard limit: {hard_limit:,}\n"
            f"  Why it's needed: LLM context windows have finite capacity\n"
            f"  How to fix: Reduce context files, split into smaller prompts, "
            f"or use --max-tokens to override"
        )

    if token_estimate > soft_limit:
        warnings.append(
            f"Compiled prompt exceeds soft limit\n"
            f"  Tokens: ~{token_estimate:,} (estimated)\n"
            f"  Soft limit: {soft_limit:,}\n"
            f"  Suggestions:\n"
            f"    - Reduce context files (exclude PRD or UX if not needed)\n"
            f"    - Use section extraction for large files\n"
            f"    - Enable sharding for large documents"
        )

    return warnings
