# Analytics Chatbot — Technical Walkthrough

> A step-by-step guide to how the Fuel Retail Analytics Chatbot works, from the moment a user types a question to the final answer — with every LangChain, LangGraph, and MongoDB interaction explained.

---

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────────────────────────────────────────┐
│  Svelte Frontend │────▶│  FastAPI Backend (port 8002)                         │
│  (SvelteKit)     │◀────│                                                      │
└─────────────────┘     │  ┌────────────────────────────────────────────────┐  │
                        │  │  LangGraph ReAct Agent                         │  │
                        │  │  ┌──────────┐  ┌───────────┐  ┌────────────┐  │  │
                        │  │  │ MCP Tools │  │ Memory    │  │ Claude     │  │  │
                        │  │  │ (MongoDB) │  │ Tools     │  │ (Bedrock)  │  │  │
                        │  │  └─────┬─────┘  └─────┬─────┘  └──────┬─────┘  │  │
                        │  └────────┼──────────────┼───────────────┼────────┘  │
                        └───────────┼──────────────┼───────────────┼───────────┘
                                    ▼              ▼               ▼
                        ┌───────────────┐  ┌─────────────┐  ┌───────────┐
                        │ MongoDB Atlas │  │ Voyage AI   │  │ AWS       │
                        │ (MCP Server)  │  │ Embeddings  │  │ Bedrock   │
                        └───────────────┘  └─────────────┘  └───────────┘
```

**MongoDB collections used:**

| Collection | Purpose |
|---|---|
| `user_profiles` | 10,000 FuelRetail user documents — the data being queried |
| `agent_memories` | Long-term user preferences (Voyage AI vector index) |
| `checkpoints` / `checkpoint_writes` | LangGraph conversation state (short-term memory) |
| `chat_conversations` | Denormalized conversation history (Atlas Search + vector) |
| `app_users` | Demo user personas |

---

## Step-by-Step: What Happens When You Ask a Question

Let's trace a real question: **"How many premium users are flagged by screening?"** asked by user **Sarah Chen (analyst-1)**.

---

### Step 1 — Application Startup

Before any question is asked, the FastAPI lifespan initialises all services:

```python
# backend/main.py — lifespan startup

await connect_pymongo(...)                   # Sync PyMongo client (for LangGraph)
await init_memory_layer()                    # Checkpointer + memory store
await seed_app_users()                       # Upsert demo users into app_users
```

**`init_memory_layer()`** creates two LangGraph persistence layers:

```python
# backend/services/analytics/memory.py

# 1. Short-term memory: MongoDBSaver checkpointer
_checkpointer = MongoDBSaver(client, db_name="FuelRetail_screening")

# 2. Long-term memory: MongoDBStore with Voyage AI embeddings
embeddings = VoyageEmbeddings(
    model="voyage-4-large",
    api_key=settings.voyage_api_key,
    dimensions=1024,
)
index_config = create_vector_index_config(
    embed=embeddings, dims=1024, fields=["$"],
)
_memory_store = MongoDBStore(
    collection=client["FuelRetail_screening"]["agent_memories"],
    index_config=index_config,
    auto_index_timeout=120,
)
```

> **What this creates in MongoDB:**
> - Collections `checkpoints` and `checkpoint_writes` for conversation state
> - Collection `agent_memories` with an Atlas Vector Search index for semantic memory retrieval

---

### Step 2 — MCP Session (Lazy, Once)

On the first question, a persistent MCP (Model Context Protocol) session is established:

```python
# backend/services/analytics/agent.py — _MCPSession._ensure_session()

params = StdioServerParameters(
    command="npx",
    args=["-y", "mongodb-mcp-server"],
    env={"MDB_MCP_CONNECTION_STRING": "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"},
)
stdio_cm = stdio_client(params)            # Spawn subprocess
session = ClientSession(read, write)       # Establish MCP protocol
await session.initialize()                 # Handshake
```

Then tools are loaded via LangChain's MCP adapter:

```python
all_tools = await load_mcp_tools(session)  # ~20 MongoDB tools
tools = [t for t in all_tools if t.name not in EXCLUDED_TOOLS]
# Excluded: "connect", "atlas-local-*", "mongodb-logs", etc.
# Kept: "find", "count", "aggregate", "collection-schema", etc.
```

> **Key insight:** The MCP server reads MongoDB's schema dynamically. No query templates, no embeddings needed for the data layer — the LLM sees the actual schema and writes MQL directly.

---

### Step 3 — Build the Agent

For each question, a fresh LangGraph ReAct agent is assembled:

```python
# backend/services/analytics/agent.py — ask_question()

