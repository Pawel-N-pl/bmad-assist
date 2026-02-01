"""TEA Knowledge Base module for test architecture knowledge.

This module provides loading and caching of TEA knowledge fragments
that inject domain-specific testing knowledge into LLM prompts.

Public API:
    KnowledgeFragment: Immutable data class for knowledge fragment metadata
    KnowledgeIndex: Immutable data class for index state
    KnowledgeBaseLoader: Main loader class with caching
    get_knowledge_loader: Singleton factory for loader instances

Usage:
    from bmad_assist.testarch.knowledge import get_knowledge_loader

    loader = get_knowledge_loader(project_root)
    fragments = loader.load_by_tags(["fixtures", "playwright"])
    print(fragments)  # Markdown content with <!-- KNOWLEDGE: name --> headers
"""

from bmad_assist.testarch.knowledge.loader import (
    KnowledgeBaseLoader,
    get_knowledge_loader,
)
from bmad_assist.testarch.knowledge.models import (
    KnowledgeFragment,
    KnowledgeIndex,
)

__all__ = [
    "KnowledgeFragment",
    "KnowledgeIndex",
    "KnowledgeBaseLoader",
    "get_knowledge_loader",
]
