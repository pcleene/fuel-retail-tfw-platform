"""UC2b: Analytics Chatbot API routes."""

import uuid
from fastapi import APIRouter
from backend.models.analytics import (
    AskRequest, AskResponse, HistoryEntry,
    TerminologyEntry, StatsResponse,
    ConversationSearchRequest, ConversationSearchResponse,
    ConversationDetail,
)
from backend.services import analytics as analytics_service
from backend.services.analytics import conversation_search

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    """
    Ask a natural language question about FuelRetail's user data.
    The LangChain agent translates it to MQL via the MongoDB MCP Server,
    executes it, and returns a formatted answer.
    """
    session_id = request.session_id or str(uuid.uuid4())
    result = await analytics_service.ask_question(
        request.question, session_id, user_id=request.user_id
    )
    return AskResponse(**result)


@router.get("/history/{session_id}", response_model=list[HistoryEntry])
async def get_history(session_id: str):
    """Get conversation history for a session."""
    return await analytics_service.get_history(session_id)


@router.get("/terminology", response_model=list[TerminologyEntry])
async def get_terminology():
    """Get FuelRetail-specific terminology mappings."""
    return analytics_service.get_terminology()


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get chatbot usage statistics."""
    return analytics_service.get_stats()


# ─── Conversation Search & History ─────────────────────────────────

@router.post("/conversations/search", response_model=ConversationSearchResponse)
async def search_conversations(request: ConversationSearchRequest):
    """Full-text search over conversation history with highlights, facets, and pagination."""
    result = await conversation_search.search_conversations(
        query=request.query,
        filters=request.filters,
        cursor=request.cursor,
        limit=request.limit,
        use_facets=request.use_facets,
        debug=request.debug,
    )
    return ConversationSearchResponse(**result)


@router.get("/conversations/{thread_id}", response_model=ConversationDetail)
async def get_conversation(thread_id: str):
    """Get full conversation by thread ID."""
    doc = await analytics_service.get_conversation(thread_id)
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Format datetime fields
    for field in ("createdAt", "updatedAt"):
        if doc.get(field) and hasattr(doc[field], "isoformat"):
            doc[field] = doc[field].isoformat()
    return ConversationDetail(**doc)


@router.get("/conversations/{thread_id}/resume", response_model=ConversationDetail)
async def resume_conversation(thread_id: str):
    """Resume a conversation: returns conversation data + confirms checkpoint exists."""
    result = await analytics_service.resume_conversation(thread_id)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")
    for field in ("createdAt", "updatedAt"):
        if result.get(field) and hasattr(result[field], "isoformat"):
            result[field] = result[field].isoformat()
    result.pop("_id", None)
    return ConversationDetail(**result)


@router.get("/memories/{user_id}")
async def get_memories(user_id: str):
    """Get stored long-term memories for a user."""
    return await analytics_service.get_memories(user_id)


@router.get("/users")
async def get_users():
    """Get demo app users."""
    return await analytics_service.get_users()