# Add user-scoped memory tools (2 tools)
memory_tools = build_memory_tools(user_id="analyst-1")
tools.extend(memory_tools)
# Total: ~18 MCP tools + 2 memory tools = ~20 tools

# LLM: Claude Sonnet via AWS Bedrock
model = ChatBedrockConverse(
    model="apac.anthropic.claude-sonnet-4-20250514-v1:0",
    region_name="ap-southeast-1",
    max_tokens=4096,
)

# Assemble the LangGraph agent
agent = create_react_agent(
    model=model,
    tools=tools,
    checkpointer=get_checkpointer(),    # MongoDBSaver
    store=get_memory_store(),           # MongoDBStore
    prompt=SYSTEM_PROMPT,               # FuelRetail terminology + rules
)
```

The **system prompt** gives the agent:
- Database context (`FuelRetail_screening.user_profiles`)
- A terminology table mapping business terms to MongoDB fields (e.g., "premium users" → `wallet.tier = "premium"`)
- Response formatting rules (show MQL, format currency as RM, etc.)
- Instructions to always use `recall_memories` before answering and `save_memory` when asked

---

### Step 4 — Invoke with Checkpointer (Short-Term Memory)

The agent is invoked with only the **new message** — the checkpointer handles conversation history:

```python
config = {
    "configurable": {
        "thread_id": "dd24f4c9-...",     # Session ID
        "user_id": "analyst-1",
    }
}
result = await agent.ainvoke(
    {"messages": [HumanMessage(content="How many premium users are flagged?")]},
    config=config,
)
```

> **What LangGraph does under the hood:**
>
> **Before invoke** — The `MongoDBSaver` checkpointer loads prior state:
> ```
> db.checkpoints.findOne({ thread_id: "dd24f4c9-..." })
> ```
> This restores all previous messages, tool calls, and tool results from earlier turns in the session. The agent "remembers" the full conversation so far.
>
> **After invoke** — The updated state (with the new Q&A) is saved back:
> ```
> db.checkpoint_writes.updateOne(
>   { thread_id: "dd24f4c9-...", checkpoint_id: "...", task_id: "..." },
>   { $set: { channel: "__root__", value: <serialized state> } },
>   { upsert: true }
> )
> ```

---

### Step 5 — Agent Reasoning Loop (ReAct)

The LangGraph `create_react_agent` runs a **Reason + Act** loop. Claude decides which tools to call and in what order. Here's what a typical execution trace looks like:

#### 5a. Recall Long-Term Memories

The agent's first action (instructed by the system prompt) is to check for user preferences:

```
AIMessage:
  tool_calls: [{
    name: "recall_memories",
    args: { query: "user preferences formatting compliance" }
  }]
```

**What happens in MongoDB:**

```python
# MongoDBStore.asearch() runs a $vectorSearch on agent_memories
namespace = ("user_analyst-1_preferences",)
items = await _memory_store.asearch(namespace, query="user preferences...", limit=5)
```

> **Under the hood**, this generates a Voyage AI embedding of the query string, then runs:
> ```javascript
> db.agent_memories.aggregate([
>   { $vectorSearch: {
>       index: "vector_index",
>       path: "embedding",
>       queryVector: [0.023, -0.114, ...],   // 1024 dimensions
>       numCandidates: 50,
>       limit: 5,
>       filter: { namespace: ["user_analyst-1_preferences"] }
>   }}
> ])
> ```

**Result returned to the agent:**

```
ToolMessage:
  "User memories:
   - compliance_threshold: Flag wallets above RM 10,000 for board reporting
   - format_preference: Always include percentages alongside raw counts
   - monthly_board_kpis: Track MAU, churn rate, flagged users, premium %"
```

The agent now knows Sarah always wants percentages and has specific compliance thresholds.

#### 5b. Query MongoDB via MCP

Next, the agent calls MCP tools to answer the actual question:

```
AIMessage:
  tool_calls: [{
    name: "aggregate",
    args: {
      database: "FuelRetail_screening",
      collection: "user_profiles",
      pipeline: [
        { "$match": { "wallet.tier": "premium", "screening.riskFlag": true } },
        { "$count": "flaggedPremiumUsers" }
      ]
    }
  }]
```

> The MCP Server executes this directly against MongoDB Atlas. No embedding, no RAG retrieval — the LLM wrote the MQL from understanding the schema.

**Result:**

```
ToolMessage:
  [{ "flaggedPremiumUsers": 47 }]
