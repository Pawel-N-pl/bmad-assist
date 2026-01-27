"""Stack-specific adapters for evaluation framework."""

from .base import BaseEvaluator
from .go_service import GoServiceAdapter
from .python_api import PythonApiAdapter
from .python_cli import PythonCliAdapter
from .python_library import PythonLibraryAdapter
from .typescript_ui import TypeScriptUiAdapter

__all__ = [
    "BaseEvaluator",
    "GoServiceAdapter",
    "PythonApiAdapter",
    "PythonCliAdapter",
    "PythonLibraryAdapter",
    "TypeScriptUiAdapter",
]
