"""Data models for the BMAD workflow compiler.

This module defines the core data structures used throughout the compiler:
- StepIR: Intermediate representation of a tri-modal step file
- WorkflowIR: Intermediate representation of parsed workflow
- CompiledWorkflow: Final compiled output ready for LLM consumption
- CompilerContext: Context passed to workflow-specific compilers
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StepIR:
    """Intermediate representation of a tri-modal step file.

    Step files are used in TEA Enterprise tri-modal workflows.
    Each step has frontmatter with metadata and markdown content.

    Attributes:
        path: Absolute path to the step file.
        name: Step name from frontmatter (e.g., 'step-01-preflight-and-context').
        description: Step description from frontmatter.
        next_step_file: Relative path to next step (e.g., './step-02.md'), or None for final step.
        knowledge_index: Path to knowledge CSV from frontmatter, or None.
        raw_content: Markdown content after frontmatter.

    """

    path: Path
    name: str
    description: str
    next_step_file: str | None
    knowledge_index: str | None
    raw_content: str


@dataclass(frozen=True)
class WorkflowIR:
    """Intermediate representation of a parsed BMAD workflow.

    Attributes:
        name: Workflow identifier (e.g., 'create-story').
        config_path: Path to the workflow.yaml configuration file.
        instructions_path: Path to the instructions.xml file.
        template_path: Template path as raw string with placeholders, or None.
        validation_path: Validation/checklist path as raw string, or None.
        raw_config: Raw parsed YAML configuration.
        raw_instructions: Raw parsed XML instructions.
        output_template: Embedded output template content, or None if should load from path.
            When loading from cached patched template, this contains the embedded template.
            When loading from original files, this is None and template_path is used.

        workflow_type: Type of workflow ("macro" for traditional, "tri_modal" for TEA).
        has_tri_modal: True if workflow has tri-modal step directories.
        steps_c_dir: Path to create mode step directory (steps-c/), or None.
        steps_v_dir: Path to validate mode step directory (steps-v/), or None.
        steps_e_dir: Path to edit mode step directory (steps-e/), or None.
        first_step_c: Path to first step file in create mode, or None.
        first_step_v: Path to first step file in validate mode, or None.
        first_step_e: Path to first step file in edit mode, or None.

    """

    name: str
    config_path: Path
    instructions_path: Path
    template_path: str | None
    validation_path: str | None
    raw_config: dict[str, Any]
    raw_instructions: str
    output_template: str | None = None
    # Tri-modal fields (default to macro workflow)
    workflow_type: str = "macro"
    has_tri_modal: bool = False
    steps_c_dir: Path | None = None
    steps_v_dir: Path | None = None
    steps_e_dir: Path | None = None
    first_step_c: Path | None = None
    first_step_v: Path | None = None
    first_step_e: Path | None = None


@dataclass(frozen=True)
class CompiledWorkflow:
    """Final compiled workflow output ready for LLM consumption.

    Attributes:
        workflow_name: Workflow identifier.
        mission: Task description for the LLM.
        context: Ordered file contents (general to specific).
        variables: Resolved variable values.
        instructions: Filtered instruction steps.
        output_template: Expected output format/template.
        token_estimate: Estimated token count for the compiled output.

    """

    workflow_name: str
    mission: str
    context: str
    variables: dict[str, Any]
    instructions: str
    output_template: str
    token_estimate: int = 0


@dataclass
class CompilerContext:
    """Context passed to workflow-specific compilers during compilation.

    This is a mutable container that accumulates data during the
    compilation process. Workflow compilers can read and modify this
    context as needed.

    Attributes:
        project_root: Root directory of the project being compiled for.
        output_folder: Directory where BMAD outputs (PRD, epics, etc.) are stored.
        project_knowledge: Directory containing project documentation (docs/).
            If not set, defaults to project_root/docs.
        cwd: Current working directory (for CWD-based patch/cache discovery).
        workflow_ir: Parsed intermediate representation of the workflow.
        patch_path: Path to the patch file (for post_process loading).
        resolved_variables: Variables resolved during compilation.
        discovered_files: Files discovered via glob patterns.
        file_contents: Loaded file contents keyed by pattern name.
        links_only: If True, show only file paths in context (no content).

    """

    project_root: Path
    output_folder: Path
    project_knowledge: Path | None = None  # External docs path (defaults to project_root/docs)
    cwd: Path | None = None
    workflow_ir: WorkflowIR | None = None
    patch_path: Path | None = None  # Path to patch file for post_process
    resolved_variables: dict[str, Any] = field(default_factory=dict)
    discovered_files: dict[str, list[Path]] = field(default_factory=dict)
    file_contents: dict[str, str] = field(default_factory=dict)
    # Debug options
    links_only: bool = False  # If True, show only file paths in context (no content)
