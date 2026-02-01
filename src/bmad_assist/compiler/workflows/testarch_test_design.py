"""Compiler for the testarch-test-design workflow.

This module implements the WorkflowCompiler protocol for the testarch-test-design
workflow, producing standalone prompts for test planning and design.

The test-design workflow operates in dual-mode: system-level testability review
during Solutioning phase, or epic-level test planning during Implementation phase.

Public API:
    TestarchTestDesignCompiler: Workflow compiler class
"""

from bmad_assist.compiler.workflows.testarch_base import TestarchTriModalCompiler


class TestarchTestDesignCompiler(TestarchTriModalCompiler):
    """Compiler for the testarch-test-design workflow.

    Implements the WorkflowCompiler protocol to compile the testarch-test-design
    workflow into a standalone prompt. The test-design workflow auto-detects
    mode based on project phase for appropriate test planning.

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "testarch-test-design"
