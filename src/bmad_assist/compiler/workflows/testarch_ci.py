"""Compiler for the testarch-ci workflow.

This module implements the WorkflowCompiler protocol for the testarch-ci
workflow, producing standalone prompts for CI/CD quality pipeline scaffolding.

The CI workflow scaffolds continuous integration pipelines with test execution,
burn-in loops, and artifact collection.

Public API:
    TestarchCiCompiler: Workflow compiler class
"""

from bmad_assist.compiler.workflows.testarch_base import TestarchTriModalCompiler


class TestarchCiCompiler(TestarchTriModalCompiler):
    """Compiler for the testarch-ci workflow.

    Implements the WorkflowCompiler protocol to compile the testarch-ci
    workflow into a standalone prompt. The CI workflow scaffolds quality
    pipelines with test execution and artifact collection.

    """

    @property
    def workflow_name(self) -> str:
        """Unique workflow identifier."""
        return "testarch-ci"
