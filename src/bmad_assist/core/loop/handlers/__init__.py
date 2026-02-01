"""Phase handlers package.

Each phase has its own handler that:
1. Loads prompt configuration from ~/.bmad-assist/handlers/{phase}.yaml
2. Renders the prompt template with state context
3. Invokes the configured provider
4. Returns PhaseResult with provider output

NOTE: Uses lazy loading to avoid importing heavy dependencies (benchmarking -> textstat -> nltk).
"""

from typing import TYPE_CHECKING

# Light import - BaseHandler and HandlerConfig are always needed
from bmad_assist.core.loop.handlers.base import BaseHandler, HandlerConfig

# Type hints only
if TYPE_CHECKING:
    from bmad_assist.core.loop.handlers.code_review import CodeReviewHandler as CodeReviewHandler
    from bmad_assist.core.loop.handlers.code_review_synthesis import (
        CodeReviewSynthesisHandler as CodeReviewSynthesisHandler,
    )
    from bmad_assist.core.loop.handlers.create_story import CreateStoryHandler as CreateStoryHandler
    from bmad_assist.core.loop.handlers.dev_story import DevStoryHandler as DevStoryHandler
    from bmad_assist.core.loop.handlers.qa_plan_execute import QaPlanExecuteHandler as QaPlanExecuteHandler
    from bmad_assist.core.loop.handlers.qa_plan_generate import QaPlanGenerateHandler as QaPlanGenerateHandler
    from bmad_assist.core.loop.handlers.retrospective import RetrospectiveHandler as RetrospectiveHandler
    from bmad_assist.core.loop.handlers.validate_story import ValidateStoryHandler as ValidateStoryHandler
    from bmad_assist.core.loop.handlers.validate_story_synthesis import (
        ValidateStorySynthesisHandler as ValidateStorySynthesisHandler,
    )

__all__ = [
    "BaseHandler",
    "HandlerConfig",
    "CreateStoryHandler",
    "ValidateStoryHandler",
    "ValidateStorySynthesisHandler",
    "DevStoryHandler",
    "CodeReviewHandler",
    "CodeReviewSynthesisHandler",
    "RetrospectiveHandler",
    "QaPlanGenerateHandler",
    "QaPlanExecuteHandler",
]

# Lazy loading for heavy handler imports
_lazy_imports = {
    "CodeReviewHandler": ".code_review",
    "CodeReviewSynthesisHandler": ".code_review_synthesis",
    "CreateStoryHandler": ".create_story",
    "DevStoryHandler": ".dev_story",
    "QaPlanExecuteHandler": ".qa_plan_execute",
    "QaPlanGenerateHandler": ".qa_plan_generate",
    "RetrospectiveHandler": ".retrospective",
    "ValidateStoryHandler": ".validate_story",
    "ValidateStorySynthesisHandler": ".validate_story_synthesis",
}


def __getattr__(name: str):
    """Lazy load handler classes on first access."""
    if name in _lazy_imports:
        import importlib

        module = importlib.import_module(_lazy_imports[name], __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
