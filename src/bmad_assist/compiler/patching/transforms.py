"""Prompt formatting for workflow patches.

This module handles formatting prompts for LLM to apply transforms
to workflow content. Transforms are simple instruction strings.

Also includes post-processing for deterministic cleanups that don't
need LLM (removing redundant file references, etc.).
"""

import logging
import re
import xml.etree.ElementTree as ET

from bmad_assist.compiler.patching.config import get_patcher_config
from bmad_assist.compiler.patching.types import PostProcessRule

logger = logging.getLogger(__name__)


# Conservative pattern: < followed by digit, space, =, or common comparison chars
_UNESCAPED_LT_CONSERVATIVE = re.compile(r"<(\d|[=\s])")

# Aggressive pattern: < NOT followed by valid XML construct starters
# (tag name [a-zA-Z_:], closing tag /, comment/CDATA !, processing instruction ?)
_UNESCAPED_LT_AGGRESSIVE = re.compile(r"<(?![a-zA-Z_:/!?])")

# Bare ampersand not followed by a valid entity reference (name + ;) or numeric ref (# + digits + ;)
_BARE_AMPERSAND = re.compile(r"&(?![a-zA-Z#][a-zA-Z0-9]*;)")


def fix_xml_entities(content: str) -> str:
    """Fix unescaped < and & characters in XML text content.

    LLMs sometimes convert &lt; back to < when transforming XML.
    This function attempts to fix such cases by escaping < characters
    that appear in text content (not as part of XML tags).

    Uses a two-pass strategy:
    1. Conservative: escape < before digits/spaces/= (most common case)
    2. Aggressive: escape any < not followed by valid XML construct starters,
       and fix bare & not followed by valid entity references

    Args:
        content: XML content that may have unescaped < or & in text.

    Returns:
        Content with problematic characters escaped.

    """
    # First check if XML is already valid
    try:
        ET.fromstring(f"<root>{content}</root>")
        return content  # Already valid, no fix needed
    except ET.ParseError:
        pass  # Need to fix

    # Pass 1: Conservative fix for < before digits/spaces/=
    fixed = _UNESCAPED_LT_CONSERVATIVE.sub(r"&lt;\1", content)

    try:
        ET.fromstring(f"<root>{fixed}</root>")
        logger.info("Fixed unescaped < characters in XML content (conservative)")
        return fixed
    except ET.ParseError:
        pass  # Try more aggressive fix

    # Pass 2: Aggressive fix — escape any < not followed by valid XML constructs,
    # plus fix bare & characters
    fixed = _UNESCAPED_LT_AGGRESSIVE.sub("&lt;", content)
    fixed = _BARE_AMPERSAND.sub("&amp;", fixed)

    try:
        ET.fromstring(f"<root>{fixed}</root>")
        logger.info("Fixed unescaped XML entities (aggressive)")
        return fixed
    except ET.ParseError as e:
        # Neither fix worked, return original and let caller handle error
        logger.warning("Could not auto-fix XML content: %s", e)
        return content


# Map of flag names to re module constants
_FLAG_MAP = {
    "IGNORECASE": re.IGNORECASE,
    "I": re.IGNORECASE,
    "MULTILINE": re.MULTILINE,
    "M": re.MULTILINE,
    "DOTALL": re.DOTALL,
    "S": re.DOTALL,
}


def _parse_flags(flags_str: str) -> int:
    """Parse flags string into re module flags.

    Args:
        flags_str: Space or comma separated flag names (e.g., "MULTILINE IGNORECASE").

    Returns:
        Combined re flags integer.

    """
    if not flags_str:
        return 0

    combined = 0
    for flag_name in re.split(r"[,\s]+", flags_str.upper()):
        flag_name = flag_name.strip()
        if flag_name and flag_name in _FLAG_MAP:
            combined |= _FLAG_MAP[flag_name]
    return combined


def post_process_compiled(
    content: str,
    rules: list[PostProcessRule] | None = None,
) -> str:
    """Apply deterministic post-processing to compiled workflow.

    Applies regex-based replacements defined in patch config to remove
    redundant file references and other cleanup. Rules are defined in
    the patch YAML post_process section.

    Args:
        content: LLM-transformed workflow content.
        rules: List of PostProcessRule from patch config. If None, no processing.

    Returns:
        Post-processed content with rules applied.

    """
    if rules is None:
        return content

    for rule in rules:
        try:
            flags = _parse_flags(rule.flags)
            pattern = re.compile(rule.pattern, flags)
            content = pattern.sub(rule.replacement, content)
        except re.error as e:
            logger.warning(
                "Invalid post_process regex pattern '%s': %s",
                rule.pattern,
                e,
            )
            continue

    # Clean up multiple blank lines that may result from removals
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content


def format_transform_prompt(
    instructions: list[str],
    workflow_content: str,
) -> str:
    """Format all transform instructions into a single prompt for LLM.

    Args:
        instructions: List of natural language transform instructions.
        workflow_content: The source workflow content to transform.

    Returns:
        Formatted prompt string with all instructions.

    """
    config = get_patcher_config()
    parts = []

    # System context from config
    parts.append("<task-context>")
    parts.append(config.system_prompt.strip())
    parts.append("</task-context>")
    parts.append("")

    # Source document
    parts.append("<source-document>")
    parts.append(workflow_content)
    parts.append("</source-document>")
    parts.append("")

    # Instructions
    parts.append("<instructions>")
    parts.append("Apply these changes IN ORDER:")
    parts.append("")

    for i, instruction in enumerate(instructions, 1):
        parts.append(f"{i}. {instruction}")

    parts.append("")
    parts.append("</instructions>")
    parts.append("")

    # Output format from config
    parts.append("<output-format>")
    parts.append(config.output_format.strip())
    parts.append("</output-format>")

    return "\n".join(parts)
