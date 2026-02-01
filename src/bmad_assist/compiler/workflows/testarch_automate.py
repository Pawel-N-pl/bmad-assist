"""Compiler for the testarch-automate workflow.

This module implements the WorkflowCompiler protocol for the testarch-automate
workflow, producing standalone prompts for expanding test automation coverage.

The automate workflow expands test coverage after implementation or analyzes
existing codebases to generate comprehensive test suites.

Public API:
    TestarchAutomateCompiler: Workflow compiler class
"""

from bmad_assist.compiler.workflows.testarch_base import TestarchTriModalCompiler


class TestarchAutomateCompiler(TestarchTriModalCompiler):
    """Compiler for the testarch-automate workflow.

    Implements the WorkflowCompiler protocol to compile the testarch-automate
    workflow into a standalone prompt. The automate workflow expands test
    automation coverage for existing code.

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "testarch-automate"
