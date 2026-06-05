"""
Long-term memory layer: Voyage AI embeddings, MongoDBStore initialisation,
and user-scoped memory tools exposed to the agent.
"""

import logging

from langchain_core.embeddings import Embeddings
from langchain_core.tools import tool
from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.store.mongodb import MongoDBStore, create_vector_index_config
import voyageai

from backend.config import settings
from backend.database import get_pymongo_client, get_screening_db

logger = logging.getLogger(__name__)


# ─── Custom Voyage AI Embeddings ──────────────────────────────────

class VoyageEmbeddings(Embeddings):
    """Lightweight LangChain-compatible wrapper around the voyageai SDK."""

    def __init__(self, model: str, api_key: str, dimensions: int | None = None):
        self._client = voyageai.Client(api_key=api_key)
        self._model = model
        self._dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = self._client.embed(
            texts, model=self._model, output_dimension=self._dimensions
        )
        return result.embeddings

    def embed_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * (self._dimensions or 1024)
        result = self._client.embed(
            [text], model=self._model, output_dimension=self._dimensions
        )
        return result.embeddings[0]


# ─── Singletons ───────────────────────────────────────────────────

_checkpointer: MongoDBSaver | None = None
_memory_store: MongoDBStore | None = None


def get_checkpointer() -> MongoDBSaver | None:
    return _checkpointer


def get_memory_store() -> MongoDBStore | None:
    return _memory_store


# ─── Initialisation ──────────────────────────────────────────────

async def init_memory_layer():
    """Initialise checkpointer and memory store. Called from lifespan."""
    global _checkpointer, _memory_store

    client = get_pymongo_client()
    db_name = settings.screening_db

    # Short-term memory: checkpointing (conversation state)
    _checkpointer = MongoDBSaver(client, db_name=db_name)
    logger.info("MongoDBSaver checkpointer ready (db=%s)", db_name)

    # Long-term memory: semantic store with Voyage AI embeddings
    embeddings = VoyageEmbeddings(
        model=settings.voyage_model,
        api_key=settings.voyage_api_key,
        dimensions=settings.voyage_dimensions,
    )
    index_config = create_vector_index_config(
        embed=embeddings,
        dims=settings.voyage_dimensions,
        fields=["$"],
    )
    collection = client[db_name]["agent_memories"]

    _memory_store = MongoDBStore(
        collection=collection,
        index_config=index_config,
        auto_index_timeout=120,
    )
    logger.info("MongoDBStore (long-term memory) ready with vector search")


# ─── Memory Tools (exposed to the agent) ─────────────────────────

def build_memory_tools(user_id: str) -> list:
    """Build user-scoped memory tools the agent can call."""

    @tool
    async def save_memory(key: str, content: str) -> str:
        """Save a piece of information to long-term memory for this user.
        Use this when the user says 'remember...', 'my preference is...', or shares
        a reusable fact (thresholds, formatting preferences, frequently used filters).

        Args:
            key: A short snake_case identifier (e.g. 'format_preference', 'compliance_threshold')
            content: The information to remember
        """
        if not _memory_store:
            return "Memory store not available."
        namespace = (f"user_{user_id}_preferences",)
        await _memory_store.aput(namespace, key, {"content": content})
        logger.info("Saved memory for user %s: %s", user_id, key)
        return f"Remembered: {key} = {content}"

    @tool
    async def recall_memories(query: str) -> str:
        """Search long-term memory for relevant user preferences or saved context.
        Call this at the start of a conversation or when the user's question might
        relate to previously saved preferences.

        Args:
            query: A natural language description of what to search for (e.g. 'formatting preferences', 'compliance thresholds')
        """
        if not _memory_store:
            return "No memories found."
        namespace = (f"user_{user_id}_preferences",)
        items = await _memory_store.asearch(namespace, query=query, limit=5)
        if not items:
            return "No relevant memories found."
        memories = []
        for item in items:
            memories.append(f"- {item.key}: {item.value.get('content', str(item.value))}")
        return "User memories:\n" + "\n".join(memories)

    return [save_memory, recall_memories]


# ─── Memory Retrieval ─────────────────────────────────────────────

async def get_memories(user_id: str) -> list[dict]:
    """Retrieve stored long-term memories for a user."""
    if not _memory_store:
        return []
    namespace = (f"user_{user_id}_preferences",)
    try:
        items = await _memory_store.asearch(namespace, query="user preferences and context", limit=20)
        return [{"key": item.key, "value": item.value, "namespace": list(item.namespace)} for item in items]
    except Exception as e:
        logger.warning("Failed to search memories: %s", e)
        return []
