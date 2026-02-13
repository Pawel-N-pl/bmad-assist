"""Critical instruction inserter for project-tree awareness.

This module handles inserting a <critical> instruction about the project-tree
when it is included in strategic context. The instruction helps LLMs understand
the significance of the directory structure shown in the <project-tree> tag.
"""

import logging
import re

logger = logging.getLogger(__name__)

# The critical instruction text (with HTML-escaped quotes)
PROJECT_TREE_INSTRUCTION = (
    'The &quot;project-tree&quot; tag above contains the CURRENT directory structure '
    "at compilation time. Files are sorted by modification time (newest first). "
    "Pay attention to recently modified files as they likely relate to the current task."
)


def insert_project_tree_instruction(compiled_xml: str) -> str:
    """Insert critical instruction about project-tree into compiled XML.

    The instruction is inserted AFTER the first <critical> tag in
    <instructions><workflow> if one exists. If no <critical> tag exists,
    it is inserted at the beginning of <instructions><workflow>.

    Args:
        compiled_xml: The compiled workflow XML string

    Returns:
        Modified XML with the critical instruction inserted

    """
    # Check if project-tree is present in the XML
    if "<project-tree>" not in compiled_xml:
        logger.debug("No project-tree in XML, skipping critical instruction")
        return compiled_xml

    # Prepare the new critical tag
    new_critical = f"<critical>{PROJECT_TREE_INSTRUCTION}</critical>"

    # Try to find the first <critical> tag in <instructions><workflow>
    # Pattern: <instructions>...<workflow>...<critical>...</critical>...
    # We need to insert AFTER the first </critical>

    # Strategy: Find <instructions> section, then find first <critical> within it
    instructions_match = re.search(r"(<instructions>)(.*?)(</instructions>)", compiled_xml, re.DOTALL)

    if not instructions_match:
        logger.debug("No <instructions> section found, skipping critical instruction")
        return compiled_xml

    instructions_content_start = instructions_match.start(2)  # Start of content
    instructions_content_end = instructions_match.end(2)  # End of content

    # Extract the instructions content
    instructions_content = compiled_xml[instructions_content_start:instructions_content_end]

    # Check if there's a <workflow> tag within instructions
    workflow_match = re.search(r"(<workflow[^>]*>)(.*?)(</workflow>)", instructions_content, re.DOTALL)

    if workflow_match:
        # Found <workflow> tag - insert within it
        workflow_content_start = workflow_match.start(2)
        workflow_content_end = workflow_match.end(2)
        workflow_content = instructions_content[workflow_content_start:workflow_content_end]

        # Look for first <critical> tag within workflow
        critical_match = re.search(r"(<critical>.*?</critical>)", workflow_content, re.DOTALL)

        if critical_match:
            # Insert AFTER the first </critical>
            critical_end = critical_match.end()
            # Calculate absolute position in original XML
            absolute_insert_pos = (
                instructions_content_start +
                workflow_content_start +
                critical_end
            )

            # Insert the new critical tag
            result = (
                compiled_xml[:absolute_insert_pos] +
                f"\n{new_critical}" +
                compiled_xml[absolute_insert_pos:]
            )
            logger.debug("Inserted project-tree instruction after existing <critical>")
            return result
        else:
            # No <critical> found in workflow - insert at beginning of <workflow>
            absolute_insert_pos = instructions_content_start + workflow_content_start
            result = (
                compiled_xml[:absolute_insert_pos] +
                f"{new_critical}\n" +
                compiled_xml[absolute_insert_pos:]
            )
            logger.debug("Inserted project-tree instruction at start of <workflow>")
            return result
    else:
        # No <workflow> tag - insert at beginning of <instructions>
        absolute_insert_pos = instructions_content_start
        result = (
            compiled_xml[:absolute_insert_pos] +
            f"{new_critical}\n" +
            compiled_xml[absolute_insert_pos:]
        )
        logger.debug("Inserted project-tree instruction at start of <instructions>")
        return result


def has_project_tree_instruction(compiled_xml: str) -> bool:
    """Check if the project-tree instruction is already present.

    Args:
        compiled_xml: The compiled workflow XML string

    Returns:
        True if the instruction is already present, False otherwise

    """
    return PROJECT_TREE_INSTRUCTION in compiled_xml
