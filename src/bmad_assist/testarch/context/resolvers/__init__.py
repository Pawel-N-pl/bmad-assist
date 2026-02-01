"""TEA Context Resolvers package.

This package provides artifact resolvers for the TEA context loader.
Each resolver handles finding and loading a specific type of TEA artifact.

Resolvers:
    TestDesignResolver: Loads test-design.md or epic-{N}-test-plan.md
    ATDDResolver: Loads ATDD checklist files (*atdd-checklist*{story}*.md)
    TestReviewResolver: Loads test-review-{story}.md
    TraceResolver: Loads trace-matrix-epic-{N}.md

Usage:
    from bmad_assist.testarch.context.resolvers import RESOLVER_REGISTRY

    resolver_cls = RESOLVER_REGISTRY["test-design"]
    resolver = resolver_cls(base_path, max_tokens=4000)
    artifacts = resolver.resolve(epic_id=25, story_id="25.1")
"""

from bmad_assist.testarch.context.resolvers.atdd import ATDDResolver
from bmad_assist.testarch.context.resolvers.base import BaseResolver
from bmad_assist.testarch.context.resolvers.test_design import TestDesignResolver
from bmad_assist.testarch.context.resolvers.test_review import TestReviewResolver
from bmad_assist.testarch.context.resolvers.trace import TraceResolver

# Registry mapping artifact type to resolver class
RESOLVER_REGISTRY: dict[str, type[BaseResolver]] = {
    "test-design": TestDesignResolver,
    "atdd": ATDDResolver,
    "test-review": TestReviewResolver,
    "trace": TraceResolver,
}

__all__ = [
    "BaseResolver",
    "TestDesignResolver",
    "ATDDResolver",
    "TestReviewResolver",
    "TraceResolver",
    "RESOLVER_REGISTRY",
]
