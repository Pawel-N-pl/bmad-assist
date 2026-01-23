"""Antipatterns extraction module.

This module extracts verified issues from synthesis reports to create
antipatterns files that help subsequent workflows avoid repeating mistakes.

Provides:
- extract_antipatterns: Extract issues from synthesis content using helper model
- append_to_antipatterns_file: Append extracted issues to antipatterns file
- extract_and_append_antipatterns: Combined convenience function

Usage:
    from bmad_assist.antipatterns import extract_and_append_antipatterns

    # In synthesis handler (after saving synthesis report):
    extract_and_append_antipatterns(
        synthesis_content=content,
        epic_id=epic_num,
        story_id="24-11",
        antipattern_type="story",  # or "code"
        project_path=project_path,
        config=config,
    )
"""

from bmad_assist.antipatterns.extractor import (
    append_to_antipatterns_file,
    extract_and_append_antipatterns,
    extract_antipatterns,
)

__all__ = [
    "extract_antipatterns",
    "append_to_antipatterns_file",
    "extract_and_append_antipatterns",
]
