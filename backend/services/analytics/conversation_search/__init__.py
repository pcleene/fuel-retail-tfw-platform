"""
Conversation search subpackage — hybrid $rankFusion search pipeline.

Re-exports the public API so callers like
  `from backend.services.analytics.conversation_search import search_conversations`
keep working unchanged.
"""

from backend.services.analytics.conversation_search.search import (  # noqa: F401
    search_conversations,
)