```

The agent might also make a second call to get the total premium count (for the percentage Sarah prefers):

```
AIMessage:
  tool_calls: [{
    name: "count",
    args: {
      database: "FuelRetail_screening",
      collection: "user_profiles",
      filter: { "wallet.tier": "premium" }
    }
  }]
```

```
ToolMessage:
  312
```

#### 5c. Generate Final Answer

Claude composes the response, applying the recalled preferences (percentages):

```
AIMessage:
  content: "**47 premium users** are currently flagged by screening,
            representing **15.1%** of all 312 premium wallet users.

            ```javascript
            // Generated MQL
            db.user_profiles.aggregate([
              { $match: { "wallet.tier": "premium", "screening.riskFlag": true } },
              { $count: "flaggedPremiumUsers" }
            ])
            ```"
```

---

### Step 6 — Extract Response & Memory Trace

Back in Python, we extract structured data from the agent's full message trace:

```python
# The final answer text
answer = result["messages"][-1].content

# Extract MQL code blocks from the answer
mql = _extract_mql(answer)   # Regex: ```javascript ... ```

# Walk ALL messages to find memory tool calls and their results
memory_trace = _extract_memory_trace(result["messages"])
# Returns: [
#   { tool: "recall_memories", input: {query: "..."}, output: "User memories:\n..." },
# ]
```

> **The memory trace is returned to the frontend** so users can click "Memory (1)" on any response and see exactly which preferences were recalled and how they influenced the answer.

---

### Step 7 — Persist Conversation (Fire-and-Forget)

After returning the response, a background task saves the turn for search indexing:

```python
asyncio.create_task(
    save_conversation_turn(session_id, user_id, question, answer, mql, latency_ms)
)
```

**First turn** — inserts a new document into `chat_conversations`:

```javascript
db.chat_conversations.insertOne({
  threadId: "dd24f4c9-...",
  userId: "analyst-1",
  messages: [{
    id: "uuid",
    question: "How many premium users are flagged?",
    content: "**47 premium users** are currently flagged...",
    mql: "db.user_profiles.aggregate([...])",
    latency_ms: 12340,
    timestamp: "2026-04-13T..."
  }],
  turnCount: 1,
  title: "",          // Populated by metadata generation
  summary: "",
  category: "",
  topics: [],
  // ... other metadata fields
})
```

**Subsequent turns** — pushes to the messages array:

```javascript
db.chat_conversations.updateOne(
  { threadId: "dd24f4c9-..." },
  {
    $push: { messages: { /* new message pair */ } },
    $set: { turnCount: 2, lastQuestion: "...", updatedAt: ISODate() }
  }
)
```

> **Note:** This is separate from the LangGraph checkpointer. The checkpointer stores raw agent state for conversation continuity. `chat_conversations` is a denormalized copy optimised for Atlas Search.

---

### Step 8 — Metadata Enrichment (Background)

On the **first turn** and every **3rd turn**, an LLM classifies the conversation:

```python
# Uses Claude 3 Haiku (cheap, fast) via Bedrock
model = ChatBedrockConverse(
    model="apac.anthropic.claude-3-haiku-20240307-v1:0",
    region_name="ap-southeast-1",
    max_tokens=500,
)
```

**Prompt sent to Haiku:**

```
Classify this analytics chatbot conversation. Return ONLY valid JSON:
- title: short descriptive title (max 60 chars)
- summary: 1-2 sentence summary
- category: one of [user-metrics, kyc-compliance, wallet-financial, ...]
- topics: array of 1-4 topic tags
- queryTypes: array from [count, aggregation, lookup, trend, ...]
- complexity: one of [simple, moderate, complex]
- intent: one of [exploration, reporting, investigation, monitoring]
- collections: array of MongoDB collections queried

Conversation:
Q: How many premium users are flagged?
A: **47 premium users** are currently flagged...

JSON:
```

**Result applied to MongoDB:**

```javascript
db.chat_conversations.updateOne(
  { threadId: "dd24f4c9-..." },
  { $set: {
      title: "Flagged Premium Users Count",
      summary: "Queried premium wallet users flagged by screening...",
      category: "wallet-financial",
      topics: ["premium", "screening", "flagged-users"],
      queryTypes: ["count", "aggregation"],
      complexity: "simple",
      intent: "reporting",
      collections: ["user_profiles"],
      searchEmbedding: [0.012, -0.087, ...]  // 1024-dim Voyage AI vector
  }}
)
```

> The `searchEmbedding` is generated by embedding `title + summary + conversation digest` via Voyage AI. This powers the hybrid vector search in the conversation history panel.

---

### Step 9 — Conversation History Search (Hybrid $rankFusion)

When a user searches past conversations in the History panel, the system uses **MongoDB's `$rankFusion`** to combine text and vector search:

```python
# backend/services/analytics/conversation_search/search.py

