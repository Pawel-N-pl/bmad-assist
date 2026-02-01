"""Compiler for the testarch-nfr-assess workflow.

This module implements the WorkflowCompiler protocol for the testarch-nfr-assess
workflow, producing standalone prompts for non-functional requirements assessment.

The NFR assess workflow evaluates performance, security, reliability, and
maintainability before release with evidence-based validation.

Public API:
    TestarchNfrAssessCompiler: Workflow compiler class
"""

from bmad_assist.compiler.workflows.testarch_base import TestarchTriModalCompiler


class TestarchNfrAssessCompiler(TestarchTriModalCompiler):
    """Compiler for the testarch-nfr-assess workflow.

    Implements the WorkflowCompiler protocol to compile the testarch-nfr-assess
    workflow into a standalone prompt. The NFR assess workflow evaluates
    non-functional requirements with evidence-based validation.

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "testarch-nfr-assess"
