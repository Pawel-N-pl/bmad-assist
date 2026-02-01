"""Compiler for the testarch-framework workflow.

This module implements the WorkflowCompiler protocol for the testarch-framework
workflow, producing standalone prompts for test framework initialization.

The framework workflow initializes production-ready test framework architecture
(Playwright or Cypress) with fixtures, helpers, and configuration.

Public API:
    TestarchFrameworkCompiler: Workflow compiler class
"""

from bmad_assist.compiler.workflows.testarch_base import TestarchTriModalCompiler


class TestarchFrameworkCompiler(TestarchTriModalCompiler):
    """Compiler for the testarch-framework workflow.

    Implements the WorkflowCompiler protocol to compile the testarch-framework
    workflow into a standalone prompt. The framework workflow initializes test
    framework architecture with best practices.

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "testarch-framework"
