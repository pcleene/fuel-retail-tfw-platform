"""UC2b: Analytics Chatbot Pydantic models."""

from pydantic import BaseModel, Field
from typing import Optional


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="Natural language question")
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity. Auto-generated if omitted.")
    user_id: str = Field("analyst-1", description="User ID for memory namespacing")


class MemoryTraceEntry(BaseModel):
    tool: str
    input: dict
    output: str = ""


class AskResponse(BaseModel):
    answer: str
    mql: Optional[str] = None
    latency_ms: float
    session_id: str
    memory_trace: list[MemoryTraceEntry] = []


class HistoryEntry(BaseModel):
    id: str
    question: str
    content: str = ""
    mql: Optional[str] = None
    latency_ms: float = 0
    timestamp: str = ""


class TerminologyEntry(BaseModel):
    term: str
    aliases: list[str]
    meaning: str
    field: str


class StatsResponse(BaseModel):
    totalQueries: int
    activeSessions: int
    avgLatencyMs: float


# ─── Conversation Search Models ──────────────────────────────────

class ConversationSearchRequest(BaseModel):
    query: str = Field("", description="Full-text search query")
    filters: dict = Field(default_factory=dict, description="Facet filters e.g. {category: ['user-metrics'], complexity: ['simple']}")
    cursor: Optional[str] = Field(None, description="Cursor for pagination (searchAfter token)")
    limit: int = Field(10, ge=1, le=50)
    use_facets: bool = Field(True, description="Include facet counts in response (disables cursor pagination)")
    debug: bool = Field(False, description="Return the raw aggregation pipeline(s) in the response")


class HighlightText(BaseModel):
    value: str
    type: str  # "hit" or "text"


class HighlightEntry(BaseModel):
    path: str
    texts: list[HighlightText]


class FacetBucket(BaseModel):
    value: str
    count: int


class Facet(BaseModel):
    field: str
    label: str
    buckets: list[FacetBucket]


class PaginationInfo(BaseModel):
    hasMore: bool
    nextCursor: Optional[str] = None
    totalEstimate: Optional[int] = None


class ConversationSearchResult(BaseModel):
    threadId: str
    title: str = ""
    summary: str = ""
    lastQuestion: str = ""
    category: str = ""
    complexity: str = ""
    intent: str = ""
    topics: list[str] = []
    collections: list[str] = []
    turnCount: int = 0
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    score: float = 0
    highlights: list[HighlightEntry] = []


class ConversationSearchResponse(BaseModel):
    results: list[ConversationSearchResult]
    facets: list[Facet] = []
    pagination: PaginationInfo
    debugPipeline: Optional[list[dict]] = None
    debugFacetPipeline: Optional[list[dict]] = None


class ConversationDetail(BaseModel):
    threadId: str
    userId: str = ""
    title: str = ""
    summary: str = ""
    category: str = ""
    complexity: str = ""
    intent: str = ""
    topics: list[str] = []
    entities: list[str] = []
    queryTypes: list[str] = []
    collections: list[str] = []
    turnCount: int = 0
    messages: list[dict] = []
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    hasCheckpoint: bool = False