# 1. Embed the search query
query_embedding = get_query_embedding("premium users flagged")
# → Voyage AI → 1024-dim vector

# 2. Build hybrid pipeline
pipeline = [
  { "$rankFusion": {
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
                "queryVector": [0.012, -0.087, ...],
                "numCandidates": 50,
                "limit": 11
            }}
          ]
        }
      }
  }},
  { "$addFields": { "score": { "$meta": "score" } } },
  { "$facet": {
      "results": [{ "$limit": 11 }, { "$project": { ... } }],
      "metadata": [{ "$count": "total" }]
  }}
]
```

> **How `$rankFusion` works:** It runs both pipelines independently, then merges results using Reciprocal Rank Fusion (RRF). A conversation that ranks high in both text relevance AND semantic similarity will bubble to the top.

**Two Atlas Search indexes power this:**

| Index | Type | Purpose |
|---|---|---|
| `conversation_search` | Atlas Search (text) | Fuzzy full-text across title, summary, messages, MQL |
| `conversation_vector` | Atlas Vector Search | Cosine similarity on `searchEmbedding` (1024-dim Voyage AI) |

---

## MongoDB Collections Summary

### `agent_memories` — Long-Term User Preferences

```javascript
// Example document
{
  namespace: ["user_analyst-1_preferences"],
  key: "compliance_threshold",
  value: { content: "Flag wallets above RM 10,000 for board reporting" },
  embedding: [0.034, -0.091, ...],          // 1024-dim Voyage AI
  namespace_prefix: ["user_analyst-1_preferences"],
  created_at: ISODate("2026-04-12T..."),
  updated_at: ISODate("2026-04-12T...")
}
```

- **Written by:** Agent's `save_memory` tool during conversations
- **Read by:** Agent's `recall_memories` tool (vector search), frontend memories panel
- **Index:** Atlas Vector Search on `embedding` field

### `checkpoints` / `checkpoint_writes` — Conversation State

```javascript
// Managed entirely by LangGraph's MongoDBSaver
{
  thread_id: "dd24f4c9-...",
  checkpoint_ns: "",
  checkpoint_id: "1f084df3-...",
  // ... serialized agent state (messages, tool calls, tool results)
}
```

- **Written by:** LangGraph checkpointer after each agent invocation
- **Read by:** LangGraph checkpointer before each agent invocation
- **Purpose:** Enables multi-turn conversation without re-sending full history

### `chat_conversations` — Searchable Conversation History

```javascript
{
  threadId: "dd24f4c9-...",
  userId: "analyst-1",
  messages: [{ question, content, mql, latency_ms, timestamp }],
  turnCount: 3,
  title: "Flagged Premium Users Count",
  summary: "Queried premium wallet users...",
  category: "wallet-financial",
  topics: ["premium", "screening"],
  searchEmbedding: [0.012, -0.087, ...],    // 1024-dim
  createdAt: ISODate("2026-04-13T..."),
  updatedAt: ISODate("2026-04-13T...")
}
```

- **Written by:** `save_conversation_turn()` + `_generate_conversation_metadata()`
- **Read by:** Conversation search (`$rankFusion`), history panel, resume
- **Indexes:** `conversation_search` (text) + `conversation_vector` (vector)

---

## File Structure

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

---

## Key Technologies

| Technology | Role | Where |
|---|---|---|
| **LangGraph** `create_react_agent` | Orchestrates the reasoning loop (Reason → Tool Call → Observe → Repeat) | `agent.py` |
| **LangGraph** `MongoDBSaver` | Short-term memory — persists conversation state per session | `memory.py` |
| **LangGraph** `MongoDBStore` | Long-term memory — stores user preferences with vector search | `memory.py` |
| **LangChain** `ChatBedrockConverse` | Claude Sonnet 4 via AWS Bedrock | `agent.py` |
| **LangChain** `@tool` decorator | Defines `save_memory` and `recall_memories` as callable tools | `memory.py` |
| **MCP** (Model Context Protocol) | MongoDB tools exposed to the LLM via stdio subprocess | `agent.py` |
| **Voyage AI** | 1024-dim embeddings for memory search + conversation search | `memory.py`, `conversations.py` |
| **MongoDB Atlas Search** | Full-text fuzzy search with facets | `conversation_search/pipeline.py` |
| **MongoDB `$rankFusion`** | Hybrid text + vector search (RRF merge) | `conversation_search/pipeline.py` |
