# Analytics Chatbot — Enhanced Architecture Walkthrough

> Deep dive into the agentic memory system and hybrid conversation search added to the Fuel Retail Analytics Chatbot.

---

## Table of Contents

1. [What Changed](#what-changed)
2. [Agentic Core Memory](#agentic-core-memory)
   - [Short-Term Memory (Checkpointing)](#short-term-memory-checkpointing)
   - [Long-Term Memory (Semantic Store)](#long-term-memory-semantic-store)
   - [Memory Tools Exposed to the Agent](#memory-tools-exposed-to-the-agent)
   - [How the Agent Uses Memory](#how-the-agent-uses-memory)
3. [Conversation Search — Hybrid $rankFusion](#conversation-search--hybrid-rankfusion)
   - [How It Works](#how-it-works)
   - [The $rankFusion Pipeline (MongoDB 8.0+)](#the-rankfusion-pipeline-mongodb-80)
   - [Faceted Search with $searchMeta](#faceted-search-with-searchmeta)
   - [Automatic Metadata Generation](#automatic-metadata-generation)
4. [Search Alternatives for Older MongoDB Versions](#search-alternatives-for-older-mongodb-versions)
   - [Option A: Atlas Search Only ($search)](#option-a-atlas-search-only-search)
   - [Option B: Vector Search Only ($vectorSearch)](#option-b-vector-search-only-vectorsearch)
   - [Comparison Matrix](#comparison-matrix)
5. [Code Structure](#code-structure)

---

## What Changed

The analytics chatbot started as a single `analytics_service.py` file. It has been refactored into a modular package with two major feature additions:

| Enhancement | What It Does |
|---|---|
| **Agentic Core Memory** | Short-term checkpointing (conversation state survives restarts) + long-term semantic memory (user preferences persist across sessions via vector search) |
| **Hybrid Conversation Search** | Users can search past conversations using `$rankFusion` which merges full-text Atlas Search with Voyage AI vector similarity in a single aggregation pipeline |

---

## Agentic Core Memory

The memory system gives the LangGraph agent two layers of persistence, both backed by MongoDB.

### Short-Term Memory (Checkpointing)

**What:** Conversation state (the full message history for a session) is checkpointed after every agent turn using LangGraph's `MongoDBSaver`.

**Why:** This lets users close a browser tab, come back later, and resume a conversation exactly where they left off — the agent sees the full prior context.

**How it's initialised** (`memory.py`):

```python
from langgraph.checkpoint.mongodb import MongoDBSaver

_checkpointer = MongoDBSaver(client, db_name="FuelRetail_screening")
```

The checkpointer is then passed to the agent:

```python
agent = create_react_agent(
    model=model,
    tools=tools,
    checkpointer=get_checkpointer(),   # ← short-term memory
    store=get_memory_store(),           # ← long-term memory
    prompt=SYSTEM_PROMPT,
)
```

**MongoDB collection:** `checkpoints` (auto-created by LangGraph)

### Long-Term Memory (Semantic Store)

**What:** A vector-indexed key-value store where the agent saves user preferences, thresholds, and reusable facts. Retrieval is via semantic similarity search — not exact key lookup.

**Why:** Different users have different preferences ("always show percentages", "my compliance threshold is 5%"). The agent remembers these across sessions and silently applies them.

**How it's initialised** (`memory.py`):

```python
from langgraph.store.mongodb import MongoDBStore, create_vector_index_config

embeddings = VoyageEmbeddings(
    model="voyage-4-large",
    api_key=settings.voyage_api_key,
    dimensions=1024,
)

index_config = create_vector_index_config(
    embed=embeddings,
    dims=1024,
    fields=["$"],
)

_memory_store = MongoDBStore(
    collection=client["FuelRetail_screening"]["agent_memories"],
    index_config=index_config,
    auto_index_timeout=120,
)
```

`VoyageEmbeddings` is a lightweight LangChain-compatible wrapper around the Voyage AI SDK. LangGraph's `MongoDBStore` handles the vector index creation automatically via `auto_index_timeout`.

**MongoDB collection:** `agent_memories` with an auto-managed vector search index

### Memory Tools Exposed to the Agent

The agent gets two tools injected at runtime, scoped to the current user:

```python
@tool
async def save_memory(key: str, content: str) -> str:
    """Save information to long-term memory for this user."""
    namespace = (f"user_{user_id}_preferences",)
    await _memory_store.aput(namespace, key, {"content": content})
    return f"Remembered: {key} = {content}"

@tool
async def recall_memories(query: str) -> str:
    """Search long-term memory for relevant user preferences."""
    namespace = (f"user_{user_id}_preferences",)
    items = await _memory_store.asearch(namespace, query=query, limit=5)
    # ... format and return
```

Key design decisions:
- **User-scoped namespaces** — each user's memories are isolated via `(f"user_{user_id}_preferences",)`
- **Semantic retrieval** — `recall_memories` takes a natural language query, not an exact key, so the agent can find "formatting preferences" even if the key was `format_preference`
- **Tools, not hardcoded logic** — the LLM decides when to save/recall, guided by the system prompt

### How the Agent Uses Memory

The system prompt instructs the agent:

1. **Before answering** any analytics question → call `recall_memories` to check for user preferences
2. **When the user says "remember"** → call `save_memory` before responding
3. **Apply preferences silently** — if recall returns a formatting preference, use it without mentioning it

Example flow:

```
User:  "Remember, I always want percentages not raw counts"
Agent: → calls save_memory(key="format_preference", content="Always display as percentages")
       → "Got it! I'll always show percentages for you."

User:  "How many users are verified?"
Agent: → calls recall_memories(query="user preferences formatting")
       → gets back "format_preference: Always display as percentages"
       → runs the MQL query
       → "78.3% of users (7,832 out of 10,000) are KYC verified."
```

---

## Conversation Search — Hybrid $rankFusion

> **Important:** `$rankFusion` requires **MongoDB 8.0+** (available on Atlas as of late 2024). See the [alternatives section](#search-alternatives-for-older-mongodb-versions) for older versions.

### How It Works

When a user searches past conversations in the History panel, the system combines two search strategies in a single aggregation:

1. **Full-text search** via `$search` — fuzzy keyword matching across titles, summaries, messages, and MQL snippets
2. **Vector search** via `$vectorSearch` — semantic similarity using Voyage AI embeddings (1024-dim)

MongoDB's `$rankFusion` merges the results using **Reciprocal Rank Fusion (RRF)**, which interleaves both ranked lists without needing to normalise scores.

### The $rankFusion Pipeline (MongoDB 8.0+)

The pipeline is built in `conversation_search/pipeline.py`:

```python
[{
    "$rankFusion": {
        "input": {
            "pipelines": {
                "textSearch": [
                    { "$search": {
                        "index": "conversation_search",
                        "text": {
                            "query": "premium users flagged",
                            "path": ["title", "summary", "lastQuestion",
                                     "messages.content", "messages.question",
                                     "messages.mql"],
                            "fuzzy": { "maxEdits": 1 }
                        }
                    }},
                    { "$limit": 11 }
                ],
                "vectorSearch": [
                    { "$vectorSearch": {
                        "index": "conversation_vector",
                        "path": "searchEmbedding",
                        "queryVector": [0.012, -0.034, ...],  # 1024 dims
                        "numCandidates": 50,
                        "limit": 11
                    }}
                ]
            }
        }
    }
}]
```

The system fetches `limit + 1` results to detect whether there are more pages (the extra result is discarded before returning to the frontend).

**Graceful degradation:** If `$rankFusion` fails (e.g. the vector index doesn't exist yet), the code automatically retries with text-only search:

```python
except Exception as e:
    if query_embedding is not None:
        logger.warning("rankFusion failed (%s), retrying text-only", e)
        pipeline = build_search_pipeline(..., query_embedding=None)
```

### Faceted Search with $searchMeta

Alongside results, a separate `$searchMeta` pipeline retrieves facet counts for the filter sidebar:

```python
[{
    "$searchMeta": {
        "index": "conversation_search",
        "facet": {
            "operator": { "text": { "query": "...", ... } },
            "facets": {
                "categoryFacet":   { "type": "string", "path": "category" },
                "topicsFacet":     { "type": "string", "path": "topics" },
                "complexityFacet": { "type": "string", "path": "complexity" },
                "intentFacet":     { "type": "string", "path": "intent" },
                "collectionsFacet":{ "type": "string", "path": "collections" },
                "turnCountFacet":  { "type": "number", "path": "turnCount",
                                     "boundaries": [1, 3, 6, 10, 20] }
            }
        }
    }
}]
```

This runs as a separate aggregation because `$rankFusion` cannot be combined with `$searchMeta` in the same pipeline. This is a trade-off specific to hybrid search — when using `$search` alone (without `$rankFusion`), facets and results can be retrieved in a **single query** using the `facet` operator inside `$search` and accessing `$$SEARCH_META`, and cursor-based pagination works natively via `searchAfter`. The extra round-trip is the cost of combining text + vector in one result set.

> **Why not put the `facet` operator inside `$search` within a `$rankFusion` sub-pipeline?**
>
> It's a reasonable idea — if the `facet` operator already works inside `$search` and populates `$$SEARCH_META`, why not use that inside `$rankFusion`? It doesn't work for two reasons:
>
> 1. **Sub-pipeline stage restrictions.** `$rankFusion` input pipelines can **only** contain `$search`, `$vectorSearch`, `$match`, `$sort`, `$skip`, and `$limit`. You cannot add `$addFields`, `$replaceWith`, or `$facet` stages inside the sub-pipeline — so even if `$search` with the `facet` operator populates `$$SEARCH_META`, there's no way to extract it before `$rankFusion` discards it.
> 2. **`$$SEARCH_META` is scoped to the sub-pipeline.** `$rankFusion` executes each sub-pipeline independently and then combines the ranked document sets. It does not propagate `$$SEARCH_META` to the outer pipeline. After the `$rankFusion` stage, that variable is gone.
>
> Even if it _did_ somehow work, the facet counts would only reflect one sub-pipeline's result set (e.g. the text search results), not the fused result set — which would be misleading.
>
> This is why the current implementation uses a separate `$searchMeta` query: it's the only reliable way to get facet counts alongside `$rankFusion` results.

### Automatic Metadata Generation

The facets above (category, topics, complexity, intent, etc.) don't come from manual tagging — they're generated automatically by an LLM.

Every time a conversation is created or updated (every 3 turns), a fire-and-forget task calls Claude Haiku to classify the conversation:

```python
asyncio.create_task(_generate_conversation_metadata(session_id))
```

The classification prompt produces structured JSON:

```json
{
  "title": "Premium User Churn Analysis",
  "summary": "Investigated churn rates among premium wallet users over Q1",
  "category": "wallet-financial",
  "topics": ["churn", "premium", "wallet-balance"],
  "queryTypes": ["aggregation", "trend"],
  "complexity": "complex",
  "intent": "investigation",
  "collections": ["user_profiles"]
}
```

This metadata is saved back to the conversation document along with a Voyage AI embedding of `title + summary + conversation digest`, which powers the vector half of hybrid search.

**Atlas Search indexes required:**

| Index Name | Type | Purpose |
|---|---|---|
| `conversation_search` | Atlas Search (text) | Fuzzy full-text across title, summary, messages, MQL |
| `conversation_vector` | Atlas Vector Search | Cosine similarity on `searchEmbedding` (1024-dim Voyage AI) |

---

## Search Alternatives for Older MongoDB Versions

`$rankFusion` is a MongoDB 8.0 feature. If you're on an earlier version, you have two clean alternatives — both are already implemented as fallback paths in the codebase.

### Option A: Atlas Search Only ($search)

**Works on:** MongoDB 6.0+ with Atlas Search

This is the text-only path that the system already falls back to when no vector embedding is available. It uses `$search` with fuzzy text matching:

```python
{
    "$search": {
        "index": "conversation_search",
        "compound": {
            "must": [{
                "text": {
                    "query": "premium users flagged",
                    "path": ["title", "summary", "lastQuestion",
                             "messages.content"],
                    "fuzzy": { "maxEdits": 1 }
                }
            }],
            "filter": [
                { "equals": { "path": "category", "value": "wallet-financial" } }
            ]
        }
    }
}
```

**Faceted search + pagination in a single aggregation:**

With plain `$search` (no `$rankFusion`), you can get results, facets, highlights, and cursor pagination all in one pipeline. This is the key operational advantage over hybrid search — no second round-trip for facet counts.

The correct approach puts facet definitions **inside** the `$search` stage using the `facet` operator, then accesses `$$SEARCH_META` to read the facet results. This is the pattern used in the [PensionFund Officer Dashboard](https://github.com/pcleene/pension-fund-officer-dashboard) codebase which implements it end-to-end:

```python
[
    # 1. $search with facet operator — facets are computed server-side
    #    and accessible via $$SEARCH_META
    {
        "$search": {
            "index": "conversation_search",
            "facet": {
                "operator": {
                    "compound": {
                        "must": [{
                            "text": {
                                "query": "premium users flagged",
                                "path": ["title", "summary", "lastQuestion",
                                         "messages.content"],
                                "fuzzy": { "maxEdits": 1 }
                            }
                        }],
                        "filter": [
                            { "equals": { "path": "category",
                                          "value": "wallet-financial" } }
                        ]
                    }
                },
                "facets": {
                    "categoryFacet":   { "type": "string", "path": "category" },
                    "topicsFacet":     { "type": "string", "path": "topics" },
                    "complexityFacet": { "type": "string", "path": "complexity" },
                    "intentFacet":     { "type": "string", "path": "intent" }
                }
            },
            "sort": { "updatedAt": -1, "_id": 1 },
            "count": { "type": "total" },
            # Cursor pagination — pass the token from the previous page
            # "searchAfter": "<token from previous page>",
            # "searchBefore": "<token>" for backward navigation
        }
    },

    # 2. Add score and pagination token BEFORE $limit
    {
        "$addFields": {
            "score": { "$meta": "searchScore" },
            "paginationToken": { "$meta": "searchSequenceToken" }
        }
    },

    # 3. Fetch limit + 1 to detect if more pages exist
    { "$limit": 11 },

    # 4. Use $facet to split results from $$SEARCH_META in one pass
    {
        "$facet": {
            "results": [
                { "$project": {
                    "_id": 0, "threadId": 1, "title": 1, "summary": 1,
                    "category": 1, "score": 1, "paginationToken": 1
                }}
            ],
            "metadata": [
                { "$replaceWith": "$$SEARCH_META" },
                { "$limit": 1 }
            ]
        }
    }
]
```

The response from this single aggregation contains everything the UI needs:
- `results` — the page of documents with scores and pagination tokens
- `metadata[0].facet` — the facet buckets (category counts, topic counts, etc.)
- `metadata[0].count.lowerBound` — estimated total result count
- `results[-1].paginationToken` — cursor for the next page (`searchAfter`)
- `results[0].paginationToken` — cursor for the previous page (`searchBefore`)

With `$rankFusion`, none of this works — `$$SEARCH_META` doesn't propagate through `$rankFusion` (see the [detailed explanation above](#faceted-search-with-searchmeta)), `searchAfter`/`searchBefore` aren't available after fusion, and the `facet` operator inside `$search` can't be accessed from within the restricted sub-pipeline stages. Facets therefore require a second query and pagination uses `limit + 1` overflow detection instead of cursors.

**Pros:**
- No embedding model needed (no Voyage AI dependency for search)
- **Facets + results + total count in a single query** — no second round-trip
- **Native `searchAfter`/`searchBefore` cursor pagination** — stateless, efficient bi-directional paging without `$skip`
- Supports highlights
- Lower latency (no embedding call before search)

**Cons:**
- Purely lexical — "wallet balance" won't match "e-money funds"
- No semantic understanding of query intent

**To use this exclusively:** Pass `query_embedding=None` to `build_search_pipeline()`, or simply don't configure `voyage_api_key`.

### Option B: Vector Search Only ($vectorSearch)

**Works on:** MongoDB 7.0+ with Atlas Vector Search

If you want semantic search without `$rankFusion`, you can use `$vectorSearch` standalone:

```python
[{
    "$vectorSearch": {
        "index": "conversation_vector",
        "path": "searchEmbedding",
        "queryVector": get_query_embedding("premium users flagged"),
        "numCandidates": 100,
        "limit": 10,
        "filter": {
            "category": "wallet-financial"
        }
    }
}]
```

**Pros:**
- Semantic matching — "wallet balance" finds "e-money funds"
- Great for vague or natural-language queries

**Cons:**
- No highlights (Atlas Search highlights are a `$search`-only feature)
- No `$searchMeta` facets — you'd need a separate aggregation for filter counts
- Requires an embedding call on every search request
- Exact keyword matches may rank lower than semantically similar but different content

**To use this exclusively:** Replace the `$rankFusion` pipeline with a standalone `$vectorSearch` stage and skip the `$search` sub-pipeline.

### Option C: UI Toggle Between Search and Semantic Search

Rather than merging text and vector results behind the scenes (which requires `$rankFusion` / MongoDB 8.0), a simpler and often more intuitive approach is to let the **user choose** their search mode. This is the pattern implemented in the [PensionFund Officer Dashboard](https://github.com/pcleene/pension-fund-officer-dashboard) codebase.

The UI provides a toggle (button group or dropdown) with two modes:

| Mode | Backend pipeline | What the user gets |
|---|---|---|
| **Search** (default) | `$search` with compound operator | Keyword matching, highlights, facets, cursor pagination — full Atlas Search experience |
| **Semantic Search** | `$vectorSearch` with Voyage AI embedding | Natural-language queries ("members with compliance issues near retirement") ranked by meaning |

The backend routes to the appropriate pipeline based on a `search_mode` parameter:

```python
if search_mode == "semantic":
    # Vector search — max ~50 results, no pagination, no facets
    return await vector_search_members(collection, query, filters, limit=50)
else:
    # Atlas Search — full facets, pagination, highlights
    return await search_with_pagination(
        collection, index_name, compound_operator,
        facets_definition=MEMBERS_FACETS,
        facet_mapping=MEMBERS_FACET_MAPPING,
        limit=limit, cursor=cursor, projection=projection,
    )
```

**Why this works well:**
- Each mode plays to its strengths — `$search` for precise keyword lookup with rich faceting, `$vectorSearch` for exploratory "find me something like..." queries
- No MongoDB 8.0 dependency
- No second round-trip for facets (in search mode)
- Users quickly learn which mode suits their task

**Trade-off:** The user has to pick. Hybrid search via `$rankFusion` removes that choice by merging both automatically, but at the cost of requiring MongoDB 8.0, losing inline facets, and losing cursor pagination.

### Comparison Matrix

| Capability | `$search` Only | `$vectorSearch` Only | `$rankFusion` (Hybrid) |
|---|---|---|---|
| **Min MongoDB version** | 6.0 (Atlas) | 7.0 (Atlas) | **8.0** (Atlas) |
| Fuzzy keyword matching | Yes | No | Yes |
| Semantic similarity | No | Yes | Yes |
| Highlights | Yes | No | Yes (text sub-pipeline) |
| Facets in same query | **Yes** (single pipeline) | No | No (separate `$searchMeta` query) |
| `searchAfter` pagination | **Yes** (native cursor) | No | No (use `$skip` or fetch extra) |
| Requires embedding model | No | Yes | Yes |
| Query latency | Lowest | Medium (embedding call) | Medium (embedding + extra query) |
| Best for | Exact/known terms | Exploratory/vague queries | **Both** |

---

## Code Structure

```
backend/services/analytics/
├── __init__.py              # Re-exports public API
├── memory.py                # VoyageEmbeddings, MongoDBStore/Saver init, memory tools
├── agent.py                 # System prompt, MCP session, ask_question(), memory trace
├── conversations.py         # Conversation CRUD, metadata generation, demo users
└── conversation_search/
    ├── __init__.py          # Re-exports search_conversations
    ├── pipeline.py          # Constants, filter builders, $search/$rankFusion assembly
    ├── parsing.py           # parse_facets, parse_highlights, format_dt
    └── search.py            # search_conversations entry point, execution, embedding
```

| File | Responsibility |
|---|---|
| `memory.py` | Initialises both memory layers at startup. Exposes `save_memory` / `recall_memories` tools scoped per user. |
| `agent.py` | Manages a persistent MCP session to the MongoDB MCP Server. Runs the LangGraph ReAct agent with Claude Sonnet (Bedrock), MCP tools, and memory tools combined. |
| `conversations.py` | Persists every Q&A turn into `chat_conversations`. Triggers async LLM-based metadata generation + embedding. Serves conversation history and resume. |
| `conversation_search/pipeline.py` | Pure functions that build `$search`, `$vectorSearch`, `$rankFusion`, and `$searchMeta` aggregation pipelines. No I/O. |
| `conversation_search/parsing.py` | Transforms raw Atlas Search output (facet buckets, highlight spans) into structured API responses. |
| `conversation_search/search.py` | Orchestrates the search flow: embed query → build pipeline → execute → fallback if needed → return results + facets + pagination. |
