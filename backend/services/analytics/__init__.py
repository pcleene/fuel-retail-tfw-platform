"""
Analytics service package.

Re-exports the public API so existing callers
(e.g. `from backend.services import analytics_service`) keep working
after the single-file → package refactor.
"""

from backend.services.analytics.memory import (  # noqa: F401
    init_memory_layer,
    get_memories,
)
from backend.services.analytics.agent import (  # noqa: F401
    ask_question,
    close_mcp,
    get_stats,
)
from backend.services.analytics.conversations import (  # noqa: F401
    get_history,
    get_conversation,
    resume_conversation,
    get_terminology,
    seed_app_users,
    get_users,
)
from backend.services.analytics.conversation_search import (  # noqa: F401
    search_conversations,
)
