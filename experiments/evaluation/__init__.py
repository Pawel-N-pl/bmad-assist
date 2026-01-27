"""Evaluation framework for benchmark fixture projects.

This framework provides a unified way to evaluate LLM-generated code
across different stacks (Python API, Python library, TypeScript UI, Go, etc.)

Usage:
    python -m tests.fixtures._evaluation run auth-service
    python -m tests.fixtures._evaluation calc auth-service
"""

from .core.scoring import score, grade
from .core.session import SessionManager
from .adapters.base import BaseEvaluator

__all__ = ["score", "grade", "SessionManager", "BaseEvaluator"]
